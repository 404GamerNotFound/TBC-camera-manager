# User guide

TBC Camera Manager combines local ONVIF/RTSP cameras, vendor cloud accounts, recording storage,
live viewing, and optional local recognition in one web interface. Which controls are visible for
a camera depends on the capabilities reported by its camera module.

## Signing in and navigation

The first account is the administrator configured during deployment. Administrators can create
additional administrator or viewer accounts under `Admin → Users`.

- **Administrators** can configure cameras, accounts, recording, AI, storage, users, plugins, and
  system integrations.
- **Viewers** can only see cameras explicitly assigned to their account. They can open permitted
  camera pages, live streams, and recordings but cannot change administrative settings.

The main navigation groups camera views, archive views, storage, operations, and administration.
The footer links to this documentation. Administrators additionally see the license page and the
debug-log drawer.

## Adding cameras

Open **Cameras** and select **+ Camera**. TBC supports three common workflows:

1. **Local camera:** choose an installed camera module and enter the host or IP address, ports,
   username, password, and, where supported, a manual RTSP/RTSPS URL.
2. **Cloud account:** configure a provider under **Cloud accounts**, discover its devices, and
   import a device as a camera. Verification-code flows are shown when required by the provider.
3. **Plugin installation:** if the manufacturer or provider is not installed, open **External
   sources** and install a compatible public plugin repository, or import a trusted plugin ZIP.

Credentials and complete stream URLs are encrypted at rest and redacted in the UI. A camera can
be checked again from its detail page after connection settings change.

## Dashboard and camera details

The camera dashboard shows a periodically refreshed preview, connection diagnostics, supported
features, active detections, and recording state. The preview interval is configured at deployment
time and does not start a permanent live stream.

The camera detail page is split into capability-dependent tabs:

- **Overview:** device information, stream availability, channels, recent clips, and health data.
- **Plugin:** module origin, version, required credentials, custom-stream support, and capabilities.
- **Network:** optional mapping to a client seen by a network-controller plugin.
- **Recording:** continuous and event-triggered recording settings.
- **AI detection:** local model settings, inclusion/exclusion areas, and loitering zones.
- **Controls:** live preview and supported ONVIF/vendor controls.
- **Connection:** host, ports, credentials, and manual-stream settings.
- **Detections:** supported detection types and their current state.

## NVRs and channels

Camera modules may expose several NVR channels. Each channel can be enabled or disabled, renamed,
opened in live view, and used as a separate stream source. Camera controls use the selected control
channel. A disabled or missing channel does not produce a stream.

## Live view

The live wall starts available camera streams and displays their state. Administrators can select
the number of columns, drag tiles into a different order, resize tiles, and optionally rotate
through pages of cameras automatically.

Two transports can be available:

- **HLS** works through the normal TBC web port and tolerates unstable connections through
  buffering, at the cost of several seconds of latency.
- **WebRTC** uses the bundled go2rtc process for sub-second latency. TCP and UDP port `8555` must
  be reachable by the viewer. If WebRTC cannot connect quickly or drops, that tile falls back to
  HLS for the current page session.

Transport selection is remembered per tile in the browser. Full-screen mode hides the normal
application chrome and can be left with Escape or the on-screen exit button.

## Recording and archives

TBC supports two local recording modes:

- **Continuous recording** writes fixed-length segments around the clock.
- **Event recording** writes clips for selected camera or local-AI triggers, with configurable
  minimum duration, pre-roll, post-roll, cooldown, and optional snapshot.

The **Clips** page filters recordings by camera, event, date range, and text. Clips can be played,
downloaded, locked, unlocked, or deleted. A locked recording is protected from manual deletion and
retention cleanup.

The **Timeline** combines continuous segments, event clips, and optional camera SD-card recordings
for one camera and day. Zooming changes the time scale; selecting a segment starts playback near
the selected point. **Activity** provides a cross-camera view of event clips for one day and can
optionally include SD-card items.

## Camera SD cards

When a camera module exposes its on-camera archive, the **SD card** page can query recordings by
camera, channel, stream, and date range. Results can be previewed or downloaded without copying
them into TBC's local recording database. Availability and metadata depend on the camera vendor.

## Local AI detection

Local AI processes sampled frames on the TBC host independently of camera-generated events. Each
camera can select a backend, sampling rate, and confidence threshold. CPU is always the default;
CUDA and Coral require their respective image/runtime and compatible hardware.

Zones refine which detections count:

- **Inclusion zone:** a selected class only counts inside the polygon.
- **Exclusion zone:** detections inside the polygon are ignored.
- **Loitering zone:** triggers after a class remains inside continuously for the configured time.

Without zones, the full image is evaluated. Local-AI detections can be selected as recording
triggers and are also available to MQTT/Home Assistant and the external API.

## Face and license-plate recognition

Recognition is disabled by default and runs locally. **Snapshot mode** processes the saved image
after a matching clip finishes; **Live mode** works in the detection loop for lower latency and
higher CPU usage.

Administrators can enroll known faces from a clear front-facing photo and maintain known license
plates with labels. Recognition events record the camera, result, confidence, and time. Models are
downloaded into the detection-model volume on first use.

## Camera controls and firmware

Depending on the module and camera, the control tab can expose pan/tilt/zoom, presets, absolute
zoom and focus, floodlight, PIR sensor, siren, quick replies, battery state, and restart. Commands
are sent asynchronously and their result appears as a status message.

Supported firmware checks and updates are downloaded directly from the camera vendor. The camera
is unavailable while applying an update and usually restarts afterward. Do not interrupt power or
network connectivity during an update.

## Network mappings

A network-provider account reads clients from a router or controller. Map a camera to a discovered
MAC address to show online/offline state, wired or Wi-Fi connection, uplink name, signal strength,
IP address, and last-seen time. This mapping supplements the camera module; it does not carry video
or control traffic. See [network-accounts.md](network-accounts.md) for the provider contract.
