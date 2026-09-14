# PublicWebProbe design

`PublicWebGateway` exists to answer one question safely: can the current Instagram public web return the data FollowCheck needs without authenticating an Instagram account?

## Probe budget

A cold probe performs at most three Instagram-origin requests:

1. public profile lookup
2. first followers GraphQL page
3. first following GraphQL page

If the profile is private, relationship requests are skipped. If a relationship request receives 401, 403, or 429, the probe stops immediately.

## What it does not do

The probe does not:

- log into Instagram
- send a `sessionid`
- rotate proxies, accounts, devices, user agents, or fingerprints
- retry blocked/rate-limited calls
- solve challenges
- access private profiles
- automate follows or unfollows

## Current public-web strategies

V3 keeps the public identifiers configurable because Instagram changes these surfaces:

- profile: `api/v1/users/web_profile_info/?username=...`
- followers: legacy public GraphQL relationship query
- following: legacy public GraphQL relationship query

A successful first page proves only that the surface is available at that moment. Full pagination still needs separate testing and may be rate-limited.

## Completeness

FollowCheck does not trust a truncated relationship list. The profile count is used as an expected total, and the browser tracks unique identities across pagination. If the final page arrives before the expected total is reached, the scan is rejected as incomplete.

## Cache

The SQLite cache is shared across FollowCheck visitors. A fresh cached profile/page does not make another Instagram-origin request. This is the main mechanism for reducing origin traffic; it is not an attempt to evade a rate limit.
