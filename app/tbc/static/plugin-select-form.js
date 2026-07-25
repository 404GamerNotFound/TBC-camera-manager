// Shared by camera-form.js, cloud-account-form.js, and network-account-form.js:
// all three forms let the user pick a vendor module/provider from a <select>,
// then disable the whole form and show an "install this plugin" note when the
// chosen one isn't installed yet. This used to be reimplemented independently
// in each file; only the per-vendor bits (port defaults, manual-stream fields,
// provider-specific field groups) still live in the page-specific scripts.
window.tbcInitPluginAvailabilityToggle = ({
  select,
  configurableControls,
  installLink,
  unavailableNote,
  unavailableKey,
  fallbackLabelKey,
  onApply,
}) => {
  const translate = (key, parameters = {}) => window.tbcI18n?.t(key, parameters) || key;

  const relabelUninstalledOptions = () => {
    select.querySelectorAll("option[data-installed='false']").forEach((option) => {
      const description = option.dataset.description
        ? ` · ${translate(option.dataset.description)}`
        : "";
      option.textContent = translate("plugin.option_not_installed", {
        label: `${option.dataset.label || option.value}${description}`,
      });
    });
  };
  relabelUninstalledOptions();

  const apply = (isUserChange) => {
    const option = select.selectedOptions[0];
    // Some callers (camera-form) only ever have a real option selected and
    // want to no-op otherwise; others (cloud/network-account-form) treat "no
    // option" as "not installed" via fallbackLabelKey - preserves each
    // form's original behavior instead of forcing one convention on both.
    if (!option && !fallbackLabelKey) return;
    const installed = Boolean(option) && option.dataset.installed !== "false";
    select.closest("form")?.classList.toggle("is-plugin-unavailable", !installed);
    configurableControls.forEach((control) => { control.disabled = !installed; });
    if (installLink) installLink.href = option?.dataset.installUrl || "/plugin-sources";
    if (unavailableNote) {
      unavailableNote.hidden = installed;
      if (!installed) {
        unavailableNote.textContent = translate(unavailableKey, {
          label: option?.dataset.label || (fallbackLabelKey ? translate(fallbackLabelKey) : ""),
        });
      }
    }
    onApply?.(option, installed, isUserChange, translate);
  };

  select.addEventListener("change", () => apply(true));
  apply(false);

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
      apply(false);
    },
    { once: true },
  );
};
