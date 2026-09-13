import { compareRelationships, filterRelationships } from './comparison.js';

const config = window.FOLLOWCHECK_CONFIG || {};
const state = {
  profile: null,
  followers: [],
  following: [],
  results: null,
  activeTab: 'notFollowingBack',
  search: '',
  selected: new Set(),
  queue: [],
  queueIndex: 0,
  handled: new Set(),
  accessCode: localStorage.getItem('followcheck_access_code') || ''
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  form: $('#scan-form'),
  username: $('#username'),
  scanButton: $('#scan-button'),
  status: $('#status'),
  landing: $('#landing'),
  results: $('#results'),
  profileAvatar: $('#profile-avatar'),
  profileName: $('#profile-name'),
  profileHandle: $('#profile-handle'),
  statFollowers: $('#stat-followers'),
  statFollowing: $('#stat-following'),
  statMutuals: $('#stat-mutuals'),
  statNonfollowers: $('#stat-nonfollowers'),
  tabs: $('#tabs'),
  search: $('#search'),
  list: $('#account-list'),
  empty: $('#empty-state'),
  selectionBar: $('#selection-bar'),
  selectionCount: $('#selection-count'),
  selectVisible: $('#select-visible'),
  clearSelection: $('#clear-selection'),
  startQueue: $('#start-queue'),
  exportCsv: $('#export-csv'),
  newScan: $('#new-scan'),
  settings: $('#settings-button'),
  settingsDialog: $('#settings-dialog'),
  settingsForm: $('#settings-form'),
  accessCode: $('#access-code'),
  queueDialog: $('#queue-dialog'),
  queueAvatar: $('#queue-avatar'),
  queueName: $('#queue-name'),
  queueHandle: $('#queue-handle'),
  queueCounter: $('#queue-counter'),
  openInstagram: $('#open-instagram'),
  markDone: $('#mark-done'),
  queueNext: $('#queue-next'),
  queuePrev: $('#queue-prev'),
  closeQueue: $('#close-queue'),
  progressBar: $('#progress-bar'),
  progressText: $('#progress-text')
};

function apiBase() {
  return String(config.apiBaseUrl || '').replace(/\/$/, '');
}

