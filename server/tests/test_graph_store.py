from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.graph_store import GraphStore


class GraphStoreTests(unittest.TestCase):
    def test_profile_and_page_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "graph.db", profile_ttl=60, page_ttl=60)
            profile = {
                "id": "123",
                "username": "Example",
                "followers": 1,
                "following": 1,
                "is_private": False,
            }
            store.set_profile("Example", profile)
            self.assertEqual(store.get_profile("example"), profile)

            page = {
                "items": [
                    {
                        "id": "456",
                        "username": "Friend",
                        "full_name": "Friend Name",
                        "is_verified": False,
                        "is_private": False,
                        "profile_pic_url": "",
                    }
                ],
                "next_cursor": None,
                "source": "instagram_public_web",
            }
            store.set_page("Example", "123", "followers", "", page, expected_count=1)
            self.assertEqual(store.get_page("example", "followers", ""), page)

            status = store.status("example")
            self.assertTrue(status["cached"])
            self.assertEqual(status["snapshots"]["followers"]["collected"], 1)
            self.assertTrue(status["snapshots"]["followers"]["complete"])

    def test_zero_ttl_disables_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(Path(tmp) / "graph.db", profile_ttl=0, page_ttl=0)
            store.set_profile("x", {"id": "1", "username": "x"})
            self.assertIsNone(store.get_profile("x"))
