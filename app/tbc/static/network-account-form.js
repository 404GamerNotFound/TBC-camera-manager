(() => {
  const form = document.querySelector("[data-network-account-form]");
  const providerSelect = form?.querySelector("[data-network-account-provider]");
  if (!form || !providerSelect) return;

  const fieldGroups = form.querySelectorAll("[data-network-account-fields]");
  const configurableControls = form.querySelectorAll("input, textarea, button[type='submit']");
  const installLink = form.querySelector("[data-plugin-install-link]");
  const unavailableNote = form.querySelector("[data-plugin-unavailable]");

  window.tbcInitPluginAvailabilityToggle({
    select: providerSelect,
    configurableControls,
    installLink,
    unavailableNote,
    unavailableKey: "plugin.network_not_installed",
    fallbackLabelKey: "plugin.network_provider",
    onApply: (option, installed) => {
      const provider = option?.value || "";
      fieldGroups.forEach((group) => {
        const active = installed && group.dataset.networkAccountFields === provider;
        group.hidden = !active;
        group.querySelectorAll("input, select, textarea").forEach((control) => {
          control.disabled = !active;
        });
      });
    },
  });
})();
