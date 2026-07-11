# TBC - TB Camera

TBC ist ein modularer, Docker-basierter Kamera-Manager. Hersteller werden über installierbare Kamera-Module angebunden; Reolink, TP-Link/Tapo, Aqara, Ubiquiti/UniFi Protect, SONOFF, ein reines RTSP-Profil und ein herstellerneutraler Standard-ONVIF-Fallback sind eingebaut. Die aktuelle Version bringt Login, Kamera-Verwaltung, RTSP-Stream-Ermittlung, Dashboard-Vorschaubilder, ereignisbasierte Aufnahmen, Clip-Browser, Rollen, MQTT/Home-Assistant-Anbindung, Live-HLS, Retention, Benachrichtigungen, Health-Monitoring und NVR-Kanalverwaltung mit.

## Start

```bash
cp .env.example .env
docker compose up --build
```

Danach ist die Weboberflaeche unter <http://localhost:8732> erreichbar.

Standardwerte aus `docker-compose.yml`:

- Benutzer: `admin`
- Passwort: `bitte-aendern`
- Web-Port: `8732`
- Datenbank: `/data/tbc.sqlite3` im Docker-Volume `tbc-data`
- Aufnahmen: `/recordings` im Docker-Volume `tbc-recordings`
- Live-HLS-Puffer: `/tmp/tbc-live`
- Importierte Kamera-Plugins: `/data/camera-modules` im Docker-Volume `tbc-data`
- Dashboard-Snapshots: `/data/dashboard-snapshots` im Docker-Volume `tbc-data`, standardmäßig alle 600 Sekunden

Bitte `TBC_ADMIN_PASSWORD` und `TBC_SECRET_KEY` in `.env` vor einem echten Einsatz aendern. `TBC_PUBLIC_BASE_URL` sollte gesetzt werden, wenn Webhooks oder Home-Assistant-Notify Links zu Clip und Snapshot erhalten sollen.

## Installation mit Portainer

Portainer kann dieses Projekt am zuverlaessigsten als Standalone-Stack aus einem Git-Repository bauen. Der Compose-Stack enthaelt ein lokales `build: .`; wenn der Compose-Text nur in den Web-Editor kopiert wird, fehlen Dockerfile, App-Code und `requirements.txt` im Build-Kontext.

1. In Portainer `Stacks` oeffnen und `Add stack` waehlen.
2. Als Build-Methode `Repository`/`Git repository` auswaehlen.
3. Repository-URL und Branch eintragen. Als Compose-Pfad `docker-compose.yml` verwenden.
4. Environment-Variablen im Portainer-Formular setzen:
   - `TBC_ADMIN_USERNAME=admin`
   - `TBC_ADMIN_PASSWORD=<starkes-passwort>`
   - `TBC_SECRET_KEY=<lange-zufaellige-zeichenkette>`
   - `TBC_PORT=8732`
   - optional `TBC_PUBLIC_BASE_URL=https://dein-hostname`
5. Stack deployen. Portainer baut daraus das Image `tbc-camera-manager:latest` und startet den Container `tbc-camera-manager`.
6. Die Oberflaeche unter `http://<docker-host>:8732` oeffnen und mit dem gesetzten Admin-Benutzer anmelden.

Hinweise fuer typische Portainer-Probleme:

- Nicht als Swarm-Stack deployen, solange kein bereits gebautes Registry-Image verwendet wird. Docker Swarm ignoriert lokale `build`-Anweisungen.
- Der Portainer-Agent oder Docker-Host muss das Git-Repository erreichen koennen.
- Bei NAS-/Host-Aufnahmen zusaetzliche Bind-Mounts in `docker-compose.yml` eintragen und den Zielpfad anschliessend im TBC-Bereich `Speicher` hinterlegen.
- Wenn Port `8732` schon belegt ist, `TBC_PORT` aendern und denselben Wert fuer Host- und Container-Port verwenden.

## Kamera einbinden

In der Weboberflaeche zuerst das installierte Kameramodul auswählen und die Kamera mit Host/IP, Ports und Zugangsdaten anlegen. Das Modul bestimmt danach, welche Hersteller-API abgefragt und welche Funktionen angeboten werden. Das enthaltene Reolink-Modul prueft:

- ONVIF Device-Informationen
- ONVIF Media-Profile und RTSP-Stream-URI
- ONVIF Event-Properties, soweit die Kamera sie meldet
- Reolink Smart-AI-Zustaende ueber `reolink-aio`, wenn die Kamera/API sie unterstuetzt

## Installierbare Kamera-Module

