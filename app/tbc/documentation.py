from __future__ import annotations

import html
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from markdown import markdown
from markupsafe import Markup


DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
_MARKDOWN_HREF_PATTERN = re.compile(r'href="([^"]+)"')


def documentation_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def documentation_files(docs_dir: Path = DOCS_DIR) -> list[dict[str, str]]:
    documents = [
        {
            "name": path.name,
            "title": documentation_title(path),
        }
        for path in docs_dir.glob("*.md")
        if " 2" not in path.stem
    ]
    return sorted(documents, key=lambda document: (document["name"] != "README.md", document["title"].casefold()))


def resolve_documentation_file(document_name: str, docs_dir: Path = DOCS_DIR) -> Path | None:
    relative = PurePosixPath(document_name.strip())
    if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
        return None
    filename = relative.name
    if not filename:
        filename = "README.md"
    elif not PurePosixPath(filename).suffix:
        filename = f"{filename}.md"
    if PurePosixPath(filename).suffix.lower() != ".md" or " 2" in PurePosixPath(filename).stem:
        return None
    path = docs_dir / filename
    return path if path.is_file() else None


def render_documentation_markdown(source: str, docs_dir: Path = DOCS_DIR) -> Markup:
    # Documentation files are repository content, but escaping raw HTML keeps a
    # malformed or copied Markdown file from injecting executable markup into the UI.
    escaped_source = source.replace("&", "&amp;").replace("<", "&lt;")
    rendered = markdown(
        escaped_source,
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )

    def _rewrite_document_link(match: re.Match[str]) -> str:
        original = html.unescape(match.group(1))
        target = urlsplit(original)
        if target.scheme or target.netloc or target.path.startswith("/") or not target.path.lower().endswith(".md"):
            return match.group(0)
        document_path = resolve_documentation_file(target.path, docs_dir)
        if document_path is None:
            return match.group(0)
        rewritten = f"/docs/{quote(document_path.name, safe='')}"
        if target.fragment:
            rewritten = f"{rewritten}#{quote(target.fragment, safe='-._~')}"
        return f'href="{rewritten}"'

    return Markup(_MARKDOWN_HREF_PATTERN.sub(_rewrite_document_link, rendered))
