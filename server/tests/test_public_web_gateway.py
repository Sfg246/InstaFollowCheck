from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from app.errors import GatewayError
from app.public_web_gateway import PublicWebGateway


def profile_html(
    *,
    user_id: str = "100",
    username: str = "publicperson",
    followers: int = 2,
    following: int = 1,
    private: bool = False,
) -> str:
    payload = {
        "require": [
            {
                "__bbox": {
                    "result": {
                        "data": {
                            "user": {
                                "id": user_id,
                                "username": username,
                                "full_name": "Public Person",
                                "is_private": private,
                                "is_verified": False,
                                "edge_followed_by": {"count": followers},
                                "edge_follow": {"count": following},
                                "profile_pic_url": "https://example.test/a.jpg",
                            }
                        }
                    }
                }
            }
        ]
    }
    return (
        "<!doctype html><html><head>"
        '<script type="application/json" data-sjs>'
        + json.dumps(payload)
        + "</script></head><body></body></html>"
    )


def topsearch_payload(username: str = "publicperson", user_id: str = "100") -> dict:
    return {
        "users": [
            {
                "position": 0,
                "user": {
                    "pk": user_id,
                    "username": username,
                    "full_name": "Public Person",
                    "is_private": False,
                    "is_verified": False,
                    "profile_pic_url": "https://example.test/a.jpg",
                },
            }
        ],
        "status": "ok",
    }


class PublicWebGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = dict(os.environ)
        os.environ["GRAPH_DB_PATH"] = str(Path(self.tmp.name) / "graph.db")
        os.environ["PROFILE_CACHE_TTL_SECONDS"] = "60"
        os.environ["RELATIONSHIP_CACHE_TTL_SECONDS"] = "60"
        os.environ["PUBLIC_MIN_REQUEST_INTERVAL_SECONDS"] = "0"
        os.environ["PUBLIC_COOLDOWN_SECONDS"] = "60"

    async def asyncTearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    async def test_html_profile_and_relationship_page_cache(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            self.assertNotIn("authorization", request.headers)
            if request.url.path == "/publicperson/":
                self.assertNotIn("x-ig-app-id", request.headers)
                return httpx.Response(200, text=profile_html(), headers={"Content-Type": "text/html"})
            if request.url.path.endswith("/graphql/query/"):
                self.assertEqual(request.headers.get("x-ig-app-id"), gateway.app_id)
                query = parse_qs(request.url.query.decode())
                variables = json.loads(query["variables"][0])
                self.assertEqual(variables["id"], "100")
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "user": {
                                "edge_followed_by": {
                                    "count": 2,
                                    "edges": [
                                        {"node": {"id": "200", "username": "follower_one", "full_name": "Follower One"}},
                                        {"node": {"id": "201", "username": "follower_two", "full_name": "Follower Two"}},
                                    ],
                                    "page_info": {"has_next_page": False, "end_cursor": None},
                                }
                            }
                        }
                    },
                )
            return httpx.Response(404)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        profile = await gateway.profile("publicperson")
        self.assertEqual(profile["id"], "100")
        self.assertEqual(profile["source"], "profile_html")

        page = await gateway.list_page("publicperson", "followers", "")
        self.assertEqual([u["username"] for u in page["items"]], ["follower_one", "follower_two"])
        self.assertEqual(page["total_count"], 2)
        self.assertIsNone(page["next_cursor"])

        profile_again = await gateway.profile("publicperson")
        page_again = await gateway.list_page("publicperson", "followers", "")
        self.assertTrue(profile_again["cache_hit"])
        self.assertTrue(page_again["cache_hit"])
        self.assertEqual(calls, ["/publicperson/", "/graphql/query/"])
        await gateway.close()

    async def test_topsearch_strategy_exact_match(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/v1/web/search/topsearch/":
                self.assertEqual(request.headers.get("x-ig-app-id"), gateway.app_id)
                query = parse_qs(request.url.query.decode())
                self.assertEqual(query["query"][0], "publicperson")
                self.assertEqual(query["include_reel"][0], "false")
                return httpx.Response(200, json=topsearch_payload())
            return httpx.Response(500)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        report = await gateway.probe(
            "publicperson",
            profile_strategy="topsearch",
            include_relationships=False,
        )
        self.assertTrue(report["profile"]["ok"])
        self.assertEqual(report["profile"]["id"], "100")
        self.assertEqual(report["profile"]["source"], "topsearch")
        self.assertTrue(report["profile_strategies"]["topsearch"]["ok"])
        self.assertEqual(report["profile_strategies"]["profile_html"]["status"], "not_run")
        self.assertEqual(report["profile_strategies"]["web_profile_info"]["status"], "not_run")
        self.assertEqual(paths, ["/api/v1/web/search/topsearch/"])
        await gateway.close()

    async def test_topsearch_requires_exact_username(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=topsearch_payload(username="publicperson_fan", user_id="777"))

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        with self.assertRaises(GatewayError) as raised:
            await gateway.profile_by_strategy("publicperson", "topsearch", use_cache=False)
        self.assertEqual(raised.exception.code, "public_topsearch_unusable")
        await gateway.close()

    async def test_auto_profile_fallback_order_html_topsearch(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/publicperson/":
                return httpx.Response(200, text="<html><body>shell only</body></html>")
            if request.url.path == "/api/v1/web/search/topsearch/":
                return httpx.Response(200, json=topsearch_payload())
            return httpx.Response(500)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        result = await gateway.profile("publicperson")
        self.assertEqual(result["id"], "100")
        self.assertEqual(result["source"], "topsearch")
        self.assertEqual(calls, ["/publicperson/", "/api/v1/web/search/topsearch/"])
        await gateway.close()

    async def test_auto_profile_can_reach_web_info_after_two_unusable_200s(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/publicperson/":
                return httpx.Response(200, text="<html><body>shell only</body></html>")
            if request.url.path == "/api/v1/web/search/topsearch/":
                return httpx.Response(200, json={"users": [], "status": "ok"})
            if request.url.path.endswith("/web_profile_info/"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "user": {
                                "id": "100",
                                "username": "publicperson",
                                "is_private": False,
                                "edge_followed_by": {"count": 2},
                                "edge_follow": {"count": 1},
                            }
                        }
                    },
                )
            return httpx.Response(500)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        result = await gateway.profile("publicperson")
        self.assertEqual(result["source"], "web_profile_info")
        self.assertEqual(
            calls,
            ["/publicperson/", "/api/v1/web/search/topsearch/", "/api/v1/users/web_profile_info/"],
        )
        await gateway.close()

    async def test_429_stops_fallback_and_retry(self) -> None:
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(429, headers={"Retry-After": "120"}, json={"message": "rate limited"})

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        with self.assertRaises(GatewayError) as first:
            await gateway.profile("publicperson")
        self.assertEqual(first.exception.code, "instagram_rate_limited")
        self.assertGreaterEqual(first.exception.retry_after or 0, 120)
        self.assertEqual(calls, 1)

        with self.assertRaises(GatewayError) as second:
            await gateway.profile("anotherperson")
        self.assertEqual(second.exception.code, "instagram_cooldown")
        self.assertEqual(calls, 1)
        await gateway.close()

    async def test_topsearch_probe_can_reach_first_relationship_page(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/v1/web/search/topsearch/":
                return httpx.Response(200, json=topsearch_payload())
            if request.url.path.endswith("/graphql/query/"):
                query = parse_qs(request.url.query.decode())
                variables = json.loads(query["variables"][0])
                self.assertEqual(variables["id"], "100")
                if len(paths) == 2:
                    edge_name = "edge_followed_by"
                    total = 12
                else:
                    edge_name = "edge_follow"
                    total = 7
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "user": {
                                edge_name: {
                                    "count": total,
                                    "edges": [{"node": {"id": "200", "username": "someone"}}],
                                    "page_info": {"has_next_page": True, "end_cursor": "next"},
                                }
                            }
                        }
                    },
                )
            return httpx.Response(404)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        report = await gateway.probe("publicperson", profile_strategy="topsearch")
        self.assertTrue(report["profile"]["ok"])
        self.assertTrue(report["followers"]["ok"])
        self.assertEqual(report["followers"]["total_count"], 12)
        self.assertTrue(report["following"]["ok"])
        self.assertEqual(report["following"]["total_count"], 7)
        self.assertEqual(paths, ["/api/v1/web/search/topsearch/", "/graphql/query/", "/graphql/query/"])
        await gateway.close()

    async def test_probe_stops_after_relationship_access_block(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/v1/web/search/topsearch/":
                return httpx.Response(200, json=topsearch_payload())
            if request.url.path.endswith("/graphql/query/"):
                return httpx.Response(403, json={"message": "blocked"})
            return httpx.Response(404)

        gateway = PublicWebGateway()
        gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway.ready = True

        report = await gateway.probe("publicperson", profile_strategy="topsearch")
        self.assertTrue(report["profile"]["ok"])
        self.assertFalse(report["followers"]["ok"])
        self.assertEqual(report["followers"]["status"], 403)
        self.assertEqual(report["following"]["status"], "not_run")
        self.assertEqual(paths, ["/api/v1/web/search/topsearch/", "/graphql/query/"])
        await gateway.close()

    async def test_html_parser_handles_nested_json_string(self) -> None:
        nested = json.dumps(
            {
                "user": {
                    "id": "555",
                    "username": "nestedperson",
                    "full_name": "Nested Person",
                    "is_private": False,
                    "follower_count": 9,
                    "following_count": 4,
                }
            }
        )
        page = '<script type="application/json">' + json.dumps({"payload": nested}) + "</script>"
        gateway = PublicWebGateway()
        found = gateway._extract_profile_from_html(page, "nestedperson")
        self.assertIsNotNone(found)
        self.assertEqual(str(found["id"]), "555")
        self.assertEqual(found["username"], "nestedperson")
