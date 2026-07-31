(() => {
  const fullscreenButton = document.querySelector("[data-birdseye-fullscreen]");
  const kioskExitButton = document.querySelector("[data-birdseye-kiosk-exit]");
  const settingsToggleButton = document.querySelector("[data-birdseye-settings-toggle]");
  const settingsForm = document.querySelector("[data-birdseye-settings-form]");
  const player = document.querySelector("[data-birdseye-player]");

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
