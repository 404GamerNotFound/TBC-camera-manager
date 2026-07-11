(() => {
  const tabs = Array.from(document.querySelectorAll("[data-detail-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-detail-panel]"));
  if (!tabs.length || !panels.length) return;

  const available = new Set(tabs.map((tab) => tab.dataset.detailTab));

  function activate(name, updateHash = true) {
    const selected = available.has(name) ? name : "overview";
    tabs.forEach((tab) => {
      const active = tab.dataset.detailTab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.detailPanel !== selected;
    });
    if (updateHash) history.replaceState(null, "", `#${selected}`);
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activate(tab.dataset.detailTab));
    tab.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(index + offset + tabs.length) % tabs.length];
      activate(next.dataset.detailTab);
      next.focus();
    });
  });

  activate(location.hash.slice(1), false);

  const triggerFieldset = document.querySelector("[data-trigger-fieldset]");
  if (triggerFieldset) {
    triggerFieldset.querySelectorAll("[data-trigger-selection]").forEach((button) => {
      button.addEventListener("click", () => {
        const checked = button.dataset.triggerSelection === "all";
        triggerFieldset.querySelectorAll('input[name="trigger_keys"]').forEach((input) => {
          input.checked = checked;
        });
      });
    });
  }
})();
