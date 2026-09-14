(() => {
  const STORAGE_KEY = 'followcheck_cooldown_until';
  const originalFetch = window.fetch.bind(window);

  let cooldownUntil = Number(localStorage.getItem(STORAGE_KEY) || 0);
  let intervalId = null;

  function apiBase() {
    return String(window.FOLLOWCHECK_CONFIG?.apiBaseUrl || '').replace(/\/$/, '');
  }

  function formatRemaining(totalSeconds) {
    const seconds = Math.max(0, Math.ceil(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${minutes}:${String(remainder).padStart(2, '0')}`;
  }

  function cooldownElements() {
    return {
      status: document.querySelector('#status'),
      button: document.querySelector('#scan-button'),
      label: document.querySelector('#scan-button .button-label')
    };
  }

  function clearTimer() {
    if (intervalId !== null) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  function renderCooldown() {
    if (!cooldownUntil) return;

    const remaining = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
    const { status, button, label } = cooldownElements();

    if (remaining <= 0) {
      clearTimer();
      cooldownUntil = 0;
      localStorage.removeItem(STORAGE_KEY);

      if (button) button.disabled = false;
      if (label) label.textContent = 'Analyze account';
      if (status) {
        status.textContent = 'Instagram cooldown finished. You can scan again.';
        status.dataset.type = 'success';
        status.hidden = false;
      }
      return;
    }

    const display = formatRemaining(remaining);
    if (status) {
      status.textContent = `Instagram rate-limit cooldown: ${display} remaining. FollowCheck will be available automatically when the timer reaches 0:00.`;
      status.dataset.type = 'error';
      status.hidden = false;
    }
    if (button) button.disabled = true;
    if (label) label.textContent = `Cooldown ${display}`;
  }

  function beginCooldown(seconds) {
    const safeSeconds = Math.max(1, Math.ceil(Number(seconds) || 0));
    const proposedUntil = Date.now() + safeSeconds * 1000;
    cooldownUntil = Math.max(cooldownUntil, proposedUntil);
    localStorage.setItem(STORAGE_KEY, String(cooldownUntil));

    clearTimer();
    renderCooldown();
    intervalId = setInterval(renderCooldown, 1000);

    // app.js may write its generic error message immediately after fetch resolves.
    // Re-assert the countdown once that catch block has finished.
    setTimeout(renderCooldown, 50);
  }

  async function syncFromHealth() {
    const base = apiBase();
    if (!base) return;

    try {
      const response = await originalFetch(`${base}/health`, { cache: 'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      const remaining = Number(payload?.cooldown_seconds || 0);
      if (remaining > 0) beginCooldown(remaining);
    } catch (_) {}
  }

  window.fetch = async (...args) => {
    const response = await originalFetch(...args);

    if (response.status === 429) {
      let retryAfter = Number(response.headers.get('Retry-After') || 0);

      try {
        const payload = await response.clone().json();
        retryAfter = Number(payload?.error?.retry_after_seconds || retryAfter || 0);
      } catch (_) {}

      if (retryAfter > 0) beginCooldown(retryAfter);
      else setTimeout(syncFromHealth, 0);
    }

    return response;
  };

  function init() {
    if (cooldownUntil > Date.now()) {
      renderCooldown();
      clearTimer();
      intervalId = setInterval(renderCooldown, 1000);
    } else {
      cooldownUntil = 0;
      localStorage.removeItem(STORAGE_KEY);
    }

    // Ask the backend for the authoritative remaining cooldown. This also lets
    // a refreshed/new browser show the timer while a cooldown is already active.
    syncFromHealth();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
