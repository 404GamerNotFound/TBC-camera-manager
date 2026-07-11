(() => {
  const moduleSelect = document.querySelector('select[name="module_key"]');
  if (!moduleSelect) return;

  const inputs = {
    onvifPort: document.querySelector('input[name="onvif_port"]'),
    httpPort: document.querySelector('input[name="http_port"]'),
    rtspPort: document.querySelector('input[name="rtsp_port"]'),
    host: document.querySelector('input[name="host"]'),
    username: document.querySelector('input[name="username"]'),
    password: document.querySelector('input[name="password"]'),
    manualStream: document.querySelector('input[name="manual_stream_uri"]'),
  };

  const applyModule = (setPorts) => {
    const option = moduleSelect.selectedOptions[0];
    if (!option) return;
    if (setPorts) {
      if (inputs.onvifPort) inputs.onvifPort.value = option.dataset.onvifPort || "8000";
      if (inputs.httpPort) inputs.httpPort.value = option.dataset.httpPort || "80";
      if (inputs.rtspPort) inputs.rtspPort.value = option.dataset.rtspPort || "554";
    }
    const supportsManual = option.dataset.supportsManualStream === "true";
    const requiresManual = option.dataset.requiresManualStream === "true";
    const requiresCredentials = option.dataset.requiresCredentials === "true";
    const field = inputs.manualStream?.closest("label");
    if (field) field.hidden = !supportsManual;
    document.querySelectorAll(".host-field, .onvif-field, .http-field, .rtsp-field, .credential-field")
      .forEach((connectionField) => { connectionField.hidden = requiresManual; });
    if (inputs.manualStream) inputs.manualStream.required = requiresManual;
    if (inputs.username) inputs.username.required = requiresCredentials;
    if (inputs.password) inputs.password.required = requiresCredentials;
    if (inputs.host) inputs.host.required = !requiresManual;
  };

  moduleSelect.addEventListener("change", () => applyModule(true));
  applyModule(false);
})();
