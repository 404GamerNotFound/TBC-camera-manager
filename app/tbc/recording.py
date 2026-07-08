from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import database, mqtt
from .config import load_settings
from .notifications import notify_event

LOGGER = logging.getLogger(__name__)
PREBUFFER_ROOT = Path("/tmp/tbc-prebuffer")


@dataclass(frozen=True)
class RecordingJob:
    recording_id: int
    camera_id: int
    camera_name: str
    stream_uri: str
    detection_key: str
    event_label: str
    duration_seconds: int
    pre_seconds: int
    post_seconds: int
    snapshot_enabled: bool
    storage_target: dict[str, Any]


@dataclass
class ActiveRecording:
    started_at: datetime
    min_until: datetime
    active_until: datetime


class RecordingManager:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._active: dict[tuple[int, str], ActiveRecording] = {}
        self._last_started: dict[tuple[int, str], datetime] = {}
        self._prebuffers: dict[int, subprocess.Popen] = {}

    def maybe_start_event_recordings(
        self,
        camera: dict[str, Any],
        detections: list[dict[str, Any]],
    ) -> bool:
        if int(camera.get("recording_enabled") or 0) != 1:
            self._stop_prebuffer(int(camera["id"]))
            return False
        if not camera.get("stream_uri"):
            return False

        camera_id = int(camera["id"])
        pre_seconds = max(0, min(120, int(camera.get("recording_pre_seconds") or 0)))
        self._ensure_prebuffer(camera, pre_seconds)

        trigger_keys = database.list_camera_recording_triggers(self.database_path, camera_id) or ["motion"]
        active_events = _active_events(detections, trigger_keys)
        if not active_events:
            return False

        started_any = False
        for detection_key, event_label in active_events:
            active_key = (camera_id, detection_key)
            now = datetime.utcnow()
            post_seconds = max(0, min(600, int(camera.get("recording_post_seconds") or 10)))
            if active_key in self._active:
                self._active[active_key].active_until = now + timedelta(seconds=post_seconds)
                continue
            if self._event_is_in_cooldown(active_key, int(camera.get("recording_cooldown_seconds") or 0)):
                continue

            storage_id = camera.get("recording_storage_id")
            storage_target = (
                database.get_storage_target(self.database_path, int(storage_id))
                if storage_id
                else _first_storage_target(self.database_path)
            )
            if storage_target is None:
                _record_and_publish_event(
                    self.database_path,
                    camera_id,
                    "recording_skipped",
                    detection_key,
                    "Kein Speicherziel konfiguriert",
                )
                continue

            duration_seconds = max(5, min(3600, int(camera.get("recording_duration_seconds") or 30)))
            active = ActiveRecording(
                started_at=now,
                min_until=now + timedelta(seconds=duration_seconds),
                active_until=now + timedelta(seconds=post_seconds),
            )
            recording_id = database.create_recording(
                self.database_path,
                camera_id=camera_id,
                storage_id=int(storage_target["id"]),
                detection_key=detection_key,
                event_label=event_label,
                storage_kind=str(storage_target["kind"]),
                started_at=now.isoformat(timespec="seconds"),
            )
            job = RecordingJob(
                recording_id=recording_id,
                camera_id=camera_id,
                camera_name=str(camera["name"]),
                stream_uri=str(camera["stream_uri"]),
                detection_key=detection_key,
                event_label=event_label,
                duration_seconds=duration_seconds,
                pre_seconds=pre_seconds,
                post_seconds=post_seconds,
                snapshot_enabled=bool(int(camera.get("snapshot_enabled") or 0)),
                storage_target=storage_target,
            )
            self._active[active_key] = active
            self._last_started[active_key] = now
            database.mark_recording_started(self.database_path, camera_id)
            _record_and_publish_event(
                self.database_path,
                camera_id,
                "recording_started",
                detection_key,
                f"{event_label}: Vorlauf {pre_seconds}s, Nachlauf {post_seconds}s",
            )
            asyncio.create_task(self._run_job(job, active))
            started_any = True
        return started_any

    async def _run_job(self, job: RecordingJob, active: ActiveRecording) -> None:
        try:
            result = await asyncio.to_thread(_record_clip, job, active)
            database.update_recording_finished(
                self.database_path,
                job.recording_id,
                status="ready",
                file_name=result["file_name"],
                local_path=result.get("local_path"),
                remote_key=result.get("remote_key"),
                snapshot_path=result.get("snapshot_path"),
                snapshot_remote_key=result.get("snapshot_remote_key"),
                duration_seconds=result["duration_seconds"],
                size_bytes=result["size_bytes"],
                message=None,
                ended_at=result["ended_at"],
            )
            recording = database.get_recording(self.database_path, job.recording_id)
            notify_event(
                self.database_path,
                event_type="recording_finished",
                title=f"TBC: {job.event_label}",
                message=f"{job.camera_name}: Clip wurde gespeichert",
                recording=recording,
                public_base_url=load_settings().public_base_url,
            )
            _record_and_publish_event(
                self.database_path,
                job.camera_id,
                "recording_finished",
                job.detection_key,
                result["file_name"],
            )
        except Exception as exc:
            LOGGER.exception("Recording failed for camera %s", job.camera_id)
            database.update_recording_finished(
                self.database_path,
                job.recording_id,
                status="failed",
                message=str(exc),
                ended_at=datetime.utcnow().isoformat(timespec="seconds"),
            )
            notify_event(
                self.database_path,
                event_type="recording_failed",
                title="TBC: Aufnahme fehlgeschlagen",
                message=f"{job.camera_name}: {exc}",
                public_base_url=load_settings().public_base_url,
            )
            _record_and_publish_event(
                self.database_path,
                job.camera_id,
                "recording_failed",
                job.detection_key,
                str(exc),
            )
        finally:
            self._active.pop((job.camera_id, job.detection_key), None)

    def _ensure_prebuffer(self, camera: dict[str, Any], pre_seconds: int) -> None:
        camera_id = int(camera["id"])
        if pre_seconds <= 0:
            self._stop_prebuffer(camera_id)
            return
        if shutil.which("ffmpeg") is None:
            return
        process = self._prebuffers.get(camera_id)
        if process and process.poll() is None:
            return

        buffer_dir = PREBUFFER_ROOT / str(camera_id)
        shutil.rmtree(buffer_dir, ignore_errors=True)
        buffer_dir.mkdir(parents=True, exist_ok=True)
        segment_wrap = max(12, pre_seconds + 6)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            str(camera["stream_uri"]),
            "-an",
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            "1",
            "-reset_timestamps",
            "1",
            "-segment_wrap",
            str(segment_wrap),
            str(buffer_dir / "pre%03d.ts"),
        ]
        try:
            self._prebuffers[camera_id] = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            LOGGER.exception("Failed to start prebuffer for camera %s", camera_id)

    def _stop_prebuffer(self, camera_id: int) -> None:
        process = self._prebuffers.pop(camera_id, None)
        if process and process.poll() is None:
            process.terminate()

    def _event_is_in_cooldown(self, active_key: tuple[int, str], cooldown_seconds: int) -> bool:
        last_started = self._last_started.get(active_key)
        if last_started is None:
            return False
        return datetime.utcnow() < last_started + timedelta(seconds=max(0, cooldown_seconds))