Die Weboberfläche und die zentralen Kamera-Routen greifen nur auf eine herstellerunabhängige Modulschnittstelle zu. Module deklarieren Fähigkeiten für Live-Ansicht, Ereignisaufnahme, Erkennungen, Multi-Kanal-Geräte und Kamera-Archive. Im Adminbereich `Kamera-Plugins` können Plugin-ZIPs direkt importiert und installierte Plugins exportiert werden. Importierte Pakete liegen dauerhaft unter `TBC_CAMERA_MODULES_PATH` (standardmäßig `/data/camera-modules`) und erscheinen sofort in der Modulauswahl.

Bestehende Datenbanken werden automatisch migriert; vorhandene Kameras erhalten das Modul `reolink`. Die technische Anleitung zur Entwicklung zusätzlicher Module steht in [docs/camera-modules.md](docs/camera-modules.md).

Das eingebaute Modul `tplink` unterstützt TP-Link/Tapo-Kameras über ONVIF Profile S und RTSP. Beim Auswählen werden ONVIF-Port `2020` und RTSP-Port `554` vorbelegt. Als Stream werden `/stream1` und die in TBC gespeicherten separaten Kamera-Zugangsdaten verwendet. Live-Ansicht und ONVIF-Funktionserkennung sind aktiviert; Reolink-spezifisches SD-Karten-Archiv, NVR-Kanäle und ereignisgesteuerte Aufnahmen werden für dieses Modul nicht angeboten.

Das Modul `standard_onvif` ist der Fallback für weitere Hersteller. Es verwendet ausschließlich die vom Gerät gemeldeten ONVIF-Informationen, RTSP-Medienprofile und Event-Definitionen. Das Modul konstruiert keine herstellerspezifischen Streampfade.

Das Modul `aqara` prüft ONVIF-kompatible Aqara-Kameras standardmäßig auf Port `5000` und zusätzlich den lokalen Aqara-RTSP-Kanal `/ch1` auf Port `8554`. Bei der kabelgebundenen/PoE-Türklingel G400 muss in Aqara Home unter `Weitere Einstellungen` die `RTSP LAN Preview` aktiviert werden; diese Option aktiviert gleichzeitig ONVIF. Host sowie die dort angezeigten separaten LAN-Zugangsdaten werden in TBC eingetragen. Die G400 stellt zusätzlich `/ch2` und `/ch3` mit geringerer Auflösung bereit. Bei der G410 ist RTSP nur mit kabelgebundener Stromversorgung verfügbar; die ältere G4 bietet offiziell keinen lokalen RTSP-Stream. Aqara-Cloud-, HomeKit- und proprietäre Archivzugriffe sind nicht Bestandteil des Moduls.

Die Profile `ubiquiti` und `sonoff` arbeiten mit der vollständigen, vom jeweiligen Herstellersystem erzeugten Stream-URL. Bei Ubiquiti wird der RTSP-/RTSPS-Link aus UniFi Protect verwendet; Port `7447` ist für RTSP vorbelegt. Bei SONOFF wird RTSP in eWeLink aktiviert und der dort erzeugte Link in TBC eingefügt. Das Profil `rtsp_only` ermöglicht dieselbe Konfiguration herstellerneutral und überspringt ONVIF vollständig. Host/IP wird bei Bedarf aus der URL übernommen. In Formularen, Statusmeldungen und Detailansichten werden Benutzername und Passwort einer RTSP-/RTSPS-URL immer als `***:***` dargestellt.

## Dashboard-Vorschaubilder

Für jede aktivierte Kamera mit bekanntem Stream erzeugt TBC per `ffmpeg` ein JPEG-Vorschaubild. Der geschützte Cache wird standardmäßig spätestens nach zehn Minuten erneuert; fehlende Bilder werden beim ersten Aufruf der Kameraseite direkt erzeugt. Die Bildroute prüft dieselbe Kamera-Berechtigung wie Detail- und Live-Ansicht und liefert keine Zugangsdaten aus. Speicherort und Intervall können mit `TBC_DASHBOARD_SNAPSHOTS_PATH` und `TBC_DASHBOARD_SNAPSHOT_INTERVAL_SECONDS` angepasst werden.

## Aufnahmen

Pro Kamera kann aktiviert werden, dass TBC bei ausgewaehlten Reolink-Erkennungen einen Clip aufnimmt. Einstellbar sind:

- Aufnahmeziel
- Mindestdauer in Sekunden
- Vorlauf und Nachlauf
- Pause zwischen zwei Clips pro Ereignistyp
- Snapshot/Thumbnail
- Ereignistypen wie Bewegung, Person, Fahrzeug, Tier, Paket, Klingel, Linienuebertritt oder Eindringen

