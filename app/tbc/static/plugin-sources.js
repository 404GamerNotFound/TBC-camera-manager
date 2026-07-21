(() => {
  "use strict";

  const workspace = document.querySelector("[data-source-workspace]");
  if (!workspace) return;

  const search = workspace.querySelector("[data-source-search]");
  const rows = [...workspace.querySelectorAll("[data-source-row]")];
  const sections = [...workspace.querySelectorAll("[data-source-section]")];
  const empty = workspace.querySelector("[data-source-empty]");
  const state = { scope: "all", kind: "all", search: "" };

  const updateOptions = (attribute, value) => {
    const dataKey = attribute === "data-source-filter-scope" ? "sourceFilterScope" : "sourceFilterKind";
    workspace.querySelectorAll(`[${attribute}]`).forEach((option) => {
      const selected = option.dataset[dataKey] === value;
      option.classList.toggle("is-active", selected);
      option.setAttribute("aria-pressed", String(selected));
    });
  };

  const applyFilters = () => {
    let visibleRows = 0;
    rows.forEach((row) => {
      const matchesScope = state.scope === "all" || row.dataset.sourceScope === state.scope;
      const matchesKind = state.kind === "all" || row.dataset.sourceKind === state.kind;
      const matchesSearch = !state.search || (row.dataset.sourceSearch || "").includes(state.search);
      const visible = matchesScope && matchesKind && matchesSearch;
      row.hidden = !visible;
      if (visible) visibleRows += 1;
    });

    sections.forEach((section) => {
      section.hidden = !section.querySelector("[data-source-row]:not([hidden])");
    });
    if (empty) empty.hidden = visibleRows !== 0;
  };

  workspace.querySelectorAll("[data-source-filter-scope]").forEach((option) => {
    option.addEventListener("click", () => {
      state.scope = option.dataset.sourceFilterScope || "all";
      updateOptions("data-source-filter-scope", state.scope);
      applyFilters();
    });
  });

  workspace.querySelectorAll("[data-source-filter-kind]").forEach((option) => {
    option.addEventListener("click", () => {
      state.kind = option.dataset.sourceFilterKind || "all";
      updateOptions("data-source-filter-kind", state.kind);
      applyFilters();
    });
  });

  search?.addEventListener("input", () => {
    state.search = search.value.trim().toLocaleLowerCase();
    applyFilters();
  });
})();
