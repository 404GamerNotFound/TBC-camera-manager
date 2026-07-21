(() => {
  const form = document.querySelector("[data-plugin-selector-form]");
  const moduleSelect = form?.querySelector('select[name="module_key"]');
  if (!form || !moduleSelect) return;

  const installLink = form.querySelector("[data-plugin-install-link]");
  const unavailableNote = form.querySelector("[data-plugin-unavailable]");
  const configurableControls = form.querySelectorAll("input, textarea, button[type='submit']");
  const connectionFields = form.querySelectorAll(
    ".host-field, .onvif-field, .http-field, .rtsp-field, .credential-field",
  );
  const hostFieldLabel = form.querySelector("[data-host-field-label]");
  const translate = (key, parameters = {}) => window.tbcI18n?.t(key, parameters) || key;
  const inputs = {
    onvifPort: form.querySelector('input[name="onvif_port"]'),
    httpPort: form.querySelector('input[name="http_port"]'),
    rtspPort: form.querySelector('input[name="rtsp_port"]'),
    host: form.querySelector('input[name="host"]'),
    username: form.querySelector('input[name="username"]'),
    password: form.querySelector('input[name="password"]'),
    manualStream: form.querySelector('input[name="manual_stream_uri"]'),
  };

  const relabelUninstalledOptions = () => {
    moduleSelect.querySelectorAll("option[data-installed='false']").forEach((option) => {
      const description = option.dataset.description
        ? ` · ${translate(option.dataset.description)}`
        : "";
      option.textContent = translate("plugin.option_not_installed", {
        label: `${option.dataset.label || option.value}${description}`,
      });
    });
  };
  relabelUninstalledOptions();

  const applyModule = (setPorts) => {
    const option = moduleSelect.selectedOptions[0];
    if (!option) return;

    const installed = option.dataset.installed !== "false";
    const manualStreamField = inputs.manualStream?.closest("label");
    form.classList.toggle("is-plugin-unavailable", !installed);
    configurableControls.forEach((control) => { control.disabled = !installed; });
    if (installLink) installLink.href = option.dataset.installUrl || "/plugin-sources";

    if (!installed) {
      connectionFields.forEach((field) => { field.hidden = false; });
      if (manualStreamField) manualStreamField.hidden = false;
      if (unavailableNote) {
        unavailableNote.textContent = translate("plugin.camera_not_installed", {
          label: option.dataset.label || option.value,
        });
        unavailableNote.hidden = false;
      }
      return;
    }

    if (unavailableNote) unavailableNote.hidden = true;
    if (hostFieldLabel) {
      const customLabel = option.dataset.identifierLabel || "";
      if (customLabel) {
        hostFieldLabel.removeAttribute("data-i18n");
        hostFieldLabel.textContent = customLabel;
      } else {
        hostFieldLabel.setAttribute("data-i18n", "camera.host_ip");
        hostFieldLabel.textContent = translate("camera.host_ip");
      }
    }
    if (setPorts) {
      if (inputs.onvifPort) inputs.onvifPort.value = option.dataset.onvifPort || "8000";
      if (inputs.httpPort) inputs.httpPort.value = option.dataset.httpPort || "80";
      if (inputs.rtspPort) inputs.rtspPort.value = option.dataset.rtspPort || "554";
    }
    const supportsManual = option.dataset.supportsManualStream === "true";
    const requiresManual = option.dataset.requiresManualStream === "true";
    const requiresCredentials = option.dataset.requiresCredentials === "true";
    if (manualStreamField) manualStreamField.hidden = !supportsManual;
    connectionFields.forEach((field) => { field.hidden = requiresManual; });
    if (inputs.manualStream) inputs.manualStream.required = requiresManual;
    if (inputs.username) inputs.username.required = requiresCredentials;
    if (inputs.password) inputs.password.required = requiresCredentials;
    if (inputs.host) inputs.host.required = !requiresManual;
  };

  moduleSelect.addEventListener("change", () => applyModule(true));
  applyModule(false);

  // translate() silently falls back to the raw key if this script runs
  // before i18n.js's own locale fetch resolves (see the comment next to
  // `tbc:i18n-ready` in i18n.js) - redo the translated bits once it's ready
  // instead of leaving keys like "plugin.option_not_installed" on screen. No
  // need to check readiness first: if strings were already loaded by now,
  // the calls above already rendered correctly and this just fires once
  // more harmlessly; if not, this is exactly the re-render that fixes it.
  document.addEventListener(
    "tbc:i18n-ready",
    () => {
      relabelUninstalledOptions();
      applyModule(false);
    },
    { once: true },
  );
})();
