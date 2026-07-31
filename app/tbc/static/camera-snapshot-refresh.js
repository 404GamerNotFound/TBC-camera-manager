(() => {
  // The dashboard preview images otherwise only ever show the frame that was
  // present when this page was rendered - nothing re-requests them afterwards
  // unless the separate, opt-in "Dashboard refresh" setting reloads the whole
  // page. Polling just the <img> tags keeps the caption's "refresh every N
  // minutes" promise without forcing a full-page reload on everyone.
  const images = document.querySelectorAll("[data-camera-snapshot]");
  if (!images.length) return;

  // dashboard.html deliberately renders these as data-src, not src: the
  // snapshot endpoint runs a real ffmpeg capture on a stale cache (see
  // snapshots.py), which for a slow/unreachable camera can take several
  // seconds - an <img src> present at initial parse would hold up the
  // browser's own page-load completion (and tab spinner) on that, even
  // though the rest of the page is already fully interactive. Waiting for
  // the load event before assigning src guarantees these fetches start after
  // the page has already finished loading, not as part of it.
  window.addEventListener("load", () => {
    images.forEach((img) => {
      if (img.dataset.src) img.src = img.dataset.src;
    });
  });

  const REFRESH_INTERVAL_MS = 30000;

  window.setInterval(() => {
    if (document.hidden) return;
    const cacheBuster = Date.now();
    images.forEach((img) => {
      img.src = img.src.split("?")[0] + "?v=" + cacheBuster;
    });
  }, REFRESH_INTERVAL_MS);
})();
