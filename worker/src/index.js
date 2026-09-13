const PROVIDER_BASE = 'https://api.instagramapi.dev/v1';
const HANDLE_RE = /^[A-Za-z0-9._]{1,30}$/;
const LIST_KINDS = new Set(['followers', 'following']);

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      ...extraHeaders
    }
  });
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

function corsHeaders(request, env) {
  const origin = request.headers.get('Origin') || '';
  const configured = String(env.ALLOWED_ORIGINS || '*').split(',').map((s) => s.trim()).filter(Boolean);
  const allowAll = configured.includes('*');
  const allowed = allowAll || !origin || configured.includes(origin);
  return {
    allowed,
    headers: {
      'Access-Control-Allow-Origin': allowAll ? '*' : (allowed && origin ? origin : configured[0] || ''),
      'Access-Control-Allow-Methods': 'POST,GET,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-FollowCheck-Code',
      'Access-Control-Max-Age': '86400',
      'Vary': 'Origin'
    }
  };
}

function requireAccess(request, env) {
  const expected = String(env.ACCESS_CODE || '').trim();
  if (!expected) return true;
  const supplied = request.headers.get('X-FollowCheck-Code') || '';
  return timingSafeEqual(expected, supplied);
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i += 1) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

async function parseBody(request) {
  try { return await request.json(); }
  catch (_) { return {}; }
}

async function providerFetch(path, params, env) {
  if (!env.INSTAGRAMAPI_KEY) {
    return { ok: false, status: 500, body: { error: { code: 'provider_not_configured', message: 'The server is missing INSTAGRAMAPI_KEY.' } } };
  }

  const url = new URL(`${PROVIDER_BASE}${path}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }

  let response;
  try {
    response = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${env.INSTAGRAMAPI_KEY}` },
      cf: { cacheTtl: 0, cacheEverything: false }
    });
  } catch (_) {
    return { ok: false, status: 502, body: { error: { code: 'provider_unreachable', message: 'The Instagram data provider could not be reached.' } } };
  }

  let body = {};
  try { body = await response.json(); } catch (_) {}
  return { ok: response.ok, status: response.status, body };
}

function mapProviderError(result) {
  const code = result.body?.error?.code || 'provider_error';
  const messageMap = {
    invalid_api_key: 'The FollowCheck data provider key is invalid.',
    insufficient_credits: 'The FollowCheck data provider is out of credits.',
    not_found: 'No public data is available for that account. It may be private, deleted, or nonexistent.',
    upstream_error: 'Instagram data is temporarily unavailable. Try again shortly.',
    upstream_timeout: 'Instagram data timed out. Try again shortly.'
  };
  return {
    error: {
      code,
      message: messageMap[code] || result.body?.error?.message || 'The Instagram data provider returned an error.'
    }
  };
}

function cleanItem(item = {}) {
  return {
    id: item.id == null ? '' : String(item.id),
    username: String(item.username || ''),
    full_name: String(item.full_name || ''),
    is_verified: Boolean(item.is_verified),
    is_private: Boolean(item.is_private),
    profile_pic_url: String(item.profile_pic_url || '')
  };
}

async function handleProfile(request, env) {
  const body = await parseBody(request);
  const handle = normalizeHandle(body.handle);
  if (!HANDLE_RE.test(handle)) return json({ error: { code: 'invalid_handle', message: 'Enter a valid Instagram username.' } }, 400);

  const result = await providerFetch('/profile', { handle }, env);
  if (!result.ok) return json(mapProviderError(result), result.status >= 400 && result.status < 600 ? result.status : 502);

  const p = result.body?.data || {};
  const maxCombined = Number.parseInt(env.MAX_COMBINED_RELATIONSHIPS || '4000', 10);
  const combined = Number(p.followers || 0) + Number(p.following || 0);
  if (Number.isFinite(maxCombined) && maxCombined > 0 && combined > maxCombined) {
    return json({
      error: {
        code: 'scan_too_large',
        message: `This account has ${combined.toLocaleString()} combined followers/following. This FollowCheck deployment is capped at ${maxCombined.toLocaleString()} to control API cost. The owner can raise MAX_COMBINED_RELATIONSHIPS.`
      }
    }, 413);
  }

  return json({
    profile: {
      id: p.id == null ? '' : String(p.id),
      username: String(p.username || handle),
      full_name: String(p.full_name || ''),
      is_verified: Boolean(p.is_verified),
      is_private: Boolean(p.is_private),
      followers: Number(p.followers || 0),
      following: Number(p.following || 0),
      profile_pic_url: String(p.profile_pic_url || '')
    }
  });
}

async function handleList(request, env) {
  const body = await parseBody(request);
  const handle = normalizeHandle(body.handle);
  const kind = String(body.kind || '');
  const cursor = body.cursor == null ? '' : String(body.cursor);

  if (!HANDLE_RE.test(handle)) return json({ error: { code: 'invalid_handle', message: 'Enter a valid Instagram username.' } }, 400);
  if (!LIST_KINDS.has(kind)) return json({ error: { code: 'invalid_list', message: 'List kind must be followers or following.' } }, 400);
  if (cursor.length > 4096) return json({ error: { code: 'invalid_cursor', message: 'Pagination cursor is too long.' } }, 400);

  const result = await providerFetch(`/profile/${kind}`, { handle, cursor }, env);
  if (!result.ok) return json(mapProviderError(result), result.status >= 400 && result.status < 600 ? result.status : 502);

  const data = result.body?.data || {};
  return json({
    items: Array.isArray(data.items) ? data.items.map(cleanItem).filter((item) => item.username) : [],
    next_cursor: data.next_cursor || null
  });
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (!cors.allowed) return json({ error: { code: 'origin_not_allowed', message: 'This website is not allowed to use this API.' } }, 403, cors.headers);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors.headers });

    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') {
      return json({ ok: true, service: 'followcheck-api' }, 200, cors.headers);
    }

    if (!requireAccess(request, env)) {
      return json({ error: { code: 'access_code_required', message: 'A valid FollowCheck access code is required.' } }, 401, cors.headers);
    }

    let response;
    if (url.pathname === '/api/profile' && request.method === 'POST') response = await handleProfile(request, env);
    else if (url.pathname === '/api/list' && request.method === 'POST') response = await handleList(request, env);
    else response = json({ error: { code: 'not_found', message: 'Route not found.' } }, 404);

    const headers = new Headers(response.headers);
    for (const [key, value] of Object.entries(cors.headers)) headers.set(key, value);
    return new Response(response.body, { status: response.status, headers });
  }
};
