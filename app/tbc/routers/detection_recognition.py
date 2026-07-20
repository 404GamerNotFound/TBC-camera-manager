"""AI detection overview and face/plate recognition.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import json

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from .. import database
from ..detection import factory as detection_factory
from ..detection.recognition import (
    get_face_recognizer,
)
from fastapi import APIRouter

from ..main import (
    DETECTION_CORAL_MODEL_PATH,
    DETECTION_MODEL_PATH,
    RECOGNITION_MODELS_DIR,
    SETTINGS,
    _pop_flash,
    _redirect,
    _require_admin,
    _set_flash,
    templates,
)

router = APIRouter()


@router.get("/detection", response_class=HTMLResponse)
async def detection_overview_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    model_ready = DETECTION_MODEL_PATH.exists() and DETECTION_MODEL_PATH.stat().st_size > 0
    coral_model_ready = DETECTION_CORAL_MODEL_PATH.exists() and DETECTION_CORAL_MODEL_PATH.stat().st_size > 0
    return templates.TemplateResponse(
        request,
        "detection.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "backend_status": detection_factory.backend_status(),
            "detection_backend_labels": detection_factory.BACKEND_LABELS,
            "model_ready": model_ready,
            "model_size_mb": round(DETECTION_MODEL_PATH.stat().st_size / (1024 * 1024), 1) if model_ready else None,
            "model_path": str(DETECTION_MODEL_PATH),
            "coral_model_ready": coral_model_ready,
            "coral_model_size_mb": round(DETECTION_CORAL_MODEL_PATH.stat().st_size / (1024 * 1024), 1) if coral_model_ready else None,
            "coral_model_path": str(DETECTION_CORAL_MODEL_PATH),
            "default_sample_fps": SETTINGS.detection_default_sample_fps,
            "default_confidence_threshold": SETTINGS.detection_default_confidence_threshold,
            "cameras": database.list_enabled_camera_detection_settings(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.get("/recognition", response_class=HTMLResponse)
async def recognition_page(request: Request):
    guard = _require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        request,
        "recognition.html",
        {
            "app_name": SETTINGS.app_name,
            "username": request.session.get("username"),
            "role": "admin",
            "settings": database.get_recognition_settings(SETTINGS.database_path),
            "known_faces": database.list_known_faces(SETTINGS.database_path),
            "known_plates": database.list_known_plates(SETTINGS.database_path),
            "recent_events": database.list_recognition_events(SETTINGS.database_path, limit=25),
            "flash": _pop_flash(request),
        },
    )

@router.post("/recognition/settings")
async def update_recognition_settings_route(
    request: Request,
    face_enabled: str | None = Form(None),
    face_mode: str = Form("snapshot"),
    face_match_threshold: str = Form("0.363"),
    plate_enabled: str | None = Form(None),
    plate_mode: str = Form("snapshot"),
):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        threshold = max(0.0, min(1.0, float(face_match_threshold or 0.363)))
    except ValueError:
        threshold = 0.363
    database.update_recognition_settings(
        SETTINGS.database_path,
        face_enabled=bool(face_enabled),
        face_mode="live" if face_mode == "live" else "snapshot",
        face_match_threshold=threshold,
        plate_enabled=bool(plate_enabled),
        plate_mode="live" if plate_mode == "live" else "snapshot",
    )
    _set_flash(request, "recognition.settings_saved")
    return _redirect("/recognition")

@router.post("/recognition/faces")
async def create_known_face_route(request: Request, name: str = Form(...), photo: UploadFile = File(...)):
    guard = _require_admin(request)
    if guard:
        return guard
    try:
        import cv2
        import numpy as np

        raw = await photo.read(10 * 1024 * 1024 + 1)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Image file could not be read")
        recognizer = get_face_recognizer(RECOGNITION_MODELS_DIR)
        if recognizer is None:
            raise RuntimeError("Face recognition model could not be loaded")
        faces = recognizer.detect_and_embed(image)
        if not faces:
            raise ValueError("No face found in the photo")
        face = max(faces, key=lambda item: item["score"])
        database.create_known_face(
            SETTINGS.database_path, name=name.strip(), embedding=json.dumps(face["embedding"])
        )
        _set_flash(request, "face.saved", {"name": name.strip()})
    except Exception as exc:
        _set_flash(request, "face.save_failed", {"error": exc}, "error")
    finally:
        await photo.close()
    return _redirect("/recognition")

@router.post("/recognition/faces/{face_id}/delete")
async def delete_known_face_route(request: Request, face_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_known_face(SETTINGS.database_path, face_id)
    _set_flash(request, "face.removed")
    return _redirect("/recognition")

@router.post("/recognition/plates")
async def create_known_plate_route(request: Request, plate_text: str = Form(...), label: str = Form("")):
    guard = _require_admin(request)
    if guard:
        return guard
    database.create_known_plate(SETTINGS.database_path, plate_text=plate_text, label=label.strip() or None)
    _set_flash(request, "plate.saved")
    return _redirect("/recognition")

@router.post("/recognition/plates/{plate_id}")
async def update_known_plate_route(
    request: Request, plate_id: int, plate_text: str = Form(...), label: str = Form("")
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_known_plate(SETTINGS.database_path, plate_id, plate_text=plate_text, label=label.strip() or None)
    _set_flash(request, "plate.updated")
    return _redirect("/recognition")

@router.post("/recognition/plates/{plate_id}/delete")
async def delete_known_plate_route(request: Request, plate_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    database.delete_known_plate(SETTINGS.database_path, plate_id)
    _set_flash(request, "plate.removed")
    return _redirect("/recognition")
