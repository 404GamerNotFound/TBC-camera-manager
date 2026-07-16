"""One-off migration tool. Builds the master "English template text -> key"
map used by rewrite_templates.py, and emits any additional locale entries
needed for text that already had a translation in the legacy dict but
never had a real key (only implicit identity via the raw German string).
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


dicts = json.loads((HERE / "dicts.json").read_text())
GERMAN_TO_EN = dicts["english"]
GERMAN_TO_ES = dicts["spanish"]
keyed = dicts["keyedMessages"]
EN_TO_KEY = {norm(v["en"]): k for k, v in keyed.items()}

new_template_translations = json.loads((HERE / "new_template_translations.json").read_text())
EN_TO_NEW_KEY = {norm(v["en"]): k for k, v in new_template_translations.items()}

scan = json.loads((HERE / "template_scan.json").read_text())

STOPWORDS = {"the", "a", "an", "is", "are", "to", "of", "for", "and", "in", "on", "with", "this", "that"}

EXPLICIT_SKIP = {
    "recording_finished,recording_failed,unknown_face_detected,unknown_plate_detected",
    "tests/", "z. B. plugins/acme", "B-TB 1234", "notify.mobile_app",
}


def is_noise(text: str) -> bool:
    t = text.strip()
    if t in EXPLICIT_SKIP:
        return True
    if len(t) <= 1:
        return True
    if re.match(r"^[a-z_]+(\.[a-z_]+)+$", t):  # dotted key reference, e.g. nav.toggle
        return True
    if re.match(r"^[/.][\w/.\-]*\.\.\.?$", t) or re.match(r"^/[\w/.\-{}]+$", t):
        return True
    if t.isupper() and len(t) <= 5:
        return True
    if re.match(r"^[A-Za-z0-9_.\-]+\.(md|json|py|js|html|css)$", t):
        return True
    if re.match(r"^tbc_[A-Za-z0-9.]+$", t) or re.match(r"^https?://", t) or re.match(r"^(rtsp|tbc)[:/]", t):
        return True
    if t in ("TBC_DETECTION_SAMPLE_FPS", "TBC_DETECTION_CONFIDENCE_THRESHOLD", "onnxruntime-gpu", "pycoral",
              "tflite-runtime", "Dockerfile.gpu", "Dockerfile.coral", "eu-central-1", "HLS-Playlist",
              "CameraModule", "CloudAccountModule", "create_module()", "schema_version", "key", "label",
              "version", "entrypoint", "main", "git pull", "):"):
        return True
    return False


def slugify(text: str, max_words: int = 5) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    words = [w for w in words if w not in STOPWORDS] or words
    return "_".join(words[:max_words]) or "text"


def guess_namespace(template_stem: str) -> str:
    overrides = {
        "camera_detail": "camera", "camera_form": "camera_form", "camera_modules": "plugin",
        "cloud_modules": "plugin", "cloud_account_devices": "cloud_account",
        "cloud_account_edit": "cloud_account", "cloud_account_verify": "cloud_account",
        "cloud_accounts": "cloud_account", "notification_fields": "notification",
        "plugin_sources": "plugin_source", "plugin_updates": "plugin_updates",
        "sd_card": "sd_card", "storage_explorer": "storage",
    }
    return overrides.get(template_stem, template_stem)


text_to_key: dict[str, str] = {}
additional_locale_entries: dict[str, dict[str, str]] = {}
minted_keys_seen: set[str] = set()

for rel_path, entries in scan.items():
    stem = Path(rel_path).stem
    namespace = guess_namespace(stem)
    for entry in entries:
        text = entry["text"]
        if is_noise(text):
            continue
        normed = norm(text)
        if text in text_to_key:
            continue
        if normed in EN_TO_KEY:
            text_to_key[text] = EN_TO_KEY[normed]
            continue
        if normed in EN_TO_NEW_KEY:
            text_to_key[text] = EN_TO_NEW_KEY[normed]
            continue
        german = entry.get("known_german")
        if not german:
            continue  # genuinely unhandled - reported separately, should be ~0 after our manual pass
        base_key = f"{namespace}.{slugify(text)}"
        key = base_key
        suffix = 2
        while key in minted_keys_seen and additional_locale_entries.get(key, {}).get("en") != text:
            key = f"{base_key}_{suffix}"
            suffix += 1
        minted_keys_seen.add(key)
        text_to_key[text] = key
        additional_locale_entries[key] = {
            "en": text,
            "de": german,
            "es": GERMAN_TO_ES.get(german, text),
        }

unhandled = []
for rel_path, entries in scan.items():
    for entry in entries:
        if entry["text"] not in text_to_key and not is_noise(entry["text"]):
            unhandled.append((rel_path, entry["text"]))

print(f"text_to_key entries: {len(text_to_key)}")
print(f"newly minted (auto-keyed legacy translations): {len(additional_locale_entries)}")
print(f"unhandled (no translation found anywhere): {len(unhandled)}")
for rel_path, text in unhandled[:30]:
    print(f"  {rel_path}: {text!r}")

(HERE / "template_key_map.json").write_text(
    json.dumps(text_to_key, indent=2, ensure_ascii=False), encoding="utf-8"
)
(HERE / "auto_minted_locale_entries.json").write_text(
    json.dumps(additional_locale_entries, indent=2, ensure_ascii=False), encoding="utf-8"
)
(HERE / "unhandled_template_text.json").write_text(
    json.dumps(unhandled, indent=2, ensure_ascii=False), encoding="utf-8"
)
