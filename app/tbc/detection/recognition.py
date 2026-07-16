from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import database
from ..notifications import notify_event
from .model_provisioning import download_model_if_missing

LOGGER = logging.getLogger(__name__)

# Vendor-native ("person"/"vehicle") and local-AI ("ai_person"/"ai_vehicle", plus their
# loitering variants) detection keys that should trigger face/plate recognition.
FACE_TRIGGER_DETECTION_KEYS = {"ai_person", "ai_person_loitering", "person"}
PLATE_TRIGGER_DETECTION_KEYS = {"ai_vehicle", "ai_vehicle_loitering", "vehicle"}

# Official OpenCV Zoo models (https://github.com/opencv/opencv_zoo, Apache-2.0) - YuNet for
# face detection (+5 landmarks) and SFace for the 128-d face embedding used to match against
# enrolled known_faces rows.
FACE_DETECTOR_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
FACE_RECOGNIZER_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
)

# fast-alpr's default plate detector (open-image-models, MIT) + a plate-OCR model
# (fast-plate-ocr, MIT) tuned for European plates.
PLATE_DETECTOR_MODEL_URL = (
    "https://github.com/ankandrew/open-image-models/releases/download/"
    "assets/yolo-v9-t-384-license-plates-end2end.onnx"
)
PLATE_OCR_MODEL_URL = (
    "https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/european_mobile_vit_v2_ocr.onnx"
)
PLATE_OCR_CONFIG_URL = (
    "https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/european_mobile_vit_v2_ocr_config.yaml"
)

# SFace's own documented cosine-similarity threshold for "same person".
FACE_MATCH_DEFAULT_THRESHOLD = 0.363


def ensure_face_models(detector_path: Path, recognizer_path: Path) -> bool:
    ok_detector = download_model_if_missing(FACE_DETECTOR_MODEL_URL, detector_path)
    ok_recognizer = download_model_if_missing(FACE_RECOGNIZER_MODEL_URL, recognizer_path)
    return ok_detector and ok_recognizer


def ensure_plate_models(detector_path: Path, ocr_model_path: Path, ocr_config_path: Path) -> bool:
    ok_detector = download_model_if_missing(PLATE_DETECTOR_MODEL_URL, detector_path)
    ok_ocr = download_model_if_missing(PLATE_OCR_MODEL_URL, ocr_model_path)
    ok_config = download_model_if_missing(PLATE_OCR_CONFIG_URL, ocr_config_path)
    return ok_detector and ok_ocr and ok_config


def crop_with_padding(
    image: np.ndarray, box: tuple[float, float, float, float], padding_ratio: float = 0.2
) -> np.ndarray:
    """Crops `image` to a normalized (xmin, ymin, xmax, ymax) box, expanded by padding_ratio on
    each side so a tight person/vehicle box doesn't clip the face/plate just outside it."""
    height, width = image.shape[:2]
    xmin, ymin, xmax, ymax = box
    box_w = xmax - xmin
    box_h = ymax - ymin
    pad_x = box_w * padding_ratio
    pad_y = box_h * padding_ratio
    left = max(0, int((xmin - pad_x) * width))
    top = max(0, int((ymin - pad_y) * height))
    right = min(width, int((xmax + pad_x) * width))
    bottom = min(height, int((ymax + pad_y) * height))
    if right <= left or bottom <= top:
        return image
    return image[top:bottom, left:right]