Die Aufnahme verwendet den erkannten RTSP-Stream und `ffmpeg`. Speicherziele werden im Bereich `Speicher` verwaltet:

- Lokaler oder gemounteter Pfad im Container, zum Beispiel `/recordings` oder `/recordings/nas`.
- S3-kompatibler Cloud-Speicher mit Endpoint, Region, Bucket, Prefix, Access Key und Secret Key.

Ein Host- oder NAS-Verzeichnis kann in `docker-compose.yml` als zusaetzliches Volume in den Container gemountet und anschliessend im UI als Pfad hinterlegt werden.

## Clip-Browser

Der Bereich `Clips` zeigt gespeicherte Aufnahmen mit Datum, Kamera, Ereignistyp, Status und Thumbnail. Clips koennen gefiltert, abgespielt, heruntergeladen und als Admin geloescht werden. Lokale Clips werden direkt aus dem Container ausgeliefert; S3-Clips werden ueber temporaere Presigned URLs geoeffnet.

## SD-Karte / Kamera-Archiv

Der Bereich `SD-Karte` liest vorhandene Reolink-Aufnahmen direkt von der Kamera bzw. vom NVR. TBC nutzt dafuer die hinterlegten Kamera-Zugangsdaten und die Reolink-VOD-API aus `reolink-aio`.

- Auswahl nach Kamera, Kanal, Stream und Datum.
- Anzeige von Start/Ende, Dauer, Ereignistyp, Datei und Groesse.
- Abspielen und Download ueber authentifizierte TBC-Routen; TBC streamt die Datei von der Kamera zum Browser und schliesst die Reolink-Session danach wieder.
- Viewer sehen nur SD-Card-Inhalte von Kameras, fuer die sie freigegeben sind.

Die SD-Card-Dateien werden dabei nicht in die TBC-Aufnahmetabelle importiert und unterliegen nicht den Retention-Regeln. Retention gilt weiterhin nur fuer Clips, die TBC selbst aufgenommen und in einem Speicherziel abgelegt hat.

## Live-Ansicht

Der Bereich `Live` startet pro Kamera oder NVR-Kanal einen einfachen HLS-Proxy ueber `ffmpeg`. TBC schreibt die HLS-Playlist und TS-Segmente in `TBC_LIVE_PATH` und liefert sie authentifiziert ueber die Weboberflaeche aus. Der Proxy laeuft nur, wenn ein Stream gestartet wurde, und kann im UI wieder gestoppt werden.

## Retention und Speicher-Explorer

Im Bereich `Retention` koennen Admins automatische Speicherregeln anlegen:

- global oder pro Kamera
- optional pro Ereignistyp
- Loeschung nach maximalem Alter in Tagen
- Loeschung, wenn ein Groessenlimit in GB ueberschritten wird

Zusaetzlich koennen Speicherziele selbst einfache Tages- und GB-Limits erhalten. Der Bereich `Explorer` zeigt freien Speicher, Clip-Belegung pro Kamera/Ereignis und eine Cleanup-Vorschau. Der gleiche Preview-Mechanismus wird vom manuellen Cleanup und vom stuendlichen Hintergrund-Cleanup verwendet.

## Benachrichtigungen

Im Bereich `Notify` koennen mehrere Kanaele gepflegt werden:

- Webhook mit JSON-Payload und optionalen Clip-/Snapshot-URLs
- Telegram mit Snapshot-Anhang, wenn lokal vorhanden
- E-Mail per SMTP mit optionalem Snapshot-Anhang
- Pushover
- Home Assistant Notify ueber die REST-API

Kanaele koennen per kommasepariertem Event-Filter eingeschraenkt werden, zum Beispiel `recording_finished,recording_failed,cleanup_finished,health_status_changed`.

## Health-Monitoring

Der Bereich `Health` prueft Kamera-Probe-Status, Stream-Lesbarkeit per `ffprobe`, lokale Speicherziele und MQTT-Erreichbarkeit. Statuswechsel werden als Health-Events gespeichert und in der Weboberflaeche angezeigt. Der Check laeuft im Hintergrund und kann beim Oeffnen der Seite sofort aktualisiert werden.

## NVR- und Multi-Kanal-Verwaltung

Wenn `reolink-aio` mehrere Kanaele meldet, speichert TBC sie einzeln in `camera_channels`. Kanaele koennen im Kamera-Detail umbenannt, deaktiviert und einzeln fuer Live-HLS gestartet werden. Deaktivierte Kanaele werden fuer aktive Erkennungen unterdrueckt und loesen dadurch keine Aufnahmen aus. Erkannte Reolink-Funktionen werden bei Multi-Kanal-Geraeten mit Kanalbezug abgelegt.

