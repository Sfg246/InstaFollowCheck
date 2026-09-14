from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import os
import re
import time
from typing import Any, Iterable, Literal
from urllib.parse import quote

import httpx

from .errors import GatewayError
from .graph_store import GraphStore

log = logging.getLogger("followcheck.public_web")

ListKind = Literal["followers", "following"]
ProfileStrategy = Literal["profile_html", "topsearch", "web_profile_info"]

PROFILE_INFO_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
TOPSEARCH_URL = "https://www.instagram.com/web/search/topsearch/"
GRAPHQL_URL = "https://www.instagram.com/graphql/query/"
DEFAULT_APP_ID = "936619743392459"
DEFAULT_FOLLOWERS_HASH = "c76146de99bb02f6415203be841dd25a"
DEFAULT_FOLLOWING_HASH = "d04b0a864b4b54837c0d870b0e77e076"

SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)


class PublicWebGateway:
    """Read Instagram surfaces reachable without authenticating an account.

    Safety properties:
    - never accepts or sends an Instagram username/password/sessionid;
    - no proxy, account, device, fingerprint, or cookie rotation;
    - origin requests are serialized and paced;
    - 401/403/429 stops origin traffic and starts a cooldown;
    - zero automatic HTTP retries;
    - probes choose exactly one profile-discovery strategy.
    """

    def __init__(self) -> None:
        self.page_size = max(1, min(int(os.getenv("PUBLIC_PAGE_SIZE", "25")), 50))
        self.min_interval = max(0.0, float(os.getenv("PUBLIC_MIN_REQUEST_INTERVAL_SECONDS", "2.0")))
        self.cooldown_seconds = max(60, int(os.getenv("PUBLIC_COOLDOWN_SECONDS", "900")))
        self.timeout_seconds = max(3.0, float(os.getenv("PUBLIC_HTTP_TIMEOUT_SECONDS", "15")))
        self.max_html_bytes = max(64_000, int(os.getenv("PUBLIC_MAX_HTML_BYTES", "3000000")))
        self.app_id = os.getenv("PUBLIC_IG_APP_ID", DEFAULT_APP_ID).strip() or DEFAULT_APP_ID
        self.followers_hash = os.getenv("PUBLIC_FOLLOWERS_QUERY_HASH", DEFAULT_FOLLOWERS_HASH).strip()
        self.following_hash = os.getenv("PUBLIC_FOLLOWING_QUERY_HASH", DEFAULT_FOLLOWING_HASH).strip()
        self.user_agent = os.getenv(
            "PUBLIC_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        ).strip()
        self.store = GraphStore(
            os.getenv("GRAPH_DB_PATH", "/data/followcheck.db"),
            profile_ttl=int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "3600")),
            page_ttl=int(os.getenv("RELATIONSHIP_CACHE_TTL_SECONDS", "3600")),
        )
        self.lock = asyncio.Lock()
        self.client: httpx.AsyncClient | None = None
        self.ready = False
        self.blocked_until = 0.0
        self.last_request_at = 0.0
        self.last_error = "not initialized"

    async def start(self) -> None:
        if self.client is not None:
            return
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=False,
            headers={
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": self.user_agent,
            },
        )
        self.ready = True
        self.last_error = ""
        log.info("Public web gateway ready (anonymous; no Instagram account/session configured)")

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        self.client = None
        self.ready = False

    def health(self) -> dict[str, Any]:
        retry_after = max(0, int(self.blocked_until - time.time()))
        return {
            "ready": bool(self.ready and self.client is not None and retry_after == 0),
            "mode": "public_web",
            "authenticated": False,
            "profile_strategies": ["profile_html", "topsearch", "web_profile_info"],
            "cooldown_seconds": retry_after,
            "last_error": self.last_error or None,
        }

    async def profile(self, handle: str) -> dict[str, Any]:
        """Resolve a profile with conservative anonymous strategy fallback.

        Fallback only occurs after a successful HTTP response that simply lacked a
        usable exact profile. A 401/403/429 never causes another strategy request.
        """
        cached = self.store.get_profile(handle)
        if cached is not None:
            return {**cached, "cache_hit": True}

        try:
            return await self._profile_html(handle, use_cache=False)
        except GatewayError as exc:
            if exc.code != "public_profile_html_unusable":
                raise

        try:
            return await self._profile_topsearch(handle, use_cache=False)
        except GatewayError as exc:
            if exc.code != "public_topsearch_unusable":
                raise

        return await self._profile_web_info(handle, use_cache=False)

    async def profile_by_strategy(
        self,
        handle: str,
        strategy: ProfileStrategy,
        *,
        use_cache: bool = False,
    ) -> dict[str, Any]:
        if strategy == "profile_html":
            return await self._profile_html(handle, use_cache=use_cache)
        if strategy == "topsearch":
            return await self._profile_topsearch(handle, use_cache=use_cache)
        if strategy == "web_profile_info":
            return await self._profile_web_info(handle, use_cache=use_cache)
        raise GatewayError("invalid_probe_strategy", "Unknown profile probe strategy.", 400)

    async def _profile_html(self, handle: str, *, use_cache: bool) -> dict[str, Any]:
        if use_cache:
            cached = self.store.get_profile(handle)
            if cached is not None:
                return {**cached, "cache_hit": True}

        async with self.lock:
            if use_cache:
                cached = self.store.get_profile(handle)
                if cached is not None:
                    return {**cached, "cache_hit": True}

            page_url = f"https://www.instagram.com/{quote(handle)}/"
            text = await self._request_text(
                page_url,
                params={},
                referer="https://www.instagram.com/",
                context="profile_html",
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            )
            raw_user = self._extract_profile_from_html(text, handle)
            if raw_user is None:
                raise GatewayError(
                    "public_profile_html_unusable",
                    "Instagram returned the logged-out profile page, but it did not contain enough parseable public profile data.",
                    503,
                )

            result = self._profile_result(raw_user, handle, source="profile_html")
            self._cache_profile(handle, result)
            return result

    async def _profile_topsearch(self, handle: str, *, use_cache: bool) -> dict[str, Any]:
        """Resolve an exact username from Instagram's logged-out web search surface."""
        if use_cache:
            cached = self.store.get_profile(handle)
            if cached is not None:
                return {**cached, "cache_hit": True}

        async with self.lock:
            if use_cache:
                cached = self.store.get_profile(handle)
                if cached is not None:
                    return {**cached, "cache_hit": True}

            payload = await self._request_json(
                TOPSEARCH_URL,
                params={"context": "blended", "include_reel": "true", "query": handle},
                referer="https://www.instagram.com/",
                context="profile_topsearch",
                include_app_id=False,
            )
            raw_user = self._exact_topsearch_user(payload, handle)
            if raw_user is None:
                raise GatewayError(
                    "public_topsearch_unusable",
                    "Instagram's logged-out web search response did not contain an exact usable username match.",
                    503,
                )

            result = self._profile_result(raw_user, handle, source="topsearch")
            self._cache_profile(handle, result)
            return result

    async def _profile_web_info(self, handle: str, *, use_cache: bool) -> dict[str, Any]:
        if use_cache:
            cached = self.store.get_profile(handle)
            if cached is not None:
                return {**cached, "cache_hit": True}

        async with self.lock:
            if use_cache:
                cached = self.store.get_profile(handle)
                if cached is not None:
                    return {**cached, "cache_hit": True}

            payload = await self._request_json(
                PROFILE_INFO_URL,
                params={"username": handle},
                referer=f"https://www.instagram.com/{quote(handle)}/",
                context="profile_web_info",
                include_app_id=True,
            )
            raw_user = payload.get("data", {}).get("user") if isinstance(payload, dict) else None
            if not isinstance(raw_user, dict):
                raise GatewayError(
                    "public_profile_unavailable",
                    "Instagram's public profile-info response did not contain usable profile data.",
                    502,
                )
            result = self._profile_result(raw_user, handle, source="web_profile_info")
            self._cache_profile(handle, result)
            return result

    def _cache_profile(self, handle: str, result: dict[str, Any]) -> None:
        self.store.set_profile(handle, {k: v for k, v in result.items() if k != "cache_hit"})

    @staticmethod
    def _exact_topsearch_user(payload: dict[str, Any], handle: str) -> dict[str, Any] | None:
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, list):
            return None
        target = handle.lower()
        for entry in users:
            if not isinstance(entry, dict):
                continue
            user = entry.get("user")
            if not isinstance(user, dict):
                continue
            username = str(user.get("username") or "").strip()
            user_id = str(user.get("pk") or user.get("id") or user.get("user_id") or "").strip()
            if username.lower() == target and user_id.isdigit():
                return user
        return None

    def _profile_result(self, raw_user: dict[str, Any], handle: str, *, source: str) -> dict[str, Any]:
        user_id = str(raw_user.get("id") or raw_user.get("pk") or raw_user.get("user_id") or "")
        username = str(raw_user.get("username") or handle)
        if not user_id or not user_id.isdigit():
            raise GatewayError(
                "public_profile_unavailable",
                "Instagram's public profile response did not include a usable numeric user id.",
                502,
            )
        return {
            "id": user_id,
            "username": username,
            "full_name": str(raw_user.get("full_name") or raw_user.get("name") or ""),
            "is_verified": bool(raw_user.get("is_verified")),
            "is_private": bool(raw_user.get("is_private")),
            "followers": self._count(raw_user, "followers"),
            "following": self._count(raw_user, "following"),
            "profile_pic_url": str(
                raw_user.get("profile_pic_url_hd")
                or raw_user.get("profile_pic_url")
                or raw_user.get("profile_image")
                or ""
            ),
            "source": source,
            "cache_hit": False,
        }

    async def list_page(
        self,
        handle: str,
        kind: ListKind,
        cursor: str = "",
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        if use_cache:
            cached = self.store.get_page(handle, kind, cursor)
            if cached is not None:
                return {**cached, "cache_hit": True}

        profile = self.store.get_profile(handle)
        if profile is None:
            profile_with_marker = await self.profile(handle)
            profile = {k: v for k, v in profile_with_marker.items() if k != "cache_hit"}

        async with self.lock:
            if use_cache:
                cached = self.store.get_page(handle, kind, cursor)
                if cached is not None:
                    return {**cached, "cache_hit": True}

            if profile.get("is_private"):
                raise GatewayError(
                    "private_account",
                    "Username-only scanning only works for public Instagram accounts.",
                    403,
                )

            user_id = str(profile.get("id") or "")
            if not user_id or not user_id.isdigit():
                raise GatewayError("user_not_found", "Instagram account not found.", 404)

            variables: dict[str, Any] = {
                "id": user_id,
                "include_reel": True,
                "fetch_mutual": kind == "followers",
                "first": self.page_size,
            }
            if cursor:
                variables["after"] = cursor

            query_hash = self.followers_hash if kind == "followers" else self.following_hash
            if not query_hash:
                raise GatewayError(
                    "public_relationship_unavailable",
                    "No public relationship query is configured for this FollowCheck build.",
                    503,
                )

            payload = await self._request_json(
                GRAPHQL_URL,
                params={
                    "query_hash": query_hash,
                    "variables": json.dumps(variables, separators=(",", ":")),
                },
                referer=f"https://www.instagram.com/{quote(handle)}/",
                context=kind,
                include_app_id=True,
            )

            edge_name = "edge_followed_by" if kind == "followers" else "edge_follow"
            user = payload.get("data", {}).get("user") if isinstance(payload, dict) else None
            edge = user.get(edge_name) if isinstance(user, dict) else None
            if not isinstance(edge, dict):
                raise GatewayError(
                    "public_relationship_unavailable",
                    "Instagram did not expose that relationship page through its anonymous public web response.",
                    503,
                )

            raw_edges = edge.get("edges")
            if not isinstance(raw_edges, list):
                raw_edges = []
            items: list[dict[str, Any]] = []
            for raw_edge in raw_edges:
                node = raw_edge.get("node") if isinstance(raw_edge, dict) else None
                if not isinstance(node, dict):
                    continue
                cleaned = self._clean_node(node)
                if cleaned["username"]:
                    items.append(cleaned)

            page_info = edge.get("page_info") if isinstance(edge.get("page_info"), dict) else {}
            has_next = bool(page_info.get("has_next_page"))
            next_cursor = str(page_info.get("end_cursor") or "") if has_next else ""
            if has_next and not next_cursor:
                raise GatewayError(
                    "public_pagination_invalid",
                    "Instagram indicated another page exists but did not return a usable cursor.",
                    502,
                )

            profile_count = int(profile.get("followers" if kind == "followers" else "following") or 0)
            try:
                edge_count = max(0, int(edge.get("count") or 0))
            except (TypeError, ValueError):
                edge_count = 0
            expected_count = edge_count or profile_count

            result = {
                "items": items,
                "next_cursor": next_cursor or None,
                "total_count": expected_count,
                "source": "instagram_public_web_graphql",
                "cache_hit": False,
            }
            self.store.set_page(
                handle=handle,
                subject_id=user_id,
                kind=kind,
                cursor=cursor,
                payload={k: v for k, v in result.items() if k != "cache_hit"},
                expected_count=expected_count,
            )

            field = "followers" if kind == "followers" else "following"
            if edge_count > 0 and int(profile.get(field) or 0) <= 0:
                updated_profile = dict(profile)
                updated_profile[field] = edge_count
                self.store.set_profile(handle, updated_profile)

            return result

    async def probe(
        self,
        handle: str,
        profile_strategy: ProfileStrategy = "profile_html",
        *,
        include_relationships: bool = True,
    ) -> dict[str, Any]:
        """Probe one selected profile strategy plus at most one page per relationship."""
        strategies: tuple[ProfileStrategy, ...] = ("profile_html", "topsearch", "web_profile_info")
        report: dict[str, Any] = {
            "handle": handle,
            "mode": "public_web",
            "authenticated": False,
            "selected_profile_strategy": profile_strategy,
            "profile_strategies": {
                name: {"selected": profile_strategy == name, "ok": False, "status": "not_run"}
                for name in strategies
            },
            "profile": {"ok": False},
            "followers": {"ok": False, "status": "not_run"},
            "following": {"ok": False, "status": "not_run"},
        }

        try:
            profile = await self.profile_by_strategy(handle, profile_strategy, use_cache=False)
            profile_report = {
                "ok": True,
                "status": 200,
                "source": profile.get("source"),
                "id": profile.get("id"),
                "followers": profile.get("followers", 0),
                "following": profile.get("following", 0),
                "private": bool(profile.get("is_private")),
                "cache_hit": bool(profile.get("cache_hit")),
            }
            report["profile"] = profile_report
            report["profile_strategies"][profile_strategy] = {"selected": True, **profile_report}
        except GatewayError as exc:
            error = self._probe_error(exc)
            report["profile"] = error
            report["profile_strategies"][profile_strategy] = {"selected": True, **error}
            return report

        if profile.get("is_private") or not include_relationships:
            if not include_relationships:
                report["followers"]["status"] = "skipped"
                report["following"]["status"] = "skipped"
            return report

        for kind in ("followers", "following"):
            try:
                page = await self.list_page(handle, kind, "", use_cache=False)
                report[kind] = {
                    "ok": True,
                    "status": 200,
                    "items": len(page.get("items") or []),
                    "total_count": int(page.get("total_count") or 0),
                    "has_next": bool(page.get("next_cursor")),
                    "cache_hit": bool(page.get("cache_hit")),
                    "source": page.get("source"),
                }
            except GatewayError as exc:
                report[kind] = self._probe_error(exc)
                if exc.status in (401, 403, 429):
                    break
        return report

    def cache_status(self, handle: str) -> dict[str, Any]:
        return self.store.status(handle)

    async def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        referer: str,
        context: str,
        include_app_id: bool = True,
    ) -> dict[str, Any]:
        response = await self._request_response(
            url,
            params=params,
            referer=referer,
            context=context,
            accept="application/json,text/plain,*/*",
            include_app_id=include_app_id,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            self.last_error = f"Instagram public web returned non-JSON for {context}"
            raise GatewayError(
                "public_response_invalid",
                "Instagram returned an unexpected public-web response.",
                502,
            ) from exc
        if not isinstance(payload, dict):
            raise GatewayError(
                "public_response_invalid",
                "Instagram returned an unexpected public-web response.",
                502,
            )
        self.last_error = ""
        return payload

    async def _request_text(
        self,
        url: str,
        *,
        params: dict[str, Any],
        referer: str,
        context: str,
        accept: str,
    ) -> str:
        response = await self._request_response(
            url,
            params=params,
            referer=referer,
            context=context,
            accept=accept,
            include_app_id=False,
        )
        raw = response.content
        if len(raw) > self.max_html_bytes:
            raise GatewayError(
                "public_profile_html_too_large",
                "Instagram's public profile page exceeded FollowCheck's diagnostic size limit.",
                502,
            )
        self.last_error = ""
        return response.text

    async def _request_response(
        self,
        url: str,
        *,
        params: dict[str, Any],
        referer: str,
        context: str,
        accept: str,
        include_app_id: bool,
    ) -> httpx.Response:
        self._ensure_available()
        assert self.client is not None
        self._assert_anonymous_session()
        await self._pace()

        try:
            request_headers = {"Referer": referer, "Accept": accept}
            if include_app_id:
                request_headers["X-IG-App-ID"] = self.app_id
            response = await self.client.get(url, params=params, headers=request_headers)
        except httpx.TimeoutException as exc:
            self.last_error = f"public web {context} request timed out"
            raise GatewayError(
                "public_timeout",
                "Instagram's public web response timed out. No retry was attempted.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            self.last_error = f"public web {context} network error: {type(exc).__name__}"
            raise GatewayError(
                "public_network_error",
                "Instagram's public web endpoint could not be reached.",
                502,
            ) from exc
        finally:
            self.last_request_at = time.monotonic()

        if response.status_code == 404:
            if context.startswith("profile"):
                raise GatewayError("user_not_found", "Instagram account not found.", 404)
            raise GatewayError(
                "public_relationship_unavailable",
                "Instagram's public relationship endpoint is not available for this request.",
                503,
            )

        if response.status_code in (401, 403, 429):
            retry_after = self._retry_after(response)
            self.blocked_until = max(self.blocked_until, time.time() + retry_after)
            self.last_error = f"Instagram public web returned HTTP {response.status_code} during {context}"
            code = "instagram_rate_limited" if response.status_code == 429 else "public_access_blocked"
            message = (
                "Instagram rate-limited anonymous public-web requests. FollowCheck stopped and entered cooldown."
                if response.status_code == 429
                else "Instagram blocked anonymous access to this public-web request. FollowCheck stopped without retrying."
            )
            raise GatewayError(code, message, response.status_code, retry_after)

        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "")
            self.last_error = f"Instagram public web redirected {context}"
            raise GatewayError(
                "public_redirect",
                f"Instagram redirected the anonymous {context} request instead of returning the requested public data."
                + (f" Destination: {location[:160]}" if location else ""),
                503,
            )

        if response.status_code >= 500:
            self.last_error = f"Instagram public web returned HTTP {response.status_code}"
            raise GatewayError(
                "instagram_unavailable",
                "Instagram's public web service is temporarily unavailable.",
                502,
            )

        if response.status_code >= 400:
            self.last_error = f"Instagram public web returned HTTP {response.status_code}"
            raise GatewayError(
                "public_surface_unavailable",
                "Instagram did not accept this anonymous public-web request.",
                503,
            )
        return response

    def _assert_anonymous_session(self) -> None:
        if self.client is None:
            return
        auth_names = {"sessionid", "ds_user_id"}
        present = {cookie.name.lower() for cookie in self.client.cookies.jar}
        if present & auth_names:
            self.ready = False
            self.last_error = "authenticated Instagram cookie detected in anonymous gateway"
            raise GatewayError(
                "anonymous_session_contaminated",
                "FollowCheck refused to send an authenticated Instagram cookie from anonymous public-web mode.",
                503,
            )

    async def _pace(self) -> None:
        if self.min_interval <= 0 or self.last_request_at <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self.last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)

    def _ensure_available(self) -> None:
        retry_after = max(0, int(self.blocked_until - time.time()))
        if retry_after > 0:
            raise GatewayError(
                "instagram_cooldown",
                "Instagram public-web access is cooling down. FollowCheck will not send more requests until the cooldown ends.",
                429,
                retry_after,
            )
        if not self.ready or self.client is None:
            raise GatewayError(
                "public_gateway_not_ready",
                self.last_error or "Public web gateway is not ready.",
                503,
            )

    def _retry_after(self, response: httpx.Response) -> int:
        raw = response.headers.get("Retry-After", "").strip()
        try:
            header_seconds = int(raw)
        except (TypeError, ValueError):
            header_seconds = 0
        return max(self.cooldown_seconds, header_seconds, 60)

    def _extract_profile_from_html(self, text: str, handle: str) -> dict[str, Any] | None:
        target = handle.lower()
        best: tuple[int, dict[str, Any]] | None = None

        for document in self._json_documents_from_html(text):
            for node in self._walk_json(document):
                if not isinstance(node, dict):
                    continue
                username = str(node.get("username") or "").strip()
                if username.lower() != target:
                    continue
                score = self._profile_candidate_score(node)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, node)

        if best is not None:
            candidate = dict(best[1])
            if candidate.get("id") or candidate.get("pk") or candidate.get("user_id"):
                return candidate

        return self._extract_profile_regex(text, handle)

    @staticmethod
    def _profile_candidate_score(node: dict[str, Any]) -> int:
        score = 0
        if node.get("id") or node.get("pk") or node.get("user_id"):
            score += 8
        if "is_private" in node:
            score += 2
        if "full_name" in node or "name" in node:
            score += 1
        if "profile_pic_url" in node or "profile_pic_url_hd" in node or "profile_image" in node:
            score += 1
        if "follower_count" in node or isinstance(node.get("edge_followed_by"), dict):
            score += 3
        if "following_count" in node or isinstance(node.get("edge_follow"), dict):
            score += 3
        return score

    def _json_documents_from_html(self, text: str) -> Iterable[Any]:
        for match in SCRIPT_RE.finditer(text):
            content = html_lib.unescape(match.group(1)).strip()
            if not content:
                continue

            candidates = [content]
            if content.startswith("for (;;);"):
                candidates.append(content[len("for (;;);"):].lstrip())
            if content.startswith("<!--") and content.endswith("-->"):
                candidates.append(content[4:-3].strip())

            for marker in ("window._sharedData", "__additionalDataLoaded"):
                marker_at = content.find(marker)
                if marker_at >= 0:
                    brace_at = content.find("{", marker_at)
                    if brace_at >= 0:
                        obj = self._balanced_json_object(content, brace_at)
                        if obj:
                            candidates.append(obj)

            for candidate in candidates:
                try:
                    yield json.loads(candidate)
                    break
                except (json.JSONDecodeError, TypeError):
                    continue

    def _walk_json(self, value: Any) -> Iterable[Any]:
        stack = [value]
        parsed_strings = 0
        while stack:
            current = stack.pop()
            yield current
            if isinstance(current, dict):
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
            elif (
                isinstance(current, str)
                and parsed_strings < 50
                and 2 <= len(current) <= 500_000
                and current.lstrip().startswith(("{", "["))
            ):
                try:
                    nested = json.loads(current)
                except (json.JSONDecodeError, TypeError):
                    continue
                parsed_strings += 1
                stack.append(nested)

    @staticmethod
    def _balanced_json_object(text: str, start: int) -> str | None:
        if start < 0 or start >= len(text) or text[start] != "{":
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    def _extract_profile_regex(self, text: str, handle: str) -> dict[str, Any] | None:
        escaped_handle = re.escape(handle)
        patterns = (
            re.compile(
                rf'"username"\s*:\s*"{escaped_handle}"(?P<tail>.{{0,3500}}?)'
                rf'"(?:id|pk|user_id)"\s*:\s*"?(?P<id>\d{{3,}})"?',
                re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                rf'"(?:id|pk|user_id)"\s*:\s*"?(?P<id>\d{{3,}})"?(?P<tail>.{{0,3500}}?)'
                rf'"username"\s*:\s*"{escaped_handle}"',
                re.IGNORECASE | re.DOTALL,
            ),
        )
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            window_start = max(0, match.start() - 3500)
            window_end = min(len(text), match.end() + 3500)
            window = text[window_start:window_end]
            result: dict[str, Any] = {"id": match.group("id"), "username": handle}

            private = re.search(r'"is_private"\s*:\s*(true|false)', window, re.IGNORECASE)
            verified = re.search(r'"is_verified"\s*:\s*(true|false)', window, re.IGNORECASE)
            full_name = re.search(r'"full_name"\s*:\s*"((?:\\.|[^"\\])*)"', window)
            followers = re.search(r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)', window)
            following = re.search(r'"edge_follow"\s*:\s*\{\s*"count"\s*:\s*(\d+)', window)
            follower_direct = re.search(r'"follower_count"\s*:\s*(\d+)', window)
            following_direct = re.search(r'"following_count"\s*:\s*(\d+)', window)

            if private:
                result["is_private"] = private.group(1).lower() == "true"
            if verified:
                result["is_verified"] = verified.group(1).lower() == "true"
            if full_name:
                try:
                    result["full_name"] = json.loads(f'"{full_name.group(1)}"')
                except json.JSONDecodeError:
                    result["full_name"] = full_name.group(1)
            if followers:
                result["edge_followed_by"] = {"count": int(followers.group(1))}
            elif follower_direct:
                result["follower_count"] = int(follower_direct.group(1))
            if following:
                result["edge_follow"] = {"count": int(following.group(1))}
            elif following_direct:
                result["following_count"] = int(following_direct.group(1))
            return result
        return None

    @staticmethod
    def _count(user: dict[str, Any], kind: ListKind) -> int:
        if kind == "followers":
            direct = user.get("follower_count")
            nested = user.get("edge_followed_by")
        else:
            direct = user.get("following_count")
            nested = user.get("edge_follow")
        if direct is not None:
            try:
                return max(0, int(direct))
            except (TypeError, ValueError):
                pass
        if isinstance(nested, dict):
            try:
                return max(0, int(nested.get("count") or 0))
            except (TypeError, ValueError):
                pass
        return 0

    @staticmethod
    def _clean_node(node: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(node.get("id") or node.get("pk") or ""),
            "username": str(node.get("username") or ""),
            "full_name": str(node.get("full_name") or ""),
            "is_verified": bool(node.get("is_verified")),
            "is_private": bool(node.get("is_private")),
            "profile_pic_url": str(node.get("profile_pic_url") or ""),
        }

    @staticmethod
    def _probe_error(exc: GatewayError) -> dict[str, Any]:
        return {
            "ok": False,
            "code": exc.code,
            "status": exc.status,
            "message": str(exc),
            "retry_after": exc.retry_after,
        }
