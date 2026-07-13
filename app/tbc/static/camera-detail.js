(() => {
  const tabs = Array.from(document.querySelectorAll("[data-detail-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-detail-panel]"));
  if (!tabs.length || !panels.length) return;

  const available = new Set(tabs.map((tab) => tab.dataset.detailTab));

  function activate(name, updateHash = true) {
    const selected = available.has(name) ? name : "overview";
    tabs.forEach((tab) => {
      const active = tab.dataset.detailTab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.detailPanel !== selected;
    });
    if (updateHash) history.replaceState(null, "", `#${selected}`);
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activate(tab.dataset.detailTab));
    tab.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(index + offset + tabs.length) % tabs.length];
      activate(next.dataset.detailTab);
      next.focus();
    });
  });

  activate(location.hash.slice(1), false);

  const triggerFieldset = document.querySelector("[data-trigger-fieldset]");
  if (triggerFieldset) {
    triggerFieldset.querySelectorAll("[data-trigger-selection]").forEach((button) => {
      button.addEventListener("click", () => {
        const checked = button.dataset.triggerSelection === "all";
        triggerFieldset.querySelectorAll('input[name="trigger_keys"]').forEach((input) => {
          input.checked = checked;
        });
      });
    });
  }
})();

(() => {
  const panel = document.querySelector("[data-control-panel]");
  if (!panel) return;

  const channelSelect = panel.querySelector("[data-control-channel-select]");
  if (channelSelect) {
    channelSelect.addEventListener("change", () => channelSelect.form.submit());
  }

  const toastStack = panel.querySelector("[data-toast-stack]");

  function showToast(message, ok) {
    if (!toastStack) return;
    const toast = document.createElement("div");
    toast.className = `tbc-toast flash-${ok ? "success" : "error"}`;
    toast.setAttribute("role", "status");
    toast.textContent = message;
    toastStack.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
  }

  const livePlayerContainer = panel.querySelector("[data-control-live-player]");
  let livePreviewStarted = false;

  function setLivePlaceholder(text) {
    livePlayerContainer.innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "live-placeholder";
    placeholder.textContent = text;
    livePlayerContainer.append(placeholder);
  }

  function showLiveVideo(playlistUrl) {
    if (!window.TBCPlayer) return;
    livePlayerContainer.innerHTML = "";
    const video = document.createElement("video");
    video.className = "live-video";
    livePlayerContainer.append(video);
    const cameraId = livePlayerContainer.dataset.cameraId;
    const channel = Number(livePlayerContainer.dataset.controlChannel || 0);
    const ptzSupported = livePlayerContainer.dataset.ptzSupported === "1";
    new window.TBCPlayer(video, {
      mode: "live",
      src: playlistUrl,
      autoplay: true,
      muted: true,
      ptz: ptzSupported && cameraId ? { cameraId, channel, onError: (message) => showToast(message, false) } : null,
    });
  }

  async function pollLivePreview(liveKey, attempt = 0) {
    try {
      const response = await fetch("/api/live/status", { credentials: "same-origin" });
      const data = await response.json().catch(() => ({ items: [] }));
      const item = (data.items || []).find((entry) => entry.key === liveKey);
      if (item && item.status === "running") {
        showLiveVideo(item.playlist_url);
        return;
      }
      if (item && (item.status === "failed" || item.status === "missing")) {
        setLivePlaceholder(item.message || "Stream nicht verfügbar");
        return;
      }
    } catch (error) {
      // ignored, retried below
    }
    if (attempt < 10) {
      setTimeout(() => pollLivePreview(liveKey, attempt + 1), 1500);
    } else {
      setLivePlaceholder("Stream konnte nicht gestartet werden");
    }
  }

  async function startLivePreview() {
    if (livePreviewStarted || !livePlayerContainer) return;
    livePreviewStarted = true;
    const liveKey = livePlayerContainer.dataset.liveKey;
    setLivePlaceholder("Stream wird gestartet…");
    try {
      const response = await fetch(`/api/live/${encodeURIComponent(liveKey)}/start`, {
        method: "POST",
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => null);
      if (data && data.item && data.item.status === "running") {
        showLiveVideo(data.item.playlist_url);
        return;
      }
    } catch (error) {
      // fall through to polling below
    }
    pollLivePreview(liveKey);
  }

  if (livePlayerContainer) {
    const controlTabButton = document.querySelector('[data-detail-tab="control"]');
    controlTabButton?.addEventListener("click", startLivePreview, { once: true });
    if (location.hash.slice(1) === "control") startLivePreview();
  }

  panel.querySelectorAll("[data-control-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector('button[type="submit"]');
      const originalLabel = submitButton ? submitButton.textContent : null;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "…";
      }
      const pillTarget = form.dataset.controlPillTarget;
      const pillValue = form.dataset.controlPillValue;
      const pill = pillTarget ? panel.querySelector(`[data-control-pill="${pillTarget}"]`) : null;
      const previousPillText = pill ? pill.textContent : null;
      const previousPillClass = pill ? pill.className : null;
      if (pill && pillValue) {
        pill.textContent = pillValue;
        pill.className = `status-pill ${pillValue === "aus" ? "status-idle" : "status-active"}`;
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
        });
        const data = await response.json().catch(() => null);
        const ok = response.ok && data && data.ok;
        showToast((data && data.message) || (ok ? "Befehl wurde gesendet" : "Befehl fehlgeschlagen"), ok);
        if (!ok && pill && previousPillText !== null) {
          pill.textContent = previousPillText;
          pill.className = previousPillClass;
        }
      } catch (error) {
        showToast("Befehl fehlgeschlagen: Netzwerkfehler", false);
        if (pill && previousPillText !== null) {
          pill.textContent = previousPillText;
          pill.className = previousPillClass;
        }
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.textContent = originalLabel;
        }
      }
    });
  });
})();

