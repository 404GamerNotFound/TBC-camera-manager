"""AI detection overview and face/plate recognition.

Extracted from app/tbc/main.py - see that file's router-include block
at the bottom for why the `from ..main import (...)` below is safe
despite looking circular.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import automation, database
from ..detection import factory as detection_factory
from ..detection.clip_backend import clip_models_ready
from ..detection.recognition import (
    get_face_recognizer,
)
from fastapi import APIRouter

from ..main import (
    DETECTION_CORAL_MODEL_PATH,
    DETECTION_HAILO_MODEL_PATH,
    DETECTION_MODEL_PATH,
    RECOGNITION_EVENTS_PAGE_SIZE,
    RECOGNITION_MODELS_DIR,
    SETTINGS,
    _parse_optional_int,
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
    hailo_model_ready = DETECTION_HAILO_MODEL_PATH.exists() and DETECTION_HAILO_MODEL_PATH.stat().st_size > 0
    search_settings = database.get_search_settings(SETTINGS.database_path)
    search_model_name = str(search_settings["model_name"])
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
            "hailo_model_ready": hailo_model_ready,
            "hailo_model_size_mb": round(DETECTION_HAILO_MODEL_PATH.stat().st_size / (1024 * 1024), 1) if hailo_model_ready else None,
            "hailo_model_path": str(DETECTION_HAILO_MODEL_PATH),
            "default_sample_fps": SETTINGS.detection_default_sample_fps,
            "default_confidence_threshold": SETTINGS.detection_default_confidence_threshold,
            "search_settings": search_settings,
            "search_model_ready": clip_models_ready(RECOGNITION_MODELS_DIR, search_model_name),
            "search_model_path": str(RECOGNITION_MODELS_DIR / "clip" / search_model_name),
            "search_embedded_count": database.count_recording_embeddings(SETTINGS.database_path, search_model_name),
            "search_missing_count": database.count_recordings_missing_embedding(SETTINGS.database_path, search_model_name),
            "cameras": database.list_enabled_camera_detection_settings(SETTINGS.database_path),
            "flash": _pop_flash(request),
        },
    )

@router.get("/recognition", response_class=HTMLResponse)
async def recognition_page(
    request: Request,
    camera_id: str | None = Query(None),
    kind: str | None = Query(None),
    identity: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1),
):
    guard = _require_admin(request)
    if guard:
        return guard
    camera_id = _parse_optional_int(camera_id)
    matched_face_id, matched_plate_id, unknown_only = automation.parse_identity_filter(identity)
    common_filters = {
        "camera_id": camera_id,
        "kind": kind or None,
        "matched_face_id": matched_face_id,
        "matched_plate_id": matched_plate_id,
        "unknown_only": unknown_only,
        "date_from": date_from or None,
        "date_to": date_to or None,
    }
    total = database.count_recognition_events(SETTINGS.database_path, **common_filters)
    total_pages = max(1, math.ceil(total / RECOGNITION_EVENTS_PAGE_SIZE))
    current_page = min(max(1, page), total_pages)
    events = database.list_recognition_events(
        SETTINGS.database_path,
        **common_filters,
        limit=RECOGNITION_EVENTS_PAGE_SIZE,
        offset=(current_page - 1) * RECOGNITION_EVENTS_PAGE_SIZE,
    )
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
            "cameras": database.list_cameras(SETTINGS.database_path),
            "recent_events": events,
            "filters": {
                "camera_id": camera_id,
                "kind": kind or "",
                "identity": identity or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
            "total": total,
            "page": current_page,
            "total_pages": total_pages,
            "flash": _pop_flash(request),
        },
    )


@router.get("/recognition/events/{event_id}/snapshot")
async def recognition_event_snapshot(request: Request, event_id: int):
    guard = _require_admin(request)
    if guard:
        return guard
    event = database.get_recognition_event(SETTINGS.database_path, event_id)
    if not event:
        return JSONResponse({"error": "not found"}, status_code=status.HTTP_404_NOT_FOUND)
    snapshot_path = event.get("snapshot_path")
    if not snapshot_path or not Path(snapshot_path).exists():
        return JSONResponse({"error": "snapshot not available"}, status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(snapshot_path, media_type="image/jpeg")

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

@router.post("/search/settings")
async def update_search_settings_route(
    request: Request,
    enabled: str | None = Form(None),
    model_name: str = Form(...),
):
    guard = _require_admin(request)
    if guard:
        return guard
    database.update_search_settings(
        SETTINGS.database_path,
        enabled=bool(enabled),
        model_name=model_name.strip() or "ViT-B-32__openai",
    )
    _set_flash(request, "search.settings_saved")
    return _redirect("/detection")

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
