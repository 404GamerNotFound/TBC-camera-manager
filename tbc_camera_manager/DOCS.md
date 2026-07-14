# TBC Camera Manager als Home-Assistant-App

## Installation

Diese App benötigt Home Assistant OS. Öffne `Einstellungen → Apps → App-Store`,
füge über das Repository-Menü diese URL hinzu und aktualisiere anschließend den
Store:

```text
https://github.com/404GamerNotFound/TBC-camera-manager
```

Wähle danach **TBC Camera Manager**, installiere die App und setze vor dem ersten
Start mindestens `admin_password`. Über **Weboberfläche öffnen** erreichst du TBC
auf Port `8732`.

## Optionen

- `admin_username`: Benutzername des ersten TBC-Administrators.
- `admin_password`: Pflichtfeld für das erste Administratorkonto. Eine spätere
  Änderung dieser App-Option ändert kein bereits angelegtes TBC-Konto.
- `poll_interval_seconds`: Intervall für Kameraabfragen, mindestens 15 Sekunden.
- `dashboard_snapshot_interval_seconds`: Intervall für Dashboard-Vorschaubilder,
  mindestens 60 Sekunden.
- `public_base_url`: Optionale externe Basis-URL für Links in Benachrichtigungen.

## Persistenz und Backups

SQLite-Datenbank, installierte Module, Designs, Modelle und Vorschaubilder liegen
im privaten App-Verzeichnis `/data`. Home Assistant nimmt für konsistente
SQLite-Backups einen Cold-Backup vor und stoppt TBC dafür kurzzeitig.

Aufnahmen werden unter `/media/tbc-camera-manager` auf dem Home-Assistant-Host
gespeichert. Im Container ist dieses Verzeichnis als
`/recordings/tbc-camera-manager` eingebunden. Es gehört damit nicht zum privaten
App-Backup; große Videoarchive vergrößern Home-Assistant-Backups nicht automatisch.

Der Launcher erzeugt beim ersten Start einen zufälligen Sitzungsschlüssel unter
`/data/.tbc-secret-key`. Dieser Schlüssel bleibt über Neustarts und Updates stabil.

## MQTT und Home Assistant

Installiere bei Bedarf die Mosquitto-Broker-App und konfiguriere in TBC unter
`MQTT` den Broker. Bei der offiziellen Mosquitto-App ist innerhalb des
App-Netzwerks üblicherweise `core-mosquitto` auf Port `1883` erreichbar. Aktiviere
Home-Assistant-Discovery in TBC; unterstützte Erkennungen und Steuerungen werden
anschließend als Entitäten angelegt.

## Netzwerk und Weboberfläche

TBC läuft im geschützten App-Container ohne Host-Netzwerk und greift ausgehend
über die konfigurierten IP-Adressen auf Kameras, RTSP, ONVIF und MQTT zu. Die
Weboberfläche wird direkt über TCP-Port `8732` veröffentlicht. Ingress ist noch
nicht aktiviert, weil Login-Weiterleitungen, statische Ressourcen und HLS-Streams
zunächst vollständig unter dem dynamischen Ingress-Unterpfad getestet werden
müssen.

## Technischer Aufbau

Die Home-Assistant-App und das normale Docker-Deployment verwenden denselben
Anwendungscode und dasselbe Root-Dockerfile. Unter Home Assistant liest
`app/tbc/container_launcher.py` die Supervisor-Konfiguration aus
`/data/options.json`, übersetzt sie in die bestehenden `TBC_*`-Variablen, bereitet
die eingebundenen Verzeichnisse vor und reduziert anschließend die Rechte auf den
Benutzer `tbc` mit UID `10001`. Ohne `options.json` verhält sich das Image wie der
bisherige Standalone-Container und verwendet die über Docker Compose gesetzten
Umgebungsvariablen.

## Veröffentlichung für Maintainer

Die App-Version in `config.yaml` muss der TBC-Version in
`app/tbc/__init__.py` entsprechen. Ein Git-Tag im Format `vX.Y.Z` startet den
Workflow `.github/workflows/home-assistant-app.yml`. Der Workflow verweigert die
Veröffentlichung, wenn Tag und App-Version voneinander abweichen, baut getrennte
Images für `amd64` und `aarch64` und veröffentlicht danach ein gemeinsames
Multi-Arch-Manifest unter:

```text
ghcr.io/404gamernotfound/tbc-camera-manager-ha:X.Y.Z
```

Nach der ersten Veröffentlichung muss die Sichtbarkeit des GHCR-Pakets in den
GitHub-Paketeinstellungen auf **Public** stehen, damit Home Assistant das Image
ohne Registry-Anmeldung laden kann. Der `latest`-Tag wird zusätzlich gepflegt;
Home Assistant installiert und aktualisiert jedoch anhand der expliziten Version
aus `config.yaml`.
