# Home Assistant App: TBC Camera Manager (Coral)

TBC is a modular camera manager for ONVIF and RTSP cameras. This variant
additionally bundles `pycoral`/`tflite-runtime` and the Coral Edge TPU runtime
for hardware-accelerated local AI detection, for installs with a Coral USB
Accelerator or PCIe/M.2 module attached.

Everything else - the app itself, its options, and Ingress behavior - is
identical to the standard **TBC Camera Manager** app. Install this variant
instead of (not in addition to) the standard one if you have Coral hardware;
install the standard one if you don't.

Supported architecture: `amd64` only, matching Coral accelerator hardware.

**This image has not been verified against real Edge TPU hardware in TBC's own
development environment** - see `DOCS.md` for details and how to report results.
