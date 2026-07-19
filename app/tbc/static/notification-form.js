(() => {
  function syncFields(form) {
    const kind = form.querySelector('[data-notification-kind]')?.value;
    form.querySelectorAll('[data-notification-fields]').forEach((field) => {
      const isRelevant = field.dataset.notificationFields.split(',').includes(kind);
      field.hidden = !isRelevant;
      // Several channel types reuse storage fields such as `token` and `url`.
      // Disable inactive inputs so only the visible type contributes a value.
      field.querySelectorAll('input, select, textarea').forEach((control) => {
        control.disabled = !isRelevant;
      });
    });
  }

  function syncEvent(card) {
    const enabled = card.querySelector('[data-notification-event-toggle]')?.checked;
    card.classList.toggle('is-disabled', !enabled);
    card.querySelectorAll('input:not([data-notification-event-toggle]), textarea').forEach((field) => {
      // Keep the value submittable while an event is inactive, so changing the
      // toggle does not discard a previously customised text.
      field.readOnly = !enabled;
      field.setAttribute('aria-disabled', String(!enabled));
    });
  }

  document.querySelectorAll('[data-notification-form]').forEach((form) => {
    syncFields(form);
    form.querySelector('[data-notification-kind]')?.addEventListener('change', () => syncFields(form));
    form.querySelectorAll('[data-notification-event]').forEach((card) => {
      syncEvent(card);
      card.querySelector('[data-notification-event-toggle]')?.addEventListener('change', () => syncEvent(card));
    });
  });
})();
