(() => {
  const form = document.querySelector("[data-cloud-account-form]");
  const providerSelect = form?.querySelector("[data-cloud-account-provider]");
  if (!form || !providerSelect) return;

  const fieldGroups = form.querySelectorAll("[data-cloud-account-fields]");
  const configurableControls = form.querySelectorAll("input, textarea, button[type='submit']");
  const installLink = form.querySelector("[data-plugin-install-link]");
  const unavailableNote = form.querySelector("[data-plugin-unavailable]");
  const translate = (key, parameters = {}) => window.tbcI18n?.t(key, parameters) || key;

  const relabelUninstalledOptions = () => {
    providerSelect.querySelectorAll("option[data-installed='false']").forEach((option) => {
      const description = option.dataset.description
        ? ` · ${translate(option.dataset.description)}`
        : "";
      option.textContent = translate("plugin.option_not_installed", {
        label: `${option.dataset.label || option.value}${description}`,
      });
    });
  };
  relabelUninstalledOptions();

  const applyProvider = () => {
    const option = providerSelect.selectedOptions[0];
    const installed = option?.dataset.installed !== "false" && Boolean(option);
    const provider = option?.value || "";
    form.classList.toggle("is-plugin-unavailable", !installed);
    configurableControls.forEach((control) => { control.disabled = !installed; });
    if (installLink) installLink.href = option?.dataset.installUrl || "/plugin-sources";

    fieldGroups.forEach((group) => {
      const active = installed && group.dataset.cloudAccountFields === provider;
      group.hidden = !active;
      group.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = !active;
      });
    });

    if (unavailableNote) {
      unavailableNote.hidden = installed;
      if (!installed) {
        unavailableNote.textContent = translate("plugin.cloud_not_installed", {
          label: option?.dataset.label || translate("plugin.cloud_provider"),
        });
      }
    }
  };

  providerSelect.addEventListener("change", applyProvider);
  applyProvider();

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
      applyProvider();
    },
    { once: true },
  );
})();
