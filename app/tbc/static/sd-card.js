(function () {
  const player = document.querySelector("[data-sd-preview-player]");
  const title = document.querySelector("[data-sd-preview-title]");
  const meta = document.querySelector("[data-sd-preview-meta]");
  const links = document.querySelectorAll("[data-sd-play]");
  if (!player || !links.length) return;

  function stopCurrent() {
    player.pause();
    player.removeAttribute("src");
    player.load();
  }

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      stopCurrent();
      player.src = link.dataset.sdPlay || link.href;
      if (title) title.textContent = link.dataset.sdTitle || "Vorschau";
      if (meta) meta.textContent = link.dataset.sdMeta || "";
      player.load();
      player.play().catch(() => {});
      player.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
})();
