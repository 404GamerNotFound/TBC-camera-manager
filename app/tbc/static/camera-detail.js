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

(() => {
  const panel = document.querySelector("[data-control-panel]");
  if (!panel) return;

  const channelSelect = panel.querySelector("[data-control-channel-select]");
  if (channelSelect) {
    channelSelect.addEventListener("change", () => channelSelect.form.submit());
  }

  const toastStack = panel.querySelector("[data-toast-stack]");

  function showToast(message, ok) {
    if (!toastStack) return;
    const toast = document.createElement("div");
    toast.className = `tbc-toast flash-${ok ? "success" : "error"}`;
    toast.setAttribute("role", "status");
    toast.textContent = message;
    toastStack.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
  }

  panel.querySelectorAll("[data-control-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector('button[type="submit"]');
      const originalLabel = submitButton ? submitButton.textContent : null;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "…";
      }
      const pillTarget = form.dataset.controlPillTarget;
      const pillValue = form.dataset.controlPillValue;
      const pill = pillTarget ? panel.querySelector(`[data-control-pill="${pillTarget}"]`) : null;
      const previousPillText = pill ? pill.textContent : null;
      const previousPillClass = pill ? pill.className : null;
      if (pill && pillValue) {
        pill.textContent = pillValue;
        pill.className = `status-pill ${pillValue === "aus" ? "status-idle" : "status-active"}`;
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
        });
        const data = await response.json().catch(() => null);
        const ok = response.ok && data && data.ok;
        showToast((data && data.message) || (ok ? "Befehl wurde gesendet" : "Befehl fehlgeschlagen"), ok);
        if (!ok && pill && previousPillText !== null) {
          pill.textContent = previousPillText;
          pill.className = previousPillClass;
        }
      } catch (error) {
        showToast("Befehl fehlgeschlagen: Netzwerkfehler", false);
        if (pill && previousPillText !== null) {
          pill.textContent = previousPillText;
          pill.className = previousPillClass;
        }
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
          submitButton.textContent = originalLabel;
        }
      }
    });
  });
})();
