# Cloud-Konten entwickeln

TBC trennt Kamera-Protokolle (siehe [camera-modules.md](camera-modules.md)) von Cloud-Konten. Ein Kamera-Modul spricht direkt mit einer einzelnen Kamera über Host, Port und Zugangsdaten. Ein Cloud-Konto meldet sich einmal bei einem Herstellerkonto an und listet mehrere Geräte. Beide Ebenen sind deshalb als getrennte Plugin-Systeme umgesetzt.

Sobald ein Cloud-Konto Geräte gefunden hat, werden sie als normale Einträge in der `cameras`-Tabelle angelegt und nutzen dieselbe Live-, Steuerungs- und Erkennungsinfrastruktur wie jede andere Kamera. Ein Cloud-Plugin braucht kein eigenes `CameraModule`, wenn die Konto-API ein Gerät auf eine dauerhafte RTSP-/RTSPS-URL auflösen kann.

## Plugin-Datei und Kontoformular

Eine Cloud-Plugin-ZIP ist wie eine Kamera-Plugin-ZIP aufgebaut: Dateien direkt im Hauptverzeichnis oder in genau einem gemeinsamen Ordner, mit `manifest.json` als verbindlicher Konfiguration:

```json
{
  "schema_version": 1,
  "key": "acme_cloud",
  "label": "Acme Cloud",
  "version": "1.0.0",
  "description": "Acme-Kamerakonten",
  "entrypoint": "plugin.py",
  "auth_type": "credentials",
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
    },
    {
      "key": "region",
      "label": "Region",
      "type": "select",
      "default": "eu",
      "options": [
        {"value": "eu", "label": "Europa"},
        {"value": "us", "label": "USA"}
      ]
    }
  ]
}
```

`account_fields` ist die vollständig vom Plugin gelieferte Beschreibung des Kontoformulars. Das Hauptprojekt kennt keine Anbieterfelder. Unterstützte Typen sind `text`, `email`, `password`, `number`, `checkbox` und `select`. Je Feld stehen `required`, `placeholder`, `help_text`, `autocomplete`, `default`, `min`, `max`, `full_width`, `transient` und bei Auswahlfeldern `options` zur Verfügung. Ein Feld mit `transient: true` wird nach einem erfolgreichen Verbindungstest oder einer erfolgreichen Gerätesuche automatisch geleert; das ist für Einmalcodes gedacht. Schlüssel dürfen aus Kleinbuchstaben, Zahlen und Unterstrichen bestehen.

Beim Absenden validiert TBC ausschließlich die Felder des gewählten Plugins und speichert sie als JSON in `cloud_accounts.config_json`. Vor `test_connection()` oder `discover_devices()` wird die Konfiguration zusätzlich flach in das `account`-Dictionary eingeblendet, sodass ein Plugin direkt `account["email"]` verwenden kann. Die alten Schema-v1-Angaben `identifier_label`, `secret_label`, `requires_host` und `default_port` bleiben kompatibel: Fehlt `account_fields`, erzeugt der Loader daraus das bisherige Standardformular.

Die eingebauten Plugins liegen vollständig unter `app/tbc/cloud_plugins/<schlüssel>/`. Sie sind in sich geschlossen und als ZIP exportierbar.

## Öffentlicher Vertrag

Ein Cloud-Plugin erbt von `tbc_cloud_api.CloudAccountModule`:

```python
from tbc_cloud_api import CloudAccountModule, CloudDevice


class AcmeCloudModule(CloudAccountModule):
    async def test_connection(self, account: dict) -> str:
        return "Verbunden mit Acme-Konto"

    async def discover_devices(self, account: dict) -> list[CloudDevice]:
        return [
            CloudDevice(
                external_id="cam-1",
                name="Eingang",
                manual_stream_uri="rtsp://192.0.2.10:554/stream1",
                suggested_module_key="rtsp_only",
            )
        ]


def create_module():
    return AcmeCloudModule()
```

`account` enthält die generischen Kontometadaten sowie alle vom Plugin deklarierten Felder. Bei Fehlern lösen Module `CloudConnectionError` aus. `CloudDevice.manual_stream_uri` ist optional: Liefert die API keine dauerhaft nutzbare Stream-URL, bleibt es leer und die Weboberfläche bietet für dieses Gerät keinen „Als Kamera hinzufügen“-Knopf an.

