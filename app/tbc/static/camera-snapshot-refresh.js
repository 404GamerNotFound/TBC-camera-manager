(() => {
  // The dashboard preview images otherwise only ever show the frame that was
  // present when this page was rendered - nothing re-requests them afterwards
  // unless the separate, opt-in "Dashboard refresh" setting reloads the whole
  // page. Polling just the <img> tags keeps the caption's "refresh every N
  // minutes" promise without forcing a full-page reload on everyone.
  const images = document.querySelectorAll("[data-camera-snapshot]");
  if (!images.length) return;

  const REFRESH_INTERVAL_MS = 30000;

  window.setInterval(() => {
    if (document.hidden) return;
    const cacheBuster = Date.now();
    images.forEach((img) => {
      img.src = img.src.split("?")[0] + "?v=" + cacheBuster;
    });
  }, REFRESH_INTERVAL_MS);
})();
