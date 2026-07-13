from __future__ import annotations

import zipfile
from io import BytesIO


def build_camera_plugin_template() -> bytes:
    """A minimal, installable example camera plugin - manifest, module, and a self-test.

    Meant to be downloaded, edited (key/label/probe() logic) and either
    re-uploaded as a ZIP or pushed to a public GitHub repo for use with
    Admin -> Externe Quellen. See docs/plugin-sources.md.
    """
    files = {
        "manifest.json": """{
  "schema_version": 1,
  "key": "acme_camera",
  "label": "Acme Camera",
  "version": "1.0.0",
  "description": "Vorlage fuer ein eigenes Kamera-Plugin - Schluessel, Namen und probe() anpassen",
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
    """Vorlage fuer ein eigenes TBC-Kamera-Plugin.

    Diese Klasse, den Schluessel in manifest.json und probe() an die eigene
    Kamera-API anpassen. `camera` enthaelt host/onvif_port/http_port/
    username/password aus der TBC-Kamerakonfiguration.
    """

    async def probe(self, camera: dict[str, Any]) -> CameraSnapshot:
        # TODO: Hersteller-API abfragen und das Ergebnis hier eintragen.
        return CameraSnapshot(
            status="ok",
            message="Beispielantwort - probe() noch nicht implementiert",
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
        "README.md": """# Acme Camera (Vorlage)

Diese Vorlage ist ein vollstaendiges, installierbares Kamera-Plugin fuer TBC.
Vor der Verwendung anpassen:

1. `manifest.json`: `key`, `label`, `description` und die Standard-Ports fuer die eigene Kamera setzen.
2. `module.py`: `probe()` mit der eigenen Kamera-API implementieren.
3. `tests/test_module.py`: eigene Tests ergaenzen - `Admin -> Kamera-Plugins -> Tests ausfuehren`
   fuehrt sie direkt in TBC aus.

Siehe docs/camera-modules.md (im TBC-Repository) fuer den vollstaendigen Vertrag
(`CameraModule`, `CameraSnapshot`, optionale Faehigkeiten wie `CONTROL`/`FIRMWARE`).
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
  "description": "Vorlage fuer ein eigenes Cloud-Konto-Plugin - Schluessel, Namen und Felder anpassen",
  "entrypoint": "plugin.py",
  "auth_type": "credentials",
  "verification_support": "not_applicable",
  "account_fields": [
    {
      "key": "email",
      "label": "E-Mail-Adresse",
      "type": "email",
      "required": true,
      "autocomplete": "username"
    },
    {
      "key": "password",
      "label": "Passwort",
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
    """Vorlage fuer ein eigenes TBC-Cloud-Konto-Plugin.

    Diese Klasse, den Schluessel in manifest.json und die Anmelde-/Geraetesuche-
    Logik an die eigene Cloud-API anpassen. `account` enthaelt die in
    manifest.json deklarierten Felder (hier: email, password).

    Verlangt der Anbieter einen Bestaetigungscode (2FA/E-Mail/SMS), ein
    eigenes account_fields-Feld mit "transient": true dafuer anlegen und bei
    Bedarf `CloudVerificationRequired(message, field_key="...")` auslösen -
    siehe docs/cloud-accounts.md, Abschnitt "Zwei-Faktor-/Bestaetigungscodes".
    """

    async def test_connection(self, account: dict[str, Any]) -> str:
        email = str(account.get("email") or "")
        if not email:
            raise CloudConnectionError("E-Mail-Adresse ist erforderlich")
        # TODO: bei der eigenen Cloud-API anmelden.
        return "Beispielantwort - test_connection() noch nicht implementiert"

    async def discover_devices(self, account: dict[str, Any]) -> list[CloudDevice]:
        # TODO: Geraeteliste von der eigenen Cloud-API abfragen.
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
        "README.md": """# Acme Cloud (Vorlage)

Diese Vorlage ist ein vollstaendiges, installierbares Cloud-Konto-Plugin fuer TBC.
Vor der Verwendung anpassen:

1. `manifest.json`: `key`, `label`, `description`, `account_fields` (Kontoformular)
   und `verification_support` (`supported`, falls der Anbieter Bestaetigungscodes
   verlangen kann) an die eigene Cloud-API anpassen.
2. `module.py`: `test_connection()` und `discover_devices()` implementieren.
   `CloudDevice.manual_stream_uri` setzen, wenn die Cloud-API eine feste
   RTSP-/RTSPS-URL liefert - dann bietet TBC automatisch "Als Kamera hinzufuegen" an.
3. `tests/test_module.py`: eigene Tests ergaenzen - `Admin -> Cloud-Anbieter -> Tests ausfuehren`
   fuehrt sie direkt in TBC aus.

Siehe docs/cloud-accounts.md (im TBC-Repository) fuer den vollstaendigen Vertrag.
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
  "description": "Vorlage fuer ein eigenes Design - Schluessel, Namen und styles.css anpassen",
  "stylesheet": "styles.css"
}
""",
        "static/styles.css": """/* Vorlage fuer ein eigenes TBC-Design.
   Diese Datei ueberschreibt/ergaenzt das Standard-Stylesheet vollstaendig -
   siehe docs/design-themes.md (im TBC-Repository) fuer die verwendeten
   CSS-Variablen und Klassen. Minimal-Beispiel: */

:root {
  --accent-color: #2f6f4f;
}
""",
        "README.md": """# Acme Design (Vorlage)

Diese Vorlage ist ein vollstaendiges, installierbares Design fuer TBC. Designs
enthalten keinen ausfuehrbaren Code - nur `manifest.json` und `static/styles.css`
(plus optional weitere Bilder/Icons unter `static/`).

Vor der Verwendung anpassen:

1. `manifest.json`: `key`, `label`, `description` anpassen.
2. `static/styles.css`: eigenes Stylesheet ergaenzen.

Siehe docs/design-themes.md (im TBC-Repository) fuer die vollstaendige Liste
der verwendeten CSS-Variablen und Klassen.
""",
    }
    return _build_zip(files)


def _build_zip(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return output.getvalue()
