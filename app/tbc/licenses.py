"""Static attribution list, plus installed-plugin license discovery, for the /license page.

Licenses were verified against each project's PyPI metadata and/or GitHub repository
at the time this list was written - re-check before adding a new dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .camera_modules.registry import list_camera_module_registrations
from .cloud_modules.registry import list_cloud_module_registrations
from .network_modules.registry import list_network_module_registrations
from .themes.registry import list_theme_registrations

_LICENSE_FILENAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE")

THIRD_PARTY_LICENSES: list[dict[str, str]] = [
    # Web framework & core
    {"category": "Web framework & core", "name": "FastAPI", "license": "MIT", "url": "https://github.com/fastapi/fastapi"},
    {"category": "Web framework & core", "name": "Starlette", "license": "BSD-3-Clause", "url": "https://github.com/Kludex/starlette"},
    {"category": "Web framework & core", "name": "Uvicorn", "license": "BSD-3-Clause", "url": "https://github.com/Kludex/uvicorn"},
    {"category": "Web framework & core", "name": "Jinja2", "license": "BSD-3-Clause", "url": "https://github.com/pallets/jinja"},
    {"category": "Web framework & core", "name": "itsdangerous", "license": "BSD-3-Clause", "url": "https://github.com/pallets/itsdangerous"},
    {"category": "Web framework & core", "name": "python-multipart", "license": "Apache-2.0", "url": "https://github.com/Kludex/python-multipart"},
    {"category": "Web framework & core", "name": "MCP Python SDK", "license": "MIT", "url": "https://github.com/modelcontextprotocol/python-sdk"},

    # Camera & cloud integrations
    {"category": "Camera & cloud integrations", "name": "paho-mqtt", "license": "EPL-2.0 / EDL-1.0", "url": "https://github.com/eclipse-paho/paho.mqtt.python"},
    {"category": "Camera & cloud integrations", "name": "boto3", "license": "Apache-2.0", "url": "https://github.com/boto/boto3"},
    {"category": "Camera & cloud integrations", "name": "go2rtc", "license": "MIT", "url": "https://github.com/AlexxIT/go2rtc"},

    # AI detection & recognition
    {"category": "AI detection & recognition", "name": "NumPy", "license": "BSD-3-Clause", "url": "https://github.com/numpy/numpy"},
    {"category": "AI detection & recognition", "name": "Pillow", "license": "HPND (MIT-style)", "url": "https://github.com/python-pillow/Pillow"},
    {"category": "AI detection & recognition", "name": "ONNX Runtime", "license": "MIT", "url": "https://github.com/microsoft/onnxruntime"},
    {"category": "AI detection & recognition", "name": "OpenCV (opencv-python-headless)", "license": "Apache-2.0", "url": "https://github.com/opencv/opencv-python"},
    {"category": "AI detection & recognition", "name": "OpenCV Zoo (YuNet & SFace models)", "license": "Apache-2.0", "url": "https://github.com/opencv/opencv_zoo"},
    {"category": "AI detection & recognition", "name": "fast-alpr", "license": "MIT", "url": "https://github.com/ankandrew/fast-alpr"},
    {"category": "AI detection & recognition", "name": "fast-plate-ocr (+ plate OCR models)", "license": "MIT", "url": "https://github.com/ankandrew/fast-plate-ocr"},
    {"category": "AI detection & recognition", "name": "open-image-models (plate detector)", "license": "MIT", "url": "https://github.com/ankandrew/open-image-models"},
    {"category": "AI detection & recognition", "name": "ONNX Model Zoo (default detection model)", "license": "Apache-2.0", "url": "https://github.com/onnx/models"},
    {"category": "AI detection & recognition", "name": "Coral test_data (default Edge TPU model)", "license": "Apache-2.0", "url": "https://github.com/google-coral/test_data"},

    # Frontend
    {"category": "Frontend", "name": "Bootstrap", "license": "MIT", "url": "https://github.com/twbs/bootstrap"},
    {"category": "Frontend", "name": "hls.js", "license": "Apache-2.0", "url": "https://github.com/video-dev/hls.js"},
]


def _license_file_content(path: Path) -> str | None:
    for filename in _LICENSE_FILENAMES:
        candidate = path / filename
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return None
    return None


def list_plugin_licenses() -> list[dict[str, Any]]:
    """Every installed plugin (any kind) that bundles a LICENSE/COPYING/NOTICE file.

    Third-party plugins are separate git repositories the admin chose to install
    (built-in or external) - unlike THIRD_PARTY_LICENSES above, there is no way
    to know their license ahead of time, so this scans each installed plugin's
    own directory instead of hand-maintaining a list. A plugin without one of
    the recognized filenames simply doesn't appear here.
    """
    entries: list[dict[str, Any]] = []
    for registration in list_camera_module_registrations():
        if registration.package is None:
            continue
        text = _license_file_content(registration.package.path)
        if text:
            entries.append(
                {
                    "kind": "camera",
                    "kind_label": "Camera plugin",
                    "label": registration.module.label,
                    "key": registration.module.key,
                    "license_text": text,
                }
            )
    for registration in list_cloud_module_registrations():
        text = _license_file_content(registration.package.path)
        if text:
            entries.append(
                {
                    "kind": "cloud",
                    "kind_label": "Cloud provider",
                    "label": registration.module.label,
                    "key": registration.module.key,
                    "license_text": text,
                }
            )
    for registration in list_network_module_registrations():
        text = _license_file_content(registration.package.path)
        if text:
            entries.append(
                {
                    "kind": "network",
                    "kind_label": "Network provider",
                    "label": registration.module.label,
                    "key": registration.module.key,
                    "license_text": text,
                }
            )
    for registration in list_theme_registrations():
        text = _license_file_content(registration.package.path)
        if text:
            entries.append(
                {
                    "kind": "design",
                    "kind_label": "Design",
                    "label": registration.manifest.label,
                    "key": registration.manifest.key,
                    "license_text": text,
                }
            )
    entries.sort(key=lambda entry: (entry["kind"], entry["label"].lower()))
    return entries
