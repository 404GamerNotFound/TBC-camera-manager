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
    && apt-get install -y --no-install-recommends ffmpeg gcc libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

# go2rtc powers the optional WebRTC live-view mode (sub-second latency vs. HLS's
# 2s-segment delay). Bundled but never started unless an admin enables it in
# Live settings - see app/tbc/go2rtc.py. Binary is pinned and checksum-verified
# rather than trusting whatever is at the URL at build time; when bumping
# GO2RTC_VERSION, recompute both hashes from the new release's assets.
ARG GO2RTC_VERSION=1.9.14
RUN case "${BUILD_ARCH}" in \
        amd64) GO2RTC_ARCH=amd64; GO2RTC_SHA256=32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6 ;; \
        aarch64) GO2RTC_ARCH=arm64; GO2RTC_SHA256=359fabade8a7a51e81a55fe6df6b0ef81764a5e1d63179577534eaaa71904b50 ;; \
        *) echo "unsupported BUILD_ARCH for go2rtc: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/go2rtc \
        "https://github.com/AlexxIT/go2rtc/releases/download/v${GO2RTC_VERSION}/go2rtc_linux_${GO2RTC_ARCH}" \
    && echo "${GO2RTC_SHA256}  /usr/local/bin/go2rtc" | sha256sum -c - \
    && chmod +x /usr/local/bin/go2rtc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docs ./docs

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
EXPOSE 8555/tcp
EXPOSE 8555/udp
CMD ["python3", "/app/app/tbc/container_launcher.py"]
