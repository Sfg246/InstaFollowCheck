# FollowCheck V3.1 deployment

FollowCheck has two pieces:

1. `site/` — static phone-first frontend deployed by GitHub Pages.
2. `server/` — self-hosted FastAPI service using anonymous Instagram public-web requests and a shared SQLite cache.

There is no Instagram collector-account login step.

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

Do not put an Instagram password or `sessionid` in V3.1 configuration.

## 2. Start locally only

```bash
docker compose up -d --build
docker compose logs --tail=100 followcheck-api
curl -sS http://127.0.0.1:8787/health
```

The API remains bound to `127.0.0.1:8787`. The Docker volume persists `/data/followcheck.db`.

A healthy response should include:

```json
{
  "mode": "public_web",
  "authenticated": false
}
```

## 3. Run one controlled profile-HTML probe

Keep the public tunnel off. If `ACCESS_CODE` is enabled, read it privately in the shell rather than placing it in chat/history:

```bash
read -rsp "FollowCheck access code: " FCODE
echo

curl -sS \
  -H "Content-Type: application/json" \
  -H "X-FollowCheck-Code: $FCODE" \
  -d '{"handle":"example","profile_strategy":"profile_html","include_relationships":true}' \
  http://127.0.0.1:8787/api/probe

echo
unset FCODE
```

Interpretation:

- `profile_strategies.profile_html.ok=true` — ordinary logged-out profile HTML exposed enough embedded data to resolve the public user.
- `followers.ok=true` — first anonymous followers GraphQL page worked.
- `following.ok=true` — first anonymous following GraphQL page worked.
- `401`, `403`, or `429` — stop. Do not immediately try another strategy.

The cold probe makes at most three Instagram-origin requests and never paginates beyond the first relationship page.

## 4. Test the other profile strategy independently

Only after any active cooldown has expired, the JSON profile-info strategy can be tested by changing:

```json
"profile_strategy": "web_profile_info"
```

A probe does not automatically chain these strategies. This is intentional so a block on one surface does not trigger another request.

## 5. HTTPS

GitHub Pages is HTTPS, so the API must also be HTTPS. Keep the service on localhost and publish it through a reverse proxy or tunnel only after the local capability test is understood.

Example:

```text
https://followcheck-api.example.com
```

Then update `site/config.js`.

## 6. Cache behavior

Fresh cached pages are reused across visitors. Default settings:

```env
PROFILE_CACHE_TTL_SECONDS=3600
RELATIONSHIP_CACHE_TTL_SECONDS=3600
PUBLIC_PAGE_SIZE=25
PUBLIC_MIN_REQUEST_INTERVAL_SECONDS=2.0
PUBLIC_COOLDOWN_SECONDS=900
PUBLIC_MAX_HTML_BYTES=3000000
```

These settings reduce origin traffic. They are not a mechanism for bypassing Instagram restrictions.

## 7. Public exposure checklist

Before turning a public tunnel back on:

- backend tests pass
- `ACCESS_CODE` is set if desired
- `/health` reports `mode=public_web` and `authenticated=false`
- no Instagram credentials are required by the container
- controlled probe behavior is understood
- FastAPI `/docs`, `/redoc`, and `/openapi.json` return 404
- frontend points to the HTTPS API URL
- incomplete relationship snapshots are rejected

## 8. Rollback

If Instagram's logged-out public surfaces do not expose complete relationship data, stop the public API/tunnel. Do not automatically switch back to the retired authenticated collector.
