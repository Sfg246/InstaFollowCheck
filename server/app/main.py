from __future__ import annotations

import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .instagram_gateway import InstagramGateway, InstagramGatewayError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("followcheck")

HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def normalize_handle(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            from urllib.parse import urlparse

            parts = [part for part in urlparse(raw).path.split("/") if part]
            raw = parts[0] if parts else ""
        except Exception:
            raw = ""
    raw = raw.lstrip("@").split("/")[0].split("?")[0].split("#")[0].strip()
    return raw


def allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "https://sfg246.github.io")
    return [item.strip() for item in raw.split(",") if item.strip()]


gateway = InstagramGateway()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await gateway.start()
    yield


app = FastAPI(title="FollowCheck Self-Hosted API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-FollowCheck-Code"],
)


class ProfileRequest(BaseModel):
    handle: str


class ListRequest(BaseModel):
    handle: str
    kind: Literal["followers", "following"]
    cursor: str | None = ""


def error_payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def check_access(request: Request) -> JSONResponse | None:
    expected = os.getenv("ACCESS_CODE", "").strip()
    if not expected:
        return None
    supplied = request.headers.get("X-FollowCheck-Code", "")
    if not hmac.compare_digest(expected, supplied):
        return JSONResponse(error_payload("access_code_required", "A valid FollowCheck access code is required."), status_code=401)
    return None


def validate_handle(raw: str) -> str:
    handle = normalize_handle(raw)
    if not HANDLE_RE.fullmatch(handle):
        raise InstagramGatewayError("invalid_handle", "Enter a valid Instagram username.", 400)
    return handle


@app.exception_handler(InstagramGatewayError)
async def gateway_error_handler(_: Request, exc: InstagramGatewayError):
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse(error_payload(exc.code, str(exc)), status_code=exc.status, headers=headers)


@app.get("/health")
async def health():
    state = gateway.health()
    return {"ok": bool(state["ready"]), "service": "followcheck-selfhosted", **state}


@app.post("/api/profile")
async def profile(body: ProfileRequest, request: Request):
    blocked = check_access(request)
    if blocked:
        return blocked
    handle = validate_handle(body.handle)
    result = await gateway.profile(handle)
    if result.get("is_private"):
        raise InstagramGatewayError(
            "private_account",
            "Username-only scanning is intentionally disabled for private Instagram accounts.",
            403,
        )
    return {"profile": result}


@app.post("/api/list")
async def relationship_list(body: ListRequest, request: Request):
    blocked = check_access(request)
    if blocked:
        return blocked
    handle = validate_handle(body.handle)
    cursor = (body.cursor or "").strip()
    if len(cursor) > 4096:
        raise InstagramGatewayError("invalid_cursor", "Pagination cursor is too long.", 400)
    return await gateway.list_page(handle, body.kind, cursor)
