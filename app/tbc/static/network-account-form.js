(() => {
  const form = document.querySelector("[data-network-account-form]");
  const providerSelect = form?.querySelector("[data-network-account-provider]");
  if (!form || !providerSelect) return;

  const fieldGroups = form.querySelectorAll("[data-network-account-fields]");
  const configurableControls = form.querySelectorAll("input, textarea, button[type='submit']");
  const installLink = form.querySelector("[data-plugin-install-link]");
  const unavailableNote = form.querySelector("[data-plugin-unavailable]");
  const translate = (key, parameters = {}) => window.tbcI18n?.t(key, parameters) || key;

  providerSelect.querySelectorAll("option[data-installed='false']").forEach((option) => {
    const description = option.dataset.description
      ? ` · ${translate(option.dataset.description)}`
      : "";
    option.textContent = translate("plugin.option_not_installed", {
      label: `${option.dataset.label || option.value}${description}`,
    });
  });

  const applyProvider = () => {
    const option = providerSelect.selectedOptions[0];
    const installed = option?.dataset.installed !== "false" && Boolean(option);
    const provider = option?.value || "";
    form.classList.toggle("is-plugin-unavailable", !installed);
    configurableControls.forEach((control) => { control.disabled = !installed; });
    if (installLink) installLink.href = option?.dataset.installUrl || "/plugin-sources";

    fieldGroups.forEach((group) => {
      const active = installed && group.dataset.networkAccountFields === provider;
      group.hidden = !active;
      group.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = !active;
      });
    });

    if (unavailableNote) {
      unavailableNote.hidden = installed;
      if (!installed) {
        unavailableNote.textContent = translate("plugin.network_not_installed", {
          label: option?.dataset.label || translate("plugin.network_provider"),
        });
      }
    }
  };

  providerSelect.addEventListener("change", applyProvider);
  applyProvider();
})();
