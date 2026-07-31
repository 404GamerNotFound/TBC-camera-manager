# Changelog

## 0.11.0 - "Redesigned & connected"
- Fixed three redesign follow-up issues on the camera dashboard: the fleet-summary "Warnings"
  count now matches statuses tolerantly (`warn`/`warning`) instead of only one exact string some
  camera-vendor plugins don't use; camera-card glyph tooltips near the card's right edge (e.g. a
  long connection-error message) no longer get clipped, since every glyph now anchors its tooltip
  from its own right edge instead of only the last one; and snapshot images now load after the
  page's own load event instead of blocking it, so a slow or offline camera's on-demand capture no
  longer holds up the whole dashboard's perceived load time.
- Carried the redesigned dashboard's `color-mix()`-tinted, hover-lift visual language onto the
  camera detail page and the live/Birdseye tiles: `.danger-button`/`.danger-icon-button` now match
  the already-modernized primary/secondary buttons (hover tint + lift instead of a flat hardcoded
  color), the probe-status/live-diagnostic banners' border tints and the active-tab shadow are now
  theme-derived instead of hardcoded literals, the overview stat numbers use tabular figures, and
  `live.html`/`birdseye.html`'s camera tiles get the same hover lift/shadow/border treatment as the
  dashboard cards (deliberately not the image-zoom effect, since these show live video, not a
  static snapshot). CSS-only changes in both theme files; `storage_explorer.html`'s plain camera
  tiles are untouched since they don't use the `.live-card` modifier this targets.
