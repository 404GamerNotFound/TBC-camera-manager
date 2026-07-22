#!/usr/bin/env python3
"""Create complete TBC locale files through Google Translate.

The script deliberately sends only public UI labels from ``en.json``.  It
keeps template placeholders (for example ``{camera}``) and uses a visible
record-separator between batches, allowing the unofficial Google Translate
endpoint to translate roughly 4,500 characters in one request while mapping
each translated value back to its original key.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
LOCALE_DIR = ROOT / "app" / "tbc" / "static" / "i18n"
SOURCE_PATH = LOCALE_DIR / "en.json"
SEPARATOR = "\n␞\n"
MAX_BATCH_CHARS = 4_400

# Twenty additional high-speaker languages. Existing locales are deliberately
# skipped, as requested; the list therefore extends beyond the first 20 where
# English, Spanish, French, Portuguese and German already existed.
TARGETS: dict[str, str] = {
    "zh": "zh-CN",  # Mandarin Chinese, simplified script
    "hi": "hi",
    "ar": "ar",
    "bn": "bn",
    "ru": "ru",
    "ur": "ur",
    "id": "id",
    "ja": "ja",
    "pa": "pa",
    "mr": "mr",
    "te": "te",
    "tr": "tr",
    "ta": "ta",
    "zh-Hant": "zh-TW",  # Yue/Cantonese audience, traditional script
    "vi": "vi",
    "tl": "tl",
    "ko": "ko",
    "fa": "fa",
    "it": "it",
    "th": "th",
}
EXISTING_TARGETS: dict[str, str] = {
    "af": "af", "bg": "bg", "de": "de", "es": "es", "fr": "fr",
    "nl": "nl", "pl": "pl", "pt": "pt",
}


def batches(items: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    result: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_length = 0
    for key, value in items:
        value_length = len(value) + (len(SEPARATOR) if current else 0)
        if current and current_length + value_length > MAX_BATCH_CHARS:
            result.append(current)
            current, current_length = [], 0
        # Individual labels in this project are much smaller than Google's
        # 5,000-character limit. Guard anyway so a future long description
        # fails loudly rather than silently producing a partial locale.
        if len(value) > MAX_BATCH_CHARS:
            raise ValueError(f"Locale value {key!r} exceeds the batch limit")
        current.append((key, value))
        current_length += value_length
    if current:
        result.append(current)
    return result


def translate_batch(text: str, target: str) -> str:
    query = urlencode({"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": text})
    request = Request(
        f"https://translate.googleapis.com/translate_a/single?{query}",
        headers={"User-Agent": "TBC locale generator/1.0"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed Google endpoint above
        payload = json.loads(response.read().decode("utf-8"))
    return "".join(segment[0] for segment in payload[0])


def translate_locale(source: dict[str, str], target: str) -> dict[str, str]:
    translated: dict[str, str] = {}
    work = batches(list(source.items()))
    for index, batch in enumerate(work, 1):
        original_values = [value for _, value in batch]
        result = translate_batch(SEPARATOR.join(original_values), target)
        values = result.split(SEPARATOR)
        if len(values) != len(batch):
            raise RuntimeError(
                f"Google Translate changed the batch separator in chunk {index}/{len(work)} for {target}"
            )
        translated.update(dict(zip((key for key, _ in batch), values, strict=True)))
        print(f"  {target}: {index}/{len(work)}", flush=True)
        time.sleep(0.15)
    if translated.keys() != source.keys():
        raise RuntimeError(f"Key parity failed for {target}")
    return translated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--languages", nargs="+", choices=sorted({**TARGETS, **EXISTING_TARGETS}), default=sorted(TARGETS))
    parser.add_argument(
        "--fill-missing",
        action="store_true",
        help="translate only keys that an existing locale does not yet contain",
    )
    args = parser.parse_args()
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    for locale in args.languages:
        print(f"Translating {locale}…", flush=True)
        destination = LOCALE_DIR / f"{locale}.json"
        existing = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
        selected_source = (
            {key: value for key, value in source.items() if key not in existing}
            if args.fill_missing
            else source
        )
        target = TARGETS[locale] if locale in TARGETS else EXISTING_TARGETS[locale]
        translated = translate_locale(selected_source, target) if selected_source else {}
        if args.fill_missing:
            existing.update(translated)
            translated = existing
        if translated.keys() != source.keys():
            raise RuntimeError(f"Key parity failed for {locale}")
        destination.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {destination.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
