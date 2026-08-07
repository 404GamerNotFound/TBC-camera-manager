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

## Birdseye

Birdseye is a single, server-composited video stream that tiles several cameras into one mosaic
image, unlike Live view's per-camera tiles. It is meant for places a single stream is needed - a
Home Assistant dashboard card, a TV or HDMI stick without a browser, or an NVR wall input - not for
per-camera detail.

An administrator selects which cameras are included (up to 16), the grid column count, and a low
frame rate, then enables it under **Birdseye → Settings**. Because compositing continuously decodes
and re-encodes every included camera instead of passing codecs through unchanged like Live view
does, it is off by default and should only include the cameras actually needed on the target
display. Full-screen mode works the same way as Live view.

**Playback** (reached via the "Playback" button on the Birdseye page) scrubs recordings from the
same selected cameras (up to 9) together on one shared timeline for a chosen day, instead of the
live mosaic - useful for reviewing what happened across several cameras at the same moment. Unlike
the live mosaic, each tile is its own independently playable recording; synchronization is
best-effort (periodically corrected while playing) rather than frame-accurate, since browsers
cannot genlock independently loaded video files.

## Recording and archives

TBC supports two local recording modes:

- **Continuous recording** writes fixed-length segments around the clock.
- **Event recording** writes clips for selected camera or local-AI triggers, with configurable
  minimum duration, pre-roll, post-roll, cooldown, and optional snapshot.

The **Clips** page filters recordings by camera, event, date range, and text. When local AI
detection produced the event, clips also carry the specific vehicle/animal type it detected
(e.g. "truck" or "cat" rather than just "vehicle") and, for vehicles, a best-effort dominant
color read from the snapshot; both are filterable and shown on the clip card. Clips can be
played, downloaded, locked, unlocked, or deleted. A locked recording is protected from manual
deletion and retention cleanup.

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
CUDA, Coral, and Hailo require their respective image/runtime and compatible hardware - Hailo also
needs a manually-supplied model (see [deployment.md](deployment.md)).

Zones refine which detections count:

- **Inclusion zone:** a selected class only counts inside the polygon.
- **Exclusion zone:** detections inside the polygon are ignored.
- **Loitering zone:** triggers after a class remains inside continuously for the configured time.
- **Counting line:** a two-point line (drawn with its own "Draw counting line" tool instead of
  the polygon tool) tallies how many tracked people/vehicles/animals cross it in each direction -
  useful for entrances, driveways, or aisles. The direction arrow shown while drawing marks which
  side counts as "in". Running totals are shown next to the zone and can be reset independently
  of deleting the zone; each crossing also briefly triggers its own recording/notification key
  (`ai_person_line_in`, `ai_vehicle_line_out`, etc.), the same way loitering zones do.

Without zones, the full image is evaluated. Local-AI detections can be selected as recording
triggers and are also available to MQTT/Home Assistant and the external API.

## Face and license-plate recognition

Recognition is disabled by default and runs locally. **Snapshot mode** processes the saved image
after a matching clip finishes; **Live mode** works in the detection loop for lower latency and
higher CPU usage.

Administrators can enroll known faces from a clear front-facing photo and maintain known license
plates with labels. Recognition events record the camera, result, confidence, and time. Models are
downloaded into the detection-model volume on first use.

## Semantic search

Disabled by default. When enabled (**Admin → AI detection**), TBC computes a CLIP image embedding
for each recording's snapshot and lets the **Clips** page rank recordings by free-text similarity
("silver van in the driveway") instead of only literal camera/event/date filters - check the
"Semantic search" box next to the search field to switch a query from literal text matching to
similarity ranking. The image/text model (~600 MB for the default `ViT-B-32__openai`) downloads on
first use into the detection-model volume, and an admin-configurable model name lets you swap in a
smaller or larger CLIP derivative. Existing recordings are backfilled with embeddings gradually in
the background after enabling; the settings page shows how many are still pending.

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

`/network-mappings` (linked from a mapped camera's **Network** tab) shows every mapped camera as a
three-level **Network topology** tree: network account → the switch or access point it currently
connects through → the cameras on that uplink. A camera that has gone offline keeps showing the
uplink it was last seen on instead of dropping out of the tree, so you can still tell where to look
for it physically. Expand a camera's **History** to see its recent connectivity events
(online/offline transitions and uplink changes) with timestamps.
