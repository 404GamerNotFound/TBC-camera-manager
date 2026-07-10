(() => {
  const state = document.querySelector("[data-health-refresh-state]");
  const refreshButton = document.querySelector("[data-health-refresh]");
  const statusBody = document.querySelector("[data-health-status-body]");
  const eventsBody = document.querySelector("[data-health-events-body]");
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

  const statusPill = (value) => {
    const span = document.createElement("span");
    span.className = `status-pill status-${value || "unknown"}`;
    span.textContent = value || "unknown";
    return span;
  };

  const renderStatus = (items) => {
    statusBody.innerHTML = "";
    items.forEach((item) => {
      const tr = document.createElement("tr");
      tr.append(cell(item.component_type), cell(item.component_id));
      const statusCell = document.createElement("td");
      statusCell.append(statusPill(item.status));
      tr.append(statusCell, cell(item.message), cell(item.checked_at));
      statusBody.append(tr);
    });
  };

  const renderEvents = (events) => {
    eventsBody.innerHTML = "";
    events.forEach((event) => {
      const tr = document.createElement("tr");
      tr.append(
        cell(event.created_at),
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
    setText("[data-health-cpu-detail]", `${usage.cpu_cores} Kerne · ${usage.load_label}`);
    setText("[data-health-memory-label]", usage.memory_label);
    setBar("[data-health-memory-bar]", usage.memory_percent);
    setText("[data-health-memory-detail]", usage.memory_detail);
  };

  const refresh = async () => {
    state.className = "status-pill status-warning";
    state.textContent = "Prüfung läuft";
    const response = await fetch("/api/health/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "Health-Check konnte nicht geladen werden");
    }
    renderUsage(data.system_usage);
    renderStatus(data.items || []);
    renderEvents(data.events || []);
    state.className = "status-pill status-active";
    state.textContent = "Aktualisiert";
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
