# Kamera-Module entwickeln

TBC trennt herstellerspezifische Kamera-APIs über `CameraModule` von der Weboberfläche. Die eingebauten Module `reolink` und `tplink` sind Referenzimplementierungen. Weitere Module können als normales Python-Paket installiert werden, ohne Routen oder Templates in TBC zu ändern.

## Öffentlicher Vertrag

Ein Modul erbt von `app.tbc.camera_modules.CameraModule` und definiert einen stabilen Schlüssel, einen Anzeigenamen und seine Fähigkeiten:

```python
from app.tbc.camera_modules import CameraCapability, CameraModule, CameraSnapshot


class AcmeCameraModule(CameraModule):
    key = "acme"
    label = "Acme Camera"
    description = "Acme-Kameras"
    capabilities = frozenset({
        CameraCapability.LIVE,
        CameraCapability.RECORDING,
        CameraCapability.DETECTIONS,
    })

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
```

`probe()` ist die einzige Pflichtmethode. Optional kann ein Modul `detection_definitions()`, `list_archive_recordings()` und `open_archive_download()` implementieren. Nur Fähigkeiten, die in `capabilities` deklariert sind, werden von Oberfläche und Routen angeboten. Ein Archiv-Download liefert ein Objekt mit `filename`, `length` und dem asynchronen Byte-Iterator `chunks()`.

Die einheitliche Momentaufnahme `CameraSnapshot` enthält Gerätestatus, Herstellerdaten, RTSP-URI, Erkennungszustände und Kanäle. Erkennungszeilen verwenden die Felder `key`, `label`, `category`, `channel`, `supported`, `active`, `source` und optional `raw_value`.

## Installation und Registrierung

Das Modul-Paket registriert seine Klasse über den Python-Entry-Point `tbc.camera_modules`:

```toml
[project.entry-points."tbc.camera_modules"]
acme = "tbc_camera_acme:AcmeCameraModule"
```

Nach Installation des Pakets in derselben Python-Umgebung und einem Neustart erscheint das Modul automatisch im Feld „Modul“ beim Anlegen einer Kamera. Modulschlüssel werden in der Datenbank pro Kamera gespeichert. Wird ein externes Modul später entfernt, bleiben die Kameradaten erhalten; herstellerspezifische Aktionen melden dann, dass das Modul nicht installiert ist.

Bei Docker-Deployments wird das zusätzliche Paket beim Image-Build installiert, zum Beispiel in einem abgeleiteten Dockerfile:

```dockerfile
FROM tbc-camera-manager:latest
RUN pip install --no-cache-dir tbc-camera-acme
```

## Fähigkeiten

- `LIVE`: Das Modul liefert einen Stream, der in der Live-Ansicht verwendet werden darf.
- `RECORDING`: Ereignisse des Moduls dürfen die generische TBC-Aufnahme auslösen.
- `DETECTIONS`: Das Modul stellt Erkennungsdefinitionen und Zustände bereit.
- `CHANNELS`: Das Modul unterstützt mehrere Kamera- oder NVR-Kanäle.
- `ARCHIVE`: Das Modul implementiert Suche, Wiedergabe und Download des Kamera-Archivs.

Das Reolink-Modul liegt unter `app/tbc/reolink/`, das TP-Link/Tapo-Modul unter `app/tbc/tplink/`. Ihre jeweiligen Adapter `module.py` sind die einzigen herstellerspezifischen Einstiegspunkte, die die Registry verwendet.
