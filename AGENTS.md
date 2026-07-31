# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, and other AGENTS.md-compatible
tools) when working with code in this repository. See also [CLAUDE.md](CLAUDE.md), which
carries the same content for Claude Code specifically.

## Project

TBC is a modular, Docker-based camera manager (FastAPI + Jinja2 + SQLite). Camera vendors,
cloud accounts, network providers, and design themes are integrated through installable plugin
packages rather than vendor-specific code in the core app.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -r .github/requirements-ci.txt

# Lint (matches CI in .github/workflows/code-quality.yml)
ruff check app tests

# Compile check
python -m compileall -q app tests

# Run the full test suite
pytest -q
# or
python -m unittest discover -s tests

# Run a single test file / test
pytest -q tests/test_camera_modules.py
pytest -q tests/test_camera_modules.py::test_specific_case

# Coverage (CI enforces --cov-fail-under=50, see .coveragerc)
python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=50

# Validate the Compose file
docker compose config --quiet

# Run the app locally
cp .env.example .env
docker compose up --build
# -> http://localhost:8732 (default admin / bitte-aendern)
```

Tests must not require real cameras, external accounts, or internet access unless explicitly
marked and skipped by default. Use fakes for ONVIF services, RTSP discovery, cloud APIs,
storage, and notifications.

## Architecture

- **Entry point / wiring**: `app/tbc/main.py` builds the FastAPI app, middleware (session
  cookies, ingress path handling), and mounts everything under `app/tbc/routers/*` (one router
  module per feature area: cameras, live, recordings, users, plugins, mqtt, etc.).
- **Persistence**: `app/tbc/database.py` — a single large module wrapping SQLite access and
  schema migrations (the app auto-migrates existing databases on startup; legacy cameras get
  assigned the `reolink` module).
- **Plugin architecture (the core extensibility model)**: four independent, near-identical
  plugin systems, each with the same shape — a `base.py` (abstract interface), `registry.py`
  (discovery/loading), and `packages.py` (ZIP import/export/validation):
  - `app/tbc/camera_modules/` — the `CameraModule` interface (probe, live, detections,
    controls, firmware, archives). Built-in vendor implementations live in
    `app/tbc/camera_plugins/<key>/` (e.g. `standard_onvif`, `rtsp_only`), each self-contained
    with its own `manifest.json`, `plugin.py`, `detections.json`, and vendor-specific
    `module.py`/`service.py`/`catalog.py`. Truly vendor-neutral code (ONVIF helpers, the base
    class, shared RTSP-only logic in `app/tbc/manual_rtsp/`) stays outside plugin packages.
    See [docs/camera-modules.md](docs/camera-modules.md).
  - `app/tbc/cloud_modules/` + `app/tbc/cloud_plugins/` — cloud account sign-in and camera
    discovery/import, separate from camera modules. See [docs/cloud-accounts.md](docs/cloud-accounts.md).
  - `app/tbc/network_modules/` + `app/tbc/network_plugins/` — controller accounts and
    camera-to-MAC mappings. See [docs/network-accounts.md](docs/network-accounts.md).
  - `app/tbc/themes/` + `app/tbc/design_themes/` — style-only packages (manifest + CSS +
    assets, no executable code). See [docs/design-themes.md](docs/design-themes.md).
  - Additional third-party packages of all four kinds can be imported as ZIPs at runtime
    (`Admin → Camera plugins` etc.) or registered as GitHub repositories synced hourly
    (`app/tbc/plugin_sources.py`); a plugin may declare its own extra pip requirements
    (`app/tbc/plugin_requirements.py`), installed only with explicit admin confirmation. See
    [docs/plugin-sources.md](docs/plugin-sources.md).
  - When adding vendor-specific behavior, prefer a plugin over touching core routes/templates —
    the core app is meant to stay vendor-independent.
- **Recording**: `app/tbc/recording.py` drives `ffmpeg` for event and continuous recording with
  pre-roll ring buffers; storage destinations are local paths or S3 (via `boto3`).
- **Live view**: `app/tbc/live.py` serves authenticated HLS (playlists/segments via `ffmpeg`).
  `app/tbc/go2rtc.py` manages an optional bundled `go2rtc` process for sub-second WebRTC,
  proxying WHEP signaling through an authenticated route while media flows directly between
  browser and `go2rtc` on a separate published port.
- **Detection**: `app/tbc/detection/` — pluggable backends (`onnx_backend.py`, `coral_backend.py`),
  tracking, loitering/zone logic, and recognition, selected via `factory.py`.
- **Cross-cutting systems**: `app/tbc/maintenance.py` (retention/cleanup), `app/tbc/notifications.py`
  (webhook/Telegram/SMTP/Pushover/HA), `app/tbc/health.py` (camera/storage/MQTT health checks),
  `app/tbc/mqtt.py` (state publishing + HA discovery), `app/tbc/mcp_server.py` (MCP interface),
  `app/tbc/backup.py`, `app/tbc/audit.py`.
- **Home Assistant packaging**: `tbc_camera_manager/` (and `tbc_camera_manager_coral/`) contain
  the HA add-on manifests/config; the app itself is the same image as the standalone Docker
  deployment.

## Conventions

- English is the source language for all user-facing strings; every new string must be added
  to all locale files under `app/tbc/static/i18n/` (do not leave raw strings in templates or JS).
- Preserve `amd64`/`aarch64` compatibility.
- Never commit camera/cloud credentials, tokens, private stream URLs, recorded footage, or
  captured vendor API responses (tests use fakes, not real devices/accounts).
- User-visible changes should update `tbc_camera_manager/CHANGELOG.md` and the relevant file
  under `docs/`.

Full docs (user guide, operations, deployment, API/MCP, plugin development) are in
[docs/README.md](docs/README.md).
