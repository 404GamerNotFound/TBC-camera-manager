FROM python:3.13-slim

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
    && mkdir -p /data /recordings \
    && chown -R tbc:tbc /data /recordings /app

USER tbc

EXPOSE 8732
CMD ["sh", "-c", "uvicorn tbc.main:app --host 0.0.0.0 --port ${TBC_PORT:-8732} --app-dir app"]
