# External read API (`/api/v1/...`)

In addition to the internal `/api/...` routes, which use session-cookie authentication for the
web UI, TBC provides a standalone, read-only API for external scripts, dashboards, and Home
Assistant integrations under `/api/v1/...`. It returns exactly the content configured in the
running installation: a camera without AI detection enabled returns an empty detection list,
and an installation without recordings returns an empty recording list. There are currently
no write or control endpoints (no PTZ, camera creation, or settings changes); access is
read-only.

## Enabling the API

Open `Admin → Settings` (`/settings`) and find the **API access** section:

- **Enable API** is the main switch. When disabled, all `/api/v1/...` routes return `404`,
  regardless of the API key.
- **Require API key** controls authentication. When disabled while the main switch is enabled,
  the API is completely open and requires no key. Use this only in trusted, isolated networks.
- **Generate new key** creates a key and displays it **exactly once** in the confirmation
  message. TBC stores only its SHA-256 hash (`app/tbc/security.py`, `hash_api_key` and
  `verify_api_key`) and cannot display the plaintext key again. A new key immediately replaces
  the previously active key.
- **Revoke key** immediately deactivates the current key.

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
individual user accounts (`user_camera_access`). There is currently one global key per
installation, not one key per user.

## Endpoints

All responses are JSON unless marked as binary.

| Method and path | Description |
|---|---|
| `GET /api/v1/status` | Application name, version, update availability, and camera count |
| `GET /api/v1/cameras` | All cameras, including capabilities, status, and detection counters |
| `GET /api/v1/cameras/{id}` | One camera |
| `GET /api/v1/cameras/{id}/snapshot` | Current preview image (binary JPEG) |
| `GET /api/v1/cameras/{id}/detections` | Current detection state for the camera |
| `GET /api/v1/recordings` | Recording list. Query parameters: `camera_id`, `detection_key`, `date_from`, `date_to`, and `limit` (default 200, maximum 1000) |
| `GET /api/v1/recordings/{id}` | Metadata for one recording |
| `GET /api/v1/recordings/{id}/media` | Video clip (binary MP4 with HTTP Range support) |
| `GET /api/v1/recordings/{id}/snapshot` | Event preview image (binary JPEG) |
| `GET /api/v1/activity` | Event recordings across all cameras for one day. Query parameter: `day` (`YYYY-MM-DD`, defaults to today) |
| `GET /api/v1/storage` | Configured storage targets without credentials |
| `GET /api/v1/health` | System utilization, health status, and health events |

Camera credentials, storage or MQTT credentials, and the API-key hash never appear in a
response. Any `stream_uri` included in a camera object is returned without credentials using
`redact_rtsp_credentials`, as elsewhere in TBC.

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
```
