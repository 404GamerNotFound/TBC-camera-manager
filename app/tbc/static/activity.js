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

  function renderLanes() {
    if (!lanesEl) return;
    lanesEl.innerHTML = "";
    cameras.forEach((camera) => {
      const lane = document.createElement("div");
      lane.className = "timeline-lane";
      lane.dataset.cameraId = camera.id;

      const label = document.createElement("span");
      label.className = "timeline-lane-label";
      label.textContent = camera.name;
      lane.appendChild(label);

      (camera.events || []).forEach((item) => {
        const startSeconds = secondsOfDay(item.start);
        const durationSeconds = Math.max((new Date(item.end) - new Date(item.start)) / 1000, item.duration || 0, 1);
        const block = document.createElement("a");
        block.className = "timeline-block timeline-block-event";
        block.style.left = `${percent(startSeconds)}%`;
        block.style.width = `${percent(durationSeconds)}%`;
        block.style.setProperty("--marker-hue", hue(item.detection_key));
        block.title = `${camera.name} · ${formatTime(item.start)}–${formatTime(item.end)}${item.label ? " · " + item.label : ""}`;
        block.href = `/timeline?camera_id=${camera.id}&day=${day}`;
        lane.appendChild(block);
      });

      lanesEl.appendChild(lane);
    });
  }

  renderHours();
  renderLanes();
  window.addEventListener("resize", renderHours);
})();
