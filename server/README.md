# FollowCheck self-hosted backend

This backend replaces the paid Instagram-data provider. It uses one dedicated Instagram collector account through `instagrapi`, stores and reuses the session, and exposes the same `/api/profile` and `/api/list` contract the phone UI already uses.

## Why a collector account is still required

Instagram does not provide the complete follower/following username lists through its supported public API. The self-hosted option therefore needs an authenticated Instagram session. Use a dedicated account, not your personal account.

## Run with Docker

```bash
cp server/.env.example server/.env
# edit server/.env with the dedicated collector account credentials
docker compose up -d --build
curl http://127.0.0.1:8787/health
```

The session is persisted in the Docker volume. `instagrapi` loads it on restart and validates/reuses it instead of doing a fresh login each time.

## Public HTTPS

The GitHub Pages frontend is HTTPS, so the backend must also be reachable over HTTPS. Put Caddy, Nginx, Traefik, or a Cloudflare Tunnel in front of `127.0.0.1:8787`, then set `site/config.js` to that HTTPS URL.

## Safety behavior

- Public accounts only. Private targets are refused even if the collector could view them.
- No mass-unfollow API is implemented. The frontend only opens profiles for the user to act on manually.
- Instagram calls are serialized through one session.
- The client uses 1–3 second randomized delays.
- Successful pages are cached for 10 minutes by default.
- On Instagram 429/temporary-wait responses, the backend enters a cooldown instead of hammering retries.
- An optional `ACCESS_CODE` can keep random visitors from using your collector.

There is no third-party API key and no per-scan credit bill. Instagram itself can still rate-limit, challenge, or invalidate the collector session.