`plugin.py` stellt entweder `create_module()` oder eine Variable `MODULE` bereit. Metadaten und `account_fields` werden aus dem Manifest validiert und auf die Modulinstanz übertragen.

## Referenzimplementierung: UniFi Protect

Das eingebaute `unifi_protect`-Plugin meldet sich über [`uiprotect`](https://pypi.org/project/uiprotect/) an einem Controller an – lokal per IP oder über eine `<konsolen-id>.ui.com`-Cloud-Adresse. `discover_devices()` liest `ProtectApiClient.update()` → `Bootstrap.cameras` und löst den ersten Kanal mit aktiviertem RTSP über `CameraChannel.rtsp_url` auf. Ist RTSP nicht aktiviert, bleibt `manual_stream_uri` leer. Gefundene Geräte werden mit `suggested_module_key="ubiquiti"` markiert.

## Referenzimplementierung: Eufy Security

Das eingebaute `eufy`-Plugin verwendet [`pyeufysecurity`](https://pypi.org/project/pyeufysecurity/) für die verschlüsselte Eufy-v2-Cloud-Anmeldung und Gerätesuche. Sein Manifest liefert E-Mail-Adresse, Passwort, ISO-Ländercode, einen einmaligen Bestätigungscode sowie optionale lokale RTSP-Zugangsdaten. Für die Anmeldung empfiehlt sich ein separates, in der Eufy-App freigegebenes Gastkonto. Verlangt Eufy die Bestätigung eines neuen Clients, fordert das Plugin den Code über Eufys E-Mail-Endpunkt an. Die zugehörige Challenge wird zehn Minuten im Prozessspeicher gehalten, damit der zweite Login denselben temporären Token und ECDH-Schlüssel verwendet. Der Administrator trägt den Code über „Konto bearbeiten“ ein; nach erfolgreicher Anmeldung wird der Client als vertrauenswürdig registriert, die Challenge entfernt und der gespeicherte Einmalcode geleert. Nach einem Container-Neustart oder Ablauf der zehn Minuten muss ein neuer Code angefordert werden. Verlangt Eufy stattdessen ein CAPTCHA, muss dieses weiterhin in der Eufy-App bestätigt werden.

Die Eufy-Cloud liefert für einen gestarteten Stream nur eine sitzungsgebundene URL. `discover_devices()` startet deshalb keine Cloud-Streams und speichert keine kurzlebigen URLs. Hat eine Kamera eine lokale IP und wurden RTSP-Zugangsdaten hinterlegt, erzeugt das Plugin die dauerhafte lokale `rtsp://…/live0`-Adresse und markiert das Gerät mit `suggested_module_key="rtsp_only"`. Bei allen anderen Eufy-Kameras bleibt `manual_stream_uri` leer: Sie erscheinen in der Gerätesuche, können aber erst nach Aktivierung von NAS/RTSP in der Eufy-App als Kamera übernommen werden.

Jeder Eufy-Verbindungstest und jede Gerätesuche erzeugt eine kurze Debug-ID. Fehlermeldungen zeigen diese ID an; im Admin-Debug-Log stehen dazu der API-Schritt, HTTP-Status, ursprünglicher Content-Type, Eufy-Fehlercode, bereinigte Eufy-Meldung und Datentyp der Antwort. Zugangsdaten, Auth-Tokens, Bestätigungscodes, verschlüsselte Payloads und vollständige API-Antworten werden nicht protokolliert.

## Import, Export und Admin-Oberfläche

Administratoren verwalten Cloud-Plugins unter `Admin → Cloud-Anbieter` und Konten unter `Admin → Cloud-Konten`: Konto anlegen, Plugin-Felder bearbeiten, Verbindung testen und Geräte suchen. Ein Plugin mit zugeordneten Konten kann nicht entfernt werden; eingebaute Plugins können weder überschrieben noch entfernt werden. Der externe Speicherort wird mit `TBC_CLOUD_MODULES_PATH` konfiguriert.

## Sicherheit

Cloud-Zugangsdaten werden wie Kamera-Zugangsdaten unverschlüsselt in der TBC-Datenbank gespeichert. Ein Cloud-Plugin enthält ausführbaren Python-Code und besitzt dieselben Rechte wie der TBC-Prozess; importiert werden dürfen deshalb nur Plugins aus vertrauenswürdigen Quellen.
