# FollowCheck deployment

FollowCheck has two pieces:

1. `site/` — the static phone-first frontend on GitHub Pages.
2. `server/` — the self-hosted Python API that maintains one dedicated Instagram collector session.

## 1. Create a dedicated Instagram collector account

Do not use your main Instagram account. Create a normal secondary account specifically for FollowCheck. The backend only performs read operations, but Instagram can still challenge or rate-limit an automated session.

If you use authenticator-app 2FA on the collector, the backend supports an optional TOTP secret through `INSTAGRAM_TOTP_SECRET`.

## 2. Configure the backend

On the server that will host FollowCheck:

```bash
git clone https://github.com/Sfg246/InstaFollowCheck.git
cd InstaFollowCheck
cp server/.env.example server/.env
nano server/.env
```

At minimum set:

```env
INSTAGRAM_USERNAME=your_dedicated_collector
INSTAGRAM_PASSWORD=your_collector_password
ALLOWED_ORIGINS=https://sfg246.github.io
```

Optionally set an `ACCESS_CODE` for friends. Do not commit `server/.env`.

## 3. Start it

```bash
docker compose up -d --build
docker compose logs -f followcheck-api
```

Check locally:

```bash
curl http://127.0.0.1:8787/health
```

A healthy response has `"ready": true`.

The Docker volume persists `/data/instagram-session.json`. On later restarts the same Instagram device/session settings are loaded and validated instead of starting from a fresh identity.

## 4. Give the backend HTTPS

GitHub Pages is HTTPS, so browsers will block an HTTP API. Put a reverse proxy or tunnel in front of `127.0.0.1:8787`.

Good options are Caddy/Nginx/Traefik with your own domain, or a Cloudflare Tunnel. The backend itself stays bound to localhost.

Example final API address:

```text
https://followcheck-api.example.com
```

## 5. Point the frontend to it

Edit `site/config.js`:

```js
window.FOLLOWCHECK_CONFIG = {
  apiBaseUrl: 'https://followcheck-api.example.com',
  appName: 'FollowCheck'
};
```

Commit and push. The existing GitHub Pages workflow republishes the site.

## 6. First-login challenges

Instagram may ask you to approve the collector login in the official app or web UI. If `/health` reports a challenge:

1. Sign into the dedicated collector account normally.
2. Complete Instagram's verification prompt.
3. Restart the backend with `docker compose restart followcheck-api`.
4. Keep the server on the same stable IP and keep the persisted session volume.

Do not put the backend into rapid login/retry loops.

## 7. How the no-provider design protects the account

- One Instagram session only, serialized through a global lock.
- `instagrapi` randomized request delay of 1–3 seconds.
- Relationship pages request up to 200 entries at a time.
- 10-minute response cache by default.
- 15-minute automatic cooldown on Instagram 429 / wait responses.
- Public targets only.
- No automatic follow/unfollow actions.

These controls do not impose paid credits or a fixed scan quota. They exist because Instagram itself can rate-limit automated access.
