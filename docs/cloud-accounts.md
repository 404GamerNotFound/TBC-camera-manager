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
  "verification_support": "not_applicable",
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

`account_fields` ist die vollständig vom Plugin gelieferte Beschreibung des Kontoformulars. Das Hauptprojekt kennt keine Anbieterfelder. Unterstützte Typen sind `text`, `email`, `password`, `number`, `checkbox` und `select`. Je Feld stehen `required`, `placeholder`, `help_text`, `autocomplete`, `default`, `min`, `max`, `full_width`, `transient` und bei Auswahlfeldern `options` zur Verfügung. Ein Feld mit `transient: true` wird nach seiner Verwendung bei einem erfolgreichen oder durch das Plugin abgelehnten Verbindungsversuch automatisch geleert; das ist für Einmalcodes gedacht. Schlüssel dürfen aus Kleinbuchstaben, Zahlen und Unterstrichen bestehen.

Transiente Felder erscheinen bewusst nicht im „Konto hinzufügen“- oder „Konto bearbeiten“-Formular: Beim ersten Anlegen eines Kontos hat der Administrator noch gar keinen Code erhalten, ein leeres Codefeld dort wäre nur verwirrend. Sie werden ausschließlich auf der in „Zwei-Faktor-/Bestätigungscodes“ beschriebenen Bestätigungsseite abgefragt, die erst nach einem tatsächlichen `CloudVerificationRequired` erscheint.

`verification_support` ist die verbindliche Selbstauskunft eines Plugins, ob sein Anbieter jemals einen Bestätigungscode verlangen kann: `supported`, wenn das Plugin dafür `CloudVerificationRequired` auslöst (siehe unten), sonst `not_applicable`. Fehlt das Feld im Manifest, gilt `not_applicable` als ehrlicher Standardwert - er behauptet nicht "kein 2FA nötig", sondern sagt nur "keine Unterstützung gemeldet". Die Admin-Oberfläche zeigt diese Angabe als Badge bei jedem installierten Cloud-Anbieter (`Admin → Cloud-Anbieter`) an, damit auf einen Blick erkennbar ist, welche Konten potenziell einen zweiten Schritt brauchen.

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

### Zwei-Faktor-/Bestätigungscodes

Verlangt der Hersteller vor dem eigentlichen Login einen Code (E-Mail, SMS, App-Bestätigung), lösen `test_connection()` oder `discover_devices()` statt eines gewöhnlichen `CloudConnectionError` ein `CloudVerificationRequired` aus:

```python
from tbc_cloud_api import CloudVerificationRequired

raise CloudVerificationRequired(
    "Acme hat einen Bestätigungscode per E-Mail gesendet.",
    field_key="verification_code",
)
```

`field_key` muss der Schlüssel eines eigenen `account_fields`-Eintrags sein (üblicherweise mit `transient: true`). Die Weboberfläche fängt diese Ausnahme zentral ab, merkt sich Feld und Meldung am Konto (`pending_verification_field`/`pending_verification_message`) und leitet den Administrator statt auf eine Fehlermeldung auf eine eigene Bestätigungsseite (`/cloud-accounts/{id}/verify`) mit genau einem Eingabefeld für diesen Code. Nach dem Absenden wird `test_connection()` automatisch erneut aufgerufen; meldet das Plugin dabei erneut `CloudVerificationRequired`, bleibt der Administrator auf der Bestätigungsseite, bei jedem anderen Fehler geht es zurück zur Kontoliste und ein neuer Verbindungsversuch fordert einen frischen Code an. Jede Bearbeitung des Kontos über „Konto bearbeiten“ verwirft eine offene Bestätigung, da sich die zugehörige Login-Anfrage sonst nicht mehr eindeutig zuordnen lässt.

Ein Plugin, das den Zustand zwischen „Code angefordert“ und „Code eingegeben“ überbrücken muss (z. B. um denselben angefangenen Login fortzusetzen statt neu zu beginnen), hält diesen Zustand selbst - üblicherweise in einem prozessweiten, zeitlich begrenzten Zwischenspeicher wie im `eufy`-Plugin (`_PENDING_CHALLENGES`). TBC selbst reicht nur den vom Administrator eingegebenen Code als Feldwert weiter.

