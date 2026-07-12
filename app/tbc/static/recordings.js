(() => {
  if (!window.TBCPlayer) return;
  document.querySelectorAll("[data-clip-video]").forEach((video) => {
    new window.TBCPlayer(video, { mode: "vod", src: video.dataset.clipVideo });
  });
})();
