"""One-off migration tool. Scans all Jinja templates for literal,
translatable text (element text content and aria-label/title/placeholder/
data-tooltip attribute values), skipping anything containing Jinja
{{ }} / {% %} syntax. Reports candidates, cross-referencing the legacy
english dict (reverse-lookup: English value -> German key) to reuse
existing translations, and flags text with no known translation as new.
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
TEMPLATES_DIR = ROOT / "app" / "tbc" / "templates"

dicts = json.loads((HERE / "dicts.json").read_text())
EN_TO_DE = {v: k for k, v in dicts["english"].items()}  # last-wins on dup, fine for a draft

TEXT_RE = re.compile(r">([^<>{}]+?)<", re.MULTILINE)
ATTR_RE = re.compile(
    r'\b(aria-label|title|placeholder|data-tooltip)="([^"{}]+?)"'
)
JINJA_MARKERS = ("{{", "{%")


def is_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if any(m in text for m in JINJA_MARKERS):
        return False
    if stripped.replace(".", "").replace(",", "").isdigit():
        return False
    return True


def main() -> None:
    report = {}
    total_candidates = 0
    total_known = 0
    total_new = 0
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        candidates = []
        for m in TEXT_RE.finditer(src):
            text = m.group(1)
            if is_translatable(text):
                candidates.append(("text", text.strip()))
        for m in ATTR_RE.finditer(src):
            attr, text = m.group(1), m.group(2)
            if is_translatable(text):
                candidates.append((f"attr:{attr}", text.strip()))
        if not candidates:
            continue
        entries = []
        for kind, text in candidates:
            known_key = EN_TO_DE.get(text)
            entries.append({"kind": kind, "text": text, "known_german": known_key})
            total_candidates += 1
            if known_key:
                total_known += 1
            else:
                total_new += 1
        report[rel] = entries

    print(f"templates with candidates: {len(report)}")
    print(f"total candidates: {total_candidates}  (known: {total_known}, new: {total_new})")
    out = HERE / "template_scan.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
