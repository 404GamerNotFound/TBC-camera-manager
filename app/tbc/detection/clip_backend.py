from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .. import database
from .model_provisioning import download_model_if_missing

LOGGER = logging.getLogger(__name__)

# immich-app publishes many CLIP derivatives on Hugging Face, all sharing the same
# visual/textual ONNX split and file layout - see
# https://huggingface.co/immich-app/ViT-B-32__openai (the default) for the reference layout.
# Swapping to a smaller/larger derivative (e.g. "RN50__openai") is just a different model_name,
# no code change needed.
HUGGINGFACE_BASE_URL = "https://huggingface.co/immich-app"
DEFAULT_MODEL_NAME = "ViT-B-32__openai"

CONTEXT_LENGTH = 77
# CLIP's <|endoftext|>/<|startoftext|> token IDs are fixed by the tokenizer.json vocabulary of
# every immich-app CLIP export, so hardcoding the pad token here (rather than reading it back
# out of tokenizer_config.json) is safe.
EOS_TOKEN_ID = 49407
EOS_TOKEN = "<|endoftext|>"

BACKFILL_BATCH_SIZE = 5
BACKFILL_INTERVAL_SECONDS = 30.0
BACKFILL_IDLE_INTERVAL_SECONDS = 300.0


def _model_files(models_dir: Path, model_name: str) -> dict[str, Path]:
    root = models_dir / "clip" / model_name
    return {
        "visual": root / "visual.onnx",
        "textual": root / "textual.onnx",
        "tokenizer": root / "tokenizer.json",
        "preprocess_cfg": root / "preprocess_cfg.json",
    }


def clip_models_ready(models_dir: Path, model_name: str) -> bool:
    """Checks whether the visual/textual pair (+ tokenizer/preprocess config) for `model_name`
    is already present on disk, without triggering a download - used by the settings page to
    show model status."""
    paths = _model_files(models_dir, model_name)
    return all(path.exists() and path.stat().st_size > 0 for path in paths.values())


def ensure_clip_models(models_dir: Path, model_name: str) -> bool:
    """Downloads the visual/textual ONNX pair (+ tokenizer/preprocess config) for `model_name`
    from the immich-app Hugging Face org on first use, unless already present.

    Best-effort like the rest of model_provisioning: a failed download is logged and returns
    False rather than raising, so a worker can retry later instead of crashing.
    """
    base = f"{HUGGINGFACE_BASE_URL}/{model_name}/resolve/main"
    paths = _model_files(models_dir, model_name)
    ok_visual = download_model_if_missing(f"{base}/visual/model.onnx", paths["visual"])
    ok_textual = download_model_if_missing(f"{base}/textual/model.onnx", paths["textual"])
    ok_tokenizer = download_model_if_missing(f"{base}/textual/tokenizer.json", paths["tokenizer"])
    ok_cfg = download_model_if_missing(f"{base}/visual/preprocess_cfg.json", paths["preprocess_cfg"])
    return ok_visual and ok_textual and ok_tokenizer and ok_cfg


@dataclass(frozen=True)
class _PreprocessConfig:
    size: tuple[int, int]
    mean: tuple[float, float, float]
    std: tuple[float, float, float]

    @classmethod
    def load(cls, path: Path) -> "_PreprocessConfig":
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        width, height = data["size"]
        mean = tuple(float(v) for v in data["mean"])
        std = tuple(float(v) for v in data["std"])
        return cls(size=(int(width), int(height)), mean=mean, std=std)


def _preprocess_image(image: np.ndarray, config: _PreprocessConfig) -> np.ndarray:
    """image: HxWx3 uint8 BGR (the cv2.imread convention used throughout this codebase).

    Resizes the shorter side to the target size and center-crops to it, matching the "shortest"
    resize_mode in every immich-app visual/preprocess_cfg.json seen so far. Returns a normalized
    NCHW float32 tensor ready for the visual ONNX model's "image" input.
    """
    target_w, target_h = config.size
    target_short = min(target_w, target_h)
    pil_image = Image.fromarray(image[:, :, ::-1])
    width, height = pil_image.size
    scale = target_short / min(width, height)
    resized = pil_image.resize((round(width * scale), round(height * scale)), Image.BICUBIC)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    array = np.asarray(cropped).astype(np.float32) / 255.0
    array = (array - np.array(config.mean, dtype=np.float32)) / np.array(config.std, dtype=np.float32)
    return np.transpose(array, (2, 0, 1))[np.newaxis, ...].astype(np.float32)


class ClipImageEncoder:
    """Wraps the visual-tower ONNX model: crop/frame in, a 512-d L2-normalized embedding out."""

    def __init__(self, visual_model_path: Path, preprocess_cfg_path: Path) -> None:
        self._model_path = visual_model_path
        self._config = _PreprocessConfig.load(preprocess_cfg_path)
        self._session: Any = None

    def _load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime

        self._session = onnxruntime.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])

    def encode_image(self, image: np.ndarray) -> np.ndarray:
        self._load()
        assert self._session is not None
        tensor = _preprocess_image(image, self._config)
        (embedding,) = self._session.run(None, {"image": tensor})
        return embedding[0].astype(np.float32)


