# FollowCheck v3 deployment

FollowCheck has two pieces:

1. `site/` — static phone-first frontend deployed by GitHub Pages.
2. `server/` — self-hosted FastAPI service using anonymous Instagram public-web requests and a shared SQLite cache.

There is no collector-account login step in v3.

## 1. Configure the backend

```bash
git clone https://github.com/Sfg246/InstaFollowCheck.git
cd InstaFollowCheck
cp server/.env.example server/.env
nano server/.env
```

At minimum verify:

```env
ALLOWED_ORIGINS=https://sfg246.github.io
ACCESS_CODE=choose-a-private-site-code
```

Do not put any Instagram password or `sessionid` in v3 configuration.

## 2. Start it locally only

```bash
docker compose up -d --build
docker compose logs --tail=100 followcheck-api
curl -sS http://127.0.0.1:8787/health
```

The API remains bound to `127.0.0.1:8787`. The Docker volume persists `/data/followcheck.db`.

## 3. Run the controlled public-web probe

Before exposing the frontend, test exactly one small public username:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-FollowCheck-Code: YOUR_CODE' \
  -d '{"handle":"instagram"}' \
  http://127.0.0.1:8787/api/probe
```

Interpretation:

- `profile.ok=true` — anonymous public profile lookup worked.
- `followers.ok=true` — first anonymous followers page worked.
- `following.ok=true` — first anonymous following page worked.
- 401/403/429 — stop. Do not retry repeatedly. Check `/health` for cooldown.

The probe never paginates and never retries automatically.

## 4. HTTPS

GitHub Pages is HTTPS, so the API must also be HTTPS. Keep the service on localhost and publish it through a reverse proxy or tunnel.

Example:

```text
https://followcheck-api.example.com
```

Then update `site/config.js`.

## 5. Cache behavior

Fresh cached pages are reused across visitors. Default settings:

```env
PROFILE_CACHE_TTL_SECONDS=3600
RELATIONSHIP_CACHE_TTL_SECONDS=3600
PUBLIC_PAGE_SIZE=25
PUBLIC_MIN_REQUEST_INTERVAL_SECONDS=2.0
PUBLIC_COOLDOWN_SECONDS=900
```

These are conservative service settings, not a mechanism for bypassing Instagram restrictions.

## 6. Public exposure checklist

Before turning the public tunnel back on:

- backend tests pass
- `ACCESS_CODE` is set
- `/health` reports `mode=public_web` and `authenticated=false`
- no `INSTAGRAM_*` credentials are required by the running container
- one controlled `/api/probe` succeeds or returns a clean unsupported/block result
- FastAPI `/docs`, `/redoc`, and `/openapi.json` return 404
- frontend points to the HTTPS API URL

## 7. Rollback

If Instagram public-web relationship pagination is unavailable, stop the public API/tunnel. Do not switch back to the previous authenticated collector automatically. V3 is designed to fail closed rather than risk another Instagram account.
