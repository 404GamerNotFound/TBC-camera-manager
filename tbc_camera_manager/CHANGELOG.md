# Changelog

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
