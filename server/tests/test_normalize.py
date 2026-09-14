import unittest

from app.main import normalize_handle


class NormalizeHandleTests(unittest.TestCase):
    def test_username(self):
        self.assertEqual(normalize_handle("@Example.User"), "Example.User")

    def test_url(self):
        self.assertEqual(
            normalize_handle("https://www.instagram.com/example.user/?hl=en"),
            "example.user",
        )
