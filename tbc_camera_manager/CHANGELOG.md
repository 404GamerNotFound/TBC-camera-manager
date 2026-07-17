# Changelog

## 0.5.0 - "Connected"

- Added a "control" scope to API tokens: a token can now optionally be allowed to change camera and detection settings, not just read them. Existing tokens stay read-only.
- Added write endpoints under `/api/v1/cameras/{id}/recording`, `/continuous-recording`, and `/detection` for control-scoped tokens, and a new read endpoint at `/api/v1/cameras/{id}/detection-settings`.
- Added an API-token-authenticated live stream (`/api/v1/cameras/{id}/stream/index.m3u8`) reusing the existing HLS pipeline, for external integrations such as Home Assistant - separate from the browser session's own live view.
- Added the official [TBC Home Assistant integration](https://github.com/404GamerNotFound/TBC-ha_integration), a custom_component built against this release's API: cameras with live streaming, last-motion sensors, health/storage sensors, and read/write camera settings.

## 0.4.0 - "Secure & Reliable"

- Added at-rest encryption for stored secrets (camera passwords, cloud account secrets, S3 keys, MQTT and notification credentials), derived from `TBC_SECRET_KEY`. Existing plaintext values are encrypted in place on first startup after upgrading.
- Added encrypted backup and restore: download a full config/database backup from Settings > Backup & restore, and restore it back (a safety copy of the current database is kept automatically).
- Added an audit log covering login/logout, user management, API token and camera credential changes, storage/MQTT settings changes, backup/restore, and recording lock/unlock/delete, viewable and filterable at Settings > Audit log.
- Replaced the single global API key with support for multiple named, independently revocable API tokens.
- Added lockable/protected recordings: locked clips are exempt from retention cleanup and cannot be deleted until unlocked.

## 0.3.0

- Added local face recognition (opt-in, snapshot or live mode) with a face enrollment page and match/unknown notifications.
- Added local license plate recognition (opt-in, snapshot or live mode) with known-plate management.
- Added self-hosted push notification channels: ntfy and Gotify.
- Added search and pagination to the Clips view.
- Added SD card recordings to the Activity overview, with a checkbox to include or exclude them.
- Added a License page listing every third-party dependency and model used, with its license.
- Fixed static assets (JS/CSS) not refreshing in browsers after an update.
- Fixed a dependency conflict and known vulnerabilities in FastAPI, Starlette, and python-multipart.
- Updated numpy, Pillow, onnxruntime, boto3, uiprotect, and the base Python image.

## 0.2.1

- Fixed JSON decoding for Home Assistant build metadata.
- Added an anonymous GHCR pull check after publishing the multi-architecture image.

## 0.2.0

- Initial Home Assistant app packaging for `amd64` and `aarch64`.
- Persistent app data and a separately mounted recording directory.
- Shared application image for Home Assistant and standalone Docker deployments.
