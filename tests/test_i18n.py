from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "app" / "tbc" / "templates"
STATIC_ROOT = ROOT / "app" / "tbc" / "static"

# Deliberately limited to strong indicators of German UI copy. Internal camera
# error matching in dashboard.html and the native language label "Deutsch" are
# allowed below; translations themselves live in i18n.js and are excluded.
GERMAN_UI = re.compile(
    r"[ÄÖÜäöüß]|\b(?:Aktivieren|Aktualisieren|Aufnahme|Aufnahmen|Benutzer|Bestätigen|"
    r"Einstellungen|Entfernen|Geräte|Hinzufügen|Kamera|Kameras|Keine|Löschen|Noch|"
    r"Öffnen|Prüfung|Schließen|Speichern|Sprache|Verbindung|Verfügbar|Zurück)\b"
)


def _ui_sources() -> list[Path]:
    return sorted(TEMPLATE_ROOT.rglob("*.html")) + sorted(
        path for path in STATIC_ROOT.glob("*.js") if path.name != "i18n.js"
    )


def test_english_is_the_document_default() -> None:
    base = (TEMPLATE_ROOT / "base.html").read_text(encoding="utf-8")
    assert '<html lang="en"' in base
    assert "<span data-current-language>English</span>" in base


def test_ui_sources_do_not_add_german_fixed_copy() -> None:
    findings: list[str] = []
    for path in _ui_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            candidate = line.replace(">Deutsch<", "><")
            if path.name == "dashboard.html" and "probe_failed" in candidate:
                continue
            if GERMAN_UI.search(candidate):
                findings.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not findings, "German fixed UI copy found:\n" + "\n".join(findings)


def test_dynamic_browser_copy_uses_language_keys() -> None:
    for path in sorted(STATIC_ROOT.glob("*.js")):
        if path.name == "i18n.js":
            continue
        source = path.read_text(encoding="utf-8")
        assert not GERMAN_UI.search(source), path.relative_to(ROOT)


def test_readme_is_english() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not GERMAN_UI.search(readme)
