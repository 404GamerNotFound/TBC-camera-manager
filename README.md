# TBC - TB Camera

TBC ist ein kleiner Docker-basierter Kamera-Manager fuer Reolink-Kameras. Die aktuelle Version bringt Login, Kamera-Verwaltung, ONVIF-Probe, RTSP-Stream-Ermittlung, einen Reolink-Erkennungskatalog, ereignisbasierte Aufnahmen, Clip-Browser, Rollen, MQTT/Home-Assistant-Anbindung, Live-HLS, Retention, Benachrichtigungen, Health-Monitoring und NVR-Kanalverwaltung mit.

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

Bitte `TBC_ADMIN_PASSWORD` und `TBC_SECRET_KEY` in `.env` vor einem echten Einsatz aendern. `TBC_PUBLIC_BASE_URL` sollte gesetzt werden, wenn Webhooks oder Home-Assistant-Notify Links zu Clip und Snapshot erhalten sollen.

## Kamera einbinden

In der Weboberflaeche eine Kamera mit Host/IP, ONVIF-Port, HTTP-Port und Reolink-Zugangsdaten anlegen. TBC prueft danach:

- ONVIF Device-Informationen
- ONVIF Media-Profile und RTSP-Stream-URI
- ONVIF Event-Properties, soweit die Kamera sie meldet
- Reolink Smart-AI-Zustaende ueber `reolink-aio`, wenn die Kamera/API sie unterstuetzt

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
- Login: Cookie-Session mit PBKDF2-SHA256 gehashtem Admin-Passwort.
- ONVIF: `onvif-zeep` fuer Device-, Media- und Event-Probe.
- Reolink: `reolink-aio` fuer modellabhaengige AI-/Smart-AI-Zustaende.
- Recording: `ffmpeg` fuer RTSP-Clips, Ringbuffer-Segmente fuer Vorlauf, Nachlaufsteuerung ueber aktive Events, optional `boto3` fuer S3-kompatible Uploads.
- Live: HLS-Proxy ueber `ffmpeg` mit authentifizierten Playlist- und Segment-Routen.
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
