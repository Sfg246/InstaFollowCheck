# FollowCheck deployment

FollowCheck has two pieces:

1. `site/` — static mobile-first frontend, deployed with GitHub Pages.
2. `worker/` — Cloudflare Worker that keeps the Instagram data-provider key private.

## 1. Create the Instagram data API key

Create an API key at `instagramapi.dev`. The worker currently uses:

- `GET /v1/profile`
- `GET /v1/profile/followers`
- `GET /v1/profile/following`

The follower/following endpoints are paginated. FollowCheck requests every page needed for a complete comparison, so a larger account costs more provider credits.

## 2. Deploy the Cloudflare Worker

From the repo:

```bash
cd worker
npm install
npx wrangler login
npx wrangler secret put INSTAGRAMAPI_KEY
npx wrangler secret put ACCESS_CODE
npm run deploy
```

`ACCESS_CODE` is optional but strongly recommended if friends will use the site, because every scan consumes third-party API credits.

The deployment prints a Worker URL similar to:

```text
https://followcheck-api.<your-subdomain>.workers.dev
```

## 3. Point the frontend at the Worker

Edit `site/config.js`:

```js
window.FOLLOWCHECK_CONFIG = {
  apiBaseUrl: 'https://followcheck-api.<your-subdomain>.workers.dev',
  appName: 'FollowCheck'
};
```

Commit and push.

## 4. Configure allowed origin

The default `worker/wrangler.toml` allows `https://sfg246.github.io`.

If FollowCheck is deployed under a custom domain or a different GitHub account, change `ALLOWED_ORIGINS` and redeploy the Worker.

Multiple origins can be comma-separated.

## 5. Enable GitHub Pages

In the repository:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

The included workflow runs the comparison tests and deploys `site/`.

For a repo named `InstaFollowCheck` under `Sfg246`, the default site URL will be:

```text
https://sfg246.github.io/InstaFollowCheck/
```

## 6. Cost guard

`MAX_COMBINED_RELATIONSHIPS` defaults to `4000` in `worker/wrangler.toml`.

The Worker first checks the public profile counts. If followers + following is above the cap, it rejects the scan before loading the relationship lists. This is a safety control because list endpoints are paginated and bill per request.

Set the value higher if you intentionally want to support larger accounts, or `0` to disable the guard.
