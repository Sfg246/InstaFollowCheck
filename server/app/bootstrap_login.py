from __future__ import annotations

import getpass
import os
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ClientError


def main() -> int:
    username = os.getenv("INSTAGRAM_USERNAME", "").strip()
    password = os.getenv("INSTAGRAM_PASSWORD", "").strip()
    session_path = Path(os.getenv("INSTAGRAM_SESSION_FILE", "/data/instagram-session.json"))
    proxy = os.getenv("INSTAGRAM_PROXY", "").strip() or None

    if not username or not password:
        print("ERROR: INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD are required.")
        return 2

    session_path.parent.mkdir(parents=True, exist_ok=True)

    client = Client(proxy=proxy, delay_range=[1, 3], request_timeout=10)
    client.set_retry_config(session_retry_total=0, session_retry_backoff_factor=0)

    if session_path.exists():
        try:
            client.load_settings(session_path)
            print("Loaded existing collector device/session settings.")
        except Exception:
            print("Existing session settings could not be loaded; continuing with a fresh local session profile.")

    def challenge_code_handler(challenge_username, choice):
        print()
        print(f"Instagram requested verification for @{challenge_username} ({choice}).")
        print("Request/use a FRESH code from Instagram. Do not paste the code into ChatGPT.")
        while True:
            code = getpass.getpass("Enter the fresh 6-digit Instagram code here: ").strip()
            if len(code) == 6 and code.isdigit():
                return code
            print("Code must be exactly 6 digits.")

    client.challenge_code_handler = challenge_code_handler

    print(f"Starting ONE controlled login attempt for @{username}.")
    print("If Instagram is still rate-limiting this account/IP, stop and wait rather than retrying repeatedly.")

    try:
        ok = client.login(username, password)
    except ClientError as exc:
        print(f"LOGIN_FAILED: {type(exc).__name__}")
        print("Instagram rejected the login attempt. Do not immediately retry if this was a rate-limit response.")
        return 1
    except Exception as exc:
        print(f"LOGIN_FAILED: {type(exc).__name__}")
        return 1

    if not ok:
        print("LOGIN_FAILED: login returned false")
        return 1

    client.dump_settings(session_path)
    print("LOGIN_SUCCESS")
    print(f"SESSION_SAVED: {session_path}")
    print("The normal FollowCheck API can now reuse this verified session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
