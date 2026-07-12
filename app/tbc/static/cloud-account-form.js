(() => {
  const providerSelect = document.querySelector("[data-cloud-account-provider]");
  if (!providerSelect) return;

  const hostField = document.querySelector(".cloud-host-field");
  const portInput = document.querySelector('input[name="port"]');
  const identifierLabel = document.querySelector("[data-cloud-account-identifier-label]");
  const secretLabel = document.querySelector("[data-cloud-account-secret-label]");
  const hostInput = document.querySelector('input[name="host"]');

  const applyProvider = () => {
    const option = providerSelect.selectedOptions[0];
    if (!option) return;
    const requiresHost = option.dataset.requiresHost === "true";
    if (hostField) hostField.hidden = !requiresHost;
    if (hostInput) hostInput.required = requiresHost;
    if (portInput) portInput.placeholder = option.dataset.defaultPort || "443";
    if (identifierLabel) identifierLabel.textContent = option.dataset.identifierLabel || "Benutzername";
    if (secretLabel) secretLabel.textContent = option.dataset.secretLabel || "Passwort";
  };

  providerSelect.addEventListener("change", applyProvider);
  applyProvider();
})();
