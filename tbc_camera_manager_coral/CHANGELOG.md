# Changelog

## 0.9.7 - "Diagnosis you can trust"

- Kept in version lockstep with the standard app's 0.9.7 release: fixes a race condition (issue #34) where the live-stream diagnosis message could be lost on a fast crash-and-retry. No Coral-specific changes in this release.

## 0.9.6 - "Coral, for real"

- Initial release of the Coral Edge TPU-accelerated Home Assistant app variant, built from
  `Dockerfile.coral`. Bundles `ai-edge-litert` (Google's maintained successor to
  `tflite-runtime`, which - like `pycoral` - never shipped a Linux wheel past Python 3.9,
  incompatible with this project's other pinned dependencies) and Google's
  `libedgetpu1-std` runtime, so the Coral backend actually works instead of reporting
  itself unavailable. Runs the exact same `requirements.txt` and Python version as the
  standard app. Requests `usb: true` for Coral USB Accelerator passthrough. `amd64` only,
  matching Coral accelerator hardware. The image builds, boots, and its Python-level Coral
  detection has been exercised without a real device attached - not yet verified against
  real Edge TPU hardware end to end. See this app's `DOCS.md`.
