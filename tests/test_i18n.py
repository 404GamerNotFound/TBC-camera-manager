from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "app" / "tbc" / "templates"
STATIC_ROOT = ROOT / "app" / "tbc" / "static"
BACKEND_ROOT = ROOT / "app" / "tbc"
LOCALE_ROOT = STATIC_ROOT / "i18n"

# Deliberately limited to strong indicators of German UI copy. Internal camera
# error matching in dashboard.html and the native language label "Deutsch" are
# allowed below; translations themselves live in the locale JSON files and are
# excluded.
GERMAN_UI = re.compile(
    r"[ÄÖÜäöüß]|\b(?:Aktivieren|Aktualisieren|Aufnahme|Aufnahmen|Benutzer|Bestätigen|"
    r"Daueraufzeichnung|Einstellungen|eingebaut|Entfernen|Fokus|Geräte|Hinzufügen|Kamera|"
    r"Kameras|Keine|Kerne|Löschen|Minuten|Noch|Öffnen|Prüfung|Python-Paket|Schließen|"
    r"SD-Karte|Speichern|Spalten|Sprache|Verbindung|Verfügbar|Vorschaubild|Zurück)\b"
)

# data-i18n="key", data-i18n-aria-label="key", data-i18n-params="..." (skipped,
# it carries JSON not a key), and Jinja-computed data-i18n="{{ 'a' if x else 'b' }}".
DATA_I18N_LITERAL = re.compile(r'data-i18n(?:-(?!params)[\w-]+)?="([\w.]+)"')
DATA_I18N_JINJA_TERNARY = re.compile(r"data-i18n=\"\{\{ '([\w.]+)' if .*? else '([\w.]+)' \}\}\"")


def _locales() -> dict[str, dict[str, str]]:
    return {
        lang: json.loads((LOCALE_ROOT / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in ("af", "bg", "de", "en", "es", "fr", "nl", "pl", "pt")
    }


def _ui_sources() -> list[Path]:
    return sorted(TEMPLATE_ROOT.rglob("*.html")) + sorted(
        path for path in STATIC_ROOT.glob("*.js") if path.name != "i18n.js"
    )


class _UnkeyedTemplateCopyScanner(HTMLParser):
    """Find literal text nodes that are not covered by an i18n marker."""

    ALLOWED = re.compile(
        r"^(?:TBC|REST|MCP|HLS|s ·|dBm–|· °C|MB|GB-|(?:· ){2}Not installed)$"
    )

    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.findings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text or not re.search(r"[A-Za-zÄÖÜäöüß]", text) or not self.stack:
            return
        if any(tag in {"script", "style", "code", "pre"} for tag, _ in self.stack):
            return
        if any(
            "data-i18n" in attrs
            or "data-current-language" in attrs
            or attrs.get("aria-hidden") == "true"
            for _, attrs in self.stack
        ):
            return
        if self.ALLOWED.fullmatch(text):
            return
        line, _ = self.getpos()
        self.findings.append(f"{self.path.relative_to(ROOT)}:{line}: {text}")


def _backend_python_sources() -> list[Path]:
    return sorted(
        path
        for path in BACKEND_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _logger_call_line_numbers(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for candidate in ast.walk(tree):
        if not isinstance(candidate, ast.Call):
            continue
        func = candidate.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "LOGGER"):
            continue
        for arg in list(candidate.args) + [kw.value for kw in candidate.keywords]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                lines.add(arg.lineno)
    return lines


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


def test_runtime_templates_do_not_leave_literal_ui_copy_unkeyed() -> None:
    findings: list[str] = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        # Files carrying the " 2" suffix are archival copies and are never
        # selected by Jinja's template loader.
        if " 2" in path.name:
            continue
        source = path.read_text(encoding="utf-8")
        # Jinja control/output blocks are dynamic data, not literal UI copy.
        # Preserve their line breaks so reported source locations stay useful.
        source = re.sub(
            r"\{[{%#].*?[}%#]\}",
            lambda match: "\n" * match.group(0).count("\n"),
            source,
            flags=re.DOTALL,
        )
        scanner = _UnkeyedTemplateCopyScanner(path)
        scanner.feed(source)
        findings.extend(scanner.findings)
    assert not findings, "Literal UI copy without data-i18n found:\n" + "\n".join(findings)


def test_readme_is_english() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not GERMAN_UI.search(readme)


def test_backend_python_does_not_add_untranslated_german_copy() -> None:
    """Guards the bulk-translated backend tier: LOGGER.*() calls are exempt
    (internal operational logs, never shown to a user), everything else must
    be English. See scripts/i18n_migrate/ (removed once this branch merges)
    for how the existing German strings were translated."""
    findings: list[str] = []
    for path in _backend_python_sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        logger_lines = _logger_call_line_numbers(tree)
        for number, line in enumerate(source.splitlines(), 1):
            if number in logger_lines or line.strip().startswith("#"):
                continue
            if GERMAN_UI.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not findings, "Untranslated German backend copy found:\n" + "\n".join(findings)


def test_locale_json_key_parity() -> None:
    locales = _locales()
    key_sets = {lang: set(strings) for lang, strings in locales.items()}
    reference = key_sets["en"]
    for lang, keys in key_sets.items():
        missing = reference - keys
        extra = keys - reference
        assert not missing, f"{lang}.json is missing keys present in en.json: {sorted(missing)[:10]}"
        assert not extra, f"{lang}.json has keys not present in en.json: {sorted(extra)[:10]}"


def test_all_data_i18n_keys_exist() -> None:
    en = _locales()["en"]
    missing: list[str] = []
    for path in _ui_sources():
        source = path.read_text(encoding="utf-8")
        for match in DATA_I18N_LITERAL.finditer(source):
            key = match.group(1)
            if key not in en:
                missing.append(f"{path.relative_to(ROOT)}: {key!r}")
        for match in DATA_I18N_JINJA_TERNARY.finditer(source):
            for key in match.groups():
                if key not in en:
                    missing.append(f"{path.relative_to(ROOT)}: {key!r}")
    assert not missing, "data-i18n keys with no locale entry:\n" + "\n".join(missing)
