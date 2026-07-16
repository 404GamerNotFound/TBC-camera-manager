from __future__ import annotations

import asyncio
import json
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
CONTINUOUS_ROOT = Path("/tmp/tbc-continuous")
_SEGMENT_NAME_RE = re.compile(r"_(\d{8}T\d{6})\.mp4$")


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
    bbox: tuple[float, float, float, float] | None = None


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
                bbox=_bbox_for_active_event(detections, detection_key),
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
            if result.get("snapshot_path"):
                await asyncio.to_thread(_run_snapshot_recognition, self.database_path, job, result["snapshot_path"])
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
            "-fflags",
            "+genpts+discardcorrupt",
            "-use_wallclock_as_timestamps",
            "1",
            "-rtsp_transport",
            "tcp",
            "-i",
            str(camera["stream_uri"]),
            "-an",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
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


class ContinuousRecordingManager:
    """Runs a 24/7 ffmpeg segmenter per camera and registers finished chunks as recordings."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._processes: dict[int, subprocess.Popen] = {}
        self._fingerprints: dict[int, tuple[Any, ...]] = {}
        self._last_start: dict[int, datetime] = {}
        self._known_files: dict[int, set[str]] = {}

    def sync(self, cameras: list[dict[str, Any]]) -> None:
        active_ids: set[int] = set()
        for camera in cameras:
            if int(camera.get("enabled") or 0) != 1:
                continue
            if int(camera.get("continuous_recording_enabled") or 0) != 1:
                continue
            if not camera.get("stream_uri"):
                continue
            camera_id = int(camera["id"])
            active_ids.add(camera_id)
            try:
                self._ensure_process(camera)
                self._collect_segments(camera)
            except Exception:
                LOGGER.exception("Continuous recording sync failed for camera %s", camera_id)

        for camera_id in list(self._processes):
            if camera_id in active_ids:
                continue
            self._stop_process(camera_id)
            camera = database.get_camera(self.database_path, camera_id)
            if camera is not None:
                try:
                    self._collect_segments(camera, include_latest=True)
                except Exception:
                    LOGGER.exception("Failed to finalize continuous segments for camera %s", camera_id)
            self._known_files.pop(camera_id, None)

    def _ensure_process(self, camera: dict[str, Any]) -> None:
        camera_id = int(camera["id"])
        segment_seconds = max(60, min(1800, int(camera.get("continuous_segment_seconds") or 300)))
        fingerprint = (camera["stream_uri"], segment_seconds)

        existing = self._processes.get(camera_id)
        if existing is not None:
            if existing.poll() is None and self._fingerprints.get(camera_id) == fingerprint:
                return
            self._stop_process(camera_id)

        last_start = self._last_start.get(camera_id)
        if last_start and datetime.utcnow() < last_start + timedelta(seconds=5):
            return
        if shutil.which("ffmpeg") is None:
            return

        work_dir = CONTINUOUS_ROOT / str(camera_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        pattern = work_dir / f"{_slug(str(camera['name']))}_%Y%m%dT%H%M%S.mp4"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts+discardcorrupt",
            "-use_wallclock_as_timestamps",
            "1",
            "-rtsp_transport",
            "tcp",
            "-i",
            str(camera["stream_uri"]),
            "-an",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            "-segment_format_options",
            "movflags=+faststart",
            str(pattern),
        ]
        try:
            self._processes[camera_id] = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._fingerprints[camera_id] = fingerprint
            self._last_start[camera_id] = datetime.utcnow()
        except Exception:
            LOGGER.exception("Failed to start continuous recording for camera %s", camera_id)

    def _stop_process(self, camera_id: int) -> None:
        process = self._processes.pop(camera_id, None)
        self._fingerprints.pop(camera_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)

    def _known_file_set(self, camera_id: int) -> set[str]:
        if camera_id not in self._known_files:
            self._known_files[camera_id] = set(
                database.list_continuous_file_names(self.database_path, camera_id)
            )
        return self._known_files[camera_id]

    def _collect_segments(self, camera: dict[str, Any], *, include_latest: bool = False) -> None:
        camera_id = int(camera["id"])
        work_dir = CONTINUOUS_ROOT / str(camera_id)
        if not work_dir.exists():
            return
        files = sorted((path for path in work_dir.glob("*.mp4") if path.is_file()), key=lambda path: path.name)
        if not files:
            return
        finished = files if include_latest else files[:-1]
        if not finished:
            return

        known = self._known_file_set(camera_id)
        storage_id = camera.get("continuous_storage_id")
        storage_target = (
            database.get_storage_target(self.database_path, int(storage_id))
            if storage_id
            else _first_storage_target(self.database_path)
        )

        for segment_path in finished:
            if segment_path.name in known:
                segment_path.unlink(missing_ok=True)
                continue
            self._register_segment(camera, segment_path, storage_target, camera.get("continuous_segment_seconds"))
            known.add(segment_path.name)

    def _register_segment(
        self,
        camera: dict[str, Any],
        segment_path: Path,
        storage_target: dict[str, Any] | None,
        default_duration: int | None,
    ) -> None:
        camera_id = int(camera["id"])
        match = _SEGMENT_NAME_RE.search(segment_path.name)
        if not match or storage_target is None or segment_path.stat().st_size == 0:
            segment_path.unlink(missing_ok=True)
            return
        try:
            started_at = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
        except ValueError:
            segment_path.unlink(missing_ok=True)
            return

        duration_seconds = _probe_duration(segment_path) or max(1, int(default_duration or 300))
        size_bytes = segment_path.stat().st_size
        ended_at = started_at + timedelta(seconds=duration_seconds)
        target_is_s3 = storage_target["kind"] == "s3"
        local_path: str | None = None
        remote_key: str | None = None

        try:
            if target_is_s3:
                remote_key = _upload_to_s3(segment_path, storage_target)
                segment_path.unlink(missing_ok=True)
            else:
                local_base = Path(storage_target.get("local_path") or "/recordings") / "continuous" / str(camera_id)
                local_base.mkdir(parents=True, exist_ok=True)
                destination = local_base / segment_path.name
                shutil.move(str(segment_path), str(destination))
                local_path = str(destination)
            database.create_continuous_recording(
                self.database_path,
                camera_id=camera_id,
                storage_id=int(storage_target["id"]),
                storage_kind=str(storage_target["kind"]),
                file_name=segment_path.name,
                local_path=local_path,
                remote_key=remote_key,
                duration_seconds=duration_seconds,
                size_bytes=size_bytes,
                started_at=started_at.isoformat(timespec="seconds"),
                ended_at=ended_at.isoformat(timespec="seconds"),
            )
        except Exception:
            LOGGER.exception("Failed to register continuous segment %s for camera %s", segment_path, camera_id)


def _probe_duration(path: Path) -> int | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return max(1, int(float(result.stdout.strip())))
    except Exception:
        return None


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
        snapshot_path = _create_snapshot(output_file, job.snapshot_enabled, bbox=job.bbox)

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
        "-fflags",
        "+genpts+discardcorrupt",
        "-use_wallclock_as_timestamps",
        "1",
        "-rtsp_transport",
        "tcp",
        "-y",
        "-i",
        stream_uri,
        "-an",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
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


def _create_snapshot(
    video_file: Path,
    enabled: bool,
    *,
    bbox: tuple[float, float, float, float] | None = None,
) -> Path | None:
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
    ]
    drawbox = _drawbox_filter(bbox)
    if drawbox:
        command += ["-vf", drawbox]
    command += [
        "-q:v",
        "3",
        str(snapshot_file),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not snapshot_file.exists() or snapshot_file.stat().st_size == 0:
        return None
    return snapshot_file


def _drawbox_filter(bbox: tuple[float, float, float, float] | None) -> str | None:
    """Builds an ffmpeg drawbox expression from a normalized (xmin, ymin, xmax, ymax) box.

    Uses ffmpeg's iw/ih (input width/height) expressions so no ffprobe call is needed
    to learn the actual pixel resolution first. The box reflects where the object was
    at the moment the event triggered, not necessarily the exact snapshot frame - it is
    approximate whenever a pre-roll shifts the snapshot away from that moment.
    """
    if not bbox:
        return None
    xmin, ymin, xmax, ymax = (max(0.0, min(1.0, value)) for value in bbox)
    width = max(0.01, xmax - xmin)
    height = max(0.01, ymax - ymin)
    return f"drawbox=x=iw*{xmin:.4f}:y=ih*{ymin:.4f}:w=iw*{width:.4f}:h=ih*{height:.4f}:color=red@0.9:thickness=4"


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


def _bbox_for_active_event(detections: list[dict[str, Any]], detection_key: str) -> tuple[float, float, float, float] | None:
    """Extracts the local-AI bounding box for the detection that triggered this event, if any.

    Only local_ai-sourced detections carry a box in raw_value; camera-native events
    (ONVIF/vendor) have no box to draw, so this returns None for them.
    """
    for detection in detections:
        raw_key = str(detection.get("key") or "")
        base_key = raw_key.split(":", 1)[-1]
        if base_key != detection_key or not detection.get("active"):
            continue
        if detection.get("source") != "local_ai":
            continue
        raw_value = detection.get("raw_value")
        if not raw_value:
            continue
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError):
            continue
        box = payload.get("box")
        if isinstance(box, list) and len(box) == 4:
            return tuple(float(value) for value in box)
    return None


def _first_storage_target(database_path: str) -> dict[str, Any] | None:
    targets = database.list_storage_targets(database_path)
    return targets[0] if targets else None


def _run_snapshot_recognition(database_path: str, job: RecordingJob, snapshot_path: str) -> None:
    """Runs face/plate recognition on a just-finished recording's snapshot (mode="snapshot").

    Called via asyncio.to_thread from _run_job since recognition inference is blocking; any
    failure here (missing opencv, unreadable image, model errors) is caught and logged - it must
    never break the recording job itself, matching the try/except discipline the rest of _run_job
    already uses around notifications.
    """
    try:
        import cv2

        from .detection.recognition import process_recognition

        image = cv2.imread(snapshot_path)
        if image is None:
            return
        settings = load_settings()
        process_recognition(
            database_path,
            Path(settings.detection_models_path),
            camera_id=job.camera_id,
            camera_name=job.camera_name,
            recording_id=job.recording_id,
            detection_key=job.detection_key,
            mode="snapshot",
            image=image,
            box=job.bbox,
            public_base_url=settings.public_base_url,
            existing_snapshot_path=snapshot_path,
        )
    except Exception:
        LOGGER.exception("Snapshot-Erkennung für Aufnahme %s fehlgeschlagen", job.recording_id)


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
