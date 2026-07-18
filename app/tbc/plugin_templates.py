from __future__ import annotations

import zipfile
from io import BytesIO


def build_camera_plugin_template() -> bytes:
    """A minimal, installable example camera plugin - manifest, module, and a self-test.

    Meant to be downloaded, edited (key/label/probe() logic) and either
    re-uploaded as a ZIP or pushed to a public GitHub repo for use with
    Admin -> External sources. See docs/plugin-sources.md.
    """
    files = {
        "manifest.json": """{
  "schema_version": 1,
  "key": "acme_camera",
  "label": "Acme Camera",
  "version": "1.0.0",
  "description": "Template for a custom camera plugin - adjust the key, name, and probe()",
  "entrypoint": "plugin.py",
  "capabilities": ["live"],
  "ports": {"onvif": 8000, "http": 80, "rtsp": 554}
}
""",
        "plugin.py": '''from .module import AcmeCameraModule


def create_module():
    return AcmeCameraModule()
''',
        "module.py": '''from __future__ import annotations

from typing import Any

from tbc_camera_api import CameraModule, CameraSnapshot


class AcmeCameraModule(CameraModule):
    """Template for a custom TBC camera plugin.

    Adjust this class, the key in manifest.json, and probe() to match the
    actual camera API. `camera` contains host/onvif_port/http_port/
    username/password from the TBC camera configuration.
    """

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        # TODO: Query the vendor API and record the result here.
        return CameraSnapshot(
            status="ok",
            message="Example response - probe() not implemented yet",
            manufacturer="Acme",
            model="Camera",
        )
''',
        "detections.json": "[]\n",
        "tests/test_module.py": '''import unittest

from tbc_camera_api import CameraSnapshot

from module import AcmeCameraModule


class AcmeCameraModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_returns_a_snapshot(self):
        module = AcmeCameraModule()

        snapshot = await module.probe({"host": "192.0.2.1", "username": "admin", "password": "secret"})

        self.assertIsInstance(snapshot, CameraSnapshot)
        self.assertEqual(snapshot.status, "ok")


if __name__ == "__main__":
    unittest.main()
''',
        "README.md": """# Acme Camera (template)

This template is a complete, installable camera plugin for TBC.
Before using it:

1. `manifest.json`: set `key`, `label`, `description`, and the default ports for the actual camera.
2. `module.py`: implement `probe()` against the actual camera API.
3. `tests/test_module.py`: add your own tests - `Admin -> Camera plugins -> Run tests`
   runs them directly in TBC.

See docs/camera-modules.md (in the TBC repository) for the full contract
(`CameraModule`, `CameraSnapshot`, optional capabilities like `CONTROL`/`FIRMWARE`).
""",
    }
    return _build_zip(files)


def build_cloud_plugin_template() -> bytes:
    """A minimal, installable example cloud-account plugin - manifest, module, and a self-test."""
    files = {
        "manifest.json": """{
  "schema_version": 1,
  "key": "acme_cloud",
  "label": "Acme Cloud",
  "version": "1.0.0",
  "description": "Template for a custom cloud-account plugin - adjust the key, name, and fields",
  "entrypoint": "plugin.py",
  "auth_type": "credentials",
  "verification_support": "not_applicable",
  "account_fields": [
    {
      "key": "email",
      "label": "Email address",
      "type": "email",
      "required": true,
      "autocomplete": "username"
    },
    {
      "key": "password",
      "label": "Password",
      "type": "password",
      "required": true,
      "autocomplete": "current-password"
    }
  ]
}
""",
        "plugin.py": '''from .module import AcmeCloudModule


def create_module():
    return AcmeCloudModule()
''',
        "module.py": '''from __future__ import annotations

from typing import Any

from tbc_cloud_api import CloudAccountModule, CloudConnectionError, CloudDevice


class AcmeCloudModule(CloudAccountModule):
    """Template for a custom TBC cloud-account plugin.

    Adjust this class, the key in manifest.json, and the sign-in/device-
    discovery logic to match the actual cloud API. `account` contains the
    fields declared in manifest.json (here: email, password).

    If the provider requires a verification code (2FA/email/SMS), add a
    dedicated account_fields entry with "transient": true and raise
    `CloudVerificationRequired(message, field_key="...")` where needed -
    see docs/cloud-accounts.md, section "Two-factor/verification codes".
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        email = str(account.get("email") or "")
        if not email:
            raise CloudConnectionError("Email address is required")
        # TODO: Sign in to the actual cloud API.
        return "Example response - test_connection() not implemented yet"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        # TODO: Query the device list from the actual cloud API.
        return []


def create_module():
    return AcmeCloudModule()
''',
        "tests/test_module.py": '''import unittest

from tbc_cloud_api import CloudConnectionError

from module import AcmeCloudModule


class AcmeCloudModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_requires_email(self):
        module = AcmeCloudModule()

        with self.assertRaises(CloudConnectionError):
            await module.test_connection({})

    async def test_discover_devices_returns_a_list(self):
        module = AcmeCloudModule()

        devices = await module.discover_devices({"email": "guest@example.com"})

        self.assertEqual(devices, [])


if __name__ == "__main__":
    unittest.main()
''',
        "README.md": """# Acme Cloud (template)

This template is a complete, installable cloud-account plugin for TBC.
Before using it:

1. `manifest.json`: adjust `key`, `label`, `description`, `account_fields` (account form)
   and `verification_support` (`supported` if the provider can require verification
   codes) to match the actual cloud API.
2. `module.py`: implement `test_connection()` and `discover_devices()`.
   Set `CloudDevice.manual_stream_uri` if the cloud API provides a fixed
   RTSP/RTSPS URL - TBC then automatically offers "Add as camera".
3. `tests/test_module.py`: add your own tests - `Admin -> Cloud providers -> Run tests`
   runs them directly in TBC.

See docs/cloud-accounts.md (in the TBC repository) for the full contract.
""",
    }
    return _build_zip(files)


