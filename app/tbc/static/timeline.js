(() => {
  "use strict";

  const root = document.querySelector("[data-timeline-root]");
  if (!root) return;

  const dataScript = root.querySelector("[data-timeline-json]");
  let data = { segments: [], events: [], day: "", camera_id: null, sd_card_available: false };
  try {
    data = Object.assign(data, JSON.parse((dataScript && dataScript.textContent) || "{}"));
  } catch (_) {
    // keep defaults
  }

  const scrollEl = root.querySelector("[data-timeline-scroll]");
  const innerEl = root.querySelector("[data-timeline-inner]");
  const hoursEl = root.querySelector("[data-timeline-hours]");
  const gridEl = root.querySelector("[data-timeline-grid]");
  const laneContinuous = root.querySelector("[data-timeline-lane-continuous]");
  const laneEvents = root.querySelector("[data-timeline-lane-events]");
  const laneSdCard = root.querySelector("[data-timeline-lane-sdcard]");
  const cursor = root.querySelector("[data-timeline-cursor]");
  const emptyHint = root.querySelector("[data-timeline-empty]");
  const toggleLocal = root.querySelector('[data-timeline-toggle="local"]');
  const toggleSdCard = root.querySelector('[data-timeline-toggle="sdcard"]');
  const zoomInBtn = root.querySelector("[data-timeline-zoom-in]");
  const zoomOutBtn = root.querySelector("[data-timeline-zoom-out]");
  const zoomResetBtn = root.querySelector("[data-timeline-zoom-reset]");
  const zoomLabel = root.querySelector("[data-timeline-zoom-label]");

  const player = document.querySelector("[data-timeline-player]");
  if (player && window.TBCPlayer) {
    new window.TBCPlayer(player, { mode: "vod" });
  }
  const titleEl = document.querySelector("[data-timeline-title]");
  const metaEl = document.querySelector("[data-timeline-meta]");
  const listBody = document.querySelector("[data-timeline-list]");
  const listCount = document.querySelector("[data-timeline-list-count]");

  const DAY_SECONDS = 24 * 60 * 60;
  const dayStart = data.day ? new Date(`${data.day}T00:00:00`) : new Date();
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 64;
  const NICE_INTERVALS = [4 * 3600, 2 * 3600, 3600, 1800, 900, 600, 300, 120, 60, 30, 15, 10, 5];

  let zoom = MIN_ZOOM;

  const secondsOfDay = (isoString) => (new Date(isoString).getTime() - dayStart.getTime()) / 1000;
  const percent = (seconds) => Math.min(100, Math.max(0, (seconds / DAY_SECONDS) * 100));

  const hue = (key) => {
    let hash = 0;
    const value = String(key || "");
    for (let index = 0; index < value.length; index += 1) {
      hash = (hash * 31 + value.charCodeAt(index)) % 360;
    }
    return hash;
  };

  const formatTime = (isoString) =>
    new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const formatClock = (secondsFromMidnight) => {
    const h = Math.floor(secondsFromMidnight / 3600) % 24;
    const m = Math.floor((secondsFromMidnight % 3600) / 60);
    if (m === 0) return `${String(h).padStart(2, "0")}:00`;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  };

  const state = {
    continuous: [...data.segments].sort((a, b) => new Date(a.start) - new Date(b.start)),
    events: [...data.events].sort((a, b) => new Date(a.start) - new Date(b.start)),
    sdcard: [],
    sdCardLoaded: false,
    sdCardLoading: false,
  };

  // ---- zoom + ruler -------------------------------------------------

  function innerWidthPx() {
    const containerWidth = (scrollEl && scrollEl.clientWidth) || 760;
    return Math.max(containerWidth, Math.round(containerWidth * zoom));
  }

  function pickInterval(widthPx) {
    const minPxBetweenLabels = 70;
    for (const interval of NICE_INTERVALS) {
      const px = (interval / DAY_SECONDS) * widthPx;
      if (px >= minPxBetweenLabels) return interval;
    }
    return NICE_INTERVALS[NICE_INTERVALS.length - 1];
  }

  function renderHours(widthPx) {
    if (!hoursEl) return;
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

  function currentCenterRatio() {
    if (!scrollEl) return 0.5;
    const width = innerEl.getBoundingClientRect().width || 1;
    return (scrollEl.scrollLeft + scrollEl.clientWidth / 2) / width;
  }

  function applyZoom(centerRatio) {
    const ratio = centerRatio == null ? currentCenterRatio() : centerRatio;
    const widthPx = innerWidthPx();
    innerEl.style.width = `${widthPx}px`;
    renderHours(widthPx);
    if (zoomLabel) zoomLabel.textContent = `${zoom % 1 === 0 ? zoom : zoom.toFixed(1)}×`;
    if (zoomOutBtn) zoomOutBtn.disabled = zoom <= MIN_ZOOM;
    if (zoomInBtn) zoomInBtn.disabled = zoom >= MAX_ZOOM;
    if (scrollEl) {
      const newWidth = innerEl.getBoundingClientRect().width || widthPx;
      scrollEl.scrollLeft = Math.max(0, ratio * newWidth - scrollEl.clientWidth / 2);
    }
  }

  function setZoom(nextZoom, centerRatio) {
    zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
    applyZoom(centerRatio);
  }

  if (zoomInBtn) zoomInBtn.addEventListener("click", () => setZoom(zoom * 1.6));
  if (zoomOutBtn) zoomOutBtn.addEventListener("click", () => setZoom(zoom / 1.6));
  if (zoomResetBtn) zoomResetBtn.addEventListener("click", () => setZoom(MIN_ZOOM, 0));

  if (scrollEl) {
    scrollEl.addEventListener(
      "wheel",
      (event) => {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        const rect = innerEl.getBoundingClientRect();
        const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
        setZoom(zoom * (event.deltaY < 0 ? 1.25 : 1 / 1.25), ratio);
      },
      { passive: false }
    );
  }

  window.addEventListener("resize", () => applyZoom(currentCenterRatio()));

  // ---- playback -------------------------------------------------

  function playItem(item, offsetSeconds, laneKind) {
    if (!player || !item) return;
    const alreadyLoaded = player.dataset.currentId === String(item.id);
    player.dataset.currentId = String(item.id);
    player.dataset.currentKind = laneKind || item.detection_key || "event";

    const seek = () => {
      if (offsetSeconds > 0) {
        try {
          player.currentTime = offsetSeconds;
        } catch (_) {
          // media not ready yet; playback still starts at 0
        }
      }
      player.play().catch(() => {});
    };

    if (alreadyLoaded) {
      seek();
    } else {
      player.src = item.media_url;
      player.addEventListener("loadedmetadata", seek, { once: true });
    }

    if (titleEl) {
      titleEl.textContent =
        laneKind === "continuous" ? "Daueraufzeichnung" : laneKind === "sdcard" ? `SD-Karte · ${item.label}` : item.label;
    }
    if (metaEl) metaEl.textContent = `${formatTime(item.start)} – ${formatTime(item.end)}`;
  }

  // ---- lane rendering -------------------------------------------------

  function laneItems(kind) {
    if (kind === "continuous") return state.continuous;
    if (kind === "sdcard") return state.sdcard;
    return state.events;
  }

  function renderLane(laneEl, kind, colorClass) {
    if (!laneEl) return;
    laneEl.querySelectorAll(".timeline-block").forEach((node) => node.remove());
    const items = laneItems(kind);
    items.forEach((item) => {
      const startSeconds = secondsOfDay(item.start);
      const durationSeconds = Math.max((new Date(item.end) - new Date(item.start)) / 1000, item.duration || 0, 1);
      const block = document.createElement("button");
      block.type = "button";
      block.className = `timeline-block ${colorClass}`;
      block.style.left = `${percent(startSeconds)}%`;
      block.style.width = `${percent(durationSeconds)}%`;
      if (kind === "events") block.style.setProperty("--marker-hue", hue(item.detection_key));
      block.title = `${formatTime(item.start)} – ${formatTime(item.end)}${item.label ? " · " + item.label : ""}`;
      block.addEventListener("click", (event) => {
        event.stopPropagation();
        const rect = block.getBoundingClientRect();
        const withinRatio = rect.width ? (event.clientX - rect.left) / rect.width : 0;
        playItem(item, Math.max(0, withinRatio) * durationSeconds, kind);
      });
      laneEl.appendChild(block);
    });
  }

  function renderAllLanes() {
    renderLane(laneContinuous, "continuous", "timeline-block-continuous");
    renderLane(laneEvents, "events", "timeline-block-event");
    renderLane(laneSdCard, "sdcard", "timeline-block-sdcard");
    renderList();
    updateEmptyHint();
  }

  function laneBackgroundClick(laneEl, kind) {
    if (!laneEl) return;
    laneEl.addEventListener("click", (event) => {
      const items = laneItems(kind);
      if (!items.length) return;
      const rect = laneEl.getBoundingClientRect();
      const ratio = rect.width ? Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) : 0;
      const clickedSeconds = ratio * DAY_SECONDS;
      let nearest = null;
      let nearestDistance = Infinity;
      items.forEach((item) => {
        const distance = Math.abs(secondsOfDay(item.start) - clickedSeconds);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearest = item;
        }
      });
      if (nearest) playItem(nearest, 0, kind);
    });
  }

  laneBackgroundClick(laneContinuous, "continuous");
  laneBackgroundClick(laneEvents, "events");
  laneBackgroundClick(laneSdCard, "sdcard");

  // ---- cursor + auto-advance -------------------------------------------------

  if (player) {
    player.addEventListener("timeupdate", () => {
      const currentId = player.dataset.currentId;
      const current = [...state.continuous, ...state.events, ...state.sdcard].find(
        (item) => String(item.id) === currentId
      );
      if (!current || !cursor) return;
      cursor.style.left = `${percent(secondsOfDay(current.start) + player.currentTime)}%`;
      cursor.hidden = false;
    });

    player.addEventListener("ended", () => {
      const kind = player.dataset.currentKind;
      if (kind !== "continuous" && kind !== "sdcard") return;
      const items = laneItems(kind);
      const index = items.findIndex((item) => String(item.id) === player.dataset.currentId);
      const next = index >= 0 ? items[index + 1] : null;
      if (next) playItem(next, 0, kind);
    });
  }

  // ---- event list (local events only) -------------------------------------------------

  function renderList() {
    if (!listBody) return;
    listBody.innerHTML = "";
    const items = state.events;
    if (listCount) listCount.textContent = String(items.length);
    items.forEach((eventItem) => {
      const item = document.createElement("li");
      const heading = document.createElement("div");
      heading.className = "event-list-heading";
      const strong = document.createElement("strong");
      strong.textContent = eventItem.label;
      const span = document.createElement("span");
      span.className = "event-trigger";
      span.textContent = formatTime(eventItem.start);
      heading.appendChild(strong);
      heading.appendChild(span);

      const actions = document.createElement("div");
      actions.className = "button-row";
      const playButton = document.createElement("button");
      playButton.type = "button";
      playButton.className = "secondary-button";
      playButton.textContent = window.tbcI18n.t("timeline.play");
      playButton.addEventListener("click", () => playItem(eventItem, 0, "events"));
      actions.appendChild(playButton);

      item.appendChild(heading);
      item.appendChild(actions);
      listBody.appendChild(item);
    });
    if (!items.length) {
      const empty = document.createElement("li");
      empty.textContent = window.tbcI18n.t("timeline.no_events");
      listBody.appendChild(empty);
    }
  }

  function updateEmptyHint() {
    if (!emptyHint) return;
    const localVisible = toggleLocal ? toggleLocal.checked : true;
    const sdVisible = toggleSdCard ? toggleSdCard.checked : false;
    const hasLocal = localVisible && (state.continuous.length > 0 || state.events.length > 0);
    const hasSd = sdVisible && state.sdcard.length > 0;
    emptyHint.hidden = hasLocal || hasSd;
  }

  // ---- layer toggles -------------------------------------------------

  function applyLayerVisibility() {
    const showLocal = toggleLocal ? toggleLocal.checked : true;
    const showSd = toggleSdCard ? toggleSdCard.checked : false;
    if (laneContinuous) laneContinuous.hidden = !showLocal;
    if (laneEvents) laneEvents.hidden = !showLocal;
    if (laneSdCard) laneSdCard.hidden = !showSd;
    updateEmptyHint();
  }

  if (toggleLocal) {
    toggleLocal.addEventListener("change", applyLayerVisibility);
  }
  if (toggleSdCard) {
    toggleSdCard.addEventListener("change", () => {
      applyLayerVisibility();
      if (toggleSdCard.checked) loadSdCard();
    });
  }

  // ---- SD card lazy load -------------------------------------------------

  async function loadSdCard() {
    if (state.sdCardLoaded || state.sdCardLoading) return;
    if (!data.sd_card_available || !data.camera_id) return;
    state.sdCardLoading = true;
    try {
      const params = new URLSearchParams({
        camera_id: String(data.camera_id),
        date_from: data.day,
        date_to: data.day,
      });
      const response = await fetch(`/api/sd-card/recordings?${params.toString()}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok) {
        state.sdcard = (payload.recordings || [])
          .filter((row) => row.start_time)
          .map((row) => ({
            id: `sd-${row.source}-${row.start_id}`,
            start: String(row.start_time).replace(" ", "T"),
            end: row.end_time ? String(row.end_time).replace(" ", "T") : row.start_time.replace(" ", "T"),
            duration: row.duration_seconds || 0,
            label: row.trigger_label || row.file_name || "SD-Karte",
            media_url: row.media_url,
            detection_key: "sdcard",
          }))
          .sort((a, b) => new Date(a.start) - new Date(b.start));
      }
    } catch (_) {
      // network/camera error: leave the lane empty rather than breaking the page
    } finally {
      state.sdCardLoading = false;
      state.sdCardLoaded = true;
      renderLane(laneSdCard, "sdcard", "timeline-block-sdcard");
      updateEmptyHint();
      if (player && !player.dataset.currentId && state.sdcard.length) {
        playItem(state.sdcard[0], 0, "sdcard");
      }
    }
  }

  // ---- init -------------------------------------------------

  applyZoom(0);
  applyLayerVisibility();
  renderAllLanes();

  if (state.continuous.length) playItem(state.continuous[0], 0, "continuous");
  else if (state.events.length) playItem(state.events[0], 0, "events");

  if (toggleSdCard && toggleSdCard.checked) loadSdCard();
})();
