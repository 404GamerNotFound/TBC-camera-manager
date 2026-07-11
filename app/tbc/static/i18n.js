(() => {
  "use strict";

  const STORAGE_KEY = "tbc-language";
  const english = {
    "Analyse": "Analytics",
    "Anwesenheit": "Presence",
    "Basis": "Basic",
    "Besucher / Klingel": "Visitor / doorbell",
    "Bewegung": "Motion",
    "Eindringen Fahrzeug": "Vehicle intrusion",
    "Eindringen Hund/Katze": "Dog/cat intrusion",
    "Eindringen Person": "Person intrusion",
    "Entfernter Gegenstand": "Removed item",
    "Fahrzeug": "Vehicle",
    "Geräuscherkennung": "Sound detection",
    "Gesicht": "Face",
    "Haustier": "Pet",
    "I/O Eingang": "I/O input",
    "KI-Erkennung": "AI detection",
    "KI-Objekte": "AI objects",
    "Klingeln / Besucher": "Doorbell / visitor",
    "Linienübertritt": "Line crossing",
    "Linienübertritt Fahrzeug": "Vehicle line crossing",
    "Linienübertritt Hund/Katze": "Dog/cat line crossing",
    "Linienübertritt Person": "Person line crossing",
    "Manipulation / Videoverlust": "Tampering / video loss",
    "Nicht-motorisiertes Fahrzeug": "Non-motor vehicle",
    "Objekterkennung": "Object detection",
    "ONVIF-Verbindung erfolgreich": "ONVIF connection successful",
    "Paket": "Package",
    "Ruhezustand": "Sleep mode",
    "Tier": "Animal",
    "Türklingel": "Doorbell",
    "Vergessener Gegenstand": "Forgotten item",
    "Verweilen": "Loitering",
    "Verweilen Fahrzeug": "Vehicle loitering",
    "Verweilen Hund/Katze": "Dog/cat loitering",
    "Verweilen Person": "Person loitering",
    "Weinen": "Crying",
    "Reolink-Kameras und NVR via ONVIF und reolink-aio": "Reolink cameras and NVRs via ONVIF and reolink-aio",
    "Reolink-Status erfolgreich abgefragt": "Reolink status retrieved successfully",
    "Aqara-Kameras sowie kompatible Video-Türklingeln": "Aqara cameras and compatible video doorbells",
    "TP-Link-Tapo-Kameras via ONVIF und RTSP": "TP-Link Tapo cameras via ONVIF and RTSP",
    "Standard ONVIF Verbindung": "Standard ONVIF connection",
    "Herstellerneutraler ONVIF-Fallback für weitere Kameramodelle": "Vendor-neutral ONVIF fallback for additional camera models",
    "Manueller Stream": "Manual stream",
    "RTSP/RTSPS-Link in UniFi Protect erzeugen und hier vollständig eintragen": "Create an RTSP/RTSPS link in UniFi Protect and enter it here in full",
    "RTSP in eWeLink aktivieren, Link erzeugen und hier vollständig eintragen": "Enable RTSP in eWeLink, create a link, and enter it here in full",
    "+ Kamera": "+ Camera",
    "· Aufnahme aktiv": "· Recording active",
    "Abbrechen": "Cancel",
    "Abmelden": "Sign out",
    "Aktiv": "Active",
    "Aktuell:": "Current:",
    "Aktualisieren": "Refresh",
    "Alle": "All",
    "Admin-Rechte werden benötigt": "Administrator permissions are required",
    "Anlegen": "Create",
    "Anmelden": "Sign in",
    "Anmeldung fehlgeschlagen": "Sign-in failed",
    "Archiv": "Archive",
    "Aufnahme aktiv": "Recording active",
    "Aufnahme bei Bewegung": "Motion recording",
    "Aufnahmen": "Recordings",
    "Aufnahmen auf SD-Karte": "Recordings on SD card",
    "Aufnahmeziele": "Recording destinations",
    "Aufnahmeeinstellungen wurden gespeichert": "Recording settings were saved",
    "aus": "off",
    "Benachrichtigungen": "Notifications",
    "Benachrichtigung wurde gelöscht": "Notification was deleted",
    "Benutzer": "Users",
    "Benutzername": "Username",
    "Benutzer wurde aktualisiert": "User was updated",
    "Benutzer wurde angelegt": "User was created",
    "Benutzer wurde gelöscht": "User was deleted",
    "Belegung pro Kamera/Ereignis": "Usage by camera/event",
    "Betrieb": "Operations",
    "Bis": "To",
    "Cleanup ausführen": "Run cleanup",
    "Cleanup-Vorschau": "Cleanup preview",
    "Clips öffnen": "Open clips",
    "Dafür werden Admin-Rechte benötigt": "Administrator permissions are required",
    "Das Debug Log sammelt laufende Meldungen der App und ffmpeg-Live-Prozesse. Es ist auf jeder Admin-Seite unten rechts als Pull-up verfuegbar.": "The debug log collects ongoing messages from the app and ffmpeg live processes. It is available as a pull-up in the bottom-right corner of every admin page.",
    "Das Kameramodul unterstützt keine Live-Ansicht": "The camera module does not support live view",
    "Datei": "File",
    "Datum": "Date",
    "Dauer": "Duration",
    "Debug Log oeffnen": "Open debug log",
    "Debug Log schliessen": "Close debug log",
    "Debug Log wurde geleert": "Debug log was cleared",
    "Deutsch": "German",
    "Die vollständige URL wird geschützt gespeichert und in der Oberfläche immer zensiert.": "The full URL is stored securely and is always redacted in the interface.",
    "Die vollständige URL wird geschützt gespeichert und in der Oberfläche zensiert.": "The full URL is stored securely and redacted in the interface.",
    "Dieser Kanal ist deaktiviert": "This channel is disabled",
    "Das Startdatum darf nicht nach dem Enddatum liegen": "The start date must not be after the end date",
    "Der aktuell angemeldete Benutzer kann nicht gelöscht werden": "The currently signed-in user cannot be deleted",
    "Einträge": "entries",
    "Eintraege": "entries",
    "Einstellungen": "Settings",
    "Ende": "End",
    "Entfernen": "Remove",
    "Erkennungen": "Detections",
    "Erstes verfügbares Ziel": "First available destination",
    "Ereignis": "Event",
    "Ereignisse": "Events",
    "Ereignistypen aufnehmen": "Record event types",
    "Eine gültige RTSP-/RTSPS-URL ist erforderlich": "A valid RTSP/RTSPS URL is required",
    "Erweiterungen": "Extensions",
    "Explorer": "Explorer",
    "Filtern": "Filter",
    "Firmware": "Firmware",
    "Frei": "Free",
    "Funktion": "Function",
    "Funktionen": "Features",
    "Für dieses Profil ist eine RTSP-/RTSPS-URL erforderlich": "An RTSP/RTSPS URL is required for this profile",
    "Geprüft": "Checked",
    "Groesse": "Size",
    "Größe": "Size",
    "Grund": "Reason",
    "Hauptnavigation": "Main navigation",
    "Hersteller": "Manufacturer",
    "Hinweis: Host beginnt mit 192.169. Im Heimnetz ist oft 192.168 gemeint.": "Note: The host starts with 192.169. On home networks, 192.168 is often intended.",
    "Home-Assistant-Discovery publizieren": "Publish Home Assistant discovery",
    "Importieren": "Import",
    "Kanal wurde aktualisiert": "Channel was updated",
    "inaktiv": "inactive",
    "Installierte Plugins": "Installed plugins",
    "ja": "yes",
    "Kamera": "Camera",
    "Kamera einbinden": "Add camera",
    "Kamera wurde angelegt und geprüft": "Camera was created and checked",
    "Kamera wurde entfernt": "Camera was removed",
    "Kamera wurde nicht gefunden": "Camera was not found",
    "Kamera-Archiv": "Camera archive",
    "Kameradaten": "Camera details",
    "Kameraliste": "Camera list",
    "Kamera-Manager": "Camera Manager",
    "Kameramodul": "Camera module",
    "Kamera-Plugins": "Camera plugins",
    "Kamera-Plugin wurde entfernt": "Camera plugin was removed",
    "Kamera-Plugins enthalten ausführbaren Python-Code. Importiere nur Pakete aus vertrauenswürdigen Quellen. Maximale Dateigröße: 10 MB.": "Camera plugins contain executable Python code. Only import packages from trusted sources. Maximum file size: 10 MB.",
    "Kameras": "Cameras",
    "Kamerazugriff": "Camera access",
    "Kamerazugriff für Viewer": "Camera access for viewers",
    "Kanal": "Channel",
    "Kanäle": "Channels",
    "Kategorie": "Category",
    "Keine Berechtigung für diese Kamera": "No permission for this camera",
    "Keine Clips gefunden": "No clips found",
    "Keine Kamera verfügbar": "No camera available",
    "Keine Kamera mit unterstütztem Kamera-Archiv verfügbar": "No camera with a supported camera archive is available",
    "Keine SD-Card-Aufnahmen gefunden": "No SD card recordings found",
    "Keine Streams": "No streams",
    "Kein Stream bekannt": "No stream is known",
    "Kein Stream für diesen Kanal bekannt": "No stream is known for this channel",
    "Kein Stream für Live-Ansicht bekannt": "No stream is known for live view",
    "Komponente": "Component",
    "Leeren": "Clear",
    "Leistung": "Performance",
    "Letzte Ereignisse": "Recent events",
    "Live-API konnte nicht geladen werden": "The live API could not be loaded",
    "Live-Ansicht konnte nicht gestartet werden": "Live view could not be started",
    "Lokaler Pfad": "Local path",
    "Lokaler Pfad im Container": "Local path in the container",
    "Lokaler oder gemounteter Pfad": "Local or mounted path",
    "Lokaler/gemounteter Pfad": "Local/mounted path",
    "Löschen": "Delete",
    "Manuelle Stream-URL entfernen": "Remove manual stream URL",
    "Max. Alter Tage": "Maximum age in days",
    "Max. Größe GB": "Maximum size in GB",
    "Meldung": "Message",
    "Mindestdauer in Sekunden": "Minimum duration in seconds",
    "Modell": "Model",
    "Modell offen": "Model unknown",
    "Modul": "Module",
    "Motion-Aufnahmen speichern": "Save motion recordings",
    "MQTT aktivieren": "Enable MQTT",
    "MQTT-Einstellungen wurden gespeichert": "MQTT settings were saved",
    "Nachlauf in Sekunden": "Post-roll in seconds",
    "Name und Host sowie die für dieses Modul benötigten Zugangsdaten sind erforderlich": "Name, host, and the credentials required by this module must be provided",
    "Navigation umschalten": "Toggle navigation",
    "Neue Regel": "New rule",
    "Neue RTSP-/RTSPS-URL": "New RTSP/RTSPS URL",
    "nein": "no",
    "Neuer Benutzer": "New user",
    "Neuer Kanal": "New channel",
    "Neues Passwort": "New password",
    "Neues Speicherziel": "New storage destination",
    "Neu starten": "Restart",
    "NVR-Kanäle": "NVR channels",
    "Noch kein Speicherziel angelegt": "No storage destination has been created yet",
    "Noch keine Ereignisse": "No events yet",
    "Noch keine Kamera": "No camera yet",
    "Noch kein Stream für ein Vorschaubild verfügbar": "No stream is available for a preview image yet",
    "Noch keine Debug-Meldungen": "No debug messages yet",
    "Noch keine Prüfung": "Not checked yet",
    "Notify": "Notifications",
    "offen": "unknown",
    "Öffnen": "Open",
    "Passwort": "Password",
    "Pause zwischen Clips": "Pause between clips",
    "Plugin importieren": "Import plugin",
    "Plugin-Datei": "Plugin file",
    "Plugin kann nicht exportiert werden": "Plugin cannot be exported",
    "Prüfung läuft": "Check running",
    "Quelle": "Source",
    "Regeln": "Rules",
    "Retention Tage": "Retention days",
    "Retention-Regel wurde aktualisiert": "Retention rule was updated",
    "Retention-Regel wurde angelegt": "Retention rule was created",
    "Retention-Regel wurde gelöscht": "Retention rule was deleted",
    "Rolle": "Role",
    "Schlüssel": "Key",
    "SD-Karte": "SD card",
    "SD-Karte öffnen": "Open SD card",
    "SD-Karteninhalt konnte nicht geladen werden": "SD card content could not be loaded",
    "SD-Karteninhalt wird geladen...": "Loading SD card content...",
    "S3-kompatibler Cloud-Speicher": "S3-compatible cloud storage",
    "Secret Key": "Secret key",
    "Snapshot anhängen": "Attach snapshot",
    "Snapshot/Thumbnail zusätzlich speichern": "Also save a snapshot/thumbnail",
    "Speicher": "Storage",
    "Speicher verwalten": "Manage storage",
    "Speicheranalyse": "Storage analysis",
    "Speichern": "Save",
    "Speichern und prüfen": "Save and check",
    "Speicherziel": "Storage destination",
    "Speicherziel wurde aktualisiert": "Storage destination was updated",
    "Speicherziel wurde angelegt": "Storage destination was created",
    "Speicherziel wurde entfernt": "Storage destination was removed",
    "Sprache wechseln": "Change language",
    "Start": "Start",
    "Status": "Status",
    "Stream gestoppt": "Stream stopped",
    "Stream konnte nicht starten": "Stream could not start",
    "Stream startet": "Stream is starting",
    "Streams werden gestartet": "Streams are starting",
    "Suchen": "Search",
    "Typ": "Type",
    "Unterstützt": "Supported",
    "Verbindung": "Connection",
    "Verbindungsstatus": "Connection status",
    "Von": "From",
    "Vorhandene Benutzer": "Existing users",
    "Vorhandene Ziele": "Existing destinations",
    "Vorlauf in Sekunden": "Pre-roll in seconds",
    "Vorschau": "Preview",
    "Vorher": "Previous",
    "Warte auf Stream": "Waiting for stream",
    "Zeit": "Time",
    "Ziele": "Destinations",
    "Zugriff": "Access",
    "ZIP exportieren": "Export ZIP"
  };

  const patterns = [
    [/^(\d+) Eintraege$/, "$1 entries"],
    [/^Aktuelles Vorschaubild von (.+)$/, "Current preview image from $1"],
    [/^(\d+) Kerne · (.+)$/, "$1 cores · $2"],
    [/^Vorschaubild · Aktualisierung alle (\d+) Minuten$/, "Preview image · refreshed every $1 minutes"],
    [/^(\d+) Clips wurden gelöscht$/, "$1 clips were deleted"],
    [/^(\d+) Clips wurden per Retention gelöscht$/, "$1 clips were deleted by retention"],
    [/^(\d+)\/(\d+) live · (\d+) starten$/, "$1/$2 live · $3 starting"],
    [/^(\d+)\/(\d+) live · (\d+) Fehler$/, "$1/$2 live · $3 errors"],
    [/^(\d+)\/(\d+) live · (\d+) starten · (\d+) Fehler$/, "$1/$2 live · $3 starting · $4 errors"],
    [/^Plugin wird noch von (\d+) Kamera\(s\) verwendet$/, "Plugin is still used by $1 camera(s)"],
    [/^Kamera-Plugin (.+) wurde installiert$/, "Camera plugin $1 was installed"],
    [/^Das Modul (.+) unterstützt keine Ereignisaufnahmen$/, "The $1 module does not support event recordings"],
    [/^Das Modul (.+) unterstützt kein Kamera-Archiv$/, "The $1 module does not support a camera archive"],
    [/^Verbindung gespeichert, Probe fehlgeschlagen: (.+)$/, "Connection saved, probe failed: $1"],
    [/^Live-Ansicht konnte nicht gestartet werden: (.+)$/, "Live view could not be started: $1"],
    [/^Speicherziel konnte nicht angelegt werden: (.+)$/, "Storage destination could not be created: $1"],
    [/^Plugin konnte nicht entfernt werden: (.+)$/, "Plugin could not be removed: $1"],
    [/^SD-Card-Inhalte konnten nicht gelesen werden: (.+)$/, "SD card content could not be read: $1"],
    [/^SD-Card-Medium konnte nicht geoeffnet werden: (.+)$/, "SD card media could not be opened: $1"],
    [/^Das Modul (.+) akzeptiert keine manuelle Stream-URL$/, "The $1 module does not accept a manual stream URL"]
  ];

  const selectedLanguage = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "de" || stored === "en") return stored;
    } catch (_) {
      // Storage can be disabled; browser language remains a safe fallback.
    }
    return (navigator.language || "en").toLowerCase().startsWith("de") ? "de" : "en";
  };

  let language = selectedLanguage();

  const translate = (value) => {
    if (language !== "en" || typeof value !== "string") return value;
    const direct = english[value];
    if (direct) return direct;
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(value)) return value.replace(pattern, replacement);
    }
    return value;
  };

  const translateTextNode = (node) => {
    const original = node.nodeValue || "";
    const trimmed = original.trim();
    if (!trimmed) return;
    const translated = translate(trimmed);
    if (translated !== trimmed) {
      node.nodeValue = original.replace(trimmed, translated);
    }
  };

  const translateElement = (element) => {
    if (!(element instanceof Element)) return;
    for (const attribute of ["aria-label", "title", "placeholder", "data-tooltip"]) {
      if (element.hasAttribute(attribute)) {
        element.setAttribute(attribute, translate(element.getAttribute(attribute)));
      }
    }
    for (const child of element.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) translateTextNode(child);
    }
    element.querySelectorAll("*").forEach((child) => {
      for (const attribute of ["aria-label", "title", "placeholder", "data-tooltip"]) {
        if (child.hasAttribute(attribute)) {
          child.setAttribute(attribute, translate(child.getAttribute(attribute)));
        }
      }
      for (const node of child.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      }
    });
  };

  const updateControls = () => {
    document.querySelectorAll("[data-language]").forEach((button) => {
      const active = button.dataset.language === language;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-current-language]").forEach((label) => {
      label.textContent = language === "de" ? "Deutsch" : "English";
    });
  };

  const setLanguage = (nextLanguage) => {
    if (nextLanguage !== "de" && nextLanguage !== "en") return;
    try {
      localStorage.setItem(STORAGE_KEY, nextLanguage);
    } catch (_) {
      // The selection still applies to the current page when storage is disabled.
    }
    document.cookie = `tbc_language=${nextLanguage}; Path=/; Max-Age=31536000; SameSite=Lax`;
    if (nextLanguage !== language) window.location.reload();
  };

  const initialize = () => {
    document.documentElement.lang = language;
    translateElement(document.body);
    updateControls();
    document.addEventListener("click", (event) => {
      const control = event.target.closest("[data-language]");
      if (control) setLanguage(control.dataset.language);
    });
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
          else if (node.nodeType === Node.ELEMENT_NODE) translateElement(node);
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.documentElement.classList.remove("i18n-pending");
  };

  window.tbcI18n = { get language() { return language; }, setLanguage, t: translate };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
