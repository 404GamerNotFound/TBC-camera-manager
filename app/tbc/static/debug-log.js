(function () {
  const t = (key, parameters) => window.tbcI18n.t(key, parameters);
  const drawer = document.querySelector("[data-debug-drawer]");
  if (!drawer) return;

  const list = drawer.querySelector("[data-debug-list]");
  const meta = drawer.querySelector("[data-debug-meta]");
  const toggles = document.querySelectorAll("[data-debug-toggle]");
  const closeButtons = drawer.querySelectorAll("[data-debug-close]");
  let timer = null;

  function levelClass(level) {
    if (level === "error" || level === "critical") return "debug-line-error";
    if (level === "warning") return "debug-line-warning";
    return "debug-line-info";
  }

  function render(entries) {
    list.innerHTML = "";
    if (!entries.length) {
      const empty = document.createElement("li");
      empty.className = "debug-line debug-line-info";
      empty.textContent = t("debug.empty");
      list.appendChild(empty);
      return;
    }
    for (const entry of entries.slice().reverse()) {
      const item = document.createElement("li");
      item.className = "debug-line " + levelClass(entry.level);

      const head = document.createElement("span");
      head.className = "debug-line-head";
      head.textContent = `${entry.created_at} · ${entry.level.toUpperCase()} · ${entry.logger}`;

      const body = document.createElement("code");
      body.textContent = entry.message;

      item.appendChild(head);
      item.appendChild(body);
      list.appendChild(item);
    }
  }

  async function refresh() {
    try {
      const response = await fetch("/api/debug-log?limit=250", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      render(payload.entries || []);
      if (meta) meta.textContent = t("debug.entry_count", {count: payload.entries.length});
    } catch (error) {
      render([{ created_at: new Date().toISOString(), level: "error", logger: "debug-log", message: String(error) }]);
    }
  }

  function openDrawer() {
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    refresh();
    if (!timer) timer = window.setInterval(refresh, 5000);
  }

  function closeDrawer() {
    drawer.setAttribute("aria-hidden", "true");
    drawer.hidden = true;
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  toggles.forEach((button) => button.addEventListener("click", openDrawer));
  closeButtons.forEach((button) => button.addEventListener("click", closeDrawer));
  drawer.querySelector("[data-debug-refresh]")?.addEventListener("click", refresh);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.hidden) closeDrawer();
  });
})();
