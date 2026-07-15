(() => {
  "use strict";

  const root = document.querySelector("[data-activity-root]");
  if (!root) return;

  const dataScript = root.querySelector("[data-activity-json]");
  let day = "";
  let cameras = [];
  try {
    const parsed = JSON.parse((dataScript && dataScript.textContent) || "{}");
    day = parsed.day || "";
    cameras = parsed.cameras || [];
  } catch (_) {
    cameras = [];
  }

  const scrollEl = root.querySelector("[data-activity-scroll]");
  const hoursEl = root.querySelector("[data-activity-hours]");
  const gridEl = root.querySelector("[data-activity-grid]");
  const lanesEl = root.querySelector("[data-activity-lanes]");
  const countEl = root.querySelector("[data-activity-count]");
  const emptyHintEl = root.querySelector("[data-activity-empty]");
  const toggleSdCard = root.querySelector('[data-activity-toggle="sdcard"]');

  const sdState = {};

  const DAY_SECONDS = 24 * 60 * 60;
  const dayStart = day ? new Date(`${day}T00:00:00`) : new Date();
  const NICE_INTERVALS = [4 * 3600, 2 * 3600, 3600, 1800, 900, 600, 300, 120, 60, 30, 15, 10, 5];

  const secondsOfDay = (isoString) => (new Date(isoString).getTime() - dayStart.getTime()) / 1000;
  const percent = (seconds) => Math.min(100, Math.max(0, (seconds / DAY_SECONDS) * 100));

  // Same hash as timeline.js's hue() - keeps a detection_key's color consistent
  // between the single-camera timeline and this cross-camera overview.
  const hue = (key) => {
    let hash = 0;
    const value = String(key || "");
    for (let index = 0; index < value.length; index += 1) {
      hash = (hash * 31 + value.charCodeAt(index)) % 360;
    }
    return hash;
  };

  const formatClock = (secondsFromMidnight) => {
    const h = Math.floor(secondsFromMidnight / 3600) % 24;
    const m = Math.floor((secondsFromMidnight % 3600) / 60);
    if (m === 0) return `${String(h).padStart(2, "0")}:00`;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  };

  const formatTime = (isoString) =>
    new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  function pickInterval(widthPx) {
    const minPxBetweenLabels = 70;
    for (const interval of NICE_INTERVALS) {
      const px = (interval / DAY_SECONDS) * widthPx;
      if (px >= minPxBetweenLabels) return interval;
    }
    return NICE_INTERVALS[NICE_INTERVALS.length - 1];
  }

  function renderHours() {
    if (!hoursEl) return;
    const widthPx = (scrollEl && scrollEl.clientWidth) || 760;
    hoursEl.innerHTML = "";
    if (gridEl) gridEl.innerHTML = "";
    const interval = pickInterval(widthPx);
    for (let seconds = 0; seconds <= DAY_SECONDS; seconds += interval) {
      const label = document.createElement("span");
      label.className = "timeline-hour-label";
      label.style.left = `${percent(seconds)}%`;
      label.textContent = formatClock(seconds);
      hoursEl.appendChild(label);
      if (gridEl) {
        const grid = document.createElement("div");
        grid.className = "timeline-gridline";
        grid.style.left = `${percent(seconds)}%`;
        gridEl.appendChild(grid);
      }
    }
  }

  const sdCardItemsFor = (camera) => {
    const entry = sdState[camera.id];
    return entry ? entry.items : [];
  };

  function updateCountAndHint(showSd) {
    let total = 0;
    cameras.forEach((camera) => {
      total += (camera.events || []).length;
      if (showSd && camera.sd_card_available) total += sdCardItemsFor(camera).length;
    });
    if (countEl) countEl.textContent = String(total);
    if (emptyHintEl) emptyHintEl.hidden = total > 0;
  }

  function renderLanes() {
    if (!lanesEl) return;
    lanesEl.innerHTML = "";
    const showSd = toggleSdCard ? toggleSdCard.checked : false;
    cameras.forEach((camera) => {
      const lane = document.createElement("div");
      lane.className = "timeline-lane";
      lane.dataset.cameraId = camera.id;

      const label = document.createElement("span");
      label.className = "timeline-lane-label";
      label.textContent = camera.name;
      lane.appendChild(label);

      const items = [
        ...(camera.events || []),
        ...(showSd && camera.sd_card_available ? sdCardItemsFor(camera) : []),
      ];

      items.forEach((item) => {
        const startSeconds = secondsOfDay(item.start);
        const durationSeconds = Math.max((new Date(item.end) - new Date(item.start)) / 1000, item.duration || 0, 1);
        const isSd = item.source === "sdcard";
        const block = document.createElement("a");
        block.className = `timeline-block ${isSd ? "timeline-block-sdcard" : "timeline-block-event"}`;
        block.style.left = `${percent(startSeconds)}%`;
        block.style.width = `${percent(durationSeconds)}%`;
        if (!isSd) block.style.setProperty("--marker-hue", hue(item.detection_key));
        block.title = `${camera.name} · ${formatTime(item.start)}–${formatTime(item.end)}${item.label ? " · " + item.label : ""}${isSd ? " · SD card" : ""}`;
        block.href = `/timeline?camera_id=${camera.id}&day=${day}`;
        lane.appendChild(block);
      });

      lanesEl.appendChild(lane);
    });

    updateCountAndHint(showSd);
  }

  async function loadSdCardForCamera(camera) {
    if (!camera.sd_card_available) return;
    let entry = sdState[camera.id];
    if (entry && (entry.loaded || entry.loading)) return entry.promise;
    entry = sdState[camera.id] = { loaded: false, loading: true, items: [], promise: null };
    entry.promise = (async () => {
      try {
        const params = new URLSearchParams({ camera_id: String(camera.id), date_from: day, date_to: day });
        const response = await fetch(`/api/sd-card/recordings?${params.toString()}`, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        const payload = await response.json().catch(() => ({}));
        if (response.ok) {
          entry.items = (payload.recordings || [])
            .filter((row) => row.start_time)
            .map((row) => ({
              id: `sd-${camera.id}-${row.source}-${row.start_id}`,
              start: String(row.start_time).replace(" ", "T"),
              end: row.end_time ? String(row.end_time).replace(" ", "T") : String(row.start_time).replace(" ", "T"),
              duration: row.duration_seconds || 0,
              label: row.trigger_label || row.file_name || "SD card",
              detection_key: "sdcard",
              source: "sdcard",
            }));
        }
      } catch (_) {
        // network/camera error: leave this camera's SD lane empty rather than breaking the page
      } finally {
        entry.loading = false;
        entry.loaded = true;
      }
    })();
    return entry.promise;
  }

  async function loadAllSdCard() {
    await Promise.all(cameras.filter((camera) => camera.sd_card_available).map(loadSdCardForCamera));
    renderLanes();
  }

  if (toggleSdCard) {
    toggleSdCard.addEventListener("change", () => {
      if (toggleSdCard.checked) loadAllSdCard();
      else renderLanes();
    });
  }

  renderHours();
  renderLanes();
  window.addEventListener("resize", renderHours);
  if (toggleSdCard && toggleSdCard.checked) loadAllSdCard();
})();
