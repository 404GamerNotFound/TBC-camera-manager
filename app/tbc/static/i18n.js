(() => {
  "use strict";

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
    fetch(`/static/i18n/${lang}.json${cacheBust}`)
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
    document.addEventListener("click", (event) => {
      const control = event.target.closest("[data-language]");
      if (control) setLanguage(control.dataset.language);
    });
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.ELEMENT_NODE) translateElement(node);
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.documentElement.classList.remove("i18n-pending");
  };

  window.tbcI18n = { get language() { return language; }, setLanguage, t: translate };

  const start = () => ready.then(initialize);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