## Benutzer und Rollen

Im Bereich `Benutzer` koennen Admins weitere Konten anlegen:

- `admin`: kann Kameras, Speicher, MQTT, Benutzer und Clips verwalten.
- `viewer`: kann nur freigegebene Kameras und deren Clips sehen.

Kamera-Freigaben werden pro Viewer gesetzt.

## MQTT / Home Assistant

Im Bereich `MQTT` kann ein Broker hinterlegt werden. TBC publiziert pro Kamera und Erkennung einen Zustand unter dem konfigurierten Topic-Prefix und kann Home-Assistant-Discovery-Nachrichten erzeugen. Aufnahme-Ereignisse wie `recording_started`, `recording_finished` und `recording_failed` werden ebenfalls als MQTT-Event publiziert.

## Enthaltene Erkennungen

Die erste Version bildet die Reolink-Erkennungen ab, die auch in der Home-Assistant-Integration als Sensoren auftauchen:

- Bewegung
- Gesicht
- Person
- Fahrzeug
- Nicht-motorisiertes Fahrzeug
- Haustier / Tier
- Paket
- Besucher / Klingel
- Weinen
- Smart-AI-Zonen: Crossline, Intrusion, Linger/Loitering
- Vergessener Gegenstand
- Entfernter Gegenstand
- I/O Eingang
- Ruhezustand

Nicht jede Reolink-Kamera liefert alle Funktionen. TBC speichert deshalb pro Kamera, ob eine Funktion unterstuetzt wird und ob sie aktuell aktiv ist.

## Technische Beschreibung

- Webserver: FastAPI mit Jinja2-Templates.
- Persistenz: SQLite unter `/data/tbc.sqlite3`.
- Schema: Tabellen fuer Kameras, Kanaele, Erkennungen, Aufnahmen, Speicherziele, Retention-Regeln, Benachrichtigungskanaele, Health-Status, Health-Events, Benutzer/Rollen und MQTT-Konfiguration.
- Kamera-Module: `CameraModule`-Schnittstelle, Capability-Modell, validierte ZIP-Plugins und optional Python-Entry-Points; die Modulauswahl wird pro Kamera als `module_key` gespeichert.
- Login: Cookie-Session mit PBKDF2-SHA256 gehashtem Admin-Passwort.
- ONVIF: `onvif-zeep` fuer Device-, Media- und Event-Probe.
- Reolink: `reolink-aio` fuer modellabhaengige AI-/Smart-AI-Zustaende.
- SD-Karte: `reolink-aio` VOD-Suche ueber `Search`, Wiedergabe ueber `Playback` und Download ueber `Download` bzw. `NvrDownload`.
- Recording: `ffmpeg` fuer RTSP-Clips, Ringbuffer-Segmente fuer Vorlauf, Nachlaufsteuerung ueber aktive Events, optional `boto3` fuer S3-kompatible Uploads.
- Live: HLS-Proxy ueber `ffmpeg` mit authentifizierten Playlist- und Segment-Routen.
- Dashboard-Snapshots: `DashboardSnapshotManager` erzeugt atomar ersetzte JPEG-Dateien per `ffmpeg`; ein Hintergrundjob prüft minütlich, ob der konfigurierbare 600-Sekunden-Zeitraum abgelaufen ist. Auslieferung erfolgt nur über eine authentifizierte, kamerabezogen autorisierte Route.
- Debug Log: In-Memory-Ringbuffer fuer App- und ffmpeg-Meldungen, abrufbar als Admin-Pull-up auf jeder Seite und unter `Einstellungen`.
- Retention: `app/tbc/maintenance.py` erzeugt Cleanup-Vorschau aus expliziten Regeln und Speicherziel-Limits und loescht lokale Dateien bzw. S3-Objekte ueber die vorhandene Recording-Abstraktion.
- Benachrichtigungen: `app/tbc/notifications.py` versendet Recording-, Cleanup- und Health-Statuswechsel an Webhook, Telegram, E-Mail, Pushover oder Home Assistant Notify.
- Health: `app/tbc/health.py` schreibt Status in `health_status`; `upsert_health_status` protokolliert Statuswechsel in `health_events`.
- MQTT: `paho-mqtt` mit optionaler Home-Assistant-Discovery.
- Rollen: `admin` und `viewer` mit optionaler Kamera-Freigabe.
- Deployment: Dockerfile und Docker Compose, Port `8732`.
- Healthcheck-Endpunkt: `/healthz`.

## Entwicklung

```bash
pytest -q
python -m unittest discover -s tests
python -m compileall app tests
docker compose config
```
