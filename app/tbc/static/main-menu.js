(() => {
  const root = document.querySelector("[data-main-menu]");
  if (!root) {
    return;
  }

  if (window.bootstrap?.Dropdown && window.bootstrap?.Collapse) {
    return;
  }

  const mobileToggle =
    document.querySelector(`[data-menu-toggle][aria-controls="${root.id}"]`) ||
    root.querySelector("[data-menu-toggle]");
  const groups = Array.from(root.querySelectorAll("[data-menu-group]"));

  const closeGroups = (except = null) => {
    groups.forEach((group) => {
      if (group === except) {
        return;
      }
      group.classList.remove("is-open");
      group.querySelector("[data-menu-trigger]")?.setAttribute("aria-expanded", "false");
    });
  };

  const openGroup = (group) => {
    closeGroups(group);
    group.classList.add("is-open");
    group.querySelector("[data-menu-trigger]")?.setAttribute("aria-expanded", "true");
  };

  const closeMobileMenu = () => {
    root.classList.remove("is-open");
    root.classList.remove("show");
    mobileToggle?.setAttribute("aria-expanded", "false");
  };

  groups.forEach((group) => {
    const trigger = group.querySelector("[data-menu-trigger]");
    const panel = group.querySelector("[data-menu-panel]");
    if (!trigger || !panel) {
      return;
    }

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      if (group.classList.contains("is-open")) {
        closeGroups();
      } else {
        openGroup(group);
      }
    });

    trigger.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openGroup(group);
        panel.querySelector("a, button")?.focus();
      }
      if (event.key === "Escape") {
        closeGroups();
        trigger.focus();
      }
    });

    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") {
        return;
      }
      closeGroups();
      trigger.focus();
    });

    panel.addEventListener("click", (event) => {
      if (event.target.closest("a, button")) {
        closeGroups();
        closeMobileMenu();
      }
    });
  });

  mobileToggle?.addEventListener("click", () => {
    const isOpen = !root.classList.contains("is-open");
    root.classList.toggle("is-open", isOpen);
    root.classList.toggle("show", isOpen);
    mobileToggle.setAttribute("aria-expanded", String(isOpen));
    if (!isOpen) {
      closeGroups();
    }
  });

  document.addEventListener("click", (event) => {
    if (!root.contains(event.target)) {
      closeGroups();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeGroups();
    }
  });
})();