- Gave `.clip-card` (the recording/snapshot tile used by both the camera detail page's "Recent
  clips" strip and the main Recordings gallery) the same hover lift and subtle media zoom as the
  redesigned dashboard camera card, instead of leaving it static while every card around it picked
  up hover polish. CSS-only change, no template edits needed since both pages already share this
  class.
- Redesigned the camera dashboard card: a full-bleed snapshot image now carries the camera name,
  connection status, and connectivity/recording indicators as overlays, replacing the previous
  stacked header/thumbnail/boxed-stat layout - the boxed stat labels were also the source of a
  truncation bug for longer translations. Per-camera stats are now a compact icon+number row
  instead of boxed text labels, and a new fleet-summary strip (online/warnings/offline/recording
  counts) sits above the grid. Also modernized `.status-pill` and button hover states across the
  whole app (theme-derived tints via `color-mix()` instead of hardcoded per-theme colors, a status
  dot, subtle hover lift) - CSS-only changes that apply everywhere those shared components are
  already used, without needing per-page template changes.
- Fixed 478 mistranslated or dropped `{placeholder}` tokens (e.g. `{error}`, `{count}`,
  `{min}`/`{max}`) across 22 of the 27 non-English locale files, spanning 82 distinct
  translation keys. The auto-translation pipeline (`scripts/translate_locales.py`) did not
  protect these tokens, so Google Translate sometimes translated the placeholder name itself
  (English `{error}` becoming French `{erreur}`, Arabic `{خطأ}`, ...) or dropped it entirely,
  which silently broke the runtime value substitution in `app/tbc/static/i18n.js` and showed
  garbled or missing dynamic values (error messages, countdowns, min/max ranges, version
  numbers, ...) to users of the affected locale. `scripts/translate_locales.py` now protects
  placeholders by swapping them for translation-proof numeric tokens before calling the
  translation API and restoring the real names by index afterwards, so newly translated or
  re-translated strings won't reintroduce this bug. Added `test_locale_placeholder_tokens_are_not_translated`
  to `tests/test_i18n.py` to catch any regression.
- Added optional Apple HomeKit integration (live view only, no HomeKit Secure Video/encrypted
  event recording), via the HAP-python library rather than a hand-rolled HAP protocol
  implementation. Exposed cameras get a stable accessory ID across restarts, streams start on
  demand the same way Live view does, and pairing uses a QR code/pincode shown on the new
  **Operations → HomeKit** page. Requires switching a standalone Docker/Docker Compose deployment
  to `network_mode: host` for mDNS pairing discovery to work at all - not currently supported
  through the Home Assistant OS add-on, which runs without host networking. The settings page now
  detects the single most common cause of a "Device not found" pairing failure (still running in
  Docker's default bridge networking) and shows a specific warning instead of leaving the admin to
  guess. Pairing itself has not yet been verified against real Apple hardware.
- Added Birdseye, an optional single server-composited mosaic stream combining several cameras
  into one ffmpeg output (via the xstack filter), for embedding as a single video widget - a
  Home Assistant dashboard card, a TV/HDMI stick, or an NVR wall input - where the existing
  per-tile Live wall doesn't fit. Off by default and capped at 16 cameras, since it continuously
  transcodes every included camera instead of passing codecs through unchanged like Live view.
  Added a bounded ffmpeg socket timeout for RTSP sources so one unreachable camera fails within
  seconds instead of hanging the entire composite indefinitely (xstack needs every input to
  deliver frames before producing any output), plus a page-level auto-refresh and live diagnostic
  message while a stream is starting rather than only once it has failed.
- Restyled the shared `.table-section` grouping used across the camera detail tabs (Controls,
  Recording, AI detection) and the Performance, License, AI detection, Network mappings,
  Recognition, SD card, and Storage explorer pages: each grouped section now renders as a
  bordered/shadowed card matching the rest of the design system, instead of a bare heading with
  no visual separation from the controls below it.
- Exposed the image, day/night, HDR, IR lights, motion/AI sensitivity, volume, and video codec
  camera controls as Home Assistant MQTT entities (previously only floodlight, PIR, siren,
  reboot, battery, and PTZ were published).
- Added camera-side PTZ presets (save/go to/delete) and patrol/tour start-stop for cameras
  controlled through the built-in ONVIF PTZ service (previously only supported via the
  external Reolink plugin), plus matching Home Assistant MQTT entities.
- Added an experimental onboard motion-detection zone editor for ONVIF-based cameras (a
  clickable grid, using the camera's own ONVIF Rule Engine analytics rather than TBC's
  server-side Local AI zones). Marked experimental because the ONVIF spec does not standardize
  how the active-cell grid is written, so support varies by camera.
- Implemented image adjustments (brightness/contrast/saturation/sharpness), day/night mode,
  and HDR for ONVIF-based camera modules (tplink, aqara, axis, dahua, foscam, hikvision,
  standard_onvif) via the ONVIF Imaging service - previously only the external Reolink plugin
  supported these controls, so the existing UI silently did nothing on ONVIF cameras. Image
  flip/mirror and an "anti-flicker" toggle were considered but dropped: neither has a
  standardized ONVIF equivalent.
- Added experimental privacy masks for ONVIF-based cameras via ONVIF Media2, a service not
  otherwise supported by this project's ONVIF library - ships its own bundled, offline-verified
  WSDL/schema closure and SOAP client construction, isolated in its own module so it can't
  affect the well-established PTZ/imaging/motion-zone ONVIF support.
- Documented and added generic template rendering for a new convention of read-only device
  status fields any camera module can report through the existing get_control_state() dict
  contract (SD card capacity, Wi-Fi signal strength, NTP sync) - no code changes were needed to
  "support" this, since the contract was already an untyped dict; this fills in the display
  side and the documented field names so an external plugin (e.g. Reolink) can start
  populating them.

## 0.10.1 - "BugFix, new Timezones"
- Timezones added
- BugFix image generation

## 0.10.0 - "Automated backups"

- Added automated encrypted system backups with selectable schedules, retention, and optional local or S3 storage replication.
- Added backup status reporting in the administration interface.


## 0.9.8 - "Automated backups"

- Added automated, encrypted system backups with selectable schedules (6, 12, 24 hours or weekly).
- Added configurable retention of 1–365 backups, applied to local and optional external copies.
- Added optional replication to existing local or S3 storage targets, isolated under `tbc-backups`.
- Added backup execution status and error visibility in the administration interface.


## 0.9.8 - "Automated backups"

- Added automated, encrypted system backups with selectable schedules (6, 12, 24 hours or weekly).
- Added configurable retention of 1–365 backups, applied to local and optional external copies.
- Added optional replication to existing local or S3 storage targets, isolated under `tbc-backups`.
- Added backup execution status and error visibility in the administration interface.


## 0.9.7 - "Diagnosis you can trust"

- Fixed a race condition (issue #34) where the live-stream diagnosis message could be lost when a stream crashed and was retried within the same few seconds: a still-running background diagnosis for a superseded attempt could no longer overwrite or hide a newer attempt's own status. Each start attempt now carries its own generation, and only the current generation's messages are ever recorded.

## 0.9.6 - "Camera diagnostics"

- Expanded camera-detail diagnostics with additional connection, stream, and status information for faster troubleshooting.

## 0.9.5 - "Personalized & multilingual"

- Added persistent display preferences for the whole installation: date format, 12/24-hour clock, optional seconds, timezone, compact layout, and configurable dashboard refresh interval.
- Timestamps in the archive, recordings, camera details, health monitoring, audit log, backups, and API-token view now use the selected date, time, and timezone format.
- Added 20 fully translated high-speaker interface languages: Arabic, Bengali, Chinese (simplified and traditional), Hindi, Indonesian, Italian, Japanese, Korean, Marathi, Persian, Punjabi, Russian, Tagalog, Tamil, Telugu, Thai, Turkish, Urdu, and Vietnamese. TBC now provides 29 selectable interface languages.
- Reworked the language picker on the login page into a scalable dropdown and expanded the authenticated navigation menu accordingly.
- Added a reproducible Google Translate locale generator which validates key parity across every locale file.

## 0.9.4 - "Live diagnostics"

- Live-wall streams are now started server-side when the page is loaded. This avoids a dependency on a separate browser API request that can fail in Home Assistant Ingress, Android WebViews, or installed PWAs.
- A browser polling failure no longer replaces an already rendered live wall with the generic Live API error.
- Failed or missing streams now expose an expandable technical error-details box on their individual live tile. RTSP credentials remain redacted.
- Direct and self-built Docker deployments remain supported unchanged.

## 0.9.3 - "Debuggable"

- Added an administrator-only download for the complete retained debug log.
- The UTF-8 text export includes every current ring-buffer entry, up to 600 messages since
  application start or the last log clear, and uses a timestamped filename.
- The download works through Home Assistant Ingress and direct Docker deployments.

## 0.9.2 - "Reliable live wall"

- Reworked Live-wall stream startup to use the same individual camera endpoint as the working
  camera-detail preview, replacing the separate bulk start path.
- A failed RTSP stream now affects only its own tile instead of the complete Live wall.
- Hardened Home Assistant Ingress and Android/PWA handling: the Ingress prefix can also be
  recovered directly from the current browser URL.
- Expired sessions now return to the TBC login page instead of repeatedly showing a generic
  Live-API error.

## 0.9.1 - "Live through Ingress"

- Fixed the Home Assistant Ingress live wall. Status polling, automatic stream retries,
  start/stop controls, and layout updates now use the ingress-aware URL helper.
- Direct access through a self-built or prebuilt Docker container is unchanged.

## 0.9.0 - "Discover, secure & automate"

- Added fully translated Afrikaans, Bulgarian, Dutch, and Polish interface languages.
- Added an onboarding assistant for first-time administrators without cameras. It guides password,
  camera, and trigger setup, can be skipped, and disappears automatically once complete.
- Added WS-Discovery camera autodiscovery using standard-library UDP multicast. Discovered cameras
  can be applied directly to the camera form; an empty scan now returns a clear message.
- Added PWA support with ingress-aware manifest, generated application icons, maskable icon, and
  Apple touch icon.
- Added test buttons for notification channels and MQTT. Failed deliveries now return the actual
  error instead of failing silently.
- Added the "Auto (system)" design option. It follows `prefers-color-scheme` through CSS, without
  requiring JavaScript.
- Added RFC 6238-compatible TOTP two-factor authentication with QR setup, eight recovery codes,
  and administrator emergency deactivation.
- Added per-camera recording quotas for maximum retention age and storage size, integrated with
  the existing cleanup logic.
- Added ONVIF PullPoint event handling for the standard ONVIF plugin, providing real-time events
  and live status instead of polling-only capability flags.

## 0.8.7 - "Back in session"

- Added Afrikaans, Bulgarian, Dutch, and Polish as fully translated interface languages. Each is
  selectable from the login and application language menus.
- Fixed the Live view error **"Live API could not be loaded"** when a browser still held a
  session for a user that no longer exists - for example after restoring an older backup or
  deleting that account. The invalid session is now cleared: web pages redirect to the login page
  and API clients receive a proper JSON `401 Unauthorized` response instead of an unhandled `500`.
- Improved the **Admin** mega menu: it uses the available width more effectively, keeps long
  localized labels inside their column, and wraps them without overlapping adjacent menu entries.

## 0.8.5 - "Tagged correctly"

- Fixed recorded clips from HEVC/H.265 cameras still failing to play (`NETWORK_NO_SOURCE`) even
  after 0.8.3's `Content-Disposition` fix. Recording uses `-c copy` (no re-encoding), which passes
  the camera's own codec tag through unchanged - and IP cameras overwhelmingly write HEVC as
  `hev1`, which Safari and QuickTime silently refuse to play in an MP4 container at all, even
  though the stream decodes fine elsewhere. Both event-clip and continuous recording now retag
  HEVC output as `hvc1`; H.264 cameras are unaffected. Root-caused with the reporter down to the
  exact codec via `ffprobe`.

## 0.8.4 - "Baseline"

- Fixed the app crashing a few seconds after startup with `RuntimeError: NumPy was built with
  baseline optimizations: (X86_V2) but your machine doesn't support` (issue #31). NumPy dropped
  its x86-64-v1-baseline wheel in 2.3.0 in favor of one requiring at least SSE4.2/POPCNT
  (x86-64-v2) - a requirement several real deployments don't meet, most commonly a Proxmox VM
  left on the default "kvm64"/"qemu64" CPU type instead of "host". `numpy` is now capped at
  `<2.3`, which still satisfies every other pinned package and ships the compatible wheel.

## 0.8.3 - "Play it back"

- Fixed recorded clips failing to play in the browser (most noticeably in Safari) while still
  downloading and streaming their bytes correctly (`206 Partial Content`). The `/recordings/{id}/media`
  endpoint (and its `/api/v1/...` counterpart) sent `Content-Disposition: attachment`, telling the
  browser to save the file instead of rendering it inline in the `<video>` element. Both now send
  `inline`; the separate **Download** button is unaffected and still forces a save dialog.
- Fixed the video player's control buttons (play/pause, mute, fullscreen, PTZ) showing raw,
  untranslated `player.*` i18n keys as their accessible names under slow/Ingress loading - the
  same underlying race condition fixed for other pages in 0.8.1, now also covering
  `video-player.js`.

## 0.8.2 - "Stored & streamlined"

- Reworked **Admin → External sources** into compact, filterable lists. A sticky sidebar now
  filters standard and registered sources by group and plugin type, with a search field; the layout
  adapts to narrow screens.
- Added French as a fully translated interface language, selectable from the login and application
  language menus.
- Creating a backup now stores the encrypted archive persistently on the device instead of
  immediately downloading it. The new backup list offers protected downloads, uses the filename
  format `TBC_v<version>_<date>-<time>.tbcbackup`, and stores archives in `TBC_BACKUPS_PATH`
  (default `/data/backups`).

## 0.8.1 - "Ready when you are"

- Fixed the plugin-selector forms (camera, cloud account, network account) and the live view's
  empty-state message showing raw, untranslated `plugin.*`/`live.*` i18n keys instead of real
  text. They read `window.tbcI18n` before its locale fetch had actually resolved and never
  re-rendered once it did - more likely under Home Assistant Ingress's extra proxy hop. `i18n.js`
  now fires a `tbc:i18n-ready` event once strings are actually loaded, and the affected scripts
  redo their translated text when it fires.
- Documented which environment variables actually need changing (issue #30): almost none of them
  are required to start the container - every one has a working default - but `TBC_ADMIN_PASSWORD`
  and `TBC_SECRET_KEY` should always be changed outside a quick local test. `docker-compose.yml`
  now groups its variables the same way inline, and `docs/deployment.md` documents the previously
  undocumented `TBC_PLUGIN_SITE_PACKAGES_PATH`.

## 0.8.0 - "Available"

- Every tagged release now publishes a multi-arch (`amd64`/`aarch64`) prebuilt image to
  `ghcr.io/404gamernotfound/tbc-camera-manager`, tagged `latest`, `<major>.<minor>`, and the
  exact version - `docker pull` now works as an alternative to `docker compose up --build`. This
  is separate from, and does not change, the existing Home Assistant app image.
- Fixed a latent bug in the Dockerfile's `BUILD_ARCH` build argument: it defaulted to `amd64`
  unconditionally, so a plain multi-arch build without an explicit override could silently bundle
  the wrong-architecture `go2rtc` binary on `aarch64`. It now derives from Docker Buildx's own
  `TARGETARCH` by default and can still be overridden explicitly (as the Home Assistant app build
  already does).
- Bumped the minimum versions of `packaging`, `Markdown`, `cryptography`, `onnxruntime`, `aiohttp`,
  and `boto3` in `requirements.txt` to match what was already being installed and tested.

## 0.7.0 - "Hardened"

- Added CSRF protection: every session-cookie-authenticated form and JS request now carries a
  per-session token, checked before the request is allowed through. The public, API-key-secured
  `/api/v1/...` API and the MCP endpoint are unaffected, since browsers never attach those
  credentials automatically.
- Added a login lockout: repeated failed sign-ins for the same username are throttled with
  increasing delays instead of being retried indefinitely.
- Added standard security response headers (`X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`/`Content-Security-Policy`, `Strict-Transport-Security` when
  `TBC_COOKIE_SECURE` is set). The clickjacking headers are skipped for requests coming through
  Home Assistant Ingress, which legitimately embeds TBC in an iframe.
- Bootstrap is now bundled locally instead of loaded from a CDN, matching how `hls.js` is
  already shipped - the UI (including the login page) no longer depends on internet access to
  render correctly.
- Added `TBC_SESSION_MAX_AGE_SECONDS` to make the session cookie lifetime configurable (default
  unchanged: 14 days).
- Added indexes for the columns the clip browser, timeline, cleanup pass, and audit log
  actually filter or sort by, so those queries stop full-scanning as recordings/events accumulate.
- Reduced the Docker image size by moving the C-toolchain packages needed to build a few
  dependencies into a separate build stage that isn't shipped in the final image.
- Removed 94 stale, accidentally committed duplicate files (`" 2"`-suffixed copies) left over
  from a local sync-tool conflict.
- Internal: split the 6,000+ line `app/tbc/main.py` route module into per-domain routers under
  `app/tbc/routers/`, and migrated off FastAPI's deprecated `on_event` startup/shutdown hooks.
  No route paths or behavior changed. Added `pytest-cov` with a 50% coverage floor in CI.

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
