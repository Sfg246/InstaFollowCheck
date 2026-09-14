(() => {
  let startedAt = 0;
  let timerId = null;
  let samples = [];

  function formatEta(totalSeconds) {
    const seconds = Math.max(0, Math.ceil(totalSeconds));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${minutes}m ${String(remainder).padStart(2, '0')}s`;
  }

  function stripEta(text) {
    return String(text || '')
      .replace(/\s·\s(?:Estimating time remaining…|About .* remaining)$/, '')
      .trim();
  }

  function stopEta() {
    if (timerId !== null) {
      clearInterval(timerId);
      timerId = null;
    }
    startedAt = 0;
    samples = [];
  }

  function updateEta() {
    const progress = document.querySelector('#progress-bar');
    const progressText = document.querySelector('#progress-text');
    const scanButton = document.querySelector('#scan-button');
    const buttonLabel = document.querySelector('#scan-button .button-label');

    if (!progress || !progressText || !startedAt) return;

    const scanning = !progress.hidden && scanButton?.disabled && buttonLabel?.textContent === 'Scanning…';
    if (!scanning) {
      stopEta();
      return;
    }

    const now = Date.now();
    const percent = Math.max(0, Math.min(100, Number(progress.value) || 0));
    const elapsed = (now - startedAt) / 1000;
    const base = stripEta(progressText.textContent);

    // Keep a rolling history so the ETA follows the actual speed of this scan
    // rather than assuming every Instagram request takes the same amount of time.
    if (!samples.length || percent !== samples[samples.length - 1].percent) {
      samples.push({ time: now, percent });
      samples = samples.filter((sample) => now - sample.time <= 30000);
    }

    if (percent < 8 || elapsed < 4 || samples.length < 2) {
      progressText.textContent = `${base || 'Analyzing account…'} · Estimating time remaining…`;
      return;
    }

    const first = samples[0];
    const last = samples[samples.length - 1];
    const sampleSeconds = Math.max(0.25, (last.time - first.time) / 1000);
    const sampleProgress = last.percent - first.percent;

    let secondsRemaining;
    if (sampleProgress > 0) {
      const rate = sampleProgress / sampleSeconds;
      secondsRemaining = (100 - percent) / rate;
    } else {
      // Fallback to average progress when there has not been a new page recently.
      const averageRate = percent / Math.max(elapsed, 1);
      secondsRemaining = (100 - percent) / Math.max(averageRate, 0.01);
    }

    // Avoid displaying absurd transient values from the first couple of pages.
    secondsRemaining = Math.max(1, Math.min(secondsRemaining, 60 * 60));
    progressText.textContent = `${base || 'Analyzing account…'} · About ${formatEta(secondsRemaining)} remaining`;
  }

  function beginEta() {
    stopEta();
    startedAt = Date.now();
    samples = [];
    updateEta();
    timerId = setInterval(updateEta, 1000);
  }

  function init() {
    const form = document.querySelector('#scan-form');
    const input = document.querySelector('#username');
    if (!form || !input) return;

    form.addEventListener('submit', () => {
      const raw = String(input.value || '').trim();
      if (!raw) return;
      // Let app.js perform the authoritative username validation. The short
      // delay lets its setLoading(true) run before the ETA checks UI state.
      setTimeout(beginEta, 0);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
