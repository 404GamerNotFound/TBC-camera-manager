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
  const inputs = {
    onvifPort: form.querySelector('input[name="onvif_port"]'),
    httpPort: form.querySelector('input[name="http_port"]'),
    rtspPort: form.querySelector('input[name="rtsp_port"]'),
    host: form.querySelector('input[name="host"]'),
    username: form.querySelector('input[name="username"]'),
    password: form.querySelector('input[name="password"]'),
    manualStream: form.querySelector('input[name="manual_stream_uri"]'),
  };

  window.tbcInitPluginAvailabilityToggle({
    select: moduleSelect,
    configurableControls,
    installLink,
    unavailableNote,
    unavailableKey: "plugin.camera_not_installed",
    onApply: (option, installed, isUserChange, translate) => {
      const manualStreamField = inputs.manualStream?.closest("label");
      if (!installed) {
        connectionFields.forEach((field) => { field.hidden = false; });
        if (manualStreamField) manualStreamField.hidden = false;
        return;
      }
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
      if (isUserChange) {
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
    },
  });
})();
