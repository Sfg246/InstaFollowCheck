# FollowCheck

Mobile-first web app for checking a **public Instagram account** and finding:

- Accounts the target follows that do not follow it back
- Mutuals
- Followers the target does not follow back
- Search/filter results
- Multi-select
- A phone-friendly manual unfollow queue
- CSV export
- Local handled-state tracking

The visitor only enters a public Instagram username/profile URL. FollowCheck never asks visitors for their Instagram password and does **not** automate mass-unfollowing.

## Current architecture — V3.1

```text
Phone / browser
      |
      v
GitHub Pages frontend
      |
      v
Self-hosted FollowCheck API
      |
      +--> shared SQLite cache
      |
      v
Instagram logged-out public web
```

The retired V2 collector architecture is no longer used. The backend does **not** use:

- an Instagram collector account
- Instagram username/password credentials
- `sessionid`
- `instagrapi`
- a paid Instagram-data provider
- a per-request API key

## Public-web strategies

Profile discovery has two anonymous strategies:

1. `profile_html` — the ordinary logged-out public profile page, parsed for embedded server-rendered profile data.
2. `web_profile_info` — Instagram's public profile-info JSON surface.

The normal app prefers `profile_html`. If the HTML request succeeds but contains no usable profile data, it may fall back to `web_profile_info`. It never falls back after an Instagram `401`, `403`, or `429`.

`POST /api/probe` can test the strategies independently so a block on one route does not get confused with proof that every route failed.

Once a public user id is available, the relationship layer tests anonymous public-web GraphQL followers/following pages.

See [`docs/PUBLIC_WEB_PROBE.md`](docs/PUBLIC_WEB_PROBE.md).

## Safety behavior

- Public targets only.
- No authenticated Instagram cookie.
- No proxy/account/device/fingerprint rotation.
- No challenge solving.
- No automatic retry after a block/rate limit.
- Instagram-origin requests are serialized and paced.
- `401`, `403`, or `429` immediately stops the active probe and enters cooldown.
- No automated bulk-follow or bulk-unfollow endpoint exists.
- Incomplete relationship snapshots are rejected rather than presented as correct.

## Cache

Successful public profiles and relationship pages are stored in SQLite so multiple visitors can reuse fresh data without repeating the same Instagram-origin request.

The cache is a traffic-reduction mechanism, not a way to bypass Instagram restrictions.

## Run tests

Frontend:

```bash
npm test
```

Backend:

```bash
cd server
python -m pip install -r requirements.txt
GRAPH_DB_PATH=/tmp/followcheck-test.db PYTHONPATH=. python -m unittest discover -s tests -v
```

## Deploy

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Important limitation

The code can be free and self-hosted, but Instagram controls its own public surfaces. Instagram may throttle, change, restrict, or remove anonymous follower/following access. FollowCheck therefore verifies completeness and fails closed instead of pretending an incomplete list is correct.

## License

MIT. See `LICENSE`.
