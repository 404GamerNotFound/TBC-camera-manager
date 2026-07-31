(() => {
  "use strict";

  // App-wide double-submit guard: once a form actually navigates (i.e. its submit
  // event was not preventDefault'ed by page-specific JS such as the zone editor),
  // its submit buttons are disabled so a second click on a slow connection can't
  // fire the same POST twice (duplicate cameras, double settings writes, ...).
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
    // Disable on the next tick, after the browser has serialized the form -
    // disabling synchronously would drop the clicked button's name/value from
    // the submitted data.
    window.setTimeout(() => {
      form.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type])').forEach((button) => {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
      });
    }, 0);
  });

  // Coming back via the back/forward cache restores the DOM exactly as it was
  // left - mid-submit, with disabled buttons - so undo the guard there.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    document.querySelectorAll('form [aria-busy="true"]').forEach((button) => {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    });
  });
})();
