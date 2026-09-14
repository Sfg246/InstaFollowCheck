# FollowCheck

FollowCheck is a mobile-first web app for comparing a **public Instagram account's** followers and following lists.

It provides:

- accounts followed by the target that do not follow back
- mutuals
- followers the target does not follow back
- search/filtering
- multi-select
- a manual unfollow queue that opens Instagram profiles
- CSV export
- local handled-state tracking
- scan progress and live ETA
- completeness checks that refuse partial comparisons

FollowCheck does not automate mass-unfollowing.

## V3 architecture: anonymous public web

```text
Phone / browser
      |
      v
GitHub Pages frontend
      |
      v
Self-hosted FollowCheck API
      |
      +--> persistent shared SQLite graph/page cache
      |
      v
Instagram public-web surfaces
(no Instagram login/session configured)
```

V3 intentionally removes the authenticated collector from the runtime path. The backend does not need an Instagram username, password, `sessionid`, TOTP secret, proxy fleet, or paid provider key.

The public-web path is **opportunistic, not guaranteed**. Instagram can change or disable these surfaces or rate-limit anonymous access. FollowCheck treats 401/403/429 as a stop condition and never implements proxy rotation, fingerprint rotation, login-account rotation, or retry loops intended to defeat those controls.

## PublicWebProbe

The backend contains a controlled capability probe:

```http
POST /api/probe
{"handle":"instagram"}
```

It attempts at most:

1. one public profile request
2. the first public followers page
3. the first public following page

There are no automatic HTTP retries. If Instagram blocks or rate-limits the probe, it stops immediately and enters cooldown.

## Shared cache

`server/app/graph_store.py` stores recent public profile/page responses in SQLite and deduplicates relationship identities into a lightweight graph table. Repeated scans can reuse fresh cached pages instead of asking Instagram again.

Default cache TTLs are one hour and are configurable in `server/.env`.

## Completeness protection

The frontend remembers the follower/following counts reported by the profile response. If pagination ends before the same number of unique identities has been loaded, FollowCheck returns an **incomplete snapshot** error rather than calculating a misleading result.

## Tests

Frontend:

```bash
npm test
```

Backend:

```bash
cd server
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -v
```

Backend tests use `httpx.MockTransport`; CI does not contact Instagram.

## Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and [`docs/PUBLIC_WEB_PROBE.md`](docs/PUBLIC_WEB_PROBE.md).

## Important limitations

- Public accounts only.
- Public-web follower/following pagination may be unavailable, incomplete, or changed by Instagram without notice.
- There is no promise of unlimited Instagram-origin traffic. The cache can make repeated FollowCheck searches cheap/free from an origin-request perspective, but Instagram still controls uncached public-web access.
- No private-account bypass exists.
- No automated follow/unfollow endpoint exists.

## Security

- Keep `server/.env` out of Git.
- Use an `ACCESS_CODE` on an internet-facing instance.
- Keep the API bound to localhost and publish it only through HTTPS.
- Keep `ALLOWED_ORIGINS` restricted to the FollowCheck frontend.
- Automatic FastAPI docs/OpenAPI endpoints are disabled in production code.

## License

MIT. See `LICENSE`.