(() => {
  const section = document.querySelector("[data-firmware-section]");
  if (!section) return;

  const cameraId = section.dataset.cameraId;
  const channel = Number(section.dataset.controlChannel || 0);
  const currentEl = section.querySelector("[data-firmware-current]");
  const resultEl = section.querySelector("[data-firmware-result]");
  const checkButton = section.querySelector("[data-firmware-check]");
  const updateButton = section.querySelector("[data-firmware-update]");
  const progressWrap = section.querySelector("[data-firmware-progress]");
  const progressFill = section.querySelector("[data-firmware-progress-fill]");

  let pollTimer = null;

  function showResult(message, kind) {
    if (!resultEl) return;
    resultEl.textContent = message;
    resultEl.className = `diagnostic-note diagnostic-${kind}`;
    resultEl.hidden = !message;
  }

  function setProgress(percent) {
    if (!progressWrap || !progressFill) return;
    const clamped = Math.max(0, Math.min(100, percent));
    progressWrap.hidden = clamped <= 0 || clamped >= 100;
    progressFill.style.width = `${clamped}%`;
  }

  async function postJson(path) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({channel: String(channel)}),
    });
    const data = await response.json().catch(() => null);
    return {ok: response.ok, data};
  }

  async function getJson(path) {
    const response = await fetch(`${path}?channel=${encodeURIComponent(channel)}`, {credentials: "same-origin"});
    const data = await response.json().catch(() => null);
    return {ok: response.ok, data};
  }

  function stopPolling() {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }

  async function pollStatus() {
    const {ok, data} = await getJson(`/cameras/${cameraId}/firmware/status`);
    if (!ok || !data) return;
    setProgress(data.progress || 0);
    if (data.status === "updating") {
      showResult(data.message || "Update läuft…", "warning");
      return;
    }
    stopPolling();
    if (data.status === "done") {
      showResult("Firmware wurde aktualisiert. Die Kamera startet neu und ist kurz nicht erreichbar.", "ok");
      if (updateButton) updateButton.hidden = true;
      if (checkButton) checkButton.disabled = false;
    } else if (data.status === "failed") {
      showResult(`Update fehlgeschlagen: ${data.message || "unbekannter Fehler"}`, "error");
      if (checkButton) checkButton.disabled = false;
      if (updateButton) updateButton.disabled = false;
    }
  }

  checkButton?.addEventListener("click", async () => {
    checkButton.disabled = true;
    if (updateButton) updateButton.hidden = true;
    showResult("Prüfe auf Updates…", "warning");
    const {ok, data} = await postJson(`/cameras/${cameraId}/firmware/check`);
    checkButton.disabled = false;
    if (!ok || !data || !data.ok) {
      showResult((data && data.message) || "Prüfung fehlgeschlagen", "error");
      return;
    }
    if (currentEl && data.current) currentEl.textContent = data.current;
    if (data.update_available) {
      showResult(`Neue Firmware verfügbar: ${data.latest}${data.release_notes ? " – " + data.release_notes : ""}`, "warning");
      if (updateButton) updateButton.hidden = false;
    } else {
      showResult("Firmware ist aktuell.", "ok");
    }
  });

  updateButton?.addEventListener("click", async () => {
    const confirmationText =
      "Firmware jetzt aktualisieren? Die Kamera ist während des Updates nicht erreichbar und startet danach neu. " +
      "Der Vorgang kann mehrere Minuten dauern und sollte nicht unterbrochen werden.";
    const confirmed = window.confirm(window.tbcI18n ? window.tbcI18n.t(confirmationText) : confirmationText);
    if (!confirmed) return;
    updateButton.disabled = true;
    checkButton.disabled = true;
    showResult("Update wird gestartet…", "warning");
    setProgress(1);
    const {ok, data} = await postJson(`/cameras/${cameraId}/firmware/update`);
    if (!ok || !data || !data.ok) {
      showResult((data && data.message) || "Update konnte nicht gestartet werden", "error");
      updateButton.disabled = false;
      checkButton.disabled = false;
      setProgress(0);
      return;
    }
    updateButton.hidden = true;
    stopPolling();
    pollTimer = window.setInterval(pollStatus, 2000);
    pollStatus();
  });
})();
