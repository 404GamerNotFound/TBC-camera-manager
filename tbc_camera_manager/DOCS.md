# TBC Camera Manager as a Home Assistant app

## Installation

This app requires Home Assistant OS. Open `Settings → Apps → App store`, add
the following URL from the repository menu, and then refresh the store:

```text
https://github.com/404GamerNotFound/TBC-camera-manager
```

Select **TBC Camera Manager**, install the app, and set at least
`admin_password` before the first start. TBC appears in the Home Assistant
sidebar once running (Ingress is enabled - see **Network and web interface**
below); **Open web UI** works the same way and routes through Supervisor's
own proxy rather than a direct connection to port `8732`.

## Options

- `admin_username`: User name of the initial TBC administrator.
- `admin_password`: Required password for the initial administrator account.
  Changing this app option later does not change an existing TBC account.
- `poll_interval_seconds`: Camera polling interval, with a minimum of 15 seconds.
- `dashboard_snapshot_interval_seconds`: Dashboard preview interval, with a
  minimum of 60 seconds.
- `public_base_url`: Optional external base URL for links in notifications.

## Persistence and backups

The SQLite database, installed modules, themes, models, and preview images are
stored in the private `/data` app directory. Home Assistant uses a cold backup
for consistent SQLite backups and briefly stops TBC during the operation.

Recordings are stored in `/media/tbc-camera-manager` on the Home Assistant host.
The directory is mounted as `/recordings/tbc-camera-manager` inside the
container. It is not part of the private app backup, so large video archives do
not automatically increase the size of Home Assistant backups.

On the first start, the launcher creates a random session secret in
`/data/.tbc-secret-key`. This secret remains stable across restarts and updates.

## MQTT and Home Assistant

Install the Mosquitto broker app if needed and configure the broker under `MQTT`
in TBC. The official Mosquitto app is usually available as `core-mosquitto` on
port `1883` within the app network. Enable Home Assistant Discovery in TBC to
create supported detection and control entities.

## Network and web interface

TBC runs in the protected app container without host networking. It connects to
cameras, RTSP, ONVIF, and MQTT through the configured IP addresses.

The web interface uses Home Assistant **Ingress**: TBC reads the dynamic,
per-installation path Supervisor assigns (`X-Ingress-Path`, sent on every
request) and prefixes every redirect, cookie, link, and API URL it emits with
it - see `app/tbc/ingress.py` for the mechanism. This is what gives TBC its
sidebar entry and lets **Open web UI** work without a direct connection to
port `8732`. Port `8732` still stays published too, for a reverse proxy or
bookmark pointed at it directly - TBC's own login still gates access either
way, so this isn't a security trade-off.

**One feature does not fully work through Ingress: WebRTC live view.** The
SDP offer/answer signaling is a same-origin request and works fine through
Ingress, but the actual video (ICE/RTP media on port `8555`) is a direct
connection between the browser and the bundled `go2rtc` process that no
HTTP-only reverse proxy - including Ingress - can tunnel. WebRTC mode
therefore still needs direct network reachability to port `8555`, exactly as
it does outside Home Assistant. **HLS live view has no such limitation** and
works fully through Ingress, including from outside the local network (e.g.
via Nabu Casa Cloud).

## Technical architecture

The Home Assistant app and the regular Docker deployment use the same
application code and root Dockerfile. Under Home Assistant,
`app/tbc/container_launcher.py` reads the Supervisor configuration from
`/data/options.json`, maps it to the existing `TBC_*` environment variables,
prepares the mounted directories, and then drops privileges to the `tbc` user
with UID `10001`. Without `options.json`, the image behaves like the standalone
container and uses the environment variables supplied by Docker Compose.

## Publishing for maintainers

The app version in `config.yaml` must match the TBC version in
`app/tbc/__init__.py`. Changing the version in `config.yaml` on `main`, pushing a
Git tag in the format `vX.Y.Z`, or manually dispatching
`.github/workflows/home-assistant-app.yml` starts the image release. The workflow
rejects a tagged release when the tag and app version differ, builds separate
`amd64` and `aarch64` images, and then publishes a shared multi-architecture
manifest as:

```text
ghcr.io/404gamernotfound/tbc-camera-manager-ha:X.Y.Z
```

Wait until the workflow and its final anonymous-pull check succeed before asking
users to install the new version. Home Assistant reads `config.yaml` directly
from the app repository and cannot install an advertised version until its
matching public image tag exists.

GitHub Container Registry creates a new package as private by default. After the
first publication, open the package settings and change its visibility to
**Public**, so Home Assistant can download it without registry credentials. The
workflow performs an anonymous pull after publishing and fails with a targeted
error until this requirement is met. Rerun the workflow after changing the
visibility.

The workflow also maintains the `latest` tag. Home Assistant installs and
updates the explicit version from `config.yaml`.

### Installation reports `denied`, `401`, or `403`

These messages mean the Supervisor cannot anonymously fetch the configured
image. Verify all of the following:

1. The Home Assistant app workflow has completed for the version from
   `config.yaml`.
2. The corresponding GHCR package exists and its visibility is **Public**.
3. The multi-architecture tag, for example `0.2.0`, is listed in the package.

After correcting the publication, reload the app store and retry the
installation. No Home Assistant registry credentials are required for a public
package.
