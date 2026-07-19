(() => {
  const t = (key, parameters) => window.tbcI18n.t(key, parameters);
  const root = document.querySelector("[data-sd-content]");
  const form = document.querySelector("[data-sd-filter-form]");
  const player = document.querySelector("[data-sd-preview-player]");
  if (player && window.TBCPlayer) {
    new window.TBCPlayer(player, { mode: "vod" });
  }
  const previewPanel = document.querySelector("[data-sd-preview-panel]");
  const title = document.querySelector("[data-sd-preview-title]");
  const meta = document.querySelector("[data-sd-preview-meta]");
  const loading = document.querySelector("[data-sd-loading]");
  const empty = document.querySelector("[data-sd-empty]");
  const errorBox = document.querySelector("[data-sd-error]");
  const tableSection = document.querySelector("[data-sd-table-section]");
  const tableBody = document.querySelector("[data-sd-recordings-body]");
  const count = document.querySelector("[data-sd-count]");

  if (!root || !form || !tableBody) return;

  const textCell = (value, className = "") => {
    const td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = value == null || value === "" ? "-" : String(value);
    return td;
  };

  const formatSize = (bytes) => {
    const value = Number(bytes || 0);
    if (!value) return "0 MB";
    return `${(value / 1048576).toFixed(1)} MB`;
  };

  const setError = (message) => {
    if (!errorBox) return;
    errorBox.textContent = message || "";
    errorBox.hidden = !message;
  };

  const stopCurrent = () => {
    if (!player) return;
    player.pause();
    player.removeAttribute("src");
    player.load();
  };

  const playRecording = (recording) => {
    if (!player || !previewPanel) return;
    stopCurrent();
    player.src = recording.media_url;
    if (title) title.textContent = recording.file_name || t("sd_card.preview");
    if (meta) meta.textContent = `${recording.start_time || ""} · ${recording.duration_seconds || 0}s`;
    previewPanel.hidden = false;
    player.load();
    player.play().catch(() => {});
    previewPanel.scrollIntoView({behavior: "smooth", block: "center"});
  };

  const renderRows = (recordings) => {
    tableBody.innerHTML = "";
    recordings.forEach((recording) => {
      const tr = document.createElement("tr");
      tr.append(
        textCell(recording.start_time),
        textCell(recording.end_time),
        textCell(`${recording.duration_seconds || 0}s`),
        textCell(recording.trigger_label),
        textCell(recording.file_name, "file-cell"),
        textCell(formatSize(recording.size_bytes)),
      );

      const actionCell = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "button-row";

      const preview = document.createElement("button");
      preview.className = "secondary-button";
      preview.type = "button";
      preview.textContent = t("sd_card.preview");
      preview.addEventListener("click", () => playRecording(recording));

      const download = document.createElement("a");
      download.className = "secondary-button";
      download.href = recording.download_url;
      download.textContent = t("common.download");

      actions.append(preview, download);
      actionCell.append(actions);
      tr.append(actionCell);
      tableBody.append(tr);
    });
  };

  const paramsFromForm = () => {
    const data = new FormData(form);
    const params = new URLSearchParams();
    ["camera_id", "channel", "stream", "date_from", "date_to"].forEach((key) => {
      const value = data.get(key);
      if (value != null && value !== "") params.set(key, String(value));
    });
    return params;
  };

  const loadRecordings = async () => {
    if (root.dataset.sdCanLoad !== "1") {
      if (loading) loading.hidden = true;
      return;
    }
    stopCurrent();
    if (previewPanel) previewPanel.hidden = true;
    if (tableSection) tableSection.hidden = true;
    if (empty) empty.hidden = true;
    if (loading) loading.hidden = false;
    setError("");

    const response = await fetch(tbcUrl(`/api/sd-card/recordings?${paramsFromForm().toString()}`), {
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("sd_card.load_failed"));
    }

    const recordings = data.recordings || [];
    renderRows(recordings);
    if (count) count.textContent = String(recordings.length);
    if (tableSection) tableSection.hidden = recordings.length === 0;
    if (empty) empty.hidden = recordings.length !== 0;
  };

  loadRecordings()
    .catch((error) => setError(error.message))
    .finally(() => {
      if (loading) loading.hidden = true;
    });
})();
