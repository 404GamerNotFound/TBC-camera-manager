# KI-Schnittstelle (MCP-Server)

Zusätzlich zur [Read-API](api.md) bietet TBC unter `/mcp/mcp` einen
[Model Context Protocol](https://modelcontextprotocol.io/)-Server (Streamable-HTTP-Transport).
Darüber kann ein KI-Agent (Claude Desktop, Claude Code, ein Claude.ai Custom Connector, oder ein
selbstgebauter MCP-Client) TBC direkt und strukturiert abfragen - "Welche Kameras habe ich?",
"Zeig mir die letzten Bewegungsmeldungen an der Einfahrt", "Wie sieht das aktuelle Bild von der
Gartenkamera aus?" - ohne dass der Agent erst die REST-API auswendig lernen muss.

## Aktivieren und Authentifizierung

Der MCP-Server teilt sich **denselben** Aktivieren-Schalter und **denselben** API-Key wie die
Read-API unter `Admin → Einstellungen` (siehe [api.md](api.md)) - es gibt keinen separaten
MCP-spezifischen Schalter oder Key. Ist die API deaktiviert, antwortet auch `/mcp/mcp` mit
`404`. Ist ein Key erforderlich, muss er als Bearer-Token oder `X-API-Key`-Header mitgeschickt
werden (identisch zur Read-API):

```
Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## Client-Konfiguration

**Claude Code:**

```bash
claude mcp add --transport http tbc https://tbc.example.com/mcp/mcp \
  --header "Authorization: Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

**Generische Konfiguration** (für MCP-Clients mit Datei-basierter Konfiguration):

```json
{
  "mcpServers": {
    "tbc": {
      "url": "https://tbc.example.com/mcp/mcp",
      "headers": {
        "Authorization": "Bearer tbc_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
      }
    }
  }
}
```

**Claude.ai / Claude Desktop:** Als Custom Connector über die Endpunkt-URL und denselben
Authorization-Header hinzufügen (Details variieren je nach Client-Version).

## Verfügbare Tools

Alle Tools sind schreibgeschützt und spiegeln die [Read-API](api.md) - jedes ruft dieselben
`database.py`-Funktionen auf, keine eigene, abweichende Logik:

| Tool | Beschreibung |
|---|---|
| `list_cameras` | Alle Kameras mit Fähigkeiten und Status |
| `get_camera` | Einzelne Kamera nach ID |
| `get_camera_detections` | Aktueller Erkennungszustand einer Kamera |
| `get_camera_snapshot` | Aktuelles Live-Vorschaubild einer Kamera (als Bild, nicht nur als URL) |
| `list_recordings` | Aufnahmenliste, filterbar nach Kamera, Erkennungstyp, Datumsbereich |
| `get_recording` | Metadaten einer einzelnen Aufnahme |
| `get_recording_snapshot` | Ereignis-Vorschaubild einer Aufnahme (nur bei lokal gespeichertem Snapshot) |
| `get_activity` | Ereignis-Aufnahmen über alle Kameras für einen Tag |
| `get_storage` | Konfigurierte Speicherziele (ohne Zugangsdaten) |
| `get_health` | Systemauslastung und Health-Status/-Ereignisse |
| `get_status` | App-Name, Version, Update-Verfügbarkeit, Kamera-Anzahl |

Wie bei der Read-API erscheinen Kamera-Zugangsdaten, Storage-/S3-Secrets und der API-Key-Hash
selbst in keiner Tool-Antwort. `get_camera_snapshot`/`get_recording_snapshot` liefern das Bild
direkt als Bildinhalt zurück, nicht als Link - ein Agent kann damit tatsächlich "sehen", was
eine Kamera aktuell zeigt oder was bei einem Ereignis erkannt wurde.

## Bekannte Einschränkungen

- Video-Clips werden bewusst nicht als eigenes Tool angeboten (kein sinnvolles
  Rückgabeformat für ein Sprachmodell) - `get_recording` enthält aber die `media_url`, falls
  ein nachgelagertes System darauf zugreifen soll.
- `get_recording_snapshot` funktioniert nur für lokal gespeicherte Aufnahmen; bei rein in
  S3-kompatiblem Speicher abgelegten Aufnahmen ohne lokale Kopie liefert das Tool eine
  Fehlermeldung statt eines Downloads.
