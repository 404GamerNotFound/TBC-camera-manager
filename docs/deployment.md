# Deployment and configuration

TBC can run as a regular Docker container or as a Home Assistant app. Both variants use the same
FastAPI application and persistent data layout.

## Docker Compose

The repository's `docker-compose.yml` builds the standard image, exposes the TBC web port, and
mounts separate volumes for application data and recordings:

```bash
docker compose up -d --build
```

Open `http://<host>:8732`. Change the administrator password and secret key before first use.
For production, place TBC behind an HTTPS reverse proxy or restrict port `8732` to a trusted
network.

## Home Assistant OS

Add the repository to `Settings → Apps → App store`, install **TBC Camera Manager**, configure at
least `admin_password`, and open the web UI. The app stores private state under `/data` and maps
recordings to Home Assistant media storage. The web UI runs behind Home Assistant Ingress (a
sidebar entry, and **Open web UI**, work without a direct connection to the container's port) -
WebRTC live view still needs direct network access to port `8555`, since Ingress cannot tunnel its
media stream; HLS live view has no such limitation. The full Home Assistant packaging notes remain
in `tbc_camera_manager/DOCS.md` in the repository.

## Persistent paths

| Path | Purpose |
|---|---|
| `/data/tbc.sqlite3` | Users, cameras, settings, accounts, tokens, recording metadata, and audit data |
| `/recordings` | Default local recording media |
| `/data/camera-modules` | Imported camera plugins |
| `/data/cloud-modules` | Imported cloud-provider plugins |
| `/data/network-modules` | Imported network-provider plugins |
| `/data/design-themes` | Imported design themes |
| `/data/detection-models` | Downloaded default, recognition, and plugin-specific models |
| `/data/dashboard-snapshots` | Periodic dashboard previews |
| `/tmp/tbc-live` | Temporary HLS output; safe to recreate after restart |

Persist `/data` and recording paths. The live directory is transient and should not be backed up.

## Environment variables

Every variable below has a working built-in default (see `app/tbc/config.py`) - **none of them are
required just to start the container.** They're grouped here by whether you should actually
change them.

### Change these before using TBC outside a quick local test

Leaving these at their defaults means anyone who reaches the port can log in and read/decrypt
stored credentials.

| Variable | Default | Description |
|---|---|---|
| `TBC_ADMIN_PASSWORD` | `bitte-aendern` | Initial administrator password; does not overwrite an existing account |
| `TBC_SECRET_KEY` | development fallback | Session signing and encryption key; keep stable and secret |

### Situational - leave at the default unless you need the specific behavior

| Variable | Default | Description |
|---|---|---|
| `TBC_ADMIN_USERNAME` | `admin` | Initial administrator name |
| `TBC_PUBLIC_BASE_URL` | empty | Public base URL used in notification links |
| `TBC_PORT` | `8732` | Web server port |
| `TBC_COOKIE_SECURE` | `false` | Mark session cookies HTTPS-only (set this behind an HTTPS reverse proxy) |
| `TBC_SESSION_MAX_AGE_SECONDS` | `1209600` (14 days) | Session cookie lifetime, minimum 300 seconds |
| `TBC_POLL_INTERVAL_SECONDS` | `60` | Camera and network polling interval, minimum 15 seconds |
| `TBC_DASHBOARD_SNAPSHOT_INTERVAL_SECONDS` | `600` | Preview refresh interval, minimum 60 seconds |
| `TBC_DETECTION_SAMPLE_FPS` | `2.0` | Default local-AI sample rate |
| `TBC_DETECTION_CONFIDENCE_THRESHOLD` | `0.5` | Default local-AI confidence threshold |

### Storage paths - matched to the volume/bind mounts in `docker-compose.yml`

Change one only together with its mount, otherwise the app just looks in a different, unmounted,
non-persistent place.

| Variable | Default | Description |
|---|---|---|
| `TBC_DATABASE_PATH` | `/data/tbc.sqlite3` | SQLite database path |
| `TBC_RECORDINGS_PATH` | `/recordings` | Default recording directory |
| `TBC_PLUGIN_SITE_PACKAGES_PATH` | `/data/plugin-site-packages` | Where plugin-declared pip requirements are installed, so they survive image/App updates |
| `TBC_LIVE_PATH` | `/tmp/tbc-live` | Temporary HLS directory; safe to recreate after restart |
| `TBC_CAMERA_MODULES_PATH` | `/data/camera-modules` | External camera-plugin directory |
| `TBC_CLOUD_MODULES_PATH` | `/data/cloud-modules` | External cloud-plugin directory |
| `TBC_NETWORK_MODULES_PATH` | `/data/network-modules` | External network-plugin directory |
| `TBC_THEME_MODULES_PATH` | `/data/design-themes` | External theme directory |
| `TBC_DETECTION_MODELS_PATH` | `/data/detection-models` | Model cache directory |
| `TBC_DASHBOARD_SNAPSHOTS_PATH` | `/data/dashboard-snapshots` | Dashboard preview directory |

## Ports and network access

- `8732/tcp`: web UI, API, MCP, HLS playlists, and HLS segments.
- `8555/tcp` and `8555/udp`: go2rtc WebRTC media when WebRTC is enabled.
- Outbound access: camera HTTP/ONVIF/RTSP ports, cloud-provider APIs, MQTT, S3-compatible storage,
  GitHub for plugin/update checks, and model/vendor downloads when those features are used.

WebRTC clients outside the container network must be able to reach port `8555`. If this is not
possible, disable WebRTC or use HLS.

## CPU, CUDA, and Coral images

The standard image includes ONNX Runtime for CPU inference. `Dockerfile.gpu` replaces it with
`onnxruntime-gpu` and requires a compatible NVIDIA runtime. `Dockerfile.coral` installs the Coral
runtime and expects a connected Edge TPU device. Hardware availability is reported on the AI
detection page; verify optional backends on the target host before production use.

## Upgrades

Before an application upgrade:

1. Preserve the database, `TBC_SECRET_KEY`, plugins/themes, and any recording paths.
2. Read the release notes and pull or build the new image.
3. Restart the container and check **Performance**, camera status, recording destinations, and
   live view.
4. Keep the prior image and database backup available for rollback.

Database initialization and schema migrations run at startup. Do not run two TBC instances against
the same SQLite database or writable recording directory.

## Troubleshooting startup

- Confirm all mounted directories are writable by the container user.
- Confirm `TBC_SECRET_KEY` did not change when existing encrypted credentials suddenly fail.
- Check the debug log or container output for database, ffmpeg, go2rtc, plugin, and model errors.
- Verify DNS and outbound HTTPS when GitHub, cloud providers, model downloads, or S3 cannot be
  reached.
- Verify camera routes and credentials from the TBC container network, not only from the host.
