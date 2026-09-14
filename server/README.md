# FollowCheck self-hosted backend

FollowCheck V3.1 is a username-only public-account experiment that uses Instagram's **logged-out public web surfaces**. It does not use an Instagram collector account, visitor Instagram credentials, a `sessionid`, a paid provider, or an API key.

## Architecture

```text
GitHub Pages
    |
    v
FollowCheck FastAPI backend
    |
    +--> shared SQLite cache
    |
    +--> Instagram logged-out public web
```

The frontend keeps the existing `/api/profile` and `/api/list` contract.

## Profile discovery

V3.1 has two anonymous profile strategies:

- `profile_html` — normal logged-out profile HTML + embedded public data parser
- `web_profile_info` — Instagram public profile-info JSON surface

The normal app path prefers `profile_html`. It only falls back to `web_profile_info` after a successful HTML response that contained no usable profile data. It does not fall back after `401`, `403`, or `429`.

`/api/probe` lets the two strategies be tested independently.

## Run with Docker

```bash
cp server/.env.example server/.env
docker compose up -d --build
curl http://127.0.0.1:8787/health
```

A healthy response includes:

```json
{
  "mode": "public_web",
  "authenticated": false
}
```

No Instagram username/password/session file is required.

## Probe one public strategy

If `ACCESS_CODE` is enabled, enter it privately in your terminal and send it as the header. Example request body:

```json
{
  "handle": "example",
  "profile_strategy": "profile_html",
  "include_relationships": true
}
```

A cold relationship probe makes at most one profile request plus one first-page request for followers and one for following. `401`, `403`, or `429` stops the probe immediately.

See `docs/PUBLIC_WEB_PROBE.md` for the response format and safety rules.

## Cache

The Docker volume stores `/data/followcheck.db`. Successful public profiles/pages are shared across visitors for the configured TTL.

The cache stores public relationship data already returned to FollowCheck. It does not contain visitor Instagram credentials.

## Safety behavior

- Public targets only.
- No login or authenticated Instagram cookie.
- No proxy/account/device/fingerprint rotation.
- No challenge solving.
- No automatic HTTP retry.
- Requests are serialized and paced.
- `401`, `403`, and `429` trigger a cooldown.
- No automatic follow/unfollow endpoint exists.
- HTML parsing has a configurable response-size ceiling.

Instagram can change or remove public surfaces at any time. This project cannot promise unlimited access to Instagram itself.
