(() => {
  const script = document.currentScript;
  const seconds = Number(script?.dataset.dashboardRefreshSeconds || 0);
  if (!Number.isFinite(seconds) || seconds < 5) return;

  window.setTimeout(() => {
    // Do not interrupt someone interacting with a menu, dialog, or form.
    if (document.hidden || document.querySelector("input:focus, select:focus, textarea:focus, [contenteditable='true']:focus")) return;
    window.location.reload();
  }, seconds * 1000);
})();
