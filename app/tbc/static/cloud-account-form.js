(() => {
  const providerSelect = document.querySelector("[data-cloud-account-provider]");
  if (!providerSelect) return;

  const fieldGroups = document.querySelectorAll("[data-cloud-account-fields]");

  const applyProvider = () => {
    const provider = providerSelect.value;
    fieldGroups.forEach((group) => {
      const active = group.dataset.cloudAccountFields === provider;
      group.hidden = !active;
      group.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = !active;
      });
    });
  };

  providerSelect.addEventListener("change", applyProvider);
  applyProvider();
})();
