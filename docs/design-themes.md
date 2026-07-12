# Designs entwickeln

TBC trennt das visuelle Design von der Weboberfläche über eine Design-Schnittstelle, die genauso funktioniert wie die Kamera-Plugins: Ein Design ist ein in sich geschlossenes Paket aus Metadaten und Stylesheet, das eingebaut oder als ZIP importiert sein kann. Die Weboberfläche selbst enthält keine fest verdrahteten Farben oder Layout-Regeln mehr — sie referenziert nur noch das gerade aktive Design.

Ausgeliefert werden zwei Designs: `standard` (das bisherige helle Design, weiterhin Vorgabe) und `midnight` (ein dunkles Design mit blauem Akzent).

## Design-Paket

Ein Design-ZIP enthält seine Dateien direkt im Hauptverzeichnis oder in genau einem gemeinsamen Ordner:

```text
acme-design.zip
├── manifest.json
└── static/
    └── styles.css
```

`manifest.json` ist die verbindliche Konfiguration:

```json
{
  "schema_version": 1,
  "key": "acme",
  "label": "Acme Design",
  "version": "1.0.0",
  "description": "Ein Beispiel-Design",
  "stylesheet": "styles.css"
}
```

`stylesheet` verweist auf eine Datei relativ zu `static/` innerhalb des Pakets. Anders als ein Kamera-Plugin enthält ein Design-Paket ausschließlich Stylesheets (`.css`), Metadaten (`.json`, `.md`) und Bilder (`.png`, `.jpg`, `.jpeg`, `.svg`, `.webp`, `.ico`) — keinen ausführbaren Code. Dadurch ist ein Design-Import deutlich risikoärmer als ein Kamera-Plugin-Import.

Die eingebauten Designs liegen vollständig unter `app/tbc/design_themes/<schlüssel>/`, inklusive ihres kompletten Stylesheets — genauso in sich geschlossen wie ein extern installiertes Design.

## Aktives Design

TBC merkt sich das aktive Design pro Installation in der Datenbank (Tabelle `ui_settings`, Vorgabe `standard`). Jede gerenderte Seite bindet automatisch das Stylesheet des aktiven Designs über die Route `/design/{schlüssel}/static/{pfad}` ein; diese Route ist wie `/static` ohne Login erreichbar, damit auch die Login-Seite korrekt gestaltet ist.

## Import, Aktivierung und Export

Administratoren öffnen `Admin → Design` und importieren dort eine Design-ZIP-Datei. TBC prüft Manifest, Pfade, Dateitypen, Dateianzahl und entpackte Größe (maximal 5 MB Archiv, 10 MB entpackt) und installiert das Design anschließend atomar. Ein vorhandenes externes Design mit demselben Schlüssel wird dabei aktualisiert. Eingebaute Designs können weder überschrieben noch entfernt werden.

Über dieselbe Seite wird ein Design aktiviert (`Aktivieren`-Button) oder als ZIP exportiert. Das aktive Design kann nicht entfernt werden. Der Speicherort externer Designs wird mit `TBC_THEME_MODULES_PATH` konfiguriert (Vorgabe `/data/design-themes`) und liegt im Docker-Setup im persistenten `/data`-Volume.

## Sicherheit

Ein Design-Paket enthält keinen ausführbaren Code, sondern nur Stylesheets, Metadaten und Bilder. Die ZIP-Prüfung verhindert Pfad- und Dateityp-Angriffe. Trotzdem sollten nur Designs aus vertrauenswürdigen Quellen importiert werden, da ein Stylesheet die gesamte Oberfläche verändern kann.
