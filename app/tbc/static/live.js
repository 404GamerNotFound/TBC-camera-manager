(() => {
  const cards = Array.from(document.querySelectorAll("[data-live-card]"));
  const summary = document.querySelector("[data-live-summary]");
  const refreshButton = document.querySelector("[data-live-refresh]");
  if (!cards.length) {
    if (summary) summary.textContent = "Keine Streams";
    return;
  }

  const byKey = new Map(cards.map((card) => [card.dataset.liveKey, card]));
  let pollTimer = null;

  const statusClass = (status) => {
    if (status === "running") return "status-active";
    if (status === "starting") return "status-warning";
    if (status === "failed" || status === "missing") return "status-error";
    return "status-idle";
  };

  const setSummary = (items) => {
    if (!summary) return;
    const running = items.filter((item) => item.status === "running").length;
    const starting = items.filter((item) => item.status === "starting").length;
    const failed = items.filter((item) => item.status === "failed" || item.status === "missing").length;
    summary.className = `status-pill ${failed ? "status-error" : starting ? "status-warning" : "status-active"}`;
    summary.textContent = `${running}/${items.length} live${starting ? ` · ${starting} starten` : ""}${failed ? ` · ${failed} Fehler` : ""}`;
  };

  const placeholderText = (status) => {
    if (status === "starting") return "Stream startet";
    if (status === "failed") return "Stream konnte nicht starten";
    if (status === "missing") return "Kein Stream bekannt";
    if (status === "stopped") return "Stream gestoppt";
    return "Warte auf Stream";
  };

  const ensurePlaceholder = (container, status) => {
    const current = container.querySelector(".live-placeholder");
    if (current) {
      current.textContent = placeholderText(status);
      return;
    }
    container.innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "live-placeholder";
    placeholder.textContent = placeholderText(status);
    container.append(placeholder);
  };

  const ensureVideo = (container, item) => {
    const current = container.querySelector("video");
    if (current && current.getAttribute("src") === item.playlist_url) {
      return;
    }
    container.innerHTML = "";
    const video = document.createElement("video");
    video.className = "live-video";
    video.controls = true;
    video.muted = true;
    video.playsInline = true;
    video.autoplay = true;
    video.src = item.playlist_url;
    container.append(video);
    video.play().catch(() => {});
  };

  const renderItem = (item) => {
    const card = byKey.get(item.key);
    if (!card) return;
    const pill = card.querySelector("[data-live-status]");
    const message = card.querySelector("[data-live-message]");
    const player = card.querySelector("[data-live-player]");
    if (pill) {
      pill.className = `status-pill ${statusClass(item.status)}`;
      pill.textContent = item.status;
    }
    if (message) {
      message.textContent = item.message || "";
      message.hidden = !item.message;
    }
    if (player) {
      if (item.status === "running") {
        ensureVideo(player, item);
      } else {
        ensurePlaceholder(player, item.status);
      }
    }
  };

  const renderItems = (items) => {
    items.forEach(renderItem);
    setSummary(items);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "Live-API konnte nicht geladen werden");
    }
    return data;
  };

  const refresh = async () => {
    const data = await fetchJson("/api/live/status");
    renderItems(data.items || []);
  };

  const startAll = async () => {
    if (summary) summary.textContent = "Streams werden gestartet";
    const data = await fetchJson("/api/live/start-all", {method: "POST"});
    renderItems(data.items || []);
  };

  const schedulePolling = () => {
    window.clearInterval(pollTimer);
    pollTimer = window.setInterval(() => {
      refresh().catch((error) => {
        if (summary) {
          summary.className = "status-pill status-error";
          summary.textContent = error.message;
        }
      });
    }, 3000);
  };

  cards.forEach((card) => {
    const key = card.dataset.liveKey;
    card.querySelector("[data-live-retry]")?.addEventListener("click", async () => {
      await fetchJson(`/api/live/${encodeURIComponent(key)}/start`, {method: "POST"});
      await refresh();
    });
    card.querySelector("[data-live-stop]")?.addEventListener("click", async () => {
      await fetchJson(`/api/live/${encodeURIComponent(key)}/stop`, {method: "POST"});
      await refresh();
    });
  });

  refreshButton?.addEventListener("click", () => {
    refresh().catch((error) => {
      if (summary) {
        summary.className = "status-pill status-error";
        summary.textContent = error.message;
      }
    });
  });

  startAll()
    .catch((error) => {
      if (summary) {
        summary.className = "status-pill status-error";
        summary.textContent = error.message;
      }
    })
    .finally(schedulePolling);
})();
