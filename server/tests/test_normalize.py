import unittest

from app.main import normalize_handle


class NormalizeHandleTests(unittest.TestCase):
    def test_plain_username(self):
        self.assertEqual(normalize_handle("@some.user"), "some.user")

    def test_instagram_url(self):
        self.assertEqual(normalize_handle("https://instagram.com/some.user/?hl=en"), "some.user")


if __name__ == "__main__":
    unittest.main()