## Referenzimplementierung: UniFi Protect

Das eingebaute `unifi_protect`-Plugin meldet sich über [`uiprotect`](https://pypi.org/project/uiprotect/) an einem Controller an – lokal per IP oder über eine `<konsolen-id>.ui.com`-Cloud-Adresse. `discover_devices()` liest `ProtectApiClient.update()` → `Bootstrap.cameras` und löst den ersten Kanal mit aktiviertem RTSP über `CameraChannel.rtsp_url` auf. Ist RTSP nicht aktiviert, bleibt `manual_stream_uri` leer. Gefundene Geräte werden mit `suggested_module_key="ubiquiti"` markiert.

`uiprotect` bietet aktuell keinerlei Schnittstelle für Zwei-Faktor-/Bestätigungscodes (weder eine passende Exception noch eine Login-Methode dafür) - das Plugin meldet das im Manifest ehrlich als `verification_support: "not_applicable"`, statt eine Unterstützung vorzutäuschen, die es nicht geben kann. Schlägt die Anmeldung mit `NotAuthorized` fehl, weist die Fehlermeldung zusätzlich darauf hin, dass ein für dieses Konto aktiviertes 2FA die eigentliche Ursache sein könnte, ohne das als sicher zu behaupten (das lässt sich über diese Bibliothek nicht zuverlässig feststellen). Betroffene Admins benötigen ein separates lokales Konto ohne 2FA.

## Referenzimplementierung: Eufy Security

Das eingebaute `eufy`-Plugin verwendet [`pyeufysecurity`](https://pypi.org/project/pyeufysecurity/) für die verschlüsselte Eufy-v2-Cloud-Anmeldung und Gerätesuche. Sein Manifest liefert E-Mail-Adresse, Passwort, ISO-Ländercode, einen einmaligen Bestätigungscode (`transient: true`) sowie optionale lokale RTSP-Zugangsdaten. Für die Anmeldung empfiehlt sich ein separates, in der Eufy-App freigegebenes Gastkonto. Verlangt Eufy die Bestätigung eines neuen Clients, fordert das Plugin den Code über Eufys E-Mail-Endpunkt an und löst `CloudVerificationRequired(field_key="verification_code")` aus; die Weboberfläche leitet daraufhin automatisch auf die Bestätigungsseite des Kontos weiter. Die zugehörige Challenge wird zehn Minuten im Prozessspeicher gehalten, damit der zweite Login denselben temporären Token und ECDH-Schlüssel verwendet. Nach Eingabe des Codes wird der Client als vertrauenswürdig registriert, die Challenge entfernt und der gespeicherte Einmalcode automatisch geleert. Ein alter Code ohne passende Challenge wird verworfen; ein falscher oder abgelaufener Code führt zurück zur Kontoliste und verlangt einen neuen „Verbindung testen“-Versuch, der einen frischen Code anfordert - genau wie nach einem Container-Neustart, der den Prozessspeicher leert. Verlangt Eufy stattdessen ein CAPTCHA, muss dieses weiterhin in der Eufy-App bestätigt werden.

Die Eufy-Cloud liefert für einen gestarteten Stream nur eine sitzungsgebundene URL. `discover_devices()` startet deshalb keine Cloud-Streams und speichert keine kurzlebigen URLs. Hat eine Kamera eine lokale IP und wurden RTSP-Zugangsdaten hinterlegt, erzeugt das Plugin die dauerhafte lokale `rtsp://…/live0`-Adresse und markiert das Gerät mit `suggested_module_key="rtsp_only"`. Bei allen anderen Eufy-Kameras bleibt `manual_stream_uri` leer: Sie erscheinen in der Gerätesuche, können aber erst nach Aktivierung von NAS/RTSP in der Eufy-App als Kamera übernommen werden.

Jeder Eufy-Verbindungstest und jede Gerätesuche erzeugt eine kurze Debug-ID. Fehlermeldungen zeigen diese ID an; im Admin-Debug-Log stehen dazu der API-Schritt, HTTP-Status, ursprünglicher Content-Type, Eufy-Fehlercode, bereinigte Eufy-Meldung und Datentyp der Antwort. Zugangsdaten, Auth-Tokens, Bestätigungscodes, verschlüsselte Payloads und vollständige API-Antworten werden nicht protokolliert.

## Referenzimplementierung: eWeLink (SONOFF)

Das eingebaute `ewelink`-Plugin verwendet die [`ewelink`](https://pypi.org/project/ewelink/)-Bibliothek, die die offizielle CoolKit-Open-Platform-API anspricht (`v2/user/login`, `v2/device/thing`, HMAC-signierte Anfragen). Anders als bei Eufy oder UniFi Protect reichen das eWeLink-App-Konto (E-Mail/Passwort) allein nicht aus: CoolKit verlangt zusätzlich eine eigene **App-ID und ein App-Secret**, die unter [dev.ewelink.cc](https://dev.ewelink.cc/) kostenlos registriert werden - eine bewusste Entscheidung gegen das Verwenden reverse-engineerter, in Community-Projekten kursierender App-Zugangsdaten, die jederzeit von CoolKit gesperrt werden können. Das Manifest fragt beide Werte zusätzlich zu E-Mail-Adresse und Passwort ab.

Die offizielle API meldet Region-Fehlschläge selbst (Fehlercode `10004` liefert die zuständige Region mit); das Plugin muss deshalb keine Region konfigurieren oder erraten. Für Zwei-Faktor-Codes bietet die Bibliothek keinerlei Schnittstelle - `verification_support` steht deshalb auf `not_applicable`.

`discover_devices()` listet alle Geräte des Kontos mit Name, Modell und Online-Status auf, liefert aber **keine** RTSP-URL: Die offizielle eWeLink-Cloud-API gibt weder eine lokale IP-Adresse noch einen Stream-Link zurück. Sonoff-Kameras erzeugen den RTSP-Link weiterhin ausschließlich in der eWeLink-App selbst (Kamera → RTSP aktivieren → Link kopieren), der dann wie gehabt manuell im bestehenden `sonoff`-Kameramodul eingetragen wird. Die Gerätesuche dient hier also nur der Bestandsübersicht, nicht dem automatischen Kamera-Import - im Gegensatz zu UniFi Protect und (teilweise) Eufy bietet TBC deshalb bei eWeLink-Geräten keinen „Als Kamera hinzufügen“-Knopf an.

## Import, Export und Admin-Oberfläche

Administratoren verwalten Cloud-Plugins unter `Admin → Cloud-Anbieter` und Konten unter `Admin → Cloud-Konten`: Konto anlegen, Plugin-Felder bearbeiten, Verbindung testen und Geräte suchen. Verlangt ein Plugin einen Bestätigungscode, ersetzt die Kontokarte „Verbindung testen“ durch „Bestätigungscode eingeben“ und führt auf eine eigene, plugin-neutrale Seite mit genau einem Eingabefeld - unabhängig davon, welches Plugin den Code verlangt. Ein Plugin mit zugeordneten Konten kann nicht entfernt werden; eingebaute Plugins können weder überschrieben noch entfernt werden. Der externe Speicherort wird mit `TBC_CLOUD_MODULES_PATH` konfiguriert.

Statt eines manuellen ZIP-Uploads kann ein Cloud-Plugin auch direkt aus einem öffentlichen GitHub-Repository installiert werden (`Admin → Externe Quellen`), und ein Plugin darf einen eigenen `tests/`-Ordner mitbringen, der über einen „Tests ausführen“-Knopf direkt in der Weboberfläche gestartet werden kann - siehe [plugin-sources.md](plugin-sources.md).

## Sicherheit

Cloud-Zugangsdaten werden wie Kamera-Zugangsdaten unverschlüsselt in der TBC-Datenbank gespeichert. Ein Cloud-Plugin enthält ausführbaren Python-Code und besitzt dieselben Rechte wie der TBC-Prozess; importiert werden dürfen deshalb nur Plugins aus vertrauenswürdigen Quellen.
