# TBC Camera Manager (Coral) as a Home Assistant app

This is the Coral Edge TPU-accelerated variant of the TBC Camera Manager app.
It is identical to the standard **TBC Camera Manager** app in every way except
the local AI detection backend: this image additionally bundles
`ai-edge-litert` (Google's maintained successor to `tflite-runtime`) and
Google's `libedgetpu1-std` runtime, so the **Coral (Edge TPU)** option under a
camera's AI detection backend actually works instead of reporting itself
unavailable.

Install this app instead of (not alongside) the standard TBC Camera Manager
app if you have a Coral USB Accelerator or PCIe/M.2 module attached to the
Home Assistant host. If you don't have Coral hardware, install the standard
app - it is smaller and updates more often.

**Status: builds, boots, and its Python-level Coral detection path has been
exercised (import, delegate loading with no device present) in TBC's own
development environment - but there is no real Edge TPU device there, so the
actual accelerated inference path is not verified against real hardware end to
end.** The image intentionally avoids Google's `pycoral` package - it, like
`tflite-runtime`, never shipped a Linux wheel past Python 3.9, incompatible
with this project's other pinned dependencies - in favor of `ai-edge-litert`,
which has the same `Interpreter`/`load_delegate` API and real wheels for the
Python version this app actually runs. This app's Supervisor integration
(options, Ingress, backups) is the same code path already used and verified by
the standard app. If you install this and it works (or doesn't), please report
back via
[the repository's issues](https://github.com/404GamerNotFound/TBC-camera-manager/issues) -
that is genuinely how this gets confirmed working.

## Installation

Requires Home Assistant OS and a Coral USB Accelerator or PCIe/M.2 module.
Open `Settings → Apps → App store`, add the following URL from the
repository menu, and refresh the store:

```text
https://github.com/404GamerNotFound/TBC-camera-manager
```

Select **TBC Camera Manager (Coral)** (not the standard TBC Camera Manager),
install it, and set at least `admin_password` before the first start.

## Coral USB Accelerator access

This app requests `usb: true` in its Supervisor configuration, which maps
`/dev/bus/usb` into the app with plug-and-play support - this is what lets it
see the accelerator even though the USB Coral Accelerator re-enumerates as a
different USB device once its driver loads.

If the Coral backend still reports itself unavailable after installing this
app:

1. Open this app's **Info** tab in Home Assistant and confirm it shows as
   running.
2. Try disabling **Protection mode** for this app (Info tab) - some hosts
   need this in addition to `usb: true` for USB accelerator passthrough, the
   same requirement reported for other apps that use a Coral USB Accelerator
   through Supervisor.
3. For a **PCIe/M.2** Coral module (not USB), Supervisor's `usb` option does
   not apply - device passthrough for PCIe modules currently is not supported
   through this app's Supervisor packaging. Use the standalone Docker image
   (`Dockerfile.coral`) with `--device /dev/apex_0` instead.
4. Check this app's log and the **Backend status** page inside TBC
   (Admin → AI detection) for the specific error the Edge TPU runtime reports.

## Options, persistence, MQTT, and networking

Identical to the standard TBC Camera Manager app - see its `DOCS.md` for
`admin_username`, `admin_password`, `poll_interval_seconds`,
`dashboard_snapshot_interval_seconds`, `public_base_url`, backup/persistence
behavior, MQTT/Home Assistant discovery, and Ingress/WebRTC networking
details. None of that differs between the two apps.

## Technical architecture

Built from the repository-root `Dockerfile.coral` instead of the standard
app's `Dockerfile` - the only difference is the extra Coral-specific system
packages and Python dependency (`ai-edge-litert`) on top; both use the same
Python version and the same `requirements.txt`. The two images share the same
application code and the same `app/tbc/container_launcher.py` entry point,
which reads Supervisor's `/data/options.json` the same way for both apps.

## Publishing for maintainers

Mirrors the standard app's release process (see its `DOCS.md`), against
`tbc_camera_manager_coral/config.yaml` and the
`.github/workflows/home-assistant-app-coral.yml` workflow instead. The
published image is:

```text
ghcr.io/404gamernotfound/tbc-camera-manager-ha-coral:X.Y.Z
```

Keep this app's `version` in sync with the standard app's version at each
release, for a consistent user-facing version number - they otherwise release
independently since a Coral-specific fix does not need a standard-app release
and vice versa.
