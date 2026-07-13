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

„Synchronisieren“ löst zuerst den angegebenen Branch/Tag über die `commits`-Schnittstelle der GitHub-API auf eine konkrete Commit-SHA auf, lädt das Repository-Archiv bei genau dieser SHA über die offizielle, unauthentifizierte `zipball`-Schnittstelle (`https://api.github.com/repos/<besitzer>/<repository>/zipball/<sha>`), entpackt bei Bedarf nur den angegebenen Unterordner und reicht das Ergebnis an denselben Installationspfad weiter, den auch ein manueller ZIP-Upload durchläuft (`app/tbc/plugin_sources.py`, Funktion `resolve_and_fetch_plugin`). Dadurch gelten exakt dieselben Sicherheitsprüfungen wie beim ZIP-Import: Pfad-Traversal-Schutz, erlaubte Dateitypen, Größenlimits, und eingebaute Plugins können auch über diesen Weg nicht überschrieben werden. Die installierte SHA wird gespeichert (`installed_ref_sha`) und ist die Grundlage der Update-Erkennung unten.

Git-spezifische Metadaten (`.gitattributes`, `.gitignore`, `.gitmodules`, `.github/`, `.editorconfig` und `.dockerignore`) dürfen im Repository vorhanden sein. Sie werden beim Aufbereiten des GitHub-Archivs ausgelassen, weil sie nicht zum ausführbaren Plugin-Paket gehören. Dasselbe gilt für lokale Entwicklungsartefakte wie `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.DS_Store`, `*.pyc` und `*.pyo`; solche Dateien sollten zusätzlich über die `.gitignore` des Plugin-Repositorys vom Commit ausgeschlossen werden. Alle übrigen Dateien durchlaufen weiterhin unverändert die Dateityp- und Pfadprüfung des jeweiligen Plugin-Installers.

Das Entfernen einer Quelle (`Quelle entfernen`) löscht nur die Registrierung, nicht das bereits installierte Plugin - das bereits installierte Plugin wird weiterhin über die jeweilige Plugin-Verwaltungsseite entfernt (dort greift auch weiterhin der Schutz vor dem Entfernen eingebauter oder noch verwendeter Plugins).

### Standard-Repositories

TBC kann häufig verwendete öffentliche Plugins als vorkonfigurierte Standard-Repositories anbieten. Sie erscheinen oberhalb der manuellen Quellenverwaltung und werden erst nach einem ausdrücklichen Klick eines Administrators registriert und installiert. Derzeit ist das Kamera-Plugin [Aqara](https://github.com/404GamerNotFound/TBC-aqara) mit dem Branch `main` hinterlegt.

Die Direktinstallation verwendet keinen gesonderten oder weniger strengen Installationsweg: Nach der einmaligen Registrierung wird dieselbe GitHub-Auflösung, Archivaufbereitung und Paketvalidierung wie bei einer manuell angelegten externen Quelle ausgeführt. Ist dasselbe Repository bereits als Kamera-Quelle registriert - auch mit optionalem `.git`-Suffix, abweichender Groß-/Kleinschreibung oder abschließendem Slash -, wird die vorhandene Registrierung synchronisiert und keine zweite angelegt. Eine fehlgeschlagene Erstinstallation lässt die Registrierung mit dem Fehlerstatus bestehen, damit der Administrator den Vorgang über „Synchronisieren“ wiederholen kann.

### Struktur-Vorgabe

Ein per externer Quelle installiertes Plugin muss dieselbe Struktur wie ein manuell hochgeladenes ZIP erfüllen: `manifest.json` im angegebenen Verzeichnis, der im Manifest genannte Einstiegspunkt, und bei Kamera-/Cloud-Plugins optional ein `tests/`-Ordner. Tests sind keine Voraussetzung für die Installation - ein Plugin ohne `tests/` wird genauso akzeptiert wie eines mit, zeigt in der Plugin-Übersicht aber auch keinen „Tests ausführen“-Knopf. Für neue, extern beigesteuerte Plugins ist ein mitgelieferter `tests/`-Ordner dennoch der empfohlene Weg, damit ein Administrator ein unbekanntes Plugin vor dem produktiven Einsatz gegen seine eigenen Tests prüfen kann.

Die Seite `Admin → Externe Quellen` beschreibt diese Struktur zusätzlich direkt in der Weboberfläche und bietet für jede Plugin-Art eine herunterladbare, vollständig installierbare Vorlage an (`Vorlage: Kamera-Plugin`/`Cloud-Anbieter`/`Design`, erzeugt von `app/tbc/plugin_templates.py`): Manifest, Einstiegspunkt und - bei Kamera-/Cloud-Plugins - ein `tests/`-Ordner mit einem lauffähigen Beispieltest. Jede Vorlage wird in den TBC-eigenen Tests real installiert und ihre Tests real ausgeführt, bevor sie ausgeliefert wird - sie ist also kein reines Textbeispiel, sondern ein funktionierender Ausgangspunkt zum Umbenennen und Erweitern.

### Automatische Update-Erkennung (`Admin → Updates`)

Jede registrierte Quelle wird stündlich automatisch geprüft (Hintergrund-Task, erste Prüfung 30 Sekunden nach dem Start, danach alle 60 Minuten): TBC fragt nur die aktuelle Commit-SHA des Branches/Tags ab (`GET /repos/<besitzer>/<repository>/commits/<ref>` mit `Accept: application/vnd.github.sha` - eine einzelne 40-Zeichen-Antwort, kein Repository-Download) und vergleicht sie mit der zuletzt installierten SHA. Weicht sie ab, erscheint die Quelle unter `Admin → Updates`; die Menüzeile zeigt zusätzlich die Anzahl offener Updates an (z. B. „Updates (2)“). Ein Klick auf „Jetzt aktualisieren“ führt genau dieselbe Synchronisierung wie auf der Quellen-Seite aus. Schlägt eine Aktualisierung fehl, bleibt das Update als offen markiert, bis ein Versuch erfolgreich war. Es findet keine automatische Installation statt - die stündliche Prüfung aktualisiert nur den Anzeigestatus, jede tatsächliche Installation verlangt weiterhin einen expliziten Klick.

## Sicherheit

Ein über eine externe Quelle installiertes Plugin enthält denselben ausführbaren Code wie ein manuell hochgeladenes ZIP und wird beim Laden genauso ausgeführt - die Warnung aus camera-modules.md/cloud-accounts.md gilt unverändert: Nur Repositories aus vertrauenswürdigen Quellen registrieren. Die Registrierung einer externen Quelle allein lädt oder installiert noch nichts; erst ein expliziter „Synchronisieren“-Klick eines Administrators löst tatsächlich einen Codewechsel aus. Die stündliche Update-Prüfung selbst lädt keinen Code, sondern fragt nur eine einzelne Commit-SHA ab - sie führt nichts Neues aus und installiert nichts automatisch.

„Tests ausführen“ (falls ein Plugin einen `tests/`-Ordner mitbringt) läuft in einem eigenen Python-Prozess, aber mit denselben Rechten wie der TBC-Prozess - siehe „Tests im Plugin“ oben. Das ist bewusst keine Sandbox: Ein bösartiges Plugin könnte theoretisch auch über seine eigenen Tests Schaden anrichten. Der Schutz liegt ausschließlich darin, nur vertrauenswürdige Quellen zu registrieren.
