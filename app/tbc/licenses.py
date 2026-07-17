"""Static attribution list for the /license page.

Licenses were verified against each project's PyPI metadata and/or GitHub repository
at the time this list was written - re-check before adding a new dependency.
"""

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
    {"category": "Camera & cloud integrations", "name": "python-onvif (onvif-zeep)", "license": "MIT", "url": "https://github.com/quatanium/python-onvif"},
    {"category": "Camera & cloud integrations", "name": "reolink-aio", "license": "MIT", "url": "https://github.com/starkillerOG/reolink_aio"},
    {"category": "Camera & cloud integrations", "name": "uiprotect", "license": "MIT", "url": "https://github.com/uilibs/uiprotect"},
    {"category": "Camera & cloud integrations", "name": "pyeufysecurity", "license": "MIT", "url": "https://github.com/ptarjan/pyeufysecurity"},
    {"category": "Camera & cloud integrations", "name": "ewelink", "license": "GPL-3.0", "url": "https://github.com/Olindholm/ewelink"},
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
