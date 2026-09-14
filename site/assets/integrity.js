(() => {
  const originalFetch = window.fetch.bind(window);
  const scans = new Map();

  function key(handle, kind) {
    return `${String(handle || '').toLowerCase()}:${kind}`;
  }

  function getBody(args) {
    try {
      const options = args[1] || {};
      return options.body ? JSON.parse(options.body) : null;
    } catch (_) {
      return null;
    }
  }

  function getPath(input) {
    try {
      const raw = typeof input === 'string' ? input : input?.url;
      return new URL(raw, location.href).pathname;
    } catch (_) {
      return '';
    }
  }

  function jsonResponse(payload, status = 409) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  window.fetch = async (...args) => {
    const path = getPath(args[0]);
    const body = getBody(args);
    const response = await originalFetch(...args);

    if (!response.ok || !body) return response;

    if (path.endsWith('/api/profile')) {
      try {
        const payload = await response.clone().json();
        const profile = payload?.profile;
        if (profile?.username) {
          const handle = String(profile.username).toLowerCase();
          scans.set(key(handle, 'followers'), {
            expected: Number(profile.followers || 0),
            users: new Set()
          });
          scans.set(key(handle, 'following'), {
            expected: Number(profile.following || 0),
            users: new Set()
          });
        }
      } catch (_) {}
      return response;
    }

    if (!path.endsWith('/api/list') || !body.handle || !body.kind) return response;

    try {
      const payload = await response.clone().json();
      const scanKey = key(body.handle, body.kind);
      let scan = scans.get(scanKey);
      if (!scan) {
        scan = { expected: 0, users: new Set() };
        scans.set(scanKey, scan);
      }

      if (!body.cursor) scan.users.clear();

      for (const item of Array.isArray(payload?.items) ? payload.items : []) {
        const identity = String(item?.id || item?.username || '').toLowerCase();
        if (identity) scan.users.add(identity);
      }

      if (!payload?.next_cursor && scan.expected > 0 && scan.users.size !== scan.expected) {
        return jsonResponse({
          error: {
            code: 'incomplete_snapshot',
            message: `Instagram ended ${body.kind} pagination at ${scan.users.size} of ${scan.expected}. FollowCheck stopped instead of showing an incomplete comparison.`
          }
        });
      }
    } catch (_) {}

    return response;
  };
})();
