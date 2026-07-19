from __future__ import annotations

import re
from pathlib import Path

from app.tbc.documentation import (
    DOCS_DIR,
    documentation_files,
    render_documentation_markdown,
    resolve_documentation_file,
)


EXPECTED_DOCUMENTS = {
    "README.md",
    "api.md",
    "camera-modules.md",
    "cloud-accounts.md",
    "deployment.md",
    "design-themes.md",
    "mcp.md",
    "network-accounts.md",
    "operations.md",
    "plugin-sources.md",
    "user-guide.md",
}


def test_documentation_index_contains_canonical_documents() -> None:
    documents = documentation_files()
    assert documents[0]["name"] == "README.md"
    assert {document["name"] for document in documents} == EXPECTED_DOCUMENTS
    assert all(" 2" not in document["name"] for document in documents)
    assert all(document["title"] for document in documents)


def test_document_resolution_accepts_markdown_only_and_blocks_traversal() -> None:
    assert resolve_documentation_file("api") == DOCS_DIR / "api.md"
    assert resolve_documentation_file("api.md") == DOCS_DIR / "api.md"
    assert resolve_documentation_file("api.txt") is None
    assert resolve_documentation_file("../README.md") is None
    assert resolve_documentation_file("subdirectory/api.md") is None
    assert resolve_documentation_file("api 2.md") is None
    assert resolve_documentation_file("missing.md") is None


def test_markdown_renderer_supports_reference_markup_and_neutralizes_raw_html(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# Target", encoding="utf-8")
    rendered = str(
        render_documentation_markdown(
            """# Heading

[Target](target.md#details)

| Column |
| --- |
| Value |

```python
print("safe")
```

> A note

<script>alert("unsafe")</script>
""",
            tmp_path,
        )
    )

    assert '<h1 id="heading">Heading</h1>' in rendered
    assert 'href="/docs/target.md#details"' in rendered
    assert "<table>" in rendered
    assert '<code class="language-python">' in rendered
    assert "<blockquote>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_all_internal_markdown_links_resolve() -> None:
    unresolved: list[str] = []
    link_pattern = re.compile(r"\[[^]]+]\(([^)]+\.md)(?:#[^)]+)?\)")
    for document in documentation_files():
        path = DOCS_DIR / document["name"]
        for target in link_pattern.findall(path.read_text(encoding="utf-8")):
            if resolve_documentation_file(target) is None:
                unresolved.append(f"{path.name}: {target}")
    assert not unresolved, "Unresolved documentation links:\n" + "\n".join(unresolved)