class ClipTextEncoder:
    """Wraps the textual-tower ONNX model: free text in, a 512-d L2-normalized embedding out."""

    def __init__(self, textual_model_path: Path, tokenizer_path: Path) -> None:
        self._model_path = textual_model_path
        self._tokenizer_path = tokenizer_path
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(self._tokenizer_path))
        tokenizer.enable_padding(length=CONTEXT_LENGTH, pad_id=EOS_TOKEN_ID, pad_token=EOS_TOKEN)
        tokenizer.enable_truncation(max_length=CONTEXT_LENGTH)
        self._tokenizer = tokenizer
        self._session = onnxruntime.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])

    def encode_text(self, text: str) -> np.ndarray:
        self._load()
        assert self._session is not None and self._tokenizer is not None
        encoded = self._tokenizer.encode(text)
        ids = np.asarray([encoded.ids], dtype=np.int32)
        (embedding,) = self._session.run(None, {"text": ids})
        return embedding[0].astype(np.float32)


_image_encoder: ClipImageEncoder | None = None
_text_encoder: ClipTextEncoder | None = None
_loaded_model_name: str | None = None


def get_clip_encoders(models_dir: Path, model_name: str) -> tuple[ClipImageEncoder, ClipTextEncoder] | None:
    """Lazy singleton getter, mirroring recognition.get_face_recognizer/get_plate_recognizer.

    Re-initializes if the admin changed the configured model name; returns None (rather than
    raising) whenever the models aren't available yet or fail to load, so callers can treat
    semantic search as best-effort and skip it for this call.
    """
    global _image_encoder, _text_encoder, _loaded_model_name
    if _loaded_model_name != model_name:
        _image_encoder = None
        _text_encoder = None
        _loaded_model_name = model_name
    if _image_encoder is None or _text_encoder is None:
        if not ensure_clip_models(models_dir, model_name):
            return None
        paths = _model_files(models_dir, model_name)
        try:
            _image_encoder = ClipImageEncoder(paths["visual"], paths["preprocess_cfg"])
            _text_encoder = ClipTextEncoder(paths["textual"], paths["tokenizer"])
        except Exception:
            LOGGER.exception("CLIP-Encoder für Modell %s konnte nicht initialisiert werden", model_name)
            _image_encoder = None
            _text_encoder = None
            return None
    return _image_encoder, _text_encoder


def rank_by_similarity(
    query_embedding: np.ndarray, rows: list[dict[str, Any]], *, limit: int
) -> list[tuple[int, float]]:
    """Returns up to `limit` (recording_id, score) pairs from `rows` (each a dict with
    "recording_id" and "embedding" keys, as returned by database.list_recording_embeddings),
    sorted by descending cosine similarity.

    Both the query and stored embeddings are already L2-normalized by the CLIP ONNX graphs
    themselves (verified against the reference model), so similarity is a plain dot product -
    no extra normalization or vector-DB dependency needed at self-hosted recording volumes.
    """
    if not rows:
        return []
    query = np.asarray(query_embedding, dtype=np.float32)
    matrix = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
    scores = matrix @ query
    order = np.argsort(scores)[::-1][:limit]
    return [(int(rows[index]["recording_id"]), float(scores[index])) for index in order]


async def embedding_backfill_supervisor(database_path: str, models_dir: Path) -> None:
    """Background sweep that computes embeddings for recordings created before semantic search
    was enabled (or before this recording's own embedding attempt failed).

    Mirrors the throttled-batch shape of maintenance.py's retention sweep: small batches with a
    sleep in between so it never competes with live recording/detection workers for CPU/IO. Polls
    less often while idle (nothing enabled, or fully caught up) than while actively backfilling.
    """
    await asyncio.sleep(10)
    while True:
        settings = database.get_search_settings(database_path)
        if not settings.get("enabled"):
            await asyncio.sleep(BACKFILL_IDLE_INTERVAL_SECONDS)
            continue
        model_name = str(settings["model_name"])
        pending = database.list_recordings_missing_embedding(database_path, model_name, limit=BACKFILL_BATCH_SIZE)
        if not pending:
            await asyncio.sleep(BACKFILL_IDLE_INTERVAL_SECONDS)
            continue
        encoders = await asyncio.to_thread(get_clip_encoders, models_dir, model_name)
        if encoders is None:
            await asyncio.sleep(BACKFILL_IDLE_INTERVAL_SECONDS)
            continue
        image_encoder, _ = encoders
        for row in pending:
            await asyncio.to_thread(_embed_recording_snapshot, database_path, image_encoder, model_name, row)
        await asyncio.sleep(BACKFILL_INTERVAL_SECONDS)


def _embed_recording_snapshot(
    database_path: str, image_encoder: ClipImageEncoder, model_name: str, recording: dict[str, Any]
) -> None:
    snapshot_path = recording.get("snapshot_path")
    if not snapshot_path:
        return
    try:
        import cv2

        image = cv2.imread(snapshot_path)
        if image is None:
            return
        embedding = image_encoder.encode_image(image)
        database.upsert_recording_embedding(
            database_path, int(recording["id"]), model_name, embedding.tolist()
        )
    except Exception:
        LOGGER.exception("Backfill-Embedding für Aufnahme %s fehlgeschlagen", recording.get("id"))
