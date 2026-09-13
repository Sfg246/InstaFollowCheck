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

FollowCheck never asks for an Instagram password and does **not** automate mass-unfollowing. The unfollow queue opens each selected Instagram profile so the user remains in control.

## Architecture

```text
Phone / browser
      |
      v
GitHub Pages frontend
      |
      v
Cloudflare Worker
      |
      v
instagramapi.dev
```

The API key lives only in the Worker secret store. The frontend never receives it.

## V1 stages completed

### Stage 1 — Project setup
- Static GitHub Pages site
- Cloudflare Worker backend
- GitHub Actions Pages workflow
- Tests

### Stage 2 — Instagram lookup
- Public profile lookup
- Followers pagination
- Following pagination
- Private/nonexistent account errors
- Backend-only provider secret
- Origin restriction and optional site access code

### Stage 3 — Comparison engine
- Stable-ID comparison with username fallback
- Duplicate removal
- Non-followers
- Mutuals
- Followers not followed back
- Search

### Stage 4 — Mobile UI
- Responsive dark UI
- Profile summary
- Stats
- Tabs
- Search
- Lazy-loaded avatars
- Progress feedback

### Stage 5 — Selection and unfollow queue
- Individual selection
- Select visible
- Clear selection
- Open profile in Instagram
- Previous/next queue navigation
- Local handled state
- CSV export

### Stage 6 — Test and launch tooling
- Node unit tests
- GitHub Actions test gate
- GitHub Pages deployment workflow
- Privacy page
- CORS
- No-store responses
- Scan-size cost guard
- Deployment guide

## Local test

```bash
npm test
```

For the frontend, serve `site/` with any static server. For the backend:

```bash
cd worker
npm install
npx wrangler dev
```

Then set `site/config.js` to the local Worker URL while developing.

## Deploy

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Important limitations

- Username-only mode works for **public accounts** supported by the configured provider.
- The relationship endpoints are paginated, so larger accounts can consume significant provider credits.
- FollowCheck does not bypass Instagram privacy settings.
- FollowCheck does not automatically click Instagram's unfollow controls or perform mass-unfollowing.
- Instagram/Meta and the third-party data provider can change behavior independently of this project.

## Security notes

- Do not commit `INSTAGRAMAPI_KEY` or `ACCESS_CODE`.
- Keep an access code enabled if the public GitHub Pages link is shared widely.
- Keep `ALLOWED_ORIGINS` restricted to your deployed site.
- Keep a reasonable `MAX_COMBINED_RELATIONSHIPS` to prevent unexpectedly expensive scans.

## License

MIT. See `LICENSE`.
