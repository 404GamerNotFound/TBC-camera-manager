# Cloud-Konten entwickeln

TBC trennt Kamera-Protokolle (siehe [camera-modules.md](camera-modules.md)) von Cloud-Konten. Ein Kamera-Modul spricht direkt mit einer einzelnen Kamera über Host, Port und Zugangsdaten. Ein Cloud-Konto ist etwas anderes: Es meldet sich einmal bei einem Hersteller-Konto an (Benutzername/Passwort oder Token) und listet dabei mehrere Geräte gleichzeitig auf. Beide Ebenen sind deshalb bewusst als getrennte Plugin-Systeme umgesetzt, statt das bestehende Kamera-Modul-Modell für Konto-Login und Geräte-Suche zu verbiegen.

Sobald ein Cloud-Konto Geräte gefunden hat, werden sie als ganz normale Einträge in der `cameras`-Tabelle angelegt und nutzen ab dann dieselbe Live-/Steuerungs-/Erkennungs-Infrastruktur wie jede andere Kamera. Ein Cloud-Plugin braucht dafür kein eigenes `CameraModule`: Löst die Konto-API ein Gerät auf eine reine RTSP-/RTSPS-URL auf, reicht `manual_stream_uri` direkt an ein bestehendes manuelles Modul (`rtsp_only`, `ubiquiti`, ...) weiter.

## Plugin-Datei

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
  "identifier_label": "E-Mail",
  "secret_label": "Passwort",
  "requires_host": false,
  "default_port": 443
}
```

`auth_type` ist entweder `credentials` (Benutzername/E-Mail + Passwort) oder `token` (einzelner API-Schlüssel); er steuert nur die Beschriftung im Formular, nicht die Auth-Logik selbst - die implementiert das Plugin. `requires_host` blendet das Host-Feld im Konto-Formular ein, für Anbieter, die (wie UniFi Protect) über eine selbst gehostete Adresse statt eines reinen Cloud-Endpunkts angesprochen werden.

Das eingebaute `unifi_protect`-Plugin liegt komplett unter `app/tbc/cloud_plugins/unifi_protect/` - genau wie eingebaute Kamera-Module ist es in sich geschlossen und exportierbar.

## Öffentlicher Vertrag

Ein Cloud-Plugin erbt von `tbc_cloud_api.CloudAccountModule`:

```python
from tbc_cloud_api import CloudAccountModule, CloudDevice


class AcmeCloudModule(CloudAccountModule):
    async def test_connection(self, account: dict) -> str:
        # Anmelden und einen kurzen Statustext zurückgeben, oder
        # CloudConnectionError bei einem Fehler auslösen.
        return "Verbunden mit Acme-Konto"

    async def discover_devices(self, account: dict) -> list[CloudDevice]:
        # Alle Geräte des Kontos auflisten.
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

`account` ist das gespeicherte Konto als Dictionary (`host`, `port`, `verify_ssl`, `identifier`, `secret`, ...). `CloudDevice.manual_stream_uri` ist optional: Liefert die Konto-API keine direkt nutzbare Stream-URL (z. B. weil das Gerät nur über WebRTC-Relay oder einen Cloud-Signalisierungsdienst erreichbar ist), bleibt es leer und die Weboberfläche bietet für dieses Gerät keinen "Als Kamera hinzufügen"-Knopf an, statt eine nicht funktionierende Kamera anzulegen.

`plugin.py` stellt wie bei Kamera-Plugins entweder `create_module()` oder eine Variable `MODULE` bereit. Metadaten (`auth_type`, `identifier_label`, `secret_label`, `requires_host`, `default_port`) werden aus dem Manifest auf die Modulinstanz übertragen.

## Referenzimplementierung: UniFi Protect

Das eingebaute `unifi_protect`-Plugin meldet sich über [`uiprotect`](https://pypi.org/project/uiprotect/) (dieselbe Bibliothek, die auch Home Assistants UniFi-Protect-Integration verwendet) an einem Controller an - lokal per IP oder über die von Ubiquiti bereitgestellte `<konsolen-id>.ui.com`-Cloud-Adresse, beides mit denselben Zugangsdaten. `discover_devices()` liest dafür `ProtectApiClient.update()` → `Bootstrap.cameras` und löst pro Kamera den ersten Kanal mit aktiviertem RTSP über `CameraChannel.rtsp_url` auf. Ist RTSP für keinen Kanal aktiviert, bleibt `manual_stream_uri` leer - RTSP muss vorher einmalig in der Protect-Oberfläche pro Kamera aktiviert werden, da uiprotect es nicht automatisch einschaltet. Gefundene Geräte werden mit `suggested_module_key="ubiquiti"` markiert und laufen ab dem Import wie jede andere manuell verbundene UniFi-Kamera.

## Import, Export und Admin-Oberfläche

Administratoren verwalten Cloud-Anbieter-Plugins unter `Admin → Cloud-Anbieter` (ZIP-Import/-Export/-Entfernen, identisch zu `Admin → Kamera-Plugins`) und tatsächliche Konten unter `Admin → Cloud-Konten`: Konto anlegen, „Verbindung testen“ (ruft `test_connection()` auf und speichert Status/Meldung), „Geräte suchen“ (ruft `discover_devices()` auf und zeigt eine Liste mit „Als Kamera hinzufügen“ pro Gerät). Ein Cloud-Plugin mit noch zugeordneten Konten kann nicht entfernt werden; eingebaute Plugins können weder überschrieben noch entfernt werden. Der externe Speicherort wird mit `TBC_CLOUD_MODULES_PATH` konfiguriert.

## Sicherheit

Cloud-Zugangsdaten werden wie Kamera-Zugangsdaten unverschlüsselt in der TBC-Datenbank gespeichert - derselbe Vertrauensrahmen wie beim Rest der Anwendung (selbst gehostet, eine SQLite-Datei). Ein Cloud-Plugin enthält wie ein Kamera-Plugin ausführbaren Python-Code und besitzt dieselben Rechte wie der TBC-Prozess; es dürfen deshalb nur Plugins aus vertrauenswürdigen Quellen importiert werden.
