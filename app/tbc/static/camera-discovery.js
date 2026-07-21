(() => {
  "use strict";

  const button = document.querySelector("[data-discover-button]");
  const results = document.querySelector("[data-discover-results]");
  const statusLine = document.querySelector("[data-discover-status]");
  if (!button || !results || !statusLine) return;

  const t = (key, params) => (window.tbcI18n ? window.tbcI18n.t(key, params) : key);

  const applyDevice = (device) => {
    const form = document.querySelector("[data-plugin-selector-form]");
    if (!form) return;
    const hostInput = form.querySelector('input[name="host"]');
    const portInput = form.querySelector('input[name="onvif_port"]');
    const nameInput = form.querySelector('input[name="name"]');
    if (hostInput) hostInput.value = device.host;
    if (portInput) portInput.value = device.onvif_port;
    if (nameInput && !nameInput.value.trim()) nameInput.value = device.name || device.host;
    form.scrollIntoView({behavior: "smooth", block: "start"});
    if (nameInput) nameInput.focus();
  };

  button.addEventListener("click", async () => {
    button.disabled = true;
    results.textContent = "";
    statusLine.hidden = false;
    statusLine.textContent = t("camera_form.discover_scanning");
    try {
      const response = await fetch(tbcUrl("/cameras/discover"), {
        credentials: "same-origin",
        headers: {Accept: "application/json"},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.error || response.statusText);
      if (!Array.isArray(data.devices) || !data.devices.length) {
        statusLine.textContent = t("camera_form.discover_none");
        return;
      }
      statusLine.hidden = true;
      data.devices.forEach((device) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "secondary-button";
        const details = [`${device.host}:${device.onvif_port}`];
        if (device.hardware) details.push(device.hardware);
        item.textContent = `${device.name || device.host} · ${details.join(" · ")}`;
        item.addEventListener("click", () => applyDevice(device));
        results.appendChild(item);
      });
    } catch (error) {
      statusLine.hidden = false;
      statusLine.textContent = t("camera_form.discover_failed", {error: error.message});
    } finally {
      button.disabled = false;
    }
  });
})();
