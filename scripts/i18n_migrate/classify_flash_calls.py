"""One-off migration tool. Parses app/tbc/main.py's AST, finds every
_set_flash(...) call, and classifies each by argument shape so the
migration can decide: plain-literal (mechanical key swap), f-string
(needs params), or passthrough (wraps an existing variable/exception).
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = ROOT / "app" / "tbc" / "main.py"
DICTS = json.loads((Path(__file__).parent / "dicts.json").read_text())
GERMAN_TO_EN = DICTS["english"]
GERMAN_TO_ES = DICTS["spanish"]


def render_fstring(node: ast.JoinedStr) -> tuple[str, list[str]]:
    """Render an f-string AST node back to a {name}-style template plus the
    list of param expressions (as source text) in order."""
    parts = []
    params = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(value.value.replace("{", "{{").replace("}", "}}"))
        elif isinstance(value, ast.FormattedValue):
            expr_src = ast.unparse(value.value)
            params.append(expr_src)
            parts.append("{" + expr_src + "}")
    return "".join(parts), params


def describe_arg(node: ast.expr) -> dict:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
        return {
            "kind": "literal",
            "text": text,
            "en": GERMAN_TO_EN.get(text),
            "es": GERMAN_TO_ES.get(text),
        }
    if isinstance(node, ast.JoinedStr):
        template, params = render_fstring(node)
        return {"kind": "fstring", "template": template, "params": params}
    return {"kind": "passthrough", "expr": ast.unparse(node)}


def main() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_set_flash"):
            continue
        args = node.args
        if len(args) < 2:
            continue  # request-only call, shouldn't happen
        message_arg = args[1]
        level = None
        if len(args) >= 3 and isinstance(args[2], ast.Constant):
            level = args[2].value
        for kw in node.keywords:
            if kw.arg == "level" and isinstance(kw.value, ast.Constant):
                level = kw.value.value
        entry = describe_arg(message_arg)
        entry["line"] = node.lineno
        entry["level"] = level or "success"
        results.append(entry)

    by_kind: dict[str, int] = {}
    for r in results:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    print("total _set_flash calls:", len(results))
    print("by kind:", by_kind)

    literal_no_translation = [
        r for r in results if r["kind"] == "literal" and r["en"] is None
    ]
    print(f"\nliteral calls with NO existing translation ({len(literal_no_translation)}):")
    for r in literal_no_translation:
        print(f"  line {r['line']}: {r['text']!r}")

    out_path = Path(__file__).parent / "flash_calls.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