def _record_clip(job: RecordingJob, active: ActiveRecording) -> dict[str, Any]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg ist im Container nicht installiert")

    target = job.storage_target
    target_is_s3 = target["kind"] == "s3"
    local_base_path = Path("/tmp/tbc-recordings") if target_is_s3 else Path(target.get("local_path") or "/recordings")
    local_base_path.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"tbc-{job.camera_id}-"))

    try:
        pre_segments = _copy_prebuffer_segments(job.camera_id, job.pre_seconds, work_dir)
        body_ts = work_dir / "body.ts"
        _record_body(job.stream_uri, body_ts, active)

        filename = f"{active.started_at:%Y%m%d-%H%M%S}-{_slug(job.camera_name)}-{_slug(job.detection_key)}.mp4"
        output_file = local_base_path / filename
        _build_mp4(pre_segments, body_ts, output_file, work_dir)
        snapshot_path = _create_snapshot(output_file, job.snapshot_enabled)

        ended_at = datetime.utcnow()
        size_bytes = output_file.stat().st_size if output_file.exists() else 0
        duration_seconds = max(1, int((ended_at - active.started_at).total_seconds()))
        result = {
            "file_name": filename,
            "local_path": str(output_file),
            "snapshot_path": str(snapshot_path) if snapshot_path else None,
            "remote_key": None,
            "snapshot_remote_key": None,
            "duration_seconds": duration_seconds,
            "size_bytes": size_bytes,
            "ended_at": ended_at.isoformat(timespec="seconds"),
        }
        if target_is_s3:
            result["remote_key"] = _upload_to_s3(output_file, target)
            if snapshot_path:
                result["snapshot_remote_key"] = _upload_to_s3(snapshot_path, target)
                snapshot_path.unlink(missing_ok=True)
            output_file.unlink(missing_ok=True)
            result["local_path"] = None
            result["snapshot_path"] = None
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _record_body(stream_uri: str, body_ts: Path, active: ActiveRecording) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-y",
        "-i",
        stream_uri,
        "-an",
        "-c",
        "copy",
        "-f",
        "mpegts",
        str(body_ts),
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while datetime.utcnow() < max(active.min_until, active.active_until):
            time.sleep(0.5)
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
    if not body_ts.exists() or body_ts.stat().st_size == 0:
        raise RuntimeError("ffmpeg hat keinen Videoclip erzeugt")


