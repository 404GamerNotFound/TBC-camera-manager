(() => {
  const t = (key, parameters) => window.tbcI18n.t(key, parameters);
  const state = document.querySelector("[data-health-refresh-state]");
  const refreshButton = document.querySelector("[data-health-refresh]");
  const statusBody = document.querySelector("[data-health-status-body]");
  const eventsBody = document.querySelector("[data-health-events-body]");
  const preferences = document.querySelector("[data-time-format]")?.dataset || {};
  if (!state || !statusBody || !eventsBody) return;

  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value || "";
  };

  const setBar = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.style.width = `${Number(value || 0)}%`;
  };

  const cell = (value) => {
    const td = document.createElement("td");
    td.textContent = value == null || value === "" ? "-" : String(value);
    return td;
  };

  const timestamp = (value) => {
    if (!value) return "";
    const raw = String(value);
    // SQLite CURRENT_TIMESTAMP is UTC but does not include an offset.
    const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(raw) ? raw : `${raw.replace(" ", "T")}Z`;
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) return raw;
    const zone = preferences.timezone || "Europe/Berlin";
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(parsed).reduce((result, part) => ({...result, [part.type]: part.value}), {});
    const date = preferences.dateFormat === "iso"
      ? `${parts.year}-${parts.month}-${parts.day}`
      : preferences.dateFormat === "us"
        ? `${parts.month}/${parts.day}/${parts.year}`
        : `${parts.day}.${parts.month}.${parts.year}`;
    const time = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hour: "numeric",
      minute: "2-digit",
      ...(preferences.showSeconds === "true" ? {second: "2-digit"} : {}),
      hour12: preferences.timeFormat === "12h",
    }).format(parsed);
    return `${date} ${time}`;
  };

  const statusPill = (value) => {
    const span = document.createElement("span");
    span.className = `status-pill status-${value || "unknown"}`;
    const status = value || "unknown";
    const key = `status.${status}`;
    const translated = t(key);
    span.textContent = translated === key ? status : translated;
    return span;
  };

  const renderStatus = (items) => {
    statusBody.innerHTML = "";
    items.forEach((item) => {
      const tr = document.createElement("tr");
      tr.append(cell(item.component_type), cell(item.component_id));
      const statusCell = document.createElement("td");
      statusCell.append(statusPill(item.status));
      tr.append(statusCell, cell(item.message), cell(timestamp(item.checked_at)));
      statusBody.append(tr);
    });
  };

  const renderEvents = (events) => {
    eventsBody.innerHTML = "";
    events.forEach((event) => {
      const tr = document.createElement("tr");
      tr.append(
        cell(timestamp(event.created_at)),
        cell(`${event.component_type || ""} ${event.component_id || ""}`.trim()),
        cell(event.previous_status),
      );
      const statusCell = document.createElement("td");
      statusCell.append(statusPill(event.status));
      tr.append(statusCell, cell(event.message));
      eventsBody.append(tr);
    });
  };

  const renderUsage = (usage) => {
    if (!usage) return;
    setText("[data-health-cpu-label]", usage.cpu_label);
    setBar("[data-health-cpu-bar]", usage.cpu_percent);
    setText("[data-health-cpu-detail]", t("health.cores", {count: usage.cpu_cores, load: usage.load_label}));
    setText("[data-health-memory-label]", usage.memory_label);
    setBar("[data-health-memory-bar]", usage.memory_percent);
    setText("[data-health-memory-detail]", usage.memory_detail);
  };

  const refresh = async () => {
    state.className = "status-pill status-warning";
    state.textContent = t("health.check_running");
    const response = await fetch(tbcUrl("/api/health/refresh"), {
      method: "POST",
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || t("health.check_failed"));
    }
    renderUsage(data.system_usage);
    renderStatus(data.items || []);
    renderEvents(data.events || []);
    state.className = "status-pill status-active";
    state.textContent = t("health.updated");
  };

  refreshButton?.addEventListener("click", () => {
    refresh().catch((error) => {
      state.className = "status-pill status-error";
      state.textContent = error.message;
    });
  });

  refresh().catch((error) => {
    state.className = "status-pill status-error";
    state.textContent = error.message;
  });
})();
