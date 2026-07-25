(() => {
  const form = document.querySelector("[data-cloud-account-form]");
  const providerSelect = form?.querySelector("[data-cloud-account-provider]");
  if (!form || !providerSelect) return;

  const fieldGroups = form.querySelectorAll("[data-cloud-account-fields]");
  const configurableControls = form.querySelectorAll("input, textarea, button[type='submit']");
  const installLink = form.querySelector("[data-plugin-install-link]");
  const unavailableNote = form.querySelector("[data-plugin-unavailable]");

  window.tbcInitPluginAvailabilityToggle({
    select: providerSelect,
    configurableControls,
    installLink,
    unavailableNote,
    unavailableKey: "plugin.cloud_not_installed",
    fallbackLabelKey: "plugin.cloud_provider",
    onApply: (option, installed) => {
      const provider = option?.value || "";
      fieldGroups.forEach((group) => {
        const active = installed && group.dataset.cloudAccountFields === provider;
        group.hidden = !active;
        group.querySelectorAll("input, select, textarea").forEach((control) => {
          control.disabled = !active;
        });
      });
    },
  });
})();
