"""One-off migration tool. Bulk-translates German string literals across
backend Python files (camera/cloud modules, plugins, detection backends,
etc.) to English in place, using the legacy i18n.js `english` dict as
translation memory. Only touches exact-match plain string constants - never
f-strings or partial matches, which are reported separately for manual
review. This tier is deliberately English-only going forward (see the
migration plan): it can include user-imported third-party plugin content
that can never be safely keyed for full DE/ES translation.
Not part of the runtime or CI - delete scripts/i18n_migrate/ once merged.
"""
import ast
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]

dicts = json.loads((HERE / "dicts.json").read_text())
GERMAN_TO_EN = dicts["english"]

TARGET_FILES = [
    "app/tbc/api_common.py",
    "app/tbc/app_updates.py",
    "app/tbc/camera_modules/base.py",
    "app/tbc/camera_modules/onvif.py",
    "app/tbc/camera_modules/onvif_control.py",
    "app/tbc/camera_modules/packages.py",
    "app/tbc/camera_modules/streams.py",
    "app/tbc/camera_plugins/standard_onvif/module.py",
    "app/tbc/cloud_modules/base.py",
    "app/tbc/cloud_modules/packages.py",
    "app/tbc/cloud_plugins/eufy/module.py",
    "app/tbc/cloud_plugins/ewelink/module.py",
    "app/tbc/cloud_plugins/unifi_protect/module.py",
    "app/tbc/container_launcher.py",
    "app/tbc/detection/coral_backend.py",
    "app/tbc/detection/onnx_backend.py",
    "app/tbc/detection/plugin_models.py",
    "app/tbc/detection/recognition.py",
    "app/tbc/detection/supervisor.py",
    "app/tbc/health.py",
    "app/tbc/maintenance.py",
    "app/tbc/plugin_sources.py",
    "app/tbc/plugin_templates.py",
    "app/tbc/plugin_testing.py",
    "app/tbc/recording.py",
    "app/tbc/snapshots.py",
    "app/tbc/themes/packages.py",
    "app/tbc/main.py",
]


def process_file(rel_path: str) -> tuple[int, list[str]]:
    path = ROOT / rel_path
    src_bytes = path.read_bytes()
    src = src_bytes.decode("utf-8")
    tree = ast.parse(src)

    replacements = []  # (start, end, new_text)
    unmatched_german = []

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        parent = getattr(node, "parent", None)
        is_logger = (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Attribute)
            and isinstance(parent.func.value, ast.Name)
            and parent.func.value.id == "LOGGER"
        )
        if is_logger:
            continue
        if text in GERMAN_TO_EN:
            replacements.append((node, GERMAN_TO_EN[text]))
        elif any(ch in text for ch in "äöüÄÖÜß"):
            unmatched_german.append((node.lineno, text))

    if not replacements:
        return 0, [f"{rel_path}:{line}: {text!r}" for line, text in unmatched_german]

    lines = src_bytes.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))

    def abs_offset(lineno: int, col: int) -> int:
        return line_starts[lineno - 1] + col

    # Only handle single-line string constants (the overwhelming majority);
    # multi-line (triple-quoted) literals are reported as unmatched instead
    # of risking a fragile quote-style rewrite.
    buf = src_bytes
    spans = []
    for node, new_text in replacements:
        if node.lineno != node.end_lineno:
            unmatched_german.append((node.lineno, node.value))
            continue
        start = abs_offset(node.lineno, node.col_offset)
        end = abs_offset(node.end_lineno, node.end_col_offset)
        original = buf[start:end].decode("utf-8")
        # Preserve the original quote style (single vs double) and any f/r prefix absence.
        quote = '"' if original.startswith('"') else "'"
        if original[:3] in ('"""', "'''"):
            continue  # skip triple-quoted, handled by multi-line check above defensively
        escaped = new_text.replace("\\", "\\\\").replace(quote, "\\" + quote)
        spans.append((start, end, f"{quote}{escaped}{quote}"))

    spans.sort(key=lambda s: s[0], reverse=True)
    for start, end, new_text in spans:
        buf = buf[:start] + new_text.encode("utf-8") + buf[end:]

    path.write_bytes(buf)
    return len(spans), [f"{rel_path}:{line}: {text!r}" for line, text in unmatched_german]


def main() -> None:
    total = 0
    all_unmatched = []
    for rel_path in TARGET_FILES:
        count, unmatched = process_file(rel_path)
        total += count
        all_unmatched.extend(unmatched)
        if count or unmatched:
            print(f"{rel_path}: {count} replaced, {len(unmatched)} unmatched")

    print(f"\ntotal replaced: {total}")
    print(f"total unmatched (need manual review): {len(all_unmatched)}")
    for line in all_unmatched:
        print(" ", line)

    # Verify every touched file still parses.
    bad = []
    for rel_path in TARGET_FILES:
        result = subprocess.run(
            ["python3", "-m", "py_compile", rel_path], cwd=ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            bad.append((rel_path, result.stderr))
    if bad:
        print("\nCOMPILE FAILURES:")
        for rel_path, err in bad:
            print(rel_path, err)
    else:
        print("\nall touched files still compile cleanly")


if __name__ == "__main__":
    main()
