(() => {
  const fullscreenButton = document.querySelector("[data-birdseye-fullscreen]");
  const refreshButton = document.querySelector("[data-birdseye-refresh]");
  const kioskExitButton = document.querySelector("[data-birdseye-kiosk-exit]");
  const settingsToggleButton = document.querySelector("[data-birdseye-settings-toggle]");
  const settingsForm = document.querySelector("[data-birdseye-settings-form]");
  const player = document.querySelector("[data-birdseye-player]");
  const stage = document.querySelector("[data-birdseye-stage]");

  refreshButton?.addEventListener("click", () => window.location.reload());

  // --- Auto-refresh while starting ----------------------------------------
  // The page is server-rendered from a single status snapshot taken when it
  // loaded - unlike live.html's per-tile grid, there's no client-side status
  // poll here, so a stream that takes a while to come up (or one that's
  // stuck because a selected camera never responds - ffmpeg's xstack filter
  // can block on a single slow/unreachable input) would otherwise show
  // "starting" forever until someone manually reloads. Poll by reloading the
  // whole page every few seconds, capped so a genuinely stuck stream doesn't
  // reload forever.
  const MAX_AUTO_RELOADS = 12;
  const RELOAD_INTERVAL_MS = 5000;
  const RELOAD_COUNT_KEY = "tbc-birdseye-auto-reload-count";

  if (stage?.dataset.status === "starting") {
    const count = Number(window.sessionStorage.getItem(RELOAD_COUNT_KEY) || "0");
    if (count < MAX_AUTO_RELOADS) {
      window.sessionStorage.setItem(RELOAD_COUNT_KEY, String(count + 1));
      window.setTimeout(() => window.location.reload(), RELOAD_INTERVAL_MS);
    }
  } else {
    window.sessionStorage.removeItem(RELOAD_COUNT_KEY);
  }

  // --- Fullscreen / kiosk mode (mirrors live.js's, but this page has a
  // single composited stream instead of a tiled grid) ---------------------
  const isFullscreen = () => !!document.fullscreenElement;

  const applyKioskState = () => {
    const active = isFullscreen();
    document.body.classList.toggle("live-kiosk", active);
    if (kioskExitButton) kioskExitButton.hidden = !active;
  };

  fullscreenButton?.addEventListener("click", () => {
    if (isFullscreen()) {
      document.exitFullscreen?.();
    } else {
      document.documentElement.requestFullscreen?.().catch(() => {});
    }
  });

  kioskExitButton?.addEventListener("click", () => {
    document.exitFullscreen?.();
  });

  document.addEventListener("fullscreenchange", applyKioskState);

  // --- Admin settings panel -------------------------------------------------
  settingsToggleButton?.addEventListener("click", () => {
    if (!settingsForm) return;
    const expanded = settingsToggleButton.getAttribute("aria-expanded") === "true";
    settingsForm.hidden = expanded;
    settingsToggleButton.setAttribute("aria-expanded", String(!expanded));
  });

  // --- Player -----------------------------------------------------------
  if (player) {
    const video = document.createElement("video");
    video.className = "live-video";
    player.innerHTML = "";
    player.append(video);
    new window.TBCPlayer(video, {
      mode: "live",
      src: player.dataset.src,
      autoplay: true,
      muted: true,
    });
  }
})();
