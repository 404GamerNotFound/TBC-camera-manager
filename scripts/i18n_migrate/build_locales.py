"""One-off migration tool. Merges keyedMessages (from the legacy i18n.js),
the flash-message key map, the f-string key map, and manual translations
into the final app/tbc/static/i18n/{en,de,es}.json locale files.
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]

dicts = json.loads((HERE / "dicts.json").read_text())
GERMAN_TO_EN = dicts["english"]
GERMAN_TO_ES = dicts["spanish"]
keyed = dicts["keyedMessages"]

flash_key_map = json.loads((HERE / "flash_key_map.json").read_text())
fstring_map = json.loads((HERE / "flash_fstring_map.json").read_text())
fstring_translations = json.loads((HERE / "fstring_translations.json").read_text())
new_literal_translations = json.loads((HERE / "new_literal_translations.json").read_text())

en: dict[str, str] = {}
de: dict[str, str] = {}
es: dict[str, str] = {}


def add(key: str, en_v: str, de_v: str, es_v: str, *, prefer_existing: bool = False) -> None:
    if key in en:
        if prefer_existing:
            return
        if en[key] != en_v or de[key] != de_v or es[key] != es_v:
            raise SystemExit(f"conflicting definitions for key {key!r}")
        return
    en[key] = en_v
    de[key] = de_v
    es[key] = es_v


# 1. keyedMessages carry over as-is (already correct, already in production use).
for key, translations in keyed.items():
    add(key, translations["en"], translations["de"], translations["es"])

# 2. Flash literal strings: German source text becomes the "de" value; en/es
#    come from the legacy dict, or from the 3 manually-authored translations
#    for strings that were never translated at all.
for german_text, key in flash_key_map.items():
    if german_text in GERMAN_TO_EN:
        en_v = GERMAN_TO_EN[german_text]
        es_v = GERMAN_TO_ES[german_text]
    else:
        manual = new_literal_translations[key]
        en_v, es_v = manual["en"], manual["es"]
    add(key, en_v, german_text, es_v, prefer_existing=True)

# 3. Flash f-string templates: hand-authored de/es (params already renamed
#    to {name}-style placeholders matching the params dict built at the call
#    site), en comes from the extraction draft.
fstring_keys_seen = set()
for line, entry in fstring_map.items():
    key = entry["key"]
    if key in fstring_keys_seen:
        continue
    fstring_keys_seen.add(key)
    translations = fstring_translations[key]
    add(key, entry["en"], translations["de"], translations["es"])

# 4. Transparent passthrough key for untranslatable dynamic content
#    (exception text, module-reported messages) - documents the limitation
#    instead of pretending it's localized.
add("common.raw_message", "{message}", "{message}", "{message}")

# 5. Template text with no prior translation anywhere (recognition.html,
#    license.html, and ~100 other strings never wired into the old dict).
new_template_translations = json.loads((HERE / "new_template_translations.json").read_text())
for key, translations in new_template_translations.items():
    add(key, translations["en"], translations["de"], translations["es"])

# 6. Template text that already had a legacy translation but no real key
#    (auto-minted by mint_template_keys.py from the German source + slug).
auto_minted = json.loads((HERE / "auto_minted_locale_entries.json").read_text())
for key, translations in auto_minted.items():
    add(key, translations["en"], translations["de"], translations["es"])

out_dir = ROOT / "app" / "tbc" / "static" / "i18n"
out_dir.mkdir(parents=True, exist_ok=True)
for name, data in (("en", en), ("de", de), ("es", es)):
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: {len(data)} keys")

assert en.keys() == de.keys() == es.keys(), "key sets diverged"
print("OK: all three locale files have identical key sets")