class FaceRecognizer:
    """Local face detection + embedding via OpenCV's YuNet (detector) and SFace (recognizer)."""

    def __init__(self, detector_path: Path, recognizer_path: Path) -> None:
        import cv2  # heavy optional dependency, only imported when face recognition is enabled

        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(
            model=str(detector_path),
            config="",
            input_size=(320, 320),
            score_threshold=0.6,
            nms_threshold=0.3,
            top_k=5000,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(model=str(recognizer_path), config="")

    def detect_and_embed(self, image: np.ndarray) -> list[dict[str, Any]]:
        """One entry per detected face: {"box": (x, y, w, h), "score": float, "embedding": list[float]}."""
        height, width = image.shape[:2]
        if height == 0 or width == 0:
            return []
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(image)
        if faces is None:
            return []
        results = []
        for face in faces:
            aligned = self._recognizer.alignCrop(image, face)
            embedding = self._recognizer.feature(aligned)
            results.append(
                {
                    "box": tuple(float(v) for v in face[:4]),
                    "score": float(face[14]),
                    "embedding": embedding.flatten().astype(float).tolist(),
                }
            )
        return results

    def cosine_similarity(self, embedding_a: list[float], embedding_b: list[float]) -> float:
        a = np.asarray(embedding_a, dtype=np.float32).reshape(1, -1)
        b = np.asarray(embedding_b, dtype=np.float32).reshape(1, -1)
        return float(self._recognizer.match(a, b, self._cv2.FaceRecognizerSF_FR_COSINE))


def match_known_face(
    embedding: list[float],
    known_faces: list[dict[str, Any]],
    recognizer: FaceRecognizer,
    threshold: float = FACE_MATCH_DEFAULT_THRESHOLD,
) -> tuple[int, str, float] | None:
    """Returns (known_face_id, name, score) for the best match at or above threshold, else None."""
    best: tuple[int, str, float] | None = None
    for known in known_faces:
        try:
            known_embedding = json.loads(known["embedding"])
        except (json.JSONDecodeError, TypeError):
            continue
        score = recognizer.cosine_similarity(embedding, known_embedding)
        if score >= threshold and (best is None or score > best[2]):
            best = (int(known["id"]), str(known["name"]), score)
    return best


class PlateRecognizer:
    """Local license-plate detection + OCR (fast-alpr: open-image-models detector + fast-plate-ocr)."""

    def __init__(self, detector_path: Path, ocr_model_path: Path, ocr_config_path: Path) -> None:
        from fast_alpr import ALPR
        from open_image_models.detection.core.yolo_v9.inference import YoloV9ObjectDetector

        detector = YoloV9ObjectDetector(
            model_path=str(detector_path),
            class_labels=["License Plate"],
            conf_thresh=0.4,
        )
        self._alpr = ALPR(
            detector=detector,
            ocr=None,
            ocr_model=None,
            ocr_model_path=str(ocr_model_path),
            ocr_config_path=str(ocr_config_path),
        )

    def recognize(self, image: np.ndarray) -> list[dict[str, Any]]:
        """One entry per detected plate: {"text": str, "confidence": float, "box": (x1,y1,x2,y2)}."""
        results = []
        for item in self._alpr.predict(image):
            if item.ocr is None or not item.ocr.text:
                continue
            confidences = item.ocr.confidence or []
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            box = item.detection.bounding_box
            results.append(
                {
                    "text": normalize_plate_text(item.ocr.text),
                    "confidence": float(avg_confidence),
                    "box": (box.x1, box.y1, box.x2, box.y2),
                }
            )
        return results


def normalize_plate_text(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def match_known_plate(plate_text: str, known_plates: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = normalize_plate_text(plate_text)
    for known in known_plates:
        if normalize_plate_text(known["plate_text"]) == normalized:
            return known
    return None


_face_recognizer: FaceRecognizer | None = None
_plate_recognizer: PlateRecognizer | None = None


def get_face_recognizer(models_dir: Path) -> FaceRecognizer | None:
    global _face_recognizer
    if _face_recognizer is None:
        detector_path = models_dir / "face_detection_yunet.onnx"
        recognizer_path = models_dir / "face_recognition_sface.onnx"
        if not ensure_face_models(detector_path, recognizer_path):
            return None
        try:
            _face_recognizer = FaceRecognizer(detector_path, recognizer_path)
        except Exception:
            LOGGER.exception("Gesichtserkennung konnte nicht initialisiert werden")
            return None
    return _face_recognizer


def get_plate_recognizer(models_dir: Path) -> PlateRecognizer | None:
    global _plate_recognizer
    if _plate_recognizer is None:
        detector_path = models_dir / "plate_detector.onnx"
        ocr_path = models_dir / "plate_ocr.onnx"
        ocr_config_path = models_dir / "plate_ocr_config.yaml"
        if not ensure_plate_models(detector_path, ocr_path, ocr_config_path):
            return None
        try:
            _plate_recognizer = PlateRecognizer(detector_path, ocr_path, ocr_config_path)
        except Exception:
            LOGGER.exception("Kennzeichenerkennung konnte nicht initialisiert werden")
            return None
    return _plate_recognizer


def _save_crop(image: np.ndarray, snapshot_dir: Path, camera_id: int, kind: str) -> str | None:
    try:
        import cv2

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = snapshot_dir / f"{kind}_{camera_id}_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(str(path), image)
        return str(path)
    except Exception:
        LOGGER.exception("Ausschnitt für Erkennungs-Ereignis konnte nicht gespeichert werden")
        return None


def _resolve_snapshot_path(
    image: np.ndarray, camera_id: int, kind: str, *, existing_snapshot_path: str | None, snapshot_dir: Path | None
) -> str | None:
    if existing_snapshot_path:
        return existing_snapshot_path
    if snapshot_dir:
        return _save_crop(image, snapshot_dir, camera_id, kind)
    return None


def _process_face(
    database_path: str,
    models_dir: Path,
    *,
    camera_id: int,
    camera_name: str,
    recording_id: int | None,
    image: np.ndarray,
    threshold: float,
    public_base_url: str,
    snapshot_dir: Path | None,
    existing_snapshot_path: str | None,
) -> None:
    recognizer = get_face_recognizer(models_dir)
    if recognizer is None:
        return
    faces = recognizer.detect_and_embed(image)
    if not faces:
        return
    # A crop is already scoped to one person's bounding box, so only the most confident
    # face found in it is reported (extra faces would usually be someone standing behind).
    face = max(faces, key=lambda item: item["score"])
    known_faces = database.list_known_faces(database_path)
    match = match_known_face(face["embedding"], known_faces, recognizer, threshold=threshold)
    label = match[1] if match else "Unbekannt"
    snapshot_path = _resolve_snapshot_path(
        image, camera_id, "face", existing_snapshot_path=existing_snapshot_path, snapshot_dir=snapshot_dir
    )
    database.create_recognition_event(
        database_path,
        recording_id=recording_id,
        camera_id=camera_id,
        kind="face",
        matched_face_id=match[0] if match else None,
        label=label,
        confidence=match[2] if match else face["score"],
        snapshot_path=snapshot_path,
    )
    recording = database.get_recording(database_path, recording_id) if recording_id else None
    notify_event(
        database_path,
        event_type="known_face_detected" if match else "unknown_face_detected",
        title=f"TBC: {'Bekanntes' if match else 'Unbekanntes'} Gesicht",
        message=f"{camera_name}: {label}",
        recording=recording,
        public_base_url=public_base_url,
    )


def _process_plate(
    database_path: str,
    models_dir: Path,
    *,
    camera_id: int,
    camera_name: str,
    recording_id: int | None,
    image: np.ndarray,
    public_base_url: str,
    snapshot_dir: Path | None,
    existing_snapshot_path: str | None,
) -> None:
    recognizer = get_plate_recognizer(models_dir)
    if recognizer is None:
        return
    plates = recognizer.recognize(image)
    if not plates:
        return
    plate = max(plates, key=lambda item: item["confidence"])
    known_plates = database.list_known_plates(database_path)
    match = match_known_plate(plate["text"], known_plates)
    # The plate text itself is always shown (unlike faces, it's informative even when
    # unmatched) - "label" only distinguishes a *known* match, so it's baked in here rather
    # than re-derived later from matched_plate_id, which can go stale if the known plate is
    # later deleted (ON DELETE SET NULL would otherwise silently relabel history as unknown).
    label = f"{plate['text']} ({match['label'] or match['plate_text']})" if match else plate["text"]
    snapshot_path = _resolve_snapshot_path(
        image, camera_id, "plate", existing_snapshot_path=existing_snapshot_path, snapshot_dir=snapshot_dir
    )
    database.create_recognition_event(
        database_path,
        recording_id=recording_id,
        camera_id=camera_id,
        kind="plate",
        matched_plate_id=match["id"] if match else None,
        label=label,
        confidence=plate["confidence"],
        snapshot_path=snapshot_path,
    )
    recording = database.get_recording(database_path, recording_id) if recording_id else None
    notify_event(
        database_path,
        event_type="known_plate_detected" if match else "unknown_plate_detected",
        title=f"TBC: {'Bekanntes' if match else 'Unbekanntes'} Kennzeichen",
        message=f"{camera_name}: {plate['text']}",
        recording=recording,
        public_base_url=public_base_url,
    )


def process_recognition(
    database_path: str,
    models_dir: Path,
    *,
    camera_id: int,
    camera_name: str,
    recording_id: int | None,
    detection_key: str,
    mode: str,
    image: np.ndarray,
    box: tuple[float, float, float, float] | None = None,
    public_base_url: str = "",
    snapshot_dir: Path | None = None,
    existing_snapshot_path: str | None = None,
) -> None:
    """Runs face/plate recognition for one qualifying detection (best-effort: any failure is
    logged and swallowed here so it can never break a recording job or a camera's detection loop).

    `mode` identifies the call site ("snapshot" after a recording's file is saved, "live" from
    the per-frame detection loop) and is matched against the per-feature mode setting so each
    feature only reacts to the call site the user configured it for. `existing_snapshot_path`
    lets snapshot-mode reuse the recording's own snapshot file instead of saving a new crop.
    """
    try:
        settings = database.get_recognition_settings(database_path)
        crop = crop_with_padding(image, box) if box is not None else image

        if (
            detection_key in FACE_TRIGGER_DETECTION_KEYS
            and settings["face_enabled"]
            and settings["face_mode"] == mode
        ):
            _process_face(
                database_path,
                models_dir,
                camera_id=camera_id,
                camera_name=camera_name,
                recording_id=recording_id,
                image=crop,
                threshold=float(settings["face_match_threshold"]),
                public_base_url=public_base_url,
                snapshot_dir=snapshot_dir,
                existing_snapshot_path=existing_snapshot_path,
            )

        if (
            detection_key in PLATE_TRIGGER_DETECTION_KEYS
            and settings["plate_enabled"]
            and settings["plate_mode"] == mode
        ):
            _process_plate(
                database_path,
                models_dir,
                camera_id=camera_id,
                camera_name=camera_name,
                recording_id=recording_id,
                image=crop,
                public_base_url=public_base_url,
                existing_snapshot_path=existing_snapshot_path,
                snapshot_dir=snapshot_dir,
            )
    except Exception:
        LOGGER.exception("Erkennung (Gesicht/Kennzeichen) für Kamera %s fehlgeschlagen", camera_id)
