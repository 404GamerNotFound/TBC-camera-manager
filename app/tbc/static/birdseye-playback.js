(() => {
  "use strict";

  const root = document.querySelector("[data-sync-root]");
  if (!root) return;

  const dataScript = root.querySelector("[data-sync-json]");
  let dataByCamera = {};
  try {
    dataByCamera = JSON.parse((dataScript && dataScript.textContent) || "{}");
  } catch (_) {
    dataByCamera = {};
  }

  const DAY_SECONDS = 24 * 60 * 60;
  // Not frame-accurate sync - browsers can't genlock independently-loaded video files. This is
  // how often a playing reference camera's real progress is read back and used to correct any
  // camera whose own player has drifted or needs to advance to its next segment.
  const RESYNC_INTERVAL_MS = 2000;
  const RESYNC_DRIFT_SECONDS = 1.5;
  const NICE_INTERVALS = [4 * 3600, 2 * 3600, 3600, 1800, 900, 600, 300, 120, 60, 30, 15, 10, 5];

  const hoursEl = root.querySelector("[data-sync-hours]");
  const lanesEl = root.querySelector("[data-sync-lanes]");
  const innerEl = root.querySelector("[data-sync-inner]");
  const cursorEl = root.querySelector("[data-sync-cursor]");
  const emptyHint = root.querySelector("[data-sync-empty]");
  const playPauseBtn = root.querySelector("[data-sync-play-pause]");
  const timeLabel = root.querySelector("[data-sync-time]");
  const statusLabel = root.querySelector("[data-sync-status]");

  const percent = (seconds) => Math.min(100, Math.max(0, (seconds / DAY_SECONDS) * 100));

  const dayStr = root.dataset.day;
  const dayStart = dayStr ? new Date(`${dayStr}T00:00:00`) : new Date();
  const secondsOfDay = (isoString) => (new Date(isoString).getTime() - dayStart.getTime()) / 1000;

  const formatClock = (seconds) => {
    const clamped = Math.max(0, Math.min(DAY_SECONDS, seconds));
    const h = Math.floor(clamped / 3600);
    const m = Math.floor((clamped % 3600) / 60);
    const s = Math.floor(clamped % 60);
    return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
  };

  const players = Array.from(document.querySelectorAll("[data-sync-player]")).map((video) => {
    const shell = video.closest(".live-player-shell");
    if (window.TBCPlayer) new window.TBCPlayer(video, { mode: "vod" });
    const cameraId = video.dataset.cameraId;
    const entry = dataByCamera[cameraId] || { segments: [], events: [] };
    const items = [...(entry.segments || []), ...(entry.events || [])].sort(
      (a, b) => new Date(a.start) - new Date(b.start)
    );
    return {
      video,
      cameraId,
      cameraName: video.dataset.cameraName || cameraId,
      placeholder: shell ? shell.querySelector("[data-sync-placeholder]") : null,
      items,
      currentItem: null,
    };
  });

  const hasAnyFootage = players.some((entry) => entry.items.length > 0);
  if (emptyHint) emptyHint.hidden = hasAnyFootage;

  let globalSeconds = 0;
  let playing = false;
  let resyncTimer = null;

  function pickInterval(widthPx) {
    const minPxBetweenLabels = 70;
    for (const interval of NICE_INTERVALS) {
      if ((interval / DAY_SECONDS) * widthPx >= minPxBetweenLabels) return interval;
    }
    return NICE_INTERVALS[NICE_INTERVALS.length - 1];
  }

  function renderHours() {
    if (!hoursEl) return;
    hoursEl.innerHTML = "";
    const widthPx = (innerEl && innerEl.clientWidth) || 760;
    const interval = pickInterval(widthPx);
    for (let seconds = 0; seconds <= DAY_SECONDS; seconds += interval) {
      const label = document.createElement("span");
      label.className = "timeline-hour-label";
      label.style.left = `${percent(seconds)}%`;
      label.textContent = formatClock(seconds).slice(0, 5);
      hoursEl.appendChild(label);
    }
  }

  function renderLanes() {
    if (!lanesEl) return;
    lanesEl.innerHTML = "";
    players.forEach((entry) => {
      const lane = document.createElement("div");
      lane.className = "timeline-lane";
      const label = document.createElement("span");
      label.className = "timeline-lane-label";
      label.textContent = entry.cameraName;
      lane.appendChild(label);
      entry.items.forEach((item) => {
        const startSeconds = secondsOfDay(item.start);
        const durationSeconds = Math.max((new Date(item.end) - new Date(item.start)) / 1000, item.duration || 0, 1);
        const block = document.createElement("button");
        block.type = "button";
        block.className = `timeline-block ${item.detection_key === "continuous" ? "timeline-block-continuous" : "timeline-block-event"}`;
        block.style.left = `${percent(startSeconds)}%`;
        block.style.width = `${percent(durationSeconds)}%`;
        block.title = `${entry.cameraName}: ${item.label || item.detection_key}`;
        lane.appendChild(block);
      });
      lane.addEventListener("click", (event) => {
        if (event.target !== lane) return;
        const rect = lane.getBoundingClientRect();
        const ratio = rect.width ? Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) : 0;
        seekAllTo(ratio * DAY_SECONDS);
      });
      lanesEl.appendChild(lane);
    });
  }

  function findSegmentAt(entry, seconds) {
    for (const item of entry.items) {
      const startSeconds = secondsOfDay(item.start);
      const durationSeconds = Math.max((new Date(item.end) - new Date(item.start)) / 1000, item.duration || 0, 1);
      if (seconds >= startSeconds && seconds < startSeconds + durationSeconds) {
        return { item, offset: seconds - startSeconds };
      }
    }
    return null;
  }

  function seekPlayerTo(entry, seconds) {
    const match = findSegmentAt(entry, seconds);
    if (!match) {
      entry.video.pause();
      entry.currentItem = null;
      if (entry.placeholder) entry.placeholder.hidden = false;
      return;
    }
    if (entry.placeholder) entry.placeholder.hidden = true;
    const { item, offset } = match;
    if (entry.currentItem && entry.currentItem.id === item.id) {
      if (Math.abs(entry.video.currentTime - offset) > RESYNC_DRIFT_SECONDS) {
        try {
          entry.video.currentTime = offset;
        } catch (_) {
          // media not ready; ignore, next tick retries
        }
      }
      return;
    }
    entry.currentItem = item;
    entry.video.src = item.media_url;
    const applyOffset = () => {
      try {
        entry.video.currentTime = offset;
      } catch (_) {
        // media not ready; playback still starts near 0
      }
      if (playing) entry.video.play().catch(() => {});
    };
    entry.video.addEventListener("loadedmetadata", applyOffset, { once: true });
  }

  function updateCursor() {
    if (cursorEl) cursorEl.style.left = `${percent(globalSeconds)}%`;
    if (timeLabel) timeLabel.textContent = formatClock(globalSeconds);
  }

  function seekAllTo(seconds) {
    globalSeconds = Math.min(DAY_SECONDS, Math.max(0, seconds));
    players.forEach((entry) => seekPlayerTo(entry, globalSeconds));
    updateCursor();
  }

  function referenceEntry() {
    return (
      players.find((entry) => entry.currentItem && !entry.video.paused && !entry.video.ended) ||
      players.find((entry) => entry.currentItem) ||
      null
    );
  }

  function tick() {
    const reference = referenceEntry();
    if (reference) {
      globalSeconds = secondsOfDay(reference.currentItem.start) + reference.video.currentTime;
    } else {
      // No camera has footage right now - keep advancing by wall-clock time so playback moves
      // through the gap instead of stalling until a reference player becomes available again.
      globalSeconds += RESYNC_INTERVAL_MS / 1000;
    }
    if (globalSeconds >= DAY_SECONDS) {
      pause();
      return;
    }
    seekAllTo(globalSeconds);
  }

  function play() {
    if (playing) return;
    playing = true;
    if (playPauseBtn) {
      playPauseBtn.textContent = "⏸";
      if (window.tbcI18n) playPauseBtn.setAttribute("aria-label", window.tbcI18n.t("player.play_pause"));
    }
    players.forEach((entry) => {
      if (entry.currentItem) entry.video.play().catch(() => {});
    });
    resyncTimer = window.setInterval(tick, RESYNC_INTERVAL_MS);
  }

  function pause() {
    playing = false;
    if (playPauseBtn) {
      playPauseBtn.textContent = "▶";
      if (window.tbcI18n) playPauseBtn.setAttribute("aria-label", window.tbcI18n.t("player.play_pause"));
    }
    players.forEach((entry) => entry.video.pause());
    if (resyncTimer) {
      window.clearInterval(resyncTimer);
      resyncTimer = null;
    }
  }

  if (playPauseBtn) {
    playPauseBtn.addEventListener("click", () => {
      if (playing) pause();
      else play();
    });
  }

  window.addEventListener("resize", renderHours);

  renderHours();
  renderLanes();

  // Start at the earliest available recording across all cameras, if any, rather than at
  // midnight with every tile showing "no recording".
  const earliestStart = players
    .flatMap((entry) => entry.items)
    .map((item) => secondsOfDay(item.start))
    .reduce((min, value) => (min === null || value < min ? value : min), null);
  seekAllTo(earliestStart === null ? 0 : earliestStart);

  function renderCameraCount() {
    if (statusLabel && window.tbcI18n) {
      statusLabel.textContent = window.tbcI18n.t("birdseye.playback_camera_count", { count: players.length });
    }
  }

  renderCameraCount();
  // t() falls back to the raw key if this runs before i18n.js's own locale fetch resolves (see
  // the comment next to `tbc:i18n-ready` in i18n.js) - redo it once ready, same as live.js does.
  document.addEventListener("tbc:i18n-ready", renderCameraCount, { once: true });
})();
