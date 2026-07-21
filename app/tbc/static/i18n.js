// Prefixes a root-relative path ("/api/...") with the Home Assistant Ingress
// path, if any - see app/tbc/ingress.py and base.html's inline script that
// sets window.TBC_INGRESS_PREFIX. A no-op outside Ingress. Exposed on
// `window` (not inside the IIFE below) so every other page script can call
// it for its own fetch()/src assignments instead of hardcoding a path.
window.tbcUrl = (path) => (window.TBC_INGRESS_PREFIX || "") + path;

// Reads the per-session CSRF token base.html renders into <meta
// name="csrf-token">. See the _csrf_protect middleware in app/tbc/main.py.
window.tbcCsrfToken = () => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
};

(() => {
  "use strict";

  // Every state-changing request in this app is same-origin and either a
  // classic <form method="post"> or a fetch() call using the session
  // cookie - both need the CSRF token the middleware checks. Patching
  // fetch() once here covers every existing and future fetch() call site
  // (live.js, camera-detail.js, video-player.js, health.js, ...) without
  // threading the header through each of them individually.
  const CSRF_UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const method = ((init && init.method) || (input instanceof Request ? input.method : "GET") || "GET").toUpperCase();
    if (!CSRF_UNSAFE_METHODS.has(method)) return nativeFetch(input, init);
    const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
    if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", window.tbcCsrfToken());
    return nativeFetch(input, { ...init, headers });
  };

  // Classic form POSTs (not fetch) prove the token via a hidden field
  // instead of a header - inject it into every same-page <form
  // method="post"> that doesn't already carry one.
  const injectCsrfInputs = (root) => {
    const token = window.tbcCsrfToken();
    if (!token) return;
    const forms = root instanceof HTMLFormElement ? [root] : root.querySelectorAll ? [...root.querySelectorAll("form")] : [];
    forms.forEach((form) => {
      if (form.method.toLowerCase() !== "post" || form.querySelector('input[name="csrf_token"]')) return;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = token;
      form.appendChild(input);
    });
  };

  const STORAGE_KEY = "tbc-language";
  const SUPPORTED_LANGUAGES = ["de", "en", "es", "pt"];
  const LANGUAGE_NAMES = { de: "Deutsch", en: "English", es: "Español", pt: "Português" };

  const selectedLanguage = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (SUPPORTED_LANGUAGES.includes(stored)) return stored;
    } catch (_) {
      // Storage can be disabled; English remains the deterministic default.
    }
    return "en";
  };

  let language = selectedLanguage();
  let strings = {};
  let fallbackStrings = {};

  // Reuse the same cache-busting query string this script itself was loaded
  // with (?v=<asset_version>, set per deploy in base.html) so locale files
  // roll over on every release exactly like every other static asset.
  const cacheBust = (() => {
    const current = document.currentScript;
    if (!current) return "";
    try {
      return new URL(current.src, window.location.href).search || "";
    } catch (_) {
      return "";
    }
  })();

  const loadLocale = (lang) =>
    fetch(tbcUrl(`/static/i18n/${lang}.json${cacheBust}`))
      .then((response) => (response.ok ? response.json() : {}))
      .catch(() => ({}));

  const ready =
    language === "en"
      ? loadLocale("en").then((en) => {
          strings = en;
          fallbackStrings = en;
        })
      : Promise.all([loadLocale(language), loadLocale("en")]).then(([primary, en]) => {
          strings = primary;
          fallbackStrings = en;
        });

  const interpolate = (value, parameters = {}) =>
    value.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key) =>
      Object.prototype.hasOwnProperty.call(parameters, key) ? String(parameters[key]) : match
    );

  const translate = (key, parameters = {}) => {
    if (typeof key !== "string" || !key) return key;
    const template = strings[key] ?? fallbackStrings[key] ?? key;
    return interpolate(template, parameters);
  };

  const ATTRS = ["aria-label", "title", "placeholder", "data-tooltip", "alt"];
  const datasetKeyFor = (attribute) =>
    `i18n${attribute.replace(/(^|-)([a-z])/g, (_, __, letter) => letter.toUpperCase())}`;

  const paramsFor = (element) => {
    const raw = element.dataset.i18nParams;
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (_) {
      return {};
    }
  };

  const translateElement = (element) => {
    if (!(element instanceof Element)) return;
    if (element.dataset.i18n) element.textContent = translate(element.dataset.i18n, paramsFor(element));
    for (const attribute of ATTRS) {
      const key = element.dataset[datasetKeyFor(attribute)];
      if (key) element.setAttribute(attribute, translate(key, paramsFor(element)));
    }
    element.querySelectorAll("[data-i18n], [data-i18n-aria-label], [data-i18n-title], [data-i18n-placeholder], [data-i18n-data-tooltip], [data-i18n-alt]").forEach((child) => {
      if (child.dataset.i18n) child.textContent = translate(child.dataset.i18n, paramsFor(child));
      for (const attribute of ATTRS) {
        const key = child.dataset[datasetKeyFor(attribute)];
        if (key) child.setAttribute(attribute, translate(key, paramsFor(child)));
      }
    });
  };

  const updateControls = () => {
    document.querySelectorAll("[data-language]").forEach((button) => {
      const active = button.dataset.language === language;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-current-language]").forEach((label) => {
      label.textContent = LANGUAGE_NAMES[language];
    });
  };

  const setLanguage = (nextLanguage) => {
    if (!SUPPORTED_LANGUAGES.includes(nextLanguage)) return;
    try {
      localStorage.setItem(STORAGE_KEY, nextLanguage);
    } catch (_) {
      // The selection still applies to the current page when storage is disabled.
    }
    document.cookie = `tbc_language=${nextLanguage}; Path=/; Max-Age=31536000; SameSite=Lax`;
    if (nextLanguage !== language) window.location.reload();
  };

  const initialize = () => {
    document.documentElement.lang = language;
    translateElement(document.documentElement);
    updateControls();
    injectCsrfInputs(document);
    document.addEventListener("click", (event) => {
      const control = event.target.closest("[data-language]");
      if (control) setLanguage(control.dataset.language);
    });
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType !== Node.ELEMENT_NODE) return;
          translateElement(node);
          injectCsrfInputs(node);
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.documentElement.classList.remove("i18n-pending");
    // Other page scripts (camera-form.js, cloud-account-form.js,
    // network-account-form.js, live.js, ...) run as separate <script defer>
    // tags and can call window.tbcI18n.t() before the locale fetch behind
    // `ready` above has resolved - window.tbcI18n itself already exists (see
    // below), so that doesn't throw, but `strings`/`fallbackStrings` are
    // still empty at that point, so t() just returns the raw key. This must
    // fire only from here (after `ready` resolved, i.e. strings are
    // actually populated) - firing it eagerly at module load time, before
    // the fetch even starts, would make it useless as a signal.
    document.dispatchEvent(new CustomEvent("tbc:i18n-ready"));
  };

  window.tbcI18n = { get language() { return language; }, setLanguage, t: translate };

  const start = () => ready.then(initialize);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
