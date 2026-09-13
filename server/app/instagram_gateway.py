from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyotp
from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    ClientThrottledError,
    LoginRequired,
    PleaseWaitFewMinutes,
    PrivateAccount,
    UserNotFound,
)

log = logging.getLogger("followcheck.instagram")

ListKind = Literal["followers", "following"]


class InstagramGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = max(0, ttl_seconds)
        self._data: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item.expires_at <= time.time():
            self._data.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        self._data[key] = CacheEntry(value=value, expires_at=time.time() + self.ttl_seconds)


class InstagramGateway:
    """One authenticated Instagram session with serialized, cached read access."""

    def __init__(self) -> None:
        self.username = os.getenv("INSTAGRAM_USERNAME", "").strip()
        self.password = os.getenv("INSTAGRAM_PASSWORD", "").strip()
        self.totp_secret = os.getenv("INSTAGRAM_TOTP_SECRET", "").replace(" ", "").strip()
        self.proxy = os.getenv("INSTAGRAM_PROXY", "").strip() or None
        self.session_path = Path(os.getenv("INSTAGRAM_SESSION_FILE", "/data/instagram-session.json"))
        self.page_size = max(25, min(int(os.getenv("INSTAGRAM_PAGE_SIZE", "200")), 200))
        self.cooldown_seconds = max(60, int(os.getenv("INSTAGRAM_COOLDOWN_SECONDS", "900")))
        cache_seconds = max(0, int(os.getenv("CACHE_TTL_SECONDS", "600")))
        self.cache = TTLCache(cache_seconds)
        self.lock = asyncio.Lock()
        self.client: Client | None = None
        self.ready = False
        self.last_error = "not initialized"
        self.blocked_until = 0.0

    async def start(self) -> None:
        await asyncio.to_thread(self._login_sync)

    def _login_sync(self) -> None:
        if not self.username or not self.password:
            self.ready = False
            self.last_error = "INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD are required"
            log.warning(self.last_error)
            return

        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        client = Client(proxy=self.proxy, delay_range=[1, 3], request_timeout=2)
        client.set_retry_config(session_retry_total=2, session_retry_backoff_factor=2)

        if self.session_path.exists():
            try:
                client.load_settings(self.session_path)
            except Exception as exc:
                log.warning("Could not load saved Instagram session: %s", exc)

        verification_code = ""
        if self.totp_secret:
            try:
                verification_code = pyotp.TOTP(self.totp_secret).now()
            except Exception as exc:
                log.warning("Could not generate Instagram TOTP code: %s", exc)

        try:
            client.login(self.username, self.password, verification_code=verification_code)
            client.dump_settings(self.session_path)
            self.client = client
            self.ready = True
            self.last_error = ""
            log.info("Instagram collector logged in as @%s", self.username)
        except ChallengeRequired as exc:
            self.ready = False
            self.last_error = "Instagram requires manual verification for the collector account"
            log.error("%s: %s", self.last_error, exc)
        except Exception as exc:
            self.ready = False
            self.last_error = f"Instagram collector login failed: {type(exc).__name__}"
            log.exception(self.last_error)

    def health(self) -> dict[str, Any]:
        retry_after = max(0, int(self.blocked_until - time.time()))
        return {
            "ready": self.ready and retry_after == 0,
            "logged_in": self.ready,
            "collector": self.username or None,
            "cooldown_seconds": retry_after,
            "last_error": self.last_error or None,
        }

    async def profile(self, handle: str) -> dict[str, Any]:
        key = f"profile:{handle.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        async with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
            self._ensure_available()
            try:
                user = await asyncio.to_thread(self.client.user_info_by_username, handle)
            except Exception as exc:
                raise self._map_error(exc) from exc

            result = {
                "id": str(user.pk),
                "username": str(user.username or handle),
                "full_name": str(user.full_name or ""),
                "is_verified": bool(user.is_verified),
                "is_private": bool(user.is_private),
                "followers": int(user.follower_count or 0),
                "following": int(user.following_count or 0),
                "profile_pic_url": str(user.profile_pic_url or ""),
            }
            self.cache.set(key, result)
            self.cache.set(f"userid:{handle.lower()}", str(user.pk))
            return result

    async def list_page(self, handle: str, kind: ListKind, cursor: str = "") -> dict[str, Any]:
        cache_key = f"list:{handle.lower()}:{kind}:{cursor}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        async with self.lock:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
            self._ensure_available()

            profile = self.cache.get(f"profile:{handle.lower()}")
            if profile is None:
                try:
                    user = await asyncio.to_thread(self.client.user_info_by_username, handle)
                except Exception as exc:
                    raise self._map_error(exc) from exc
                profile = {
                    "id": str(user.pk),
                    "username": str(user.username or handle),
                    "is_private": bool(user.is_private),
                }
                self.cache.set(f"profile:{handle.lower()}", profile)
                self.cache.set(f"userid:{handle.lower()}", str(user.pk))

            if profile.get("is_private"):
                raise InstagramGatewayError(
                    "private_account",
                    "Username-only scanning is intentionally disabled for private Instagram accounts.",
                    403,
                )

            user_id = self.cache.get(f"userid:{handle.lower()}") or profile.get("id")
            if not user_id:
                raise InstagramGatewayError("user_not_found", "Instagram account not found.", 404)

            try:
                if kind == "followers":
                    users, next_cursor = await asyncio.to_thread(
                        self.client.user_followers_v1_chunk,
                        str(user_id),
                        self.page_size,
                        cursor,
                    )
                else:
                    users, next_cursor = await asyncio.to_thread(
                        self.client.user_following_v1_chunk,
                        str(user_id),
                        self.page_size,
                        cursor,
                    )
            except Exception as exc:
                raise self._map_error(exc) from exc

            result = {
                "items": [self._clean_user(user) for user in users if getattr(user, "username", None)],
                "next_cursor": next_cursor or None,
            }
            self.cache.set(cache_key, result)
            return result

    def _ensure_available(self) -> None:
        retry_after = int(self.blocked_until - time.time())
        if retry_after > 0:
            raise InstagramGatewayError(
                "instagram_cooldown",
                "Instagram temporarily rate-limited the collector. FollowCheck will resume automatically after the cooldown.",
                429,
                retry_after,
            )
        if not self.ready or self.client is None:
            raise InstagramGatewayError(
                "collector_not_ready",
                self.last_error or "Instagram collector is not ready.",
                503,
            )

    def _map_error(self, exc: Exception) -> InstagramGatewayError:
        if isinstance(exc, (ClientThrottledError, PleaseWaitFewMinutes)):
            self.blocked_until = max(self.blocked_until, time.time() + self.cooldown_seconds)
            self.last_error = "Instagram rate limit/cooldown active"
            return InstagramGatewayError(
                "instagram_rate_limited",
                "Instagram rate-limited the collector. FollowCheck paused automatically instead of retrying aggressively.",
                429,
                self.cooldown_seconds,
            )
        if isinstance(exc, ChallengeRequired):
            self.ready = False
            self.last_error = "Instagram requires manual verification for the collector account"
            return InstagramGatewayError("instagram_challenge", self.last_error, 503)
        if isinstance(exc, LoginRequired):
            self.ready = False
            self.last_error = "Instagram collector session expired; restart after signing in again"
            return InstagramGatewayError("instagram_login_required", self.last_error, 503)
        if isinstance(exc, PrivateAccount):
            return InstagramGatewayError("private_account", "This Instagram account is private.", 403)
        if isinstance(exc, UserNotFound):
            return InstagramGatewayError("user_not_found", "Instagram account not found.", 404)
        if isinstance(exc, ClientError):
            log.warning("Instagram client error: %s", exc)
            return InstagramGatewayError(
                "instagram_error",
                "Instagram rejected or could not complete that request. Try again later.",
                502,
            )
        log.exception("Unexpected Instagram collector failure", exc_info=exc)
        return InstagramGatewayError("instagram_unavailable", "Instagram data is temporarily unavailable.", 502)

    @staticmethod
    def _clean_user(user: Any) -> dict[str, Any]:
        return {
            "id": str(getattr(user, "pk", "") or ""),
            "username": str(getattr(user, "username", "") or ""),
            "full_name": str(getattr(user, "full_name", "") or ""),
            "is_verified": bool(getattr(user, "is_verified", False)),
            "is_private": bool(getattr(user, "is_private", False)),
            "profile_pic_url": str(getattr(user, "profile_pic_url", "") or ""),
        }