def _build_mp4(pre_segments: list[Path], body_ts: Path, output_file: Path, work_dir: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if pre_segments:
        concat_file = work_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{segment.as_posix()}'\n" for segment in [*pre_segments, body_ts]),
            encoding="utf-8",
        )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
    else:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(body_ts),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError("ffmpeg konnte den MP4-Clip nicht erzeugen")


def _create_snapshot(video_file: Path, enabled: bool) -> Path | None:
    if not enabled:
        return None
    snapshot_file = video_file.with_suffix(".jpg")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_file),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(snapshot_file),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not snapshot_file.exists() or snapshot_file.stat().st_size == 0:
        return None
    return snapshot_file


def _copy_prebuffer_segments(camera_id: int, pre_seconds: int, work_dir: Path) -> list[Path]:
    if pre_seconds <= 0:
        return []
    source_dir = PREBUFFER_ROOT / str(camera_id)
    if not source_dir.exists():
        return []
    cutoff = time.time() - pre_seconds - 1
    segments = [
        path
        for path in source_dir.glob("*.ts")
        if path.is_file() and path.stat().st_size > 0 and path.stat().st_mtime >= cutoff
    ]
    copied: list[Path] = []
    for index, segment in enumerate(sorted(segments, key=lambda item: item.stat().st_mtime)):
        target = work_dir / f"pre_{index:03d}.ts"
        try:
            shutil.copy2(segment, target)
            copied.append(target)
        except OSError:
            LOGGER.debug("Could not copy prebuffer segment %s", segment, exc_info=True)
    return copied


def delete_recording_files(recording: dict[str, Any]) -> None:
    for key in ("local_path", "snapshot_path"):
        path = recording.get(key)
        if path:
            Path(path).unlink(missing_ok=True)
    for key in ("remote_key", "snapshot_remote_key"):
        remote_key = recording.get(key)
        if remote_key:
            _delete_s3_object(remote_key, recording)


def presigned_url(recording: dict[str, Any], *, snapshot: bool = False) -> str | None:
    key = recording.get("snapshot_remote_key" if snapshot else "remote_key")
    if not key:
        return None
    client = _s3_client(recording)
    bucket = recording.get("s3_bucket")
    if not bucket:
        return None
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=3600,
    )


def _upload_to_s3(local_file: Path, target: dict[str, Any]) -> str:
    bucket = target.get("s3_bucket")
    if not bucket:
        raise RuntimeError("S3-Bucket fehlt")
    prefix = (target.get("s3_prefix") or "").strip("/")
    key = f"{prefix}/{local_file.name}" if prefix else local_file.name
    _s3_client(target).upload_file(str(local_file), bucket, key)
    return key


def _delete_s3_object(remote_key: str, target: dict[str, Any]) -> None:
    bucket = target.get("s3_bucket")
    if not bucket:
        return
    _s3_client(target).delete_object(Bucket=bucket, Key=remote_key)


def _s3_client(target: dict[str, Any]):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 ist fuer S3-Speicherziele nicht installiert") from exc
    return boto3.client(
        "s3",
        endpoint_url=target.get("s3_endpoint_url") or None,
        region_name=target.get("s3_region") or None,
        aws_access_key_id=target.get("s3_access_key_id") or None,
        aws_secret_access_key=target.get("s3_secret_access_key") or None,
    )


def _active_events(detections: list[dict[str, Any]], trigger_keys: list[str]) -> list[tuple[str, str]]:
    triggers = set(trigger_keys)
    events: list[tuple[str, str]] = []
    for detection in detections:
        raw_key = str(detection.get("key") or "")
        base_key = raw_key.split(":", 1)[-1]
        if not detection.get("active"):
            continue
        if raw_key in triggers or base_key in triggers:
            events.append((base_key, str(detection.get("label") or base_key)))
    return events


def _motion_is_active(detections: list[dict[str, Any]]) -> bool:
    return bool(_active_events(detections, ["motion"]))


def _first_storage_target(database_path: str) -> dict[str, Any] | None:
    targets = database.list_storage_targets(database_path)
    return targets[0] if targets else None


def _record_and_publish_event(
    database_path: str,
    camera_id: int,
    event_type: str,
    detection_key: str,
    payload: str | None,
) -> None:
    database.record_event(
        database_path,
        camera_id,
        event_type=event_type,
        source="recorder",
        detection_key=detection_key,
        payload=payload,
    )
    mqtt.publish_event(
        database_path,
        camera_id=camera_id,
        event_type=event_type,
        detection_key=detection_key,
        payload=payload,
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "kamera"
