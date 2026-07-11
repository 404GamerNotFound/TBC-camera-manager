(() => {
  "use strict";

  const root = document.querySelector("[data-timeline-root]");
  if (!root) return;

  const dataScript = root.querySelector("[data-timeline-json]");
  let data = { segments: [], events: [], day: "" };
  try {
    data = JSON.parse((dataScript && dataScript.textContent) || "{}");
  } catch (_) {
    data = { segments: [], events: [], day: "" };
  }

  const track = root.querySelector("[data-timeline-track]");
  const continuousLayer = root.querySelector("[data-timeline-continuous]");
  const markersLayer = root.querySelector("[data-timeline-markers]");
  const cursor = root.querySelector("[data-timeline-cursor]");
  const player = document.querySelector("[data-timeline-player]");
  const titleEl = document.querySelector("[data-timeline-title]");
  const metaEl = document.querySelector("[data-timeline-meta]");
  const listBody = document.querySelector("[data-timeline-list]");
  const listCount = document.querySelector("[data-timeline-list-count]");

  const DAY_SECONDS = 24 * 60 * 60;
  const dayStart = data.day ? new Date(`${data.day}T00:00:00`) : new Date();

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

  const segments = [...data.segments].sort((a, b) => new Date(a.start) - new Date(b.start));
  const events = [...data.events].sort((a, b) => new Date(a.start) - new Date(b.start));

  function playItem(item, offsetSeconds) {
    if (!player || !item) return;
    const isContinuous = item.detection_key === "continuous";
    const alreadyLoaded = player.dataset.currentId === String(item.id);
    player.dataset.currentId = String(item.id);
    player.dataset.currentKind = isContinuous ? "continuous" : "event";

    const seek = () => {
      if (offsetSeconds > 0) {
        try {
          player.currentTime = offsetSeconds;
        } catch (_) {
          // media not ready yet; ignored, playback still starts at 0
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

    if (titleEl) titleEl.textContent = isContinuous ? "Daueraufzeichnung" : item.label;
    if (metaEl) metaEl.textContent = `${formatTime(item.start)} – ${formatTime(item.end)}`;
  }

  segments.forEach((segment) => {
    const startSeconds = secondsOfDay(segment.start);
    const durationSeconds = Math.max(
      segment.duration || 0,
      (new Date(segment.end) - new Date(segment.start)) / 1000,
      1
    );
    const block = document.createElement("button");
    block.type = "button";
    block.className = "timeline-block";
    block.style.left = `${percent(startSeconds)}%`;
    block.style.width = `${Math.max(percent(durationSeconds), 0.15)}%`;
    block.title = `${formatTime(segment.start)} – ${formatTime(segment.end)}`;
    block.addEventListener("click", (event) => {
      event.stopPropagation();
      playItem(segment, 0);
    });
    continuousLayer.appendChild(block);
  });

  events.forEach((eventItem) => {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "timeline-marker";
    marker.style.left = `${percent(secondsOfDay(eventItem.start))}%`;
    marker.style.setProperty("--marker-hue", hue(eventItem.detection_key));
    marker.title = `${formatTime(eventItem.start)} · ${eventItem.label}`;
    marker.addEventListener("click", (event) => {
      event.stopPropagation();
      playItem(eventItem, 0);
    });
    markersLayer.appendChild(marker);
  });

  if (track) {
    track.addEventListener("click", (event) => {
      const rect = track.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const clickedSeconds = ratio * DAY_SECONDS;

      const covering = segments.find((segment) => {
        const start = secondsOfDay(segment.start);
        return clickedSeconds >= start && clickedSeconds <= start + (segment.duration || 0);
      });
      if (covering) {
        playItem(covering, clickedSeconds - secondsOfDay(covering.start));
        return;
      }

      const closest = (items) =>
        items.reduce(
          (best, item) => {
            const distance = Math.abs(secondsOfDay(item.start) - clickedSeconds);
            return distance < best.distance ? { item, distance } : best;
          },
          { item: null, distance: Infinity }
        );

      const nearestEvent = closest(events);
      if (nearestEvent.item && nearestEvent.distance < DAY_SECONDS * 0.02) {
        playItem(nearestEvent.item, 0);
        return;
      }
      const nearestSegment = closest(segments);
      if (nearestSegment.item) playItem(nearestSegment.item, 0);
    });
  }

  if (player) {
    player.addEventListener("timeupdate", () => {
      const currentId = player.dataset.currentId;
      const current =
        segments.find((segment) => String(segment.id) === currentId) ||
        events.find((eventItem) => String(eventItem.id) === currentId);
      if (!current || !cursor) return;
      cursor.style.left = `${percent(secondsOfDay(current.start) + player.currentTime)}%`;
      cursor.hidden = false;
    });

    player.addEventListener("ended", () => {
      if (player.dataset.currentKind !== "continuous") return;
      const index = segments.findIndex((segment) => String(segment.id) === player.dataset.currentId);
      const next = index >= 0 ? segments[index + 1] : null;
      if (next) playItem(next, 0);
    });
  }

  if (listBody) {
    listCount.textContent = String(events.length);
    events.forEach((eventItem) => {
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
      playButton.textContent = "Abspielen";
      playButton.addEventListener("click", () => playItem(eventItem, 0));
      actions.appendChild(playButton);

      item.appendChild(heading);
      item.appendChild(actions);
      listBody.appendChild(item);
    });
    if (!events.length) {
      const empty = document.createElement("li");
      empty.textContent = "Noch keine Ereignisse";
      listBody.appendChild(empty);
    }
  }

  if (segments.length) playItem(segments[0], 0);
  else if (events.length) playItem(events[0], 0);
})();
