# Externe Read-API (`/api/v1/...`)

Neben den internen `/api/...`-Routen, die Session-Cookie-Auth für die eigene Web-UI nutzen,
bietet TBC unter `/api/v1/...` eine eigenständige, schreibgeschützte API für externe Skripte,
Dashboards oder Home-Assistant-Integrationen. Sie gibt genau die Inhalte aus, die in der
laufenden Installation tatsächlich konfiguriert sind - eine Kamera ohne aktivierte
KI-Erkennung liefert eine leere Erkennungsliste, eine Installation ohne Aufnahmen eine leere
Aufnahmenliste, usw. Es gibt (Stand jetzt) keine Schreib-/Steuer-Endpunkte (kein PTZ, keine
Kamera-Anlage, kein Umschalten von Einstellungen) - nur Lesezugriff.

## Aktivieren

Unter `Admin → Einstellungen` (`/settings`), Abschnitt „API-Zugriff“:

- **API aktivieren** - Hauptschalter. Ist er aus, antworten alle `/api/v1/...`-Routen mit
  `404`, unabhängig vom API-Key.
- **API-Key erforderlich** - ist dieser Schalter aus, ist die API bei aktiviertem Hauptschalter
  vollständig offen (kein Key nötig). Sinnvoll nur in vertrauenswürdigen, abgeschotteten
  Netzen.
- **Neuen Key erzeugen** - erzeugt einen neuen Key und zeigt ihn **genau einmal** im
  Bestätigungshinweis an. Gespeichert wird ausschließlich sein SHA-256-Hash
  (`app/tbc/security.py`, `hash_api_key`/`verify_api_key`) - TBC kann den Klartext-Key danach
  nicht mehr anzeigen. Ein neu erzeugter Key ersetzt einen vorher aktiven Key sofort.
- **Key widerrufen** - deaktiviert den aktuellen Key sofort.

Die API ist in einer frischen Installation standardmäßig deaktiviert.

## Authentifizierung

Der Key wird als Bearer-Token oder über einen eigenen Header übertragen:

```
Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

oder

```
X-API-Key: tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Ein API-Key hat vollen Lesezugriff auf alle Kameras - unabhängig von etwaigen
Viewer-Einschränkungen einzelner Benutzerkonten (`user_camera_access`). Es gibt aktuell nur
einen globalen Key pro Installation, keine Keys pro Benutzer.

## Endpunkte

Alle Antworten sind JSON, außer wo „Binär“ vermerkt ist.

| Methode & Pfad | Beschreibung |
|---|---|
| `GET /api/v1/status` | App-Name, Version, Update-Verfügbarkeit, Kamera-Anzahl |
| `GET /api/v1/cameras` | Alle Kameras inkl. Fähigkeiten, Status, Erkennungs-Zählern |
| `GET /api/v1/cameras/{id}` | Einzelne Kamera |
| `GET /api/v1/cameras/{id}/snapshot` | Aktuelles Vorschaubild (Binär, JPEG) |
| `GET /api/v1/cameras/{id}/detections` | Aktueller Erkennungszustand der Kamera |
| `GET /api/v1/recordings` | Aufnahmenliste. Query-Parameter: `camera_id`, `detection_key`, `date_from`, `date_to`, `limit` (Standard 200, max. 1000) |
| `GET /api/v1/recordings/{id}` | Metadaten einer Aufnahme |
| `GET /api/v1/recordings/{id}/media` | Video-Clip (Binär, MP4, unterstützt HTTP-Range) |
| `GET /api/v1/recordings/{id}/snapshot` | Ereignis-Vorschaubild (Binär, JPEG) |
| `GET /api/v1/activity` | Ereignis-Aufnahmen über alle Kameras für einen Tag. Query-Parameter: `day` (`YYYY-MM-DD`, Standard heute) |
| `GET /api/v1/storage` | Konfigurierte Speicherziele (ohne Zugangsdaten) |
| `GET /api/v1/health` | Systemauslastung + Health-Status/-Ereignisse |

Kamera-Zugangsdaten, Storage-/MQTT-Zugangsdaten und der API-Key-Hash selbst erscheinen in
keiner Antwort. Eine im Kameraobjekt enthaltene `stream_uri` wird ohne Zugangsdaten
ausgegeben (`redact_rtsp_credentials`, wie auch sonst überall in TBC).

## Beispiel

```bash
curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     https://tbc.example.com/api/v1/cameras

curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     "https://tbc.example.com/api/v1/recordings?camera_id=1&limit=20" \
  | jq '.recordings[0]'

curl -H "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" \
     -o clip.mp4 \
     https://tbc.example.com/api/v1/recordings/42/media
```
