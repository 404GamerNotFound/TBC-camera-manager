"""One-off migration tool. Adds data-i18n / data-i18n-<attr> annotations to
all 33 templates, using the text -> key map built by mint_template_keys.py.
Only rewrites unambiguous cases: an opening tag whose ENTIRE text content
(no nested elements, no Jinja expressions) matches a known key, or a
aria-label/title/placeholder/data-tooltip attribute value that matches one.
Everything else (mixed content, ternaries, dynamic text) is left alone and
reported for manual handling.
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
TEMPLATES_DIR = ROOT / "app" / "tbc" / "templates"

text_to_key: dict[str, str] = json.loads((HERE / "template_key_map.json").read_text())

# Matches <tag attrs>TEXT</tag> where TEXT has no nested tags and no Jinja
# expressions, and the tag doesn't already carry a data-i18n attribute.
ELEMENT_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][\w-]*)(?P<attrs>(?:\s+[\w:-]+(?:=\"[^\"]*\"|=\'[^\']*\')?)*)\s*>"
    r"(?P<text>[^<>{}]+?)"
    r"</(?P=tag)>"
)
ATTR_RE = re.compile(
    r'(?P<name>aria-label|title|placeholder|data-tooltip)="(?P<value>[^"{}]+?)"'
)


def already_keyed(attrs: str) -> bool:
    return "data-i18n" in attrs


def rewrite_element(match: re.Match) -> tuple[str, bool]:
    tag, attrs, text = match.group("tag"), match.group("attrs"), match.group("text")
    if already_keyed(attrs) or tag in ("script", "style", "option"):
        return match.group(0), False
    stripped = text.strip()
    normed = re.sub(r"\s+", " ", html.unescape(stripped)).strip()
    key = text_to_key.get(stripped) or text_to_key.get(normed)
    if not key:
        return match.group(0), False
    new_attrs = f'{attrs} data-i18n="{key}"'
    return f"<{tag}{new_attrs}>{text}</{tag}>", True


def rewrite_option(match: re.Match) -> tuple[str, bool]:
    tag, attrs, text = match.group("tag"), match.group("attrs"), match.group("text")
    if tag != "option" or already_keyed(attrs):
        return match.group(0), False
    stripped = text.strip()
    normed = re.sub(r"\s+", " ", html.unescape(stripped)).strip()
    key = text_to_key.get(stripped) or text_to_key.get(normed)
    if not key:
        return match.group(0), False
    new_attrs = f'{attrs} data-i18n="{key}"'
    return f"<{tag}{new_attrs}>{text}</{tag}>", True


def rewrite_attrs(text: str) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        name, value = m.group("name"), m.group("value")
        data_attr = "data-i18n-" + name
        # Idempotency guard: a previous run may have already annotated this
        # exact attribute (look a short distance ahead in the source).
        tail = text[m.end():m.end() + 200]
        if re.match(rf'\s+{re.escape(data_attr)}="', tail):
            return m.group(0)
        stripped = value.strip()
        normed = re.sub(r"\s+", " ", html.unescape(stripped)).strip()
        key = text_to_key.get(stripped) or text_to_key.get(normed)
        if not key:
            return m.group(0)
        count += 1
        return f'{m.group(0)} {data_attr}="{key}"'

    return ATTR_RE.sub(repl, text), count


def process_file(path: Path) -> tuple[int, int]:
    src = path.read_text(encoding="utf-8")
    element_hits = 0

    def repl(m: re.Match) -> str:
        nonlocal element_hits
        if m.group("tag") == "option":
            new_text, hit = rewrite_option(m)
        else:
            new_text, hit = rewrite_element(m)
        if hit:
            element_hits += 1
        return new_text

    new_src = ELEMENT_RE.sub(repl, src)
    new_src, attr_hits = rewrite_attrs(new_src)
    if new_src != src:
        path.write_text(new_src, encoding="utf-8")
    return element_hits, attr_hits


def main() -> None:
    total_elements = 0
    total_attrs = 0
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        elements, attrs = process_file(path)
        total_elements += elements
        total_attrs += attrs
        if elements or attrs:
            print(f"{path.relative_to(ROOT)}: {elements} elements, {attrs} attrs")
    print(f"\ntotal: {total_elements} elements + {total_attrs} attrs = {total_elements + total_attrs} annotations")


if __name__ == "__main__":
    main()
