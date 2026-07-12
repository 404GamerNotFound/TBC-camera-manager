(function () {
  document.querySelectorAll("[data-plugin-search]").forEach((input) => {
    const list = document.querySelector(input.getAttribute("data-plugin-search"));
    if (!list) return;
    const items = Array.from(list.querySelectorAll(":scope > [data-plugin-search-item]"));
    const empty = list.querySelector("[data-plugin-search-empty]");

    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();
      let visibleCount = 0;
      items.forEach((item) => {
        const matches = !query || item.textContent.toLowerCase().includes(query);
        item.hidden = !matches;
        if (matches) visibleCount += 1;
      });
      if (empty) empty.hidden = visibleCount !== 0 || items.length === 0;
    });
  });
})();
