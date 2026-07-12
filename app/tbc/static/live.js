(() => {
  const cards = Array.from(document.querySelectorAll("[data-live-card]"));
  const summary = document.querySelector("[data-live-summary]");
  const refreshButton = document.querySelector("[data-live-refresh]");
  const fullscreenButton = document.querySelector("[data-live-fullscreen]");
  const kioskExitButton = document.querySelector("[data-live-kiosk-exit]");
  const layoutToggleButton = document.querySelector("[data-live-layout-toggle]");
  const layoutForm = document.querySelector("[data-live-layout-form]");
  const rotationToggle = document.querySelector("[data-live-rotation-toggle]");
  const grid = document.querySelector("[data-live-grid]");
  const soloOverlay = document.querySelector("[data-live-solo-overlay]");
  const soloTitle = document.querySelector("[data-live-solo-title]");
  const soloPlayerContainer = document.querySelector("[data-live-solo-player]");
  const soloCloseButton = document.querySelector("[data-live-solo-close]");

  if (!cards.length) {
    if (summary) summary.textContent = "Keine Streams";
    return;
  }

  const byKey = new Map(cards.map((card) => [card.dataset.liveKey, card]));
  const latestItems = new Map();
  let pollTimer = null;
  let soloPlayer = null;
  let soloKey = null;

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

  const destroyPlayer = (container) => {
    if (container._tbcPlayer) {
      container._tbcPlayer.destroy();
      container._tbcPlayer = null;
    }
  };

  const ensurePlaceholder = (container, status) => {
    const current = container.querySelector(".live-placeholder");
    if (current) {
      current.textContent = placeholderText(status);
      return;
    }
    destroyPlayer(container);
    container.innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "live-placeholder";
    placeholder.textContent = placeholderText(status);
    container.append(placeholder);
  };

  const ensureVideo = (container, item) => {
    const current = container.querySelector("video");
    if (current && current.dataset.tbcSrc === item.playlist_url) {
      return;
    }
    destroyPlayer(container);
    container.innerHTML = "";
    const video = document.createElement("video");
    video.className = "live-video";
    container.append(video);
    const cameraId = container.dataset.cameraId;
    const canControl = container.dataset.canControl === "1" && !!item.ptz_supported;
    container._tbcPlayer = new window.TBCPlayer(video, {
      mode: "live",
      src: item.playlist_url,
      autoplay: true,
      muted: true,
      ptz: canControl && cameraId
        ? {
            cameraId,
            channel: Number(container.dataset.controlChannel || 0),
            onError: () => {},
          }
        : null,
    });
  };

  const renderItem = (item) => {
    latestItems.set(item.key, item);
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

  // --- Fullscreen / kiosk mode -------------------------------------------
  const isFullscreen = () => !!document.fullscreenElement;

  const applyKioskState = () => {
    const active = isFullscreen();
    document.body.classList.toggle("live-kiosk", active);
    if (kioskExitButton) kioskExitButton.hidden = !active;
  };

  fullscreenButton?.addEventListener("click", () => {
    if (isFullscreen()) {
      document.exitFullscreen?.();
    } else {
      document.documentElement.requestFullscreen?.().catch(() => {});
    }
  });

  kioskExitButton?.addEventListener("click", () => {
    document.exitFullscreen?.();
  });

  document.addEventListener("fullscreenchange", applyKioskState);

  // --- Solo / focused view -------------------------------------------------
  const closeSolo = () => {
    if (soloPlayer) {
      soloPlayer.destroy();
      soloPlayer = null;
    }
    soloKey = null;
    if (soloPlayerContainer) soloPlayerContainer.innerHTML = "";
    if (soloOverlay) soloOverlay.hidden = true;
  };

  const openSolo = (key) => {
    const item = latestItems.get(key);
    const card = byKey.get(key);
    if (!item || !card || item.status !== "running" || !soloOverlay || !soloPlayerContainer) return;
    closeSolo();
    soloKey = key;
    if (soloTitle) soloTitle.textContent = card.dataset.liveName || item.name || "";
    const video = document.createElement("video");
    video.className = "live-video";
    soloPlayerContainer.appendChild(video);
    const player = card.querySelector("[data-live-player]");
    const cameraId = player?.dataset.cameraId;
    const canControl = player?.dataset.canControl === "1" && !!item.ptz_supported;
    soloPlayer = new window.TBCPlayer(video, {
      mode: "live",
      src: item.playlist_url,
      autoplay: true,
      muted: true,
      ptz: canControl && cameraId
        ? { cameraId, channel: Number(player.dataset.controlChannel || 0), onError: () => {} }
        : null,
    });
    soloOverlay.hidden = false;
  };

  cards.forEach((card) => {
    const key = card.dataset.liveKey;
    const shell = card.querySelector("[data-live-expand]");
    shell?.addEventListener("click", (event) => {
      if (event.target.closest(".tbc-player-bar, .tbc-ptz, button, input, a")) return;
      openSolo(key);
    });
  });

  soloCloseButton?.addEventListener("click", closeSolo);
  soloOverlay?.addEventListener("click", (event) => {
    if (event.target === soloOverlay) closeSolo();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && soloOverlay && !soloOverlay.hidden) closeSolo();
  });

  // --- Admin: per-card size editor -----------------------------------------
  document.querySelectorAll("[data-live-span-editor]").forEach((editor) => {
    const key = editor.dataset.liveKey;
    const card = byKey.get(key);
    const colInput = editor.querySelector("[data-span-col]");
    const rowInput = editor.querySelector("[data-span-row]");
    const colValue = editor.querySelector("[data-span-col-value]");
    const rowValue = editor.querySelector("[data-span-row-value]");

    const preview = () => {
      if (colValue) colValue.textContent = colInput.value;
      if (rowValue) rowValue.textContent = rowInput.value;
      if (card) {
        card.style.gridColumn = `span ${colInput.value}`;
        card.style.gridRow = `span ${rowInput.value}`;
      }
    };

    const save = async () => {
      const columnSpan = Math.max(1, Math.min(4, Number(colInput.value) || 1));
      const rowSpan = Math.max(1, Math.min(4, Number(rowInput.value) || 1));
      try {
        await fetchJson("/api/live/layout/item", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            live_key: key,
            column_span: columnSpan,
            row_span: rowSpan,
            sort_order: Number(card?.dataset.sortOrder || 0),
          }),
        });
      } catch (error) {
        // best effort; the visual change already applied locally
      }
    };

    colInput?.addEventListener("input", preview);
    rowInput?.addEventListener("input", preview);
    colInput?.addEventListener("change", save);
    rowInput?.addEventListener("change", save);
  });

  // --- Admin: drag-and-drop tile reordering ---------------------------------
  let draggedKey = null;

  const persistOrder = () => {
    const ordered = Array.from(grid?.querySelectorAll("[data-live-card]") || []);
    ordered.forEach((card, index) => {
      card.dataset.sortOrder = String(index);
      const key = card.dataset.liveKey;
      const editor = card.querySelector("[data-live-span-editor]");
      const columnSpan = Number(editor?.querySelector("[data-span-col]")?.value || 1);
      const rowSpan = Number(editor?.querySelector("[data-span-row]")?.value || 1);
      fetchJson("/api/live/layout/item", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({live_key: key, column_span: columnSpan, row_span: rowSpan, sort_order: index}),
      }).catch(() => {});
    });
  };

  cards.forEach((card) => {
    const handle = card.querySelector("[data-live-drag-handle]");
    if (!handle) return;
    handle.addEventListener("dragstart", (event) => {
      draggedKey = card.dataset.liveKey;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedKey);
    });
    handle.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      cards.forEach((other) => other.classList.remove("is-drop-target"));
    });
    card.addEventListener("dragover", (event) => {
      if (!draggedKey || draggedKey === card.dataset.liveKey) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      card.classList.add("is-drop-target");
    });
    card.addEventListener("dragleave", () => {
      card.classList.remove("is-drop-target");
    });
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      card.classList.remove("is-drop-target");
      if (!draggedKey || draggedKey === card.dataset.liveKey || !grid) return;
      const draggedCard = byKey.get(draggedKey);
      if (!draggedCard) return;
      const targetRect = card.getBoundingClientRect();
      const insertAfter = event.clientX - targetRect.left > targetRect.width / 2;
      grid.insertBefore(draggedCard, insertAfter ? card.nextSibling : card);
      draggedKey = null;
      persistOrder();
    });
  });

  // --- Admin: layout panel toggle -------------------------------------------
  layoutToggleButton?.addEventListener("click", () => {
    if (!layoutForm) return;
    const nowHidden = !layoutForm.hidden;
    layoutForm.hidden = nowHidden;
    layoutToggleButton.setAttribute("aria-expanded", String(!nowHidden));
  });

  // --- Rotation: cycle through pages of cards when there are more than fit
  // on one screen. Page size is columns x columns (a simple, predictable
  // square page rather than trying to fit exact remaining vertical space,
  // which would need per-card span-aware bin packing).
  let rotationTimer = null;
  let rotationPage = 0;

  const applyRotation = () => {
    window.clearInterval(rotationTimer);
    const columns = Number(grid?.dataset.liveColumns || 3);
    const seconds = Number(grid?.dataset.rotationSeconds || 15);
    const pageSize = Math.max(1, columns * columns);
    const enabled = !!rotationToggle?.checked;
    if (!enabled || cards.length <= pageSize) {
      cards.forEach((card) => {
        card.hidden = false;
      });
      return;
    }
    const pageCount = Math.ceil(cards.length / pageSize);
    const showPage = (page) => {
      cards.forEach((card, index) => {
        card.hidden = Math.floor(index / pageSize) !== page;
      });
    };
    rotationPage = rotationPage % pageCount;
    showPage(rotationPage);
    rotationTimer = window.setInterval(() => {
      rotationPage = (rotationPage + 1) % pageCount;
      showPage(rotationPage);
    }, Math.max(5, seconds) * 1000);
  };

  rotationToggle?.addEventListener("change", applyRotation);
  applyRotation();

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
