# Contributing to TBC Camera Manager

Thank you for helping improve TBC Camera Manager. Bug reports, documentation,
translations, camera integrations, tests, and focused code changes are welcome.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.

## Before you start

- Search existing issues and pull requests to avoid duplicate work.
- Open a feature request before starting a large architectural change.
- Keep pull requests focused on one concern.
- Never include camera credentials, API tokens, private stream URLs, recorded
  footage, or other personal data in an issue, test fixture, or commit.

## Development setup

TBC requires Python, `ffmpeg`, and the packages from `requirements.txt`.
Docker Compose is the easiest way to run the complete application.

```bash
git clone https://github.com/404GamerNotFound/TBC-camera-manager.git
cd TBC-camera-manager
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r .github/requirements-ci.txt
```

Run the application with Docker:

```bash
cp .env.example .env
docker compose up --build
```

Do not use production camera or cloud credentials in a development environment.

## Making changes

1. Create a branch from the current default branch.
2. Follow the existing FastAPI, database, template, JavaScript, and test
   patterns.
3. Preserve compatibility with both `amd64` and `aarch64` where possible.
4. Add or update tests for behavior changes.
5. Update the relevant documentation and `tbc_camera_manager/CHANGELOG.md` for
   user-visible changes.
6. Add interface text to all locale files. English is the source language; do
   not leave raw user-facing strings in templates or JavaScript.

Camera-vendor behavior belongs in a camera or cloud plugin whenever possible.
The core application should continue to use the vendor-independent interfaces
described in `docs/camera-modules.md` and `docs/cloud-accounts.md`.

## Testing

Run the checks that apply to your change before opening a pull request:

```bash
pytest -q
python -m unittest discover -s tests
python -m compileall app tests
docker compose config
```

When changing a plugin, also run its packaged tests from the administration
interface or its local test directory. When changing a Dockerfile or dependency,
verify that the container builds successfully.

Tests must not require real cameras, external accounts, or internet access
unless the test is explicitly marked and safely skipped by default. Use fakes
for ONVIF services, RTSP discovery, cloud APIs, storage, and notifications.

## Reporting bugs

Use the bug-report form and provide:

- TBC version and installation method
- Host architecture and operating system
- Camera module and model, when relevant
- Exact reproduction steps
- Relevant logs with credentials and private addresses removed
- Expected and actual behavior

## Adding camera support

Before changing the core for a specific vendor, check whether the behavior can
be implemented as a camera or cloud plugin. Include a manifest, capability
declarations, tests, and documentation. Do not commit vendor SDKs, firmware,
credentials, or captured private API responses.

## Pull requests

Complete the pull-request template and describe both the user-visible result
and the technical implementation. Maintainers may ask for a smaller scope,
additional tests, migration handling, or documentation before merging.

Contributors retain copyright in their work and are responsible for ensuring
that submitted code, assets, models, and documentation may legally be included
in the project under its repository license.
