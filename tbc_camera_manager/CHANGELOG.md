# Changelog

## 0.6.1 - "Integrated, properly"

- Fixed a bug in 0.6.0's Home Assistant Ingress support: setting the ASGI `root_path` to make
  link generation prefix-aware broke routing for mounted sub-apps (`/static`, `/mcp`) instead,
  making every CSS/JS asset 404 and the page render blank when opened from the sidebar. Every
  outgoing URL is now built with a plain, manually prefixed path instead.
- A camera on a plugin that was missing a Python requirement (e.g. Reolink without
  `reolink-aio`) is now refreshed automatically right after the missing package is installed,
  instead of keeping a stale probe result on its detail page until the next background poll or
  a manual **Refresh** click.

## 0.6.0 - "Integrated"

- Added Home Assistant Ingress support: TBC now appears in the Home Assistant sidebar, and
  **Open Web UI** works through Supervisor's own proxy instead of a direct connection to the
  container's port. HLS live view works fully through Ingress; WebRTC live view still needs
  direct network access to port `8555`, since its media stream can't be tunneled by any
  HTTP-only reverse proxy.
- Camera, cloud, and network plugins can now declare their own pip requirements in their
  manifest (`"requirements": [...]`) instead of needing them added to TBC's own
  `requirements.txt`. A missing requirement blocks installation with an explicit admin
  confirmation step before anything is installed - never silently.
- Moved the `eufy`, `unifi_protect`, and `ewelink` cloud plugins out of the main repository into
  their own installable plugin repositories (`TBC-eufy`, `TBC-unifi-protect`, `TBC-ewelink`),
  matching how every other vendor integration is already packaged.
- Added a FRITZ!Box network plugin (`TBC-fritz.box`) for camera-to-device mapping and live
  connectivity status.
- Fixed a regression where `onvif-zeep` was missing from `requirements.txt`, breaking ONVIF
  connectivity for cameras that rely on it (including Reolink's ONVIF fallback).
- Fixed plugin dependency installation on a fresh deployment: the first `pip install` of a
  plugin's requirement wasn't picked up by the running process because its target directory
  didn't exist yet at startup.

## 0.5.1 - "Installable"

- Fixed Home Assistant installation and updates by automatically publishing the matching public
  multi-architecture image whenever the advertised app version changes on `main`.
- Added the repository documentation to the runtime image so the in-app Docs viewer also works in
  Docker and Home Assistant installations.
- Added package tests that keep the app version, image contents, and release triggers consistent.

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
