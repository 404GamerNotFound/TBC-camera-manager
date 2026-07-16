"""One-off migration tool. Rewrites every _set_flash(request, message[, level])
call in app/tbc/main.py into the new _set_flash(request, key, params=None,
level="success") calling convention, using flash_calls.json (classification),
flash_key_map.json (literal -> key), and flash_fstring_map.json (line -> key
+ params). Splices exact source spans via AST offsets so the rest of the
4600-line file is untouched byte-for-byte.
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import ast
import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
MAIN_PY = ROOT / "app" / "tbc" / "main.py"

flash_key_map = json.loads((HERE / "flash_key_map.json").read_text())
fstring_map = json.loads((HERE / "flash_fstring_map.json").read_text())


def python_repr_params(params: dict[str, str]) -> str:
    items = ", ".join(f'"{name}": {expr}' for name, expr in params.items())
    return "{" + items + "}"


def new_call_args(node: ast.Call) -> str:
    args = node.args
    message_arg = args[1]
    level = None
    if len(args) >= 3 and isinstance(args[2], ast.Constant):
        level = args[2].value
    for kw in node.keywords:
        if kw.arg == "level" and isinstance(kw.value, ast.Constant):
            level = kw.value.value

    if isinstance(message_arg, ast.Constant) and isinstance(message_arg.value, str):
        key = flash_key_map[message_arg.value]
        parts = ["request", f'"{key}"']
        if level and level != "success":
            parts.append(f'None, "{level}"')
        return ", ".join(parts)

    if isinstance(message_arg, ast.JoinedStr):
        entry = fstring_map[str(node.lineno)]
        key = entry["key"]
        params_src = python_repr_params(entry["params"])
        parts = ["request", f'"{key}"', params_src]
        if level and level != "success":
            parts.append(f'"{level}"')
        return ", ".join(parts)

    # passthrough (str(exc), message, snapshot.message, result.summary, ...)
    expr_src = ast.unparse(message_arg)
    parts = ["request", '"common.raw_message"', "{" + f'"message": {expr_src}' + "}"]
    if level and level != "success":
        parts.append(f'"{level}"')
    return ", ".join(parts)


def main() -> None:
    # ast.Call.col_offset/end_col_offset are UTF-8 BYTE offsets within the
    # line, not character offsets - a well-known CPython quirk that bites
    # any line containing umlauts (all over this German-authored file).
    # Work in bytes throughout to avoid the mismatch, decoding only at the
    # very end.
    src_bytes = MAIN_PY.read_bytes()
    src = src_bytes.decode("utf-8")
    tree = ast.parse(src)
    calls = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_set_flash"):
            continue
        if len(node.args) < 2:
            continue
        calls.append(node)

    calls.sort(key=lambda n: (n.lineno, n.col_offset), reverse=True)

    lines = src_bytes.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))

    def abs_offset(lineno: int, col: int) -> int:
        return line_starts[lineno - 1] + col

    buf = src_bytes
    rewritten = 0
    for node in calls:
        start = abs_offset(node.lineno, node.col_offset)
        end = abs_offset(node.end_lineno, node.end_col_offset)
        original = buf[start:end].decode("utf-8")
        assert original.startswith("_set_flash("), f"unexpected span at line {node.lineno}: {original!r}"
        new_args = new_call_args(node)
        new_text = f"_set_flash({new_args})"
        buf = buf[:start] + new_text.encode("utf-8") + buf[end:]
        rewritten += 1

    MAIN_PY.write_bytes(buf)
    print(f"rewrote {rewritten} _set_flash call sites")


if __name__ == "__main__":
    main()
