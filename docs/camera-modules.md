# Developing camera modules

TBC separates manufacturer-specific camera APIs from the web interface through
`CameraModule`. The manufacturer-neutral `standard_onvif` and `rtsp_only` modules remain
built in. The manufacturer plugins `aqara`, `axis`, `dahua`, `foscam`, `hikvision`,
`reolink`, `sonoff`, `tplink`, and `ubiquiti` are offered as directly installable default
repositories. Additional modules can be imported as ZIP plugins through the admin interface
without changing TBC routes or templates.

## Plugin file

A plugin ZIP contains its files directly at the archive root or inside exactly one common
directory:

```text
acme-camera-plugin.zip
├── manifest.json
├── plugin.py
├── detections.json
├── service.py
└── README.md
```

`manifest.json` is the authoritative configuration for metadata, ports, and capabilities:

```json
{
  "schema_version": 1,
  "key": "acme",
  "label": "Acme Camera",
  "version": "1.0.0",
  "description": "Acme cameras",
  "entrypoint": "plugin.py",
  "capabilities": ["live", "detections"],
  "ports": {"onvif": 8000, "http": 80, "rtsp": 554},
  "requirements": ["acme-camera-sdk==2.1.0"]
}
```

`requirements` is optional - a list of the plugin's own pip dependencies TBC does not already
ship, installed on demand with an explicit admin confirmation instead of having to live in
TBC's own `requirements.txt`. See
[**Plugin-declared pip requirements**](plugin-sources.md#plugin-declared-pip-requirements-requirements)
in plugin-sources.md.

Built-in modules are completely contained in `app/tbc/camera_plugins/<key>/`. This includes
not only `manifest.json`, `plugin.py`, and `detections.json`, but also the full
manufacturer-specific implementation in files such as `module.py`, `service.py`, `catalog.py`,
and optionally `control.py`. Each built-in module is therefore as self-contained as an
externally installed plugin. Only generic manufacturer-neutral code intentionally remains
outside these packages: ONVIF helpers, the `CameraModule` base class, and the shared
`manual_rtsp` implementation for RTSP-only profiles under `app/tbc/camera_modules/` and
`app/tbc/manual_rtsp/`. Profiles without a usable event source use an empty
`detections.json` list and declare only `live`.

## Public contract

A module inherits from `tbc_camera_api.CameraModule`. The key, display name, and capabilities
are defined in the manifest:

```python
from tbc_camera_api import CameraModule, CameraSnapshot


class AcmeCameraModule(CameraModule):
    async def probe(self, camera):
        # Query the manufacturer API and map it to TBC's unified model.
        return CameraSnapshot(
            status="ok",
            message="Acme camera queried successfully",
            manufacturer="Acme",
            model="Camera",
            stream_uri="rtsp://...",
            detections=[],
            channels=[],
        )


def create_module():
    return AcmeCameraModule()
```

`plugin.py` exposes either `create_module()` or a variable named `MODULE`. TBC transfers
metadata and capabilities from the manifest to the module instance. `probe()` is the only
required method. A module may optionally implement `detection_definitions()`,
`list_archive_recordings()`, `open_archive_download()`, `get_control_state()`, and
`send_control()`. An archive download returns an object with `filename`, `length`, and the
asynchronous byte iterator `chunks()`.

For real-time events, the module instance may also provide an asynchronous
`monitor_events(camera, callback)` method. Alternatively, TBC detects the same function in the
plugin's `service.py`. The callback receives current detection rows. If the persistent
connection fails, regular polling through `probe()` remains active as a fallback. The
application core therefore needs no direct import from a particular manufacturer plugin.

Modules that expect a complete stream URL instead of separate ONVIF credentials set
`supports_manual_stream_uri = True`, `requires_manual_stream_uri = True`, and
`requires_credentials = False`. TBC stores this URL separately in `manual_stream_uri`, accepts
only `rtsp://` and `rtsps://`, and never renders it unredacted in HTML. The external
`ubiquiti` and `sonoff` plugins and the built-in `rtsp_only` module use the shared
`manual_rtsp/` implementation.

The unified `CameraSnapshot` contains device status, manufacturer data, RTSP URI, detection
states, and channels. Detection rows use `key`, `label`, `category`, `channel`, `supported`,
`active`, `source`, and optionally `raw_value`.

A module whose `host` field holds something other than a local IP address (for example, an
account-linked device serial number for a cloud-only camera) may set `identifier_label` to a
plain-text string, overriding the connection form's default translated "Host / IP" label with
that text. Leave it unset (the default, `None`) to keep the normal label - this is what every
ONVIF-based module does. See the external `xsense-camera` plugin for an example of a module
whose cameras have no local IP at all.

## Import and export

Administrators open `Admin → Camera plugins` and import a ZIP. TBC validates the manifest,
paths, file types, file count, and extracted size, loads the module as a test, and then installs
it atomically. An existing external plugin with the same key is updated. Built-in plugins
cannot be overwritten or removed.

Every file-based plugin can be exported again as a ZIP from the same page. An external plugin
can be removed only when no camera references it. `TBC_CAMERA_MODULES_PATH` configures the
storage location, which resides in the persistent `/data` volume in the Docker setup.

Python distributions with the `tbc.camera_modules` entry point remain supported as an
alternative. They are installed during the image build and are not managed through ZIP files.

Instead of a manual ZIP upload, a plugin can be installed directly from a public GitHub
repository under `Admin → External sources`. A plugin may also include a `tests/` directory
that can be started from the web interface with **Run tests**. See
[plugin-sources.md](plugin-sources.md).

## Security

A camera plugin contains executable Python code and has the same privileges as the TBC
process. ZIP validation prevents technical archive attacks but cannot reliably detect
intentionally malicious Python. Import plugins only from trusted sources. Camera credentials
are stored per camera in TBC and must never be included in an exported plugin file.

## Capabilities

- `LIVE`: The module provides a stream that can be used in the live view.
- `RECORDING`: Events from the module can trigger generic TBC recording.
- `DETECTIONS`: The module provides detection definitions and states.
- `CHANNELS`: The module supports multiple camera or NVR channels.
- `ARCHIVE`: The module implements camera-archive search, playback, and download.
- `CONTROL`: The module implements `get_control_state()` and `send_control()` for live device
  control, such as PTZ with stored positions, floodlight, PIR sensor, siren, restart, and
  battery status.
- `FIRMWARE`: The module implements `check_firmware()` and `update_firmware()` for firmware
  checks and updates.

Built-in implementations reside in manufacturer packages under
`app/tbc/camera_plugins/<key>/`; external implementations reside in the configured plugin
directory. Their `module.py` adapters are the only entry points used by the registry. External
plugins access public TBC base classes and manufacturer-neutral helpers through
`tbc_camera_api`.

## Camera control (`CONTROL`)

Modules with the `CONTROL` capability implement two additional methods:

```python
async def get_control_state(self, camera: dict, *, channel: int = 0) -> dict:
    """Return the current device state, for example floodlight support and state."""

async def send_control(self, camera: dict, *, action: str, channel: int = 0, **params) -> dict:
    """Run a control command, for example action="floodlight", params={"state": True}."""
```

The external [Reolink plugin](https://github.com/404GamerNotFound/TBC-reolink) implements PTZ
pan and tilt commands, including positions stored on the camera through `reolink-aio`'s
`ptz_presets()` and `set_ptz_command(preset=...)`, as well as floodlight, PIR sensor, siren,
restart, and battery status. `tplink`, `aqara`, `axis`, `dahua`, `foscam`, and `hikvision`
provide PTZ through the manufacturer-neutral ONVIF PTZ service
(`app/tbc/camera_modules/onvif_control.py`), including camera-side presets (ONVIF
`GetPresets`/`GotoPreset`/`SetPreset`/`RemovePreset`, reported as `ptz_presets` and applied
through `send_control(action="ptz", preset=...)`, `"ptz_preset_save"`, and
`"ptz_preset_delete"`) and patrol/preset tours where the camera's ONVIF implementation
supports them (`GetPresetTours`/`OperatePresetTour`, reported as `ptz_patrol_supported` and
`ptz_patrol_tours`, started/stopped through `send_control(action="ptz_patrol", tour=...,
command="start"|"stop")`). When a camera has the `CONTROL` capability, the web interface adds
a **Control** tab. If MQTT and Home Assistant Discovery are enabled, TBC also publishes the
same actions as Home Assistant entities (lights, switches, buttons, numbers, selects, and
sensors) and accepts remote control through MQTT command topics (`app/tbc/mqtt.py`).

ONVIF-based modules also implement the `image`, `daynight`, and `hdr` actions through the
ONVIF Imaging service (`GetImagingSettings`/`SetImagingSettings`), which were previously only
implemented by the external Reolink plugin: `image_bright_supported`/`image_brightness` and
the equivalent contrast/saturation/sharpness pairs map to `tt:ImagingSettings20`'s
`Brightness`/`Contrast`/`ColorSaturation`/`Sharpness` (rescaled from the ONVIF 0-100 range to
this app's 0-255 UI range - a camera whose real range differs would be rescaled incorrectly,
a known simplification); `daynight_mode` maps to `IrCutFilter` (`AUTO`/`ON`/`OFF` for
Auto/Color/Black&White); `hdr_supported` maps to `WideDynamicRange.Mode`. There is no ONVIF
equivalent of the Reolink plugin's "hue" slider, image flip/mirror, or an "anti-flicker"
setting, so those are not implemented for ONVIF-based modules.

ONVIF-based modules also expose **experimental** onboard motion-detection zones through the
ONVIF Rule Engine's `CellMotionDetector` analytics module: `md_zone_supported`,
`md_zone_config_token`, `md_zone_columns`, and `md_zone_rows` describe a grid, applied through
`send_control(action="md_zone", config_token=..., columns=..., rows=..., cells=...)` where
`cells` is a row-major `"0"`/`"1"` string. Unlike PTZ, the ONVIF spec leaves the active-cell
bitmap itself as an unstandardized extension point, so this is best-effort: grid discovery is
reliable, but the write may be a no-op or fail outright depending on the camera's own ONVIF
stack, and the current on-camera zone configuration is never read back (the grid editor always
starts fully selected).

ONVIF-based modules also expose **experimental** privacy masks through the ONVIF **Media2**
service (`app/tbc/camera_modules/onvif_privacy_mask.py`), which is a materially bigger
departure from the rest of ONVIF support than the two features above: Media2 (`CreateMask`/
`GetMasks`/`SetMask`/`DeleteMask`) is a separate service from the classic ver10 Media service
this project's `onvif-zeep` dependency implements, and that dependency has no Media2 support
at all - no service factory, no bundled WSDL. `onvif_privacy_mask.py` builds its own Media2
SOAP client at runtime from a WSDL/schema closure bundled under
`app/tbc/camera_modules/onvif_media2_schema/` (hand-assembled from the ONVIF Foundation's own
published `media2.wsdl` and `onvif.xsd`, which do not fully agree with each other as published
- notably `onvif.xsd` doesn't define the `tt:Polygon`/`tt:Vector` types `media2.wsdl` requires;
this bundle fixes that and has been verified to parse and build real SOAP requests without any
network access), reusing `onvif-zeep`'s `ONVIFService` for the actual SOAP/WS-Security
plumbing. `privacy_mask_supported`, `privacy_mask_config_token`, and `privacy_masks` (a list of
`{token, enabled, type, points}`) report existing masks; `send_control(action=
"privacy_mask_create", config_token=..., points=[{"x":..., "y":...}, ...])` creates a solid
black polygon mask (ONVIF normalized device coordinates, -1.0 to 1.0) and `send_control(
action="privacy_mask_delete", token=...)` removes one. Kept in its own module rather than
`onvif_control.py`, deliberately: this is meaningfully less-trodden ground than PTZ/imaging/
motion zones, so a failure here shouldn't be able to affect them.

Beyond the fields above, `get_control_state()` has an established convention (see the
docstring in `app/tbc/camera_modules/base.py`) for read-only device status the core template
renders generically whenever present, for modules with their own way to report it (typically
an external plugin using a vendor SDK - none of TBC's built-in modules populate these today):
`sdcard_supported`/`sdcard_status`/`sdcard_capacity_mb`/`sdcard_free_mb` for SD card
capacity, `wifi_supported`/`wifi_signal_percent` for Wi-Fi signal strength, and
`ntp_supported`/`ntp_enabled`/`ntp_server` for NTP time sync. These are display-only fields
with no corresponding `send_control()` action - formatting an SD card or changing NTP settings
is not implemented anywhere in TBC.

For models with optical zoom, such as the RLC-823A and TrackMix series,
`get_control_state()` also reports `zoom_supported` and `focus_supported` with current
positions and value ranges through `reolink-aio`'s `zoom_range()`, `get_zoom()`, and
`get_focus()`. Control is absolute through
`send_control(action="zoom"|"focus", position=...)`, using `set_zoom()` or `set_focus()`,
rather than relative like the digital `ZoomInc` and `ZoomDec` PTZ commands. For video
doorbells, `is_doorbell`, `quick_reply_supported`, and `quick_reply_options` report audio clips
stored on the camera through `quick_reply_dict()`. Calling
`send_control(action="quick_reply", file_id=...)` plays a clip through the speaker with
`play_quick_reply()`. Both features continue to depend only on `CONTROL`, not on separate
manifest capabilities.

`get_control_state()` may also report image adjustments (`image_bright_supported` /
`image_brightness`, and the equivalent contrast/saturation/hue/sharpness pairs), day/night
mode and threshold (`daynight_mode`, `daynight_threshold`), HDR and IR lights
(`hdr_supported`, `ir_supported`), motion and per-class AI detection sensitivity
(`md_sensitivity_supported` / `md_sensitivity`, `ai_sensitivity_rows`), on-screen display
options (`osd_supported`), speaker/doorbell volume (`volume_supported` and the
`volume_speak`/`volume_doorbell` variants), and the main/sub stream video codec
(`video_codec_main`, `video_codec_sub`). Each is applied through the matching
`send_control(action=...)` (`image`, `daynight`, `daynight_threshold`, `hdr`, `ir_lights`,
`md_sensitivity`, `ai_sensitivity`, `osd`, `volume`, `video_codec`). All of these, plus PTZ
presets, battery sleep state, and doorbell quick replies, are also exposed as Home Assistant
MQTT entities (`app/tbc/mqtt.py`) — `number` entities for adjustable values, `select` for
day/night mode and video codec, `switch` for HDR/IR (optimistic, since no readback exists for
them), and dynamically generated `number`/`button` entities per AI-sensitivity class and quick
reply. The on-screen display form is not published to MQTT: it applies three fields in one
submit and has no single-value Home Assistant equivalent.

## Firmware updates (`FIRMWARE`)

Modules with the `FIRMWARE` capability implement two additional methods:

```python
async def check_firmware(self, camera: dict, *, channel: int = 0) -> dict:
    """Read the installed version and the version available from reolink.com."""

async def update_firmware(self, camera: dict, *, channel: int = 0, progress_callback=None) -> None:
    """Download and install firmware, calling progress_callback with values from 0 to 100."""
```

The external Reolink plugin uses `reolink-aio`'s `check_new_firmware()` and
`update_firmware()` to download firmware directly from reolink.com and write it to the camera.
The camera is unavailable during the operation and restarts afterward. The web interface
deliberately uses a two-step process: the read-only **Check for updates** action must first
report an available version before **Update now** is enabled. Starting the update also
requires JavaScript confirmation. The update runs as a TBC background task and is queried
through a progress endpoint because it can take several minutes.

## Custom model for local AI detection (`detection_model.json`)

By default, TBC detects people, vehicles, and animals with a manufacturer-neutral standard
model; see `Admin → AI detection`. A camera plugin may optionally include a model tailored to
its target devices. TBC automatically uses this model **instead of** the standard model for
cameras assigned to that module. Add `detection_model.json` next to `manifest.json` in the
plugin root:

```json
{
  "model_url": "https://example.com/my-model.onnx",
  "input_name": "image_tensor:0",
  "input_size": [300, 300],
  "input_dtype": "uint8",
  "output_boxes": "detection_boxes:0",
  "output_scores": "detection_scores:0",
  "output_classes": "detection_classes:0",
  "output_num": "num_detections:0",
  "classes": {
    "1": "person",
    "3": "car"
  }
}
```

- `model_url` points to the ONNX file. On first use, TBC downloads it to
  `TBC_DETECTION_MODELS_PATH/plugins/<key>/` and caches the copy. The model file itself must
  **not** be included in the plugin repository or ZIP because of its size and plugin-import
  file-type limits; include only this small JSON metadata file.
- All other fields follow the standard model's output format: TensorFlow Object Detection API
  style with post-processed boxes, scores, and classes rather than raw YOLO grid outputs. A
  different output format requires additional code in `app/tbc/detection/onnx_backend.py` and
  cannot be supported by this file alone.
- `classes` maps model-specific class indices to COCO-like labels such as `person`, `car`, and
  `dog`. TBC normalizes them internally to `ai_person`, `ai_vehicle`, and `ai_animal`; see
  `app/tbc/detection/classes.py`.
- If `model_url` or another field changes in a new plugin version, TBC downloads the model
  again automatically.
- If a user later changes a camera's module key, the detection worker resolves the responsible
  model again on its next start.
