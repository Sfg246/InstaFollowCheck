# FollowCheck v3 backend

The v3 backend uses an **anonymous public-web data source** plus a persistent shared SQLite cache. It does not require an Instagram account or a paid data-provider key.

## Runtime endpoints

- `GET /health` — public service/data-source health
- `POST /api/profile` — public profile lookup
- `POST /api/list` — one followers/following page
- `POST /api/probe` — controlled profile + first-page capability test
- `GET /api/cache/{handle}` — cache/snapshot diagnostics

All `/api/*` endpoints are protected by `ACCESS_CODE` when one is configured. `/health` remains unauthenticated so the frontend can display cooldown state.

## Safety behavior

The public-web gateway deliberately has conservative behavior:

- no Instagram credentials or authenticated session
- no automatic HTTP retries
- serialized Instagram-origin requests
- fixed minimum interval between origin requests
- 401/403/429 immediately stop new origin requests and start cooldown
- no proxy rotation or anti-bot bypass logic
- public targets only
- no follow/unfollow actions

## Shared cache

`GraphStore` persists to `/data/followcheck.db` by default. Profiles and relationship pages use independent TTLs. Relationship identities are also deduplicated into graph tables for diagnostics and future cache/history work.

## Run with Docker

```bash
cp server/.env.example server/.env
# set ACCESS_CODE before exposing the service publicly

docker compose up -d --build
curl http://127.0.0.1:8787/health
```

A healthy idle service reports roughly:

```json
{
  "ok": true,
  "service": "followcheck-public-web",
  "ready": true,
  "mode": "public_web",
  "authenticated": false,
  "cooldown_seconds": 0,
  "last_error": null
}
```

## Probe before enabling normal scans

Use one small public account and the access code:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-FollowCheck-Code: YOUR_CODE' \
  -d '{"handle":"instagram"}' \
  http://127.0.0.1:8787/api/probe
```

Do not repeatedly probe after a 401, 403, or 429. The backend will expose the remaining cooldown through `/health`.
