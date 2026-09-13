# FollowCheck

Mobile-first web app for checking a **public Instagram account** and finding:

- Accounts you follow that do not follow you back
- Mutual followers
- Followers you do not follow back
- Search/filter results
- Multi-select
- A phone-friendly manual unfollow queue
- CSV export
- Local "handled" tracking per scanned account

FollowCheck never asks your friends for their Instagram password and does **not** automate mass-unfollowing. The queue opens selected Instagram profiles so the user remains in control.

## Architecture

```text
Phone / browser
      |
      v
GitHub Pages frontend
      |
      v
Your self-hosted FollowCheck API
      |
      v
One dedicated Instagram collector session
```

There is **no paid Instagram data-provider API key and no per-request credit system**. The backend uses `instagrapi` with a dedicated Instagram account, saves the authenticated session, and reuses it between restarts.

## What changed from the first V1 backend

The original Cloudflare Worker + `instagramapi.dev` provider has been removed. The replacement lives in `server/` and keeps the same `/api/profile` and `/api/list` interface, so the mobile frontend and comparison engine stay simple.

## Run tests

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

## Deploy

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Important limitations

- Username-only scanning is intentionally limited to **public Instagram accounts**.
- A dedicated Instagram collector account is required on the server. This is an Instagram login, not an API key.
- Instagram can still throttle, challenge, or invalidate the collector session. No implementation can promise unlimited access to Instagram itself.
- FollowCheck serializes Instagram requests, adds randomized delays, caches pages, and enters a cooldown on throttling instead of retrying aggressively.
- FollowCheck does not bypass privacy settings and does not automate bulk unfollow actions.
- `instagrapi` is an unofficial Instagram interface, so Instagram changes can require maintenance.

## Security

- Never commit `server/.env` or the saved Instagram session.
- Use a **dedicated collector Instagram account**, not your main account.
- Keep the API bound to localhost behind HTTPS/reverse proxy.
- Keep `ALLOWED_ORIGINS` restricted to your FollowCheck site.
- Enable `ACCESS_CODE` if you share the public site broadly.

## License

MIT. See `LICENSE`.
