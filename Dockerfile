# Python 3.13 is intentional: some camera-provider dependencies are not yet
# compatible with Python 3.14.
FROM python:3.13-slim

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TBC_DATABASE_PATH=/data/tbc.sqlite3 \
    TBC_RECORDINGS_PATH=/recordings \
    TBC_CAMERA_MODULES_PATH=/data/camera-modules \
    TBC_DASHBOARD_SNAPSHOTS_PATH=/data/dashboard-snapshots \
    TBC_DETECTION_MODELS_PATH=/data/detection-models \
    TBC_PORT=8732

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 tbc \
    && mkdir -p /data /recordings /recordings/tbc-camera-manager \
    && chown -R tbc:tbc /data /recordings /app

LABEL io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="TBC Camera Manager" \
    org.opencontainers.image.description="Modular camera manager for ONVIF and RTSP cameras" \
    org.opencontainers.image.source="https://github.com/404GamerNotFound/TBC-camera-manager"

# The launcher prepares Home Assistant bind mounts as root and drops to the
# unprivileged tbc user before it starts uvicorn.
USER root

EXPOSE 8732
CMD ["python3", "/app/app/tbc/container_launcher.py"]
