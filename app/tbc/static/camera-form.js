(() => {
  const moduleSelect = document.querySelector('select[name="module_key"]');
  if (!moduleSelect) return;

  const inputs = {
    onvifPort: document.querySelector('input[name="onvif_port"]'),
    httpPort: document.querySelector('input[name="http_port"]'),
    rtspPort: document.querySelector('input[name="rtsp_port"]'),
  };

  moduleSelect.addEventListener("change", () => {
    const option = moduleSelect.selectedOptions[0];
    if (!option) return;
    if (inputs.onvifPort) inputs.onvifPort.value = option.dataset.onvifPort || "8000";
    if (inputs.httpPort) inputs.httpPort.value = option.dataset.httpPort || "80";
    if (inputs.rtspPort) inputs.rtspPort.value = option.dataset.rtspPort || "554";
  });
})();
