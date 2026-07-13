# Plugin-Tests und externe Quellen

Diese Seite ergänzt [camera-modules.md](camera-modules.md) (Kamera-Plugins), [cloud-accounts.md](cloud-accounts.md) (Cloud-Plugins) und [design-themes.md](design-themes.md) (Designs) um zwei Fähigkeiten, die für alle drei Plugin-Arten gleich funktionieren: Plugins können ihre eigenen Tests mitbringen, und Plugins können statt per manuellem ZIP-Upload direkt aus einem öffentlichen GitHub-Repository installiert werden.

## Tests im Plugin (`tests/`)

Ein Kamera- oder Cloud-Plugin darf einen `tests/`-Ordner mit pytest-Tests (`test_*.py`) direkt neben `manifest.json` und dem Einstiegspunkt mitbringen. Das ist keine Sonderfunktion, die eigens freigeschaltet werden muss: Die ZIP-Validierung akzeptiert `.py`-Dateien bereits an beliebiger Stelle innerhalb des Plugin-Ordners, ein `tests/`-Unterordner ist also automatisch erlaubt. Beim Export (ZIP-Download über `Admin → Kamera-Plugins`/`Cloud-Anbieter`) wird der komplette Plugin-Ordner inklusive `tests/` mitgeliefert - ein exportiertes eingebautes Plugin ist damit genauso in sich geschlossen und selbst testbar wie ein extern installiertes.

Design-Pakete enthalten bewusst keinen ausführbaren Code (siehe [design-themes.md](design-themes.md)) und damit auch keine Tests.

Referenzbeispiel: `app/tbc/cloud_plugins/unifi_protect/tests/test_unifi_protect_module.py` - ein bereits eingebautes Plugin, dessen Tests vollständig innerhalb seines eigenen Plugin-Ordners liegen, nicht im projektweiten `tests/`-Verzeichnis. Andere eingebaute Plugins haben ihre Tests historisch noch im projektweiten `tests/`-Verzeichnis; das ist weiterhin gültig, neue und extern beigesteuerte Plugins sollten aber die In-Plugin-Konvention nutzen.

### Tests ausführen

Auf `Admin → Kamera-Plugins` und `Admin → Cloud-Anbieter` erscheint bei jedem Plugin mit einem `tests/`-Ordner ein Knopf „Tests ausführen“. Er startet `pytest <plugin>/tests/ -q` als Subprozess (Timeout 120 s) und zeigt Bestehen/Fehlschlagen als Meldung an; die vollständige Ausgabe landet im Admin-Debug-Log. Das Ausführen von Tests eröffnet keine neue Vertrauensebene: Plugin-Code läuft bereits beim Laden (Import) mit denselben Rechten wie der TBC-Prozess selbst (siehe „Sicherheit“ in camera-modules.md/cloud-accounts.md) - die Tests auszuführen ist derselbe bereits vorhandene Code, nur bewusst statt implizit angestoßen.

## Externe Quellen (`Admin → Externe Quellen`)

Statt eine ZIP-Datei manuell hochzuladen, kann ein Plugin direkt aus einem öffentlichen GitHub-Repository installiert werden. Unter `Admin → Externe Quellen` wird dafür eine Quelle registriert:

- **Plugin-Art**: Kamera-Plugin, Cloud-Anbieter oder Design.
- **Repository-URL**: `https://github.com/<besitzer>/<repository>` - nur öffentliche GitHub-Repositories werden unterstützt, kein Token, keine anderen Hosts.
- **Branch/Tag** (Standard `main`).
- **Unterordner** (optional): Pfad innerhalb des Repositorys, an dem `manifest.json` liegt, falls das Plugin nicht im Repository-Hauptverzeichnis liegt (z. B. bei einem Repository mit mehreren Plugins oder einem Plugin innerhalb eines größeren Projekts).

„Synchronisieren“ lädt das Repository-Archiv über die offizielle, unauthentifizierte `zipball`-Schnittstelle der GitHub-API (`https://api.github.com/repos/<besitzer>/<repository>/zipball/<ref>`), entpackt bei Bedarf nur den angegebenen Unterordner und reicht das Ergebnis an denselben Installationspfad weiter, den auch ein manueller ZIP-Upload durchläuft (`app/tbc/plugin_sources.py`, Funktion `fetch_and_repackage_plugin`). Dadurch gelten exakt dieselben Sicherheitsprüfungen wie beim ZIP-Import: Pfad-Traversal-Schutz, erlaubte Dateitypen, Größenlimits, und eingebaute Plugins können auch über diesen Weg nicht überschrieben werden. Jede Synchronisierung installiert den aktuellen Stand neu (Update = erneut synchronisieren); es gibt keinen automatischen Hintergrund-Abgleich, jede Anfrage an GitHub wird ausschließlich durch einen expliziten Klick auf „Synchronisieren“ ausgelöst.

Das Entfernen einer Quelle (`Quelle entfernen`) löscht nur die Registrierung, nicht das bereits installierte Plugin - das bereits installierte Plugin wird weiterhin über die jeweilige Plugin-Verwaltungsseite entfernt (dort greift auch weiterhin der Schutz vor dem Entfernen eingebauter oder noch verwendeter Plugins).

### Struktur-Vorgabe

Ein per externer Quelle installiertes Plugin muss dieselbe Struktur wie ein manuell hochgeladenes ZIP erfüllen: `manifest.json` im angegebenen Verzeichnis, der im Manifest genannte Einstiegspunkt, und bei Kamera-/Cloud-Plugins optional ein `tests/`-Ordner. Tests sind keine Voraussetzung für die Installation - ein Plugin ohne `tests/` wird genauso akzeptiert wie eines mit, zeigt in der Plugin-Übersicht aber auch keinen „Tests ausführen“-Knopf. Für neue, extern beigesteuerte Plugins ist ein mitgelieferter `tests/`-Ordner dennoch der empfohlene Weg, damit ein Administrator ein unbekanntes Plugin vor dem produktiven Einsatz gegen seine eigenen Tests prüfen kann.

## Sicherheit

Ein über eine externe Quelle installiertes Plugin enthält denselben ausführbaren Code wie ein manuell hochgeladenes ZIP und wird beim Laden genauso ausgeführt - die Warnung aus camera-modules.md/cloud-accounts.md gilt unverändert: Nur Repositories aus vertrauenswürdigen Quellen registrieren. Die Registrierung einer externen Quelle allein lädt oder installiert noch nichts; erst ein expliziter „Synchronisieren“-Klick eines Administrators löst den Netzwerkzugriff und die Installation aus.