def build_network_plugin_template() -> bytes:
    """A minimal, installable example network-account plugin - manifest, module, and a self-test."""
    files = {
        "manifest.json": """{
  "schema_version": 1,
  "key": "acme_network",
  "label": "Acme Network",
  "version": "1.0.0",
  "description": "Template for a custom network-account plugin - adjust the key, name, and fields",
  "entrypoint": "plugin.py",
  "account_fields": [
    {
      "key": "host",
      "label": "Host",
      "type": "text",
      "required": true,
      "placeholder": "192.168.1.1"
    },
    {
      "key": "identifier",
      "label": "Username",
      "type": "text",
      "required": true,
      "autocomplete": "username"
    },
    {
      "key": "secret",
      "label": "Password",
      "type": "password",
      "required": true,
      "autocomplete": "current-password"
    }
  ]
}
""",
        "plugin.py": '''from .module import AcmeNetworkModule


def create_module():
    return AcmeNetworkModule()
''',
        "module.py": '''from __future__ import annotations

from typing import Any

from tbc_network_api import NetworkAccountModule, NetworkConnectionError, NetworkDevice


class AcmeNetworkModule(NetworkAccountModule):
    """Template for a custom TBC network-account plugin.

    Adjust this class, the key in manifest.json, and discover_devices() to
    match the actual controller API. `account` contains the fields declared
    in manifest.json (here: host, identifier, secret).
    """

    async def discover_devices(self, account: dict[str, Any]) -> list[NetworkDevice]:
        host = str(account.get("host") or "")
        if not host:
            raise NetworkConnectionError("Host is required")
        # TODO: Query the actual controller API for its client/device list.
        return []


def create_module():
    return AcmeNetworkModule()
''',
        "tests/test_module.py": '''import unittest

from tbc_network_api import NetworkConnectionError

from module import AcmeNetworkModule


class AcmeNetworkModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_devices_requires_host(self):
        module = AcmeNetworkModule()

        with self.assertRaises(NetworkConnectionError):
            await module.discover_devices({})

    async def test_discover_devices_returns_a_list(self):
        module = AcmeNetworkModule()

        devices = await module.discover_devices({"host": "192.168.1.1"})

        self.assertEqual(devices, [])


if __name__ == "__main__":
    unittest.main()
''',
        "README.md": """# Acme Network (template)

This template is a complete, installable network-account plugin for TBC.
Before using it:

1. `manifest.json`: adjust `key`, `label`, `description`, `account_fields`
   (account form) to match the actual controller API.
2. `module.py`: implement `discover_devices()` - return one `NetworkDevice`
   per client the controller knows about (MAC address, name, online state,
   wired/Wi-Fi, AP/switch name, signal, last seen).
3. `tests/test_module.py`: add your own tests - `Admin -> Network providers -> Run tests`
   runs them directly in TBC.

See docs/network-accounts.md (in the TBC repository) for the full contract.
""",
    }
    return _build_zip(files)


def build_design_theme_template() -> bytes:
    """A minimal, installable example design theme - manifest and stylesheet, no code."""
    files = {
        "manifest.json": """{
  "schema_version": 1,
  "key": "acme_design",
  "label": "Acme Design",
  "version": "1.0.0",
  "description": "Template for a custom design - adjust the key, name, and styles.css",
  "stylesheet": "styles.css"
}
""",
        "static/styles.css": """/* Template for a custom TBC design.
   This file fully overrides/extends the standard stylesheet -
   see docs/design-themes.md (in the TBC repository) for the
   CSS variables and classes in use. Minimal example: */

:root {
  --accent-color: #2f6f4f;
}
""",
        "README.md": """# Acme Design (template)

This template is a complete, installable design for TBC. Designs
contain no executable code - only `manifest.json` and `static/styles.css`
(plus optionally more images/icons under `static/`).

Before using it:

1. `manifest.json`: adjust `key`, `label`, `description`.
2. `static/styles.css`: add the actual stylesheet.

See docs/design-themes.md (in the TBC repository) for the full list
of CSS variables and classes in use.
""",
    }
    return _build_zip(files)


def _build_zip(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return output.getvalue()
