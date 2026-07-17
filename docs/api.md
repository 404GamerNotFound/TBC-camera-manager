# External API (`/api/v1/...`)

In addition to the internal `/api/...` routes, which use session-cookie authentication for the
web UI, TBC provides a standalone API for external scripts, dashboards, and integrations such
as the [TBC Home Assistant integration](https://github.com/404GamerNotFound/TBC-ha_integration)
under `/api/v1/...`. It returns exactly the content configured in the running installation: a
camera without AI detection enabled returns an empty detection list, and an installation
without recordings returns an empty recording list.

Most of the API is read-only. A small set of settings-changing endpoints and a live-stream
endpoint exist for integrations that need them (see below) and require a token with the
**control** scope - a plain token still cannot write anything or start a stream.

## Enabling the API

Open `Admin → Settings` (`/settings`) and find the **API access** section:

- **Enable API** is the main switch. When disabled, all `/api/v1/...` routes return `404`,
  regardless of the API key.
- **Require API key** controls authentication. When disabled while the main switch is enabled,
  the API is completely open and requires no key (this also disables control-scope checks - do
  not use this alongside the write endpoints). Use this only in trusted, isolated networks.
- Under **API tokens**, create a separate named token per integration (e.g. one for Home
  Assistant, one for a dashboard). Each token is displayed **exactly once**, right after
  creation - TBC stores only its SHA-256 hash (`app/tbc/security.py`, `hash_api_key` and
  `verify_api_key`) and cannot display the plaintext token again. Revoke a token individually
  from the same table without affecting any other token.
- Check **Allow control (write access)** when creating a token to let it use the write and
  stream endpoints below. Leave it unchecked for read-only integrations (dashboards, monitoring
  scripts) - least privilege by default.

The API is disabled by default in a new installation.

## Authentication

Send the key as a bearer token or through the dedicated header:

```text
Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

or:

```text
X-API-Key: tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

An API key has full read access to every camera, regardless of viewer restrictions on
individual user accounts (`user_camera_access`). Each token is independent - see
`GET /api/v1/status` to check whether the token in use has control access
(`"api_can_control": true/false`).

The three live-stream endpoints additionally accept the key as a `?api_key=` query parameter,
since the HLS segments are fetched directly by a video player/decoder that cannot attach a
custom header to every request. This is less safe than the header forms (visible in access
logs, proxies, browser history) - prefer a header wherever the client supports it, and keep
TBC reachable only from trusted networks when using stream URLs.

## Endpoints

All responses are JSON unless marked as binary. Endpoints marked **control** require a token
created with "Allow control" checked; every other endpoint works with any valid token.

| Method and path | Description |
|---|---|
| `GET /api/v1/status` | Application name, version, update availability, camera count, and whether the current token has control access |
| `GET /api/v1/cameras` | All cameras, including capabilities, status, and detection counters |
| `GET /api/v1/cameras/{id}` | One camera |
| `GET /api/v1/cameras/{id}/snapshot` | Current preview image (binary JPEG) |
| `GET /api/v1/cameras/{id}/detections` | Current detection state for the camera |
| `GET /api/v1/cameras/{id}/detection-settings` | The camera's AI detection settings (enabled, backend, confidence threshold, sample FPS) |
| `POST /api/v1/cameras/{id}/recording` **(control)** | Update event-recording settings. JSON body, all fields optional - only given fields change: `enabled`, `duration_seconds`, `pre_seconds`, `post_seconds`, `cooldown_seconds`, `snapshot_enabled`, `storage_id`, `trigger_keys` |
| `POST /api/v1/cameras/{id}/continuous-recording` **(control)** | Update 24/7 recording settings. JSON body: `enabled`, `segment_seconds`, `storage_id` |
| `POST /api/v1/cameras/{id}/detection` **(control)** | Update AI detection settings. JSON body: `enabled`, `confidence_threshold`, `sample_fps`, `backend` |
| `GET /api/v1/cameras/{id}/stream/index.m3u8` | Live HLS playlist for the camera, started on demand. `404` if the camera has no live capability or no reachable stream is known |
| `GET /api/v1/cameras/{id}/stream/{segment}` | HLS video segment (binary, `video/mp2t`) |
| `POST /api/v1/cameras/{id}/stream/stop` | Stop the live stream process for this camera started via the endpoint above |
| `GET /api/v1/recordings` | Recording list. Query parameters: `camera_id`, `detection_key`, `date_from`, `date_to`, and `limit` (default 200, maximum 1000) |
| `GET /api/v1/recordings/{id}` | Metadata for one recording |
| `GET /api/v1/recordings/{id}/media` | Video clip (binary MP4 with HTTP Range support) |
| `GET /api/v1/recordings/{id}/snapshot` | Event preview image (binary JPEG) |
| `GET /api/v1/activity` | Event recordings across all cameras for one day. Query parameter: `day` (`YYYY-MM-DD`, defaults to today) |
| `GET /api/v1/storage` | Configured storage targets without credentials |
| `GET /api/v1/health` | System utilization, health status, and health events |

Camera credentials, storage or MQTT credentials, and the API-key hash never appear in a
response. Any `stream_uri` included in a camera object is returned without credentials using
`redact_rtsp_credentials`, as elsewhere in TBC - the live-stream endpoints above exist
precisely so an external client can still watch the stream without ever seeing those
credentials, since TBC resolves and holds them server-side.

The three write endpoints apply a **partial update**: any field left out of the JSON body keeps
its current value, so `{"enabled": true}` only flips the enabled flag without needing to resend
every other setting. Every successful write is recorded in the audit log
(`Admin → Settings → Audit log`), attributed to `api-token:<token name>`.

The `.../stream/...` endpoints reuse the same HLS pipeline as TBC's own browser live view, under
a separate stream key so they don't interfere with a logged-in user watching the same camera.
The stream starts automatically on the first request to `index.m3u8` (no separate "start" call
needed) and keeps running until stopped or the camera is reprobed; call the `stop` endpoint when
your integration is done watching to free the ffmpeg process.

## Examples

```bash
curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     https://tbc.example.com/api/v1/cameras

curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     "https://tbc.example.com/api/v1/recordings?camera_id=1&limit=20" \
  | jq '.recordings[0]'

curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     -o clip.mp4 \
     https://tbc.example.com/api/v1/recordings/42/media

# Requires a control-scoped token:
curl -X POST -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     -H "Content-Type: application/json" -d '{"enabled": true}' \
     https://tbc.example.com/api/v1/cameras/1/recording

# Live stream (any valid token; ?api_key= also accepted for direct player use):
ffplay "https://tbc.example.com/api/v1/cameras/1/stream/index.m3u8?api_key=tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```
