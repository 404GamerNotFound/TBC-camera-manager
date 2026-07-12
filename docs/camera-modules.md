# Kamera-Module entwickeln

TBC trennt herstellerspezifische Kamera-APIs über `CameraModule` von der Weboberfläche. Die eingebauten Module `reolink`, `tplink`, `standard_onvif`, `aqara`, `ubiquiti`, `sonoff`, `rtsp_only`, `axis`, `foscam`, `hikvision` und `dahua` sind Referenzimplementierungen. Weitere Module können als ZIP-Plugin über die Admin-Oberfläche importiert werden, ohne Routen oder Templates in TBC zu ändern.

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

Die eingebauten Module liegen vollständig unter `app/tbc/camera_plugins/<schlüssel>/` — nicht nur `manifest.json`/`plugin.py`/`detections.json`, sondern auch die komplette herstellerspezifische Implementierung (`module.py`, `service.py`, `catalog.py`, ggf. `control.py`). Jedes eingebaute Modul ist damit genauso in sich geschlossen wie ein extern installiertes Plugin; nur generischer, herstellerneutraler Code (ONVIF-Hilfsfunktionen, die `CameraModule`-Basisklasse, die gemeinsame `manual_rtsp`-Implementierung für reine RTSP-Profile) liegt bewusst außerhalb, unter `app/tbc/camera_modules/` bzw. `app/tbc/manual_rtsp/`. Profile ohne auswertbare Ereignisquelle verwenden eine leere `detections.json`-Liste und deklarieren nur `live`.

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
- `CONTROL`: Das Modul implementiert `get_control_state()` und `send_control()` für Live-Gerätesteuerung (z. B. PTZ inkl. gespeicherter Positionen, Flutlicht, PIR-Sensor, Sirene, Neustart, Akkustatus).
- `FIRMWARE`: Das Modul implementiert `check_firmware()` und `update_firmware()` für Firmware-Prüfung und -Aktualisierung.

Die Implementierungen liegen in den Herstellerpaketen unter `app/tbc/camera_plugins/<schlüssel>/`. Ihre jeweiligen Adapter `module.py` sind die einzigen Einstiegspunkte, die die Registry verwendet; `plugin.py` lädt sie über `import_tbc("camera_plugins.<schlüssel>.module")` — denselben Mechanismus, den auch extern installierte Plugins für den Zugriff auf die TBC-Basisklassen nutzen.

## Kamerasteuerung (`CONTROL`)

Module mit der Fähigkeit `CONTROL` implementieren zwei zusätzliche Methoden:

```python
async def get_control_state(self, camera: dict, *, channel: int = 0) -> dict:
    """Aktuellen Gerätezustand liefern, z. B. {"floodlight_supported": True, "floodlight_state": False, ...}."""

async def send_control(self, camera: dict, *, action: str, channel: int = 0, **params) -> dict:
    """Einen Steuerbefehl ausführen, z. B. action="floodlight", params={"state": True}."""
```

Das eingebaute `reolink`-Modul (`app/tbc/camera_plugins/reolink/control.py`) implementiert darüber PTZ-Schwenk/Neige-Befehle (inkl. auf der Kamera gespeicherter PTZ-Positionen über `reolink-aio`s `ptz_presets()`/`set_ptz_command(preset=...)`), Flutlicht, PIR-Sensor, Sirene, Neustart und Akkustatus. `tplink`, `standard_onvif` und `aqara` bieten PTZ über den herstellerneutralen ONVIF-PTZ-Service (`app/tbc/camera_modules/onvif_control.py`) an, den ihre jeweiligen `camera_plugins/<schlüssel>/control.py`-Adapter nur mit dem passenden Standard-ONVIF-Port aufrufen (ohne Positionsspeicher). Die Weboberfläche zeigt bei vorhandener `CONTROL`-Fähigkeit einen zusätzlichen „Steuerung“-Tab je Kamera; ist MQTT/Home-Assistant-Discovery aktiviert, werden dieselben Aktionen zusätzlich als HA-Entities (Licht, Schalter, Taster, Sensor) veröffentlicht und über MQTT-Befehlstopics fernsteuerbar (`app/tbc/mqtt.py`).

## Firmware-Updates (`FIRMWARE`)

Module mit der Fähigkeit `FIRMWARE` implementieren zwei zusätzliche Methoden:

```python
async def check_firmware(self, camera: dict, *, channel: int = 0) -> dict:
    """Nur lesend: aktuelle und bei reolink.com verfügbare Version liefern."""

async def update_firmware(self, camera: dict, *, channel: int = 0, progress_callback=None) -> None:
    """Firmware herunterladen und auf das Gerät schreiben; ruft progress_callback(0..100) auf."""
```

Das eingebaute `reolink`-Modul lädt dafür über `reolink-aio`s `check_new_firmware()`/`update_firmware()` direkt von reolink.com herunter und schreibt sie auf die Kamera; die Kamera ist währenddessen nicht erreichbar und startet danach neu. In der Weboberfläche liegt der Ablauf bewusst zweistufig: „Auf Updates prüfen“ (rein lesend) muss zuerst erfolgreich eine verfügbare Version melden, bevor „Jetzt aktualisieren“ überhaupt aktiv wird; der Update-Start verlangt zusätzlich eine JavaScript-Bestätigung. Der Update-Vorgang läuft als Hintergrund-Task in TBC und wird über einen Fortschritts-Endpunkt abgefragt, da er mehrere Minuten dauern kann.
