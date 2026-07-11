# Kamera-Module entwickeln

TBC trennt herstellerspezifische Kamera-APIs über `CameraModule` von der Weboberfläche. Die eingebauten Module `reolink`, `tplink`, `standard_onvif`, `aqara`, `ubiquiti`, `sonoff` und `rtsp_only` sind Referenzimplementierungen. Weitere Module können als ZIP-Plugin über die Admin-Oberfläche importiert werden, ohne Routen oder Templates in TBC zu ändern.

## Plugin-Datei

Eine Plugin-ZIP enthält ihre Dateien direkt im Hauptverzeichnis oder in genau einem gemeinsamen Ordner:

```text
acme-camera-plugin.zip
├── manifest.json
├── plugin.py
├── detections.json
├── service.py
└── README.md
```

`manifest.json` ist die verbindliche Konfiguration für Metadaten, Ports und Fähigkeiten:

```json
{
  "schema_version": 1,
  "key": "acme",
  "label": "Acme Camera",
  "version": "1.0.0",
  "description": "Acme-Kameras",
  "entrypoint": "plugin.py",
  "capabilities": ["live", "detections"],
  "ports": {"onvif": 8000, "http": 80, "rtsp": 554}
}
```

Die eingebauten Konfigurationen befinden sich unter `app/tbc/camera_plugins/`. Dort liegen auch die jeweiligen `detections.json`-Dateien. Profile ohne auswertbare Ereignisquelle verwenden eine leere Liste und deklarieren nur `live`.

## Öffentlicher Vertrag

Ein Modul erbt von `tbc_camera_api.CameraModule`. Schlüssel, Anzeigename und Fähigkeiten werden im Manifest definiert:

```python
from tbc_camera_api import CameraModule, CameraSnapshot


class AcmeCameraModule(CameraModule):
    async def probe(self, camera):
        # Hersteller-API abfragen und in das einheitliche TBC-Modell übersetzen.
        return CameraSnapshot(
            status="ok",
            message="Acme-Kamera erfolgreich abgefragt",
            manufacturer="Acme",
            model="Camera",
            stream_uri="rtsp://...",
            detections=[],
            channels=[],
        )


def create_module():
    return AcmeCameraModule()
```

`plugin.py` stellt entweder `create_module()` oder eine Variable `MODULE` bereit. Metadaten und Fähigkeiten werden aus dem Manifest auf die Modulinstanz übertragen. `probe()` ist die einzige Pflichtmethode. Optional kann ein Modul `detection_definitions()`, `list_archive_recordings()`, `open_archive_download()`, `get_control_state()` und `send_control()` implementieren. Ein Archiv-Download liefert ein Objekt mit `filename`, `length` und dem asynchronen Byte-Iterator `chunks()`.

Module, die eine vollständige Stream-URL statt separater ONVIF-Zugangsdaten erwarten, setzen `supports_manual_stream_uri = True`, `requires_manual_stream_uri = True` und `requires_credentials = False`. TBC speichert diese URL getrennt in `manual_stream_uri`, validiert ausschließlich `rtsp://` und `rtsps://` und rendert sie nie unzensiert in HTML. `ubiquiti`, `sonoff` und `rtsp_only` verwenden die gemeinsame Implementierung `manual_rtsp/`.

Die einheitliche Momentaufnahme `CameraSnapshot` enthält Gerätestatus, Herstellerdaten, RTSP-URI, Erkennungszustände und Kanäle. Erkennungszeilen verwenden die Felder `key`, `label`, `category`, `channel`, `supported`, `active`, `source` und optional `raw_value`.

## Import und Export

Administratoren öffnen `Admin → Kamera-Plugins` und importieren dort die ZIP-Datei. TBC prüft Manifest, Pfade, Dateitypen, Dateianzahl und entpackte Größe, lädt das Modul testweise und installiert es anschließend atomar. Ein vorhandenes externes Plugin mit demselben Schlüssel wird dabei aktualisiert. Eingebaute Plugins können weder überschrieben noch entfernt werden.

Jedes dateibasierte Plugin kann über dieselbe Seite wieder als ZIP exportiert werden. Externe Plugins dürfen nur entfernt werden, wenn keine Kamera mehr darauf verweist. Der Speicherort wird mit `TBC_CAMERA_MODULES_PATH` konfiguriert und liegt im Docker-Setup im persistenten `/data`-Volume.

Alternativ bleiben Python-Distributionen mit dem Entry-Point `tbc.camera_modules` unterstützt. Diese werden außerhalb der ZIP-Verwaltung über den Image-Build installiert.

## Sicherheit

Ein Kamera-Plugin enthält ausführbaren Python-Code und besitzt dieselben Rechte wie der TBC-Prozess. Die ZIP-Prüfung verhindert technische Archivangriffe, kann aber keinen absichtlich schädlichen Python-Code sicher erkennen. Deshalb dürfen ausschließlich Plugins aus vertrauenswürdigen Quellen importiert werden. Zugangsdaten werden pro Kamera in TBC gespeichert und gehören niemals in eine exportierte Plugin-Datei.

## Fähigkeiten

- `LIVE`: Das Modul liefert einen Stream, der in der Live-Ansicht verwendet werden darf.
- `RECORDING`: Ereignisse des Moduls dürfen die generische TBC-Aufnahme auslösen.
- `DETECTIONS`: Das Modul stellt Erkennungsdefinitionen und Zustände bereit.
- `CHANNELS`: Das Modul unterstützt mehrere Kamera- oder NVR-Kanäle.
- `ARCHIVE`: Das Modul implementiert Suche, Wiedergabe und Download des Kamera-Archivs.
- `CONTROL`: Das Modul implementiert `get_control_state()` und `send_control()` für Live-Gerätesteuerung (z. B. PTZ, Flutlicht, PIR-Sensor, Sirene, Neustart, Akkustatus).

Die Implementierungen liegen in den Herstellerpaketen unter `app/tbc/`. Ihre jeweiligen Adapter `module.py` sind die einzigen Einstiegspunkte, die die Registry verwendet.

## Kamerasteuerung (`CONTROL`)

Module mit der Fähigkeit `CONTROL` implementieren zwei zusätzliche Methoden:

```python
async def get_control_state(self, camera: dict, *, channel: int = 0) -> dict:
    """Aktuellen Gerätezustand liefern, z. B. {"floodlight_supported": True, "floodlight_state": False, ...}."""

async def send_control(self, camera: dict, *, action: str, channel: int = 0, **params) -> dict:
    """Einen Steuerbefehl ausführen, z. B. action="floodlight", params={"state": True}."""
```

Das eingebaute `reolink`-Modul (`app/tbc/reolink/control.py`) implementiert darüber PTZ-Schwenk/Neige-Befehle, Flutlicht, PIR-Sensor, Sirene, Neustart und Akkustatus über `reolink-aio`. Die Weboberfläche zeigt bei vorhandener `CONTROL`-Fähigkeit einen zusätzlichen „Steuerung“-Tab je Kamera; ist MQTT/Home-Assistant-Discovery aktiviert, werden dieselben Aktionen zusätzlich als HA-Entities (Licht, Schalter, Taster, Sensor) veröffentlicht und über MQTT-Befehlstopics fernsteuerbar (`app/tbc/mqtt.py`).