function normalizeHandle(value) {
  let raw = String(value || '').trim();
  if (!raw) return '';
  try {
    if (/^https?:\/\//i.test(raw)) {
      const url = new URL(raw);
      raw = url.pathname.split('/').filter(Boolean)[0] || '';
    }
  } catch (_) {}
  return raw.replace(/^@/, '').split(/[/?#]/)[0].trim();
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function setStatus(message = '', type = 'info') {
  elements.status.textContent = message;
  elements.status.dataset.type = type;
  elements.status.hidden = !message;
}

function setLoading(isLoading) {
  elements.scanButton.disabled = isLoading;
  elements.username.disabled = isLoading;
  elements.scanButton.querySelector('.button-label').textContent = isLoading ? 'Scanning…' : 'Analyze account';
  elements.progressBar.hidden = !isLoading;
  elements.progressText.hidden = !isLoading;
  if (!isLoading) {
    elements.progressBar.value = 0;
    elements.progressText.textContent = '';
  }
}

async function apiFetch(path, body) {
  if (!apiBase() || apiBase().includes('YOUR-WORKER')) {
    throw new Error('FollowCheck is not connected to its backend yet. Set site/config.js after deploying the Worker.');
  }

  const response = await fetch(`${apiBase()}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(state.accessCode ? { 'X-FollowCheck-Code': state.accessCode } : {})
    },
    body: JSON.stringify(body)
  });

  let payload = {};
  try { payload = await response.json(); } catch (_) {}

  if (!response.ok) {
    const error = new Error(payload?.error?.message || payload?.message || `Request failed (${response.status})`);
    error.code = payload?.error?.code || payload?.code || `http_${response.status}`;
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function fetchAll(kind, handle, expectedTotal, progressOffset, progressSpan) {
  let cursor = null;
  const items = [];
  let page = 0;
  const seenCursors = new Set();

  do {
    const payload = await apiFetch('/api/list', { handle, kind, cursor });
    const pageItems = Array.isArray(payload.items) ? payload.items : [];
    items.push(...pageItems);
    page += 1;

    const ratio = expectedTotal > 0 ? Math.min(items.length / expectedTotal, 1) : Math.min(page / 5, 0.95);
    const overall = Math.min(progressOffset + ratio * progressSpan, 0.99);
    elements.progressBar.value = Math.round(overall * 100);
    elements.progressText.textContent = `Loading ${kind}: ${formatNumber(items.length)}${expectedTotal ? ` / ${formatNumber(expectedTotal)}` : ''}`;

    cursor = payload.next_cursor || null;
    if (cursor) {
      if (seenCursors.has(cursor)) throw new Error(`The ${kind} pagination cursor repeated. Scan stopped to prevent duplicate API charges.`);
      seenCursors.add(cursor);
    }
  } while (cursor);

  return items;
}

function storageKey() {
  return state.profile ? `followcheck_handled_${state.profile.username.toLowerCase()}` : '';
}

function loadHandled() {
  try {
    state.handled = new Set(JSON.parse(localStorage.getItem(storageKey()) || '[]'));
  } catch (_) {
    state.handled = new Set();
  }
}

function saveHandled() {
  if (storageKey()) localStorage.setItem(storageKey(), JSON.stringify([...state.handled]));
}

async function scan(handle) {
  setLoading(true);
  setStatus('');
  elements.progressBar.value = 2;
  elements.progressText.textContent = 'Checking profile…';

  try {
    const profilePayload = await apiFetch('/api/profile', { handle });
    state.profile = profilePayload.profile;

    if (state.profile.is_private) {
      throw Object.assign(new Error('This account is private. Username-only scanning only works for public Instagram accounts.'), { code: 'private_account' });
    }

    elements.progressBar.value = 5;
    const followersExpected = Number(state.profile.followers || 0);
    const followingExpected = Number(state.profile.following || 0);

    state.following = await fetchAll('following', handle, followingExpected, 0.05, 0.42);
    state.followers = await fetchAll('followers', handle, followersExpected, 0.47, 0.52);

    state.results = compareRelationships(state.followers, state.following);
    state.selected.clear();
    state.activeTab = 'notFollowingBack';
    state.search = '';
    elements.search.value = '';
    loadHandled();

    elements.progressBar.value = 100;
    elements.progressText.textContent = 'Done';
    renderResults();
    history.replaceState({}, '', `#${encodeURIComponent(state.profile.username)}`);
  } catch (error) {
    if (error.status === 401 || error.code === 'access_code_required') {
      setStatus('This FollowCheck site requires an access code. Open Settings and enter the code shared by the site owner.', 'error');
      elements.accessCode.value = state.accessCode;
      elements.settingsDialog.showModal();
    } else if (error.code === 'scan_too_large') {
      setStatus(error.message, 'error');
    } else {
      setStatus(error.message || 'Unable to scan that account.', 'error');
    }
  } finally {
    setLoading(false);
  }
}

function renderResults() {
  elements.landing.hidden = true;
  elements.results.hidden = false;

  const p = state.profile;
  elements.profileAvatar.src = p.profile_pic_url || avatarFallback(p.username);
  elements.profileAvatar.onerror = () => { elements.profileAvatar.src = avatarFallback(p.username); };
  elements.profileName.textContent = p.full_name || p.username;
  elements.profileHandle.textContent = `@${p.username}`;

  elements.statFollowers.textContent = formatNumber(state.results.followers.length);
  elements.statFollowing.textContent = formatNumber(state.results.following.length);
  elements.statMutuals.textContent = formatNumber(state.results.mutuals.length);
  elements.statNonfollowers.textContent = formatNumber(state.results.notFollowingBack.length);

  $$('.tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === state.activeTab));
  renderList();
}

function currentItems() {
  if (!state.results) return [];
  return filterRelationships(state.results[state.activeTab] || [], state.search);
}

function avatarFallback(username) {
  const letter = encodeURIComponent((username || '?').slice(0, 1).toUpperCase());
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="100%" height="100%" rx="48" fill="#202124"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#fff" font-family="Arial" font-size="38" font-weight="700">${letter}</text></svg>`)}`;
}

function renderList() {
  const items = currentItems();
  const selectable = state.activeTab === 'notFollowingBack';
  elements.list.innerHTML = '';
  elements.empty.hidden = items.length > 0;

  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const card = document.createElement('article');
    card.className = `account-card${state.handled.has(item.username.toLowerCase()) ? ' handled' : ''}`;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'account-select';
    checkbox.setAttribute('aria-label', `Select @${item.username}`);
    checkbox.checked = state.selected.has(item.username.toLowerCase());
    checkbox.hidden = !selectable;
    checkbox.addEventListener('change', () => toggleSelection(item.username, checkbox.checked));

    const avatar = document.createElement('img');
    avatar.className = 'account-avatar';
    avatar.alt = '';
    avatar.loading = 'lazy';
    avatar.referrerPolicy = 'no-referrer';
    avatar.src = item.profile_pic_url || avatarFallback(item.username);
    avatar.onerror = () => { avatar.src = avatarFallback(item.username); };

    const identity = document.createElement('div');
    identity.className = 'account-identity';
    const top = document.createElement('div');
    top.className = 'account-name-row';
    const username = document.createElement('strong');
    username.textContent = `@${item.username}`;
    top.append(username);
    if (item.is_verified) {
      const verified = document.createElement('span');
      verified.className = 'verified';
      verified.title = 'Verified';
      verified.textContent = '✓';
      top.append(verified);
    }
    if (state.handled.has(item.username.toLowerCase())) {
      const done = document.createElement('span');
      done.className = 'done-pill';
      done.textContent = 'Handled';
      top.append(done);
    }
    const fullName = document.createElement('span');
    fullName.className = 'full-name';
    fullName.textContent = item.full_name || (item.is_private ? 'Private account' : 'Instagram account');
    identity.append(top, fullName);

    const open = document.createElement('a');
    open.className = 'secondary-button compact';
    open.href = `https://www.instagram.com/${encodeURIComponent(item.username)}/`;
    open.target = '_blank';
    open.rel = 'noopener noreferrer';
    open.textContent = 'Instagram';

    card.append(checkbox, avatar, identity, open);
    fragment.append(card);
  }
  elements.list.append(fragment);
  renderSelectionBar();
}

function toggleSelection(username, selected) {
  const key = username.toLowerCase();
  if (selected) state.selected.add(key); else state.selected.delete(key);
  renderSelectionBar();
}

function renderSelectionBar() {
  const count = state.selected.size;
  elements.selectionBar.hidden = state.activeTab !== 'notFollowingBack' || count === 0;
  elements.selectionCount.textContent = `${formatNumber(count)} selected`;
  elements.startQueue.disabled = count === 0;
}

function selectVisible() {
  for (const item of currentItems()) state.selected.add(item.username.toLowerCase());
  renderList();
}

function clearSelection() {
  state.selected.clear();
  renderList();
}

function startQueue() {
  const byName = new Map(state.results.notFollowingBack.map((item) => [item.username.toLowerCase(), item]));
  state.queue = [...state.selected].map((key) => byName.get(key)).filter(Boolean);
  state.queueIndex = 0;
  if (!state.queue.length) return;
  renderQueue();
  elements.queueDialog.showModal();
}

function renderQueue() {
  const item = state.queue[state.queueIndex];
  if (!item) {
    elements.queueDialog.close();
    renderList();
    return;
  }
  elements.queueAvatar.src = item.profile_pic_url || avatarFallback(item.username);
  elements.queueAvatar.onerror = () => { elements.queueAvatar.src = avatarFallback(item.username); };
  elements.queueName.textContent = item.full_name || item.username;
  elements.queueHandle.textContent = `@${item.username}`;
  elements.queueCounter.textContent = `${state.queueIndex + 1} of ${state.queue.length}`;
  elements.openInstagram.href = `https://www.instagram.com/${encodeURIComponent(item.username)}/`;
  elements.markDone.textContent = state.handled.has(item.username.toLowerCase()) ? 'Marked handled ✓' : 'Mark handled';
  elements.markDone.classList.toggle('success', state.handled.has(item.username.toLowerCase()));
  elements.queuePrev.disabled = state.queueIndex === 0;
  elements.queueNext.textContent = state.queueIndex === state.queue.length - 1 ? 'Finish' : 'Next';
}

function markQueueHandled() {
  const item = state.queue[state.queueIndex];
  if (!item) return;
  const key = item.username.toLowerCase();
  if (state.handled.has(key)) state.handled.delete(key); else state.handled.add(key);
  saveHandled();
  renderQueue();
}

function queueStep(delta) {
  const next = state.queueIndex + delta;
  if (next >= state.queue.length) {
    elements.queueDialog.close();
    renderList();
    return;
  }
  state.queueIndex = Math.max(0, next);
  renderQueue();
}

function exportCsv() {
  if (!state.results || !state.profile) return;
  const rows = [['username', 'full_name', 'verified', 'private', 'handled']];
  for (const item of state.results.notFollowingBack) {
    rows.push([
      item.username,
      item.full_name,
      String(item.is_verified),
      String(item.is_private),
      String(state.handled.has(item.username.toLowerCase()))
    ]);
  }
  const csv = rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${state.profile.username}-not-following-back.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function reset() {
  state.profile = null;
  state.followers = [];
  state.following = [];
  state.results = null;
  state.selected.clear();
  elements.results.hidden = true;
  elements.landing.hidden = false;
  elements.username.value = '';
  setStatus('');
  history.replaceState({}, '', location.pathname + location.search);
  elements.username.focus();
}

elements.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const handle = normalizeHandle(elements.username.value);
  if (!/^[A-Za-z0-9._]{1,30}$/.test(handle)) {
    setStatus('Enter a valid Instagram username or profile link.', 'error');
    return;
  }
  scan(handle);
});

elements.tabs.addEventListener('click', (event) => {
  const button = event.target.closest('[data-tab]');
  if (!button || !state.results) return;
  state.activeTab = button.dataset.tab;
  state.selected.clear();
  renderResults();
});

elements.search.addEventListener('input', () => {
  state.search = elements.search.value;
  renderList();
});

elements.selectVisible.addEventListener('click', selectVisible);
elements.clearSelection.addEventListener('click', clearSelection);
elements.startQueue.addEventListener('click', startQueue);
elements.exportCsv.addEventListener('click', exportCsv);
elements.newScan.addEventListener('click', reset);
elements.queuePrev.addEventListener('click', () => queueStep(-1));
elements.queueNext.addEventListener('click', () => queueStep(1));
elements.markDone.addEventListener('click', markQueueHandled);
elements.closeQueue.addEventListener('click', () => { elements.queueDialog.close(); renderList(); });

elements.settings.addEventListener('click', () => {
  elements.accessCode.value = state.accessCode;
  elements.settingsDialog.showModal();
});

elements.settingsForm.addEventListener('submit', (event) => {
  event.preventDefault();
  state.accessCode = elements.accessCode.value.trim();
  if (state.accessCode) localStorage.setItem('followcheck_access_code', state.accessCode);
  else localStorage.removeItem('followcheck_access_code');
  elements.settingsDialog.close();
  setStatus(state.accessCode ? 'Access code saved on this device.' : 'Access code cleared.', 'success');
});

for (const button of $$('[data-close-dialog]')) {
  button.addEventListener('click', () => button.closest('dialog').close());
}

const initial = decodeURIComponent(location.hash.replace(/^#/, '')).trim();
if (/^[A-Za-z0-9._]{1,30}$/.test(initial)) elements.username.value = initial;
