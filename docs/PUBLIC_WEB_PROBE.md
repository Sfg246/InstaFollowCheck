# PublicWebProbe design

`PublicWebGateway` tests whether Instagram's logged-out public web can provide the data FollowCheck needs without authenticating an Instagram account.

## V3.1 profile strategies

The probe now supports two profile-discovery strategies that can be tested **independently**:

1. `profile_html` — requests the ordinary logged-out public profile page, then searches its embedded JSON/server-rendered data for the matching public user object.
2. `web_profile_info` — requests Instagram's `api/v1/users/web_profile_info` JSON surface.

The default probe strategy is `profile_html`.

A probe never automatically falls from one strategy to the other. This matters because if one surface returns `401`, `403`, or `429`, FollowCheck stops immediately instead of sending another origin request.

The normal `/api/profile` application path is slightly different: it prefers `profile_html`, and only if Instagram returned a successful HTML page that contained no usable profile data will it try `web_profile_info`. A block/rate-limit never triggers fallback.

## Probe budget

A cold probe with relationship testing enabled performs at most three Instagram-origin requests:

1. the explicitly selected profile strategy
2. first followers GraphQL page
3. first following GraphQL page

If the profile is private, relationship requests are skipped. If any request receives `401`, `403`, or `429`, the probe stops immediately.

To test only a profile strategy, send:

```json
{
  "handle": "example",
  "profile_strategy": "profile_html",
  "include_relationships": false
}
```

## Diagnostic response

The response names the selected strategy and reports each strategy separately:

```json
{
  "selected_profile_strategy": "profile_html",
  "profile_strategies": {
    "profile_html": {"selected": true, "ok": true},
    "web_profile_info": {"selected": false, "ok": false, "status": "not_run"}
  }
}
```

This prevents a failure on one profile surface from being mistaken for proof that every public-web strategy failed.

## What it does not do

The probe does not:

- log into Instagram
- send a `sessionid`
- use the retired collector account
- rotate proxies, accounts, devices, user agents, or fingerprints
- retry blocked/rate-limited calls
- solve challenges
- access private profiles
- automate follows or unfollows

## HTML parsing

Instagram changes the wrapper around server-rendered profile data frequently. The HTML strategy therefore does not depend on one JavaScript variable name. It:

- reads JSON-bearing `<script>` payloads
- recursively searches nested JSON for a user whose `username` exactly matches the requested handle
- requires a usable numeric Instagram user id
- extracts public counts/privacy/name/avatar fields when present
- has a conservative raw-text fallback for an exact username with a nearby numeric user id

The HTML response has a configurable size ceiling (`PUBLIC_MAX_HTML_BYTES`, default 3 MB).

## Relationship surface

Once a public user id is known, V3.1 still tests the existing anonymous relationship GraphQL query for:

- followers
- following

A successful profile lookup does **not** prove relationship pagination works. Those are reported separately.

## Completeness

FollowCheck does not trust a truncated relationship list. The profile count is used as the expected total, and the browser tracks unique identities across pagination. If pagination ends before the expected total is reached, the result is rejected as incomplete.

## Cache

Successful profiles and relationship pages are stored in the shared SQLite cache. Normal scans reuse fresh cached data. Capability probes intentionally bypass the cache for the surfaces they are testing so the report describes current origin behavior.

Caching is used to reduce repeated Instagram-origin traffic; it is not used to bypass a restriction or rate limit.
