from __future__ import annotations

import getpass
import os
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ClientError


def main() -> int:
    session_path = Path(os.getenv("INSTAGRAM_SESSION_FILE", "/data/instagram-session.json"))
    proxy = os.getenv("INSTAGRAM_PROXY", "").strip() or None

    print("FollowCheck existing-session bootstrap")
    print("Use a sessionid from an Instagram web session that is already logged in.")
    print("The value is a credential. Enter it only here; do not paste it into chat.")

    sessionid = getpass.getpass("Instagram sessionid: ").strip()
    if not sessionid:
        print("ERROR: sessionid is required.")
        return 2

    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = Client(proxy=proxy, delay_range=[1, 3], request_timeout=10)
    client.set_retry_config(session_retry_total=0, session_retry_backoff_factor=0)

    try:
        ok = client.login_by_sessionid(sessionid)
    except ClientError as exc:
        print(f"SESSION_LOGIN_FAILED: {type(exc).__name__}")
        return 1
    except Exception as exc:
        print(f"SESSION_LOGIN_FAILED: {type(exc).__name__}")
        return 1

    if not ok:
        print("SESSION_LOGIN_FAILED: login_by_sessionid returned false")
        return 1

    client.dump_settings(session_path)
    print("SESSION_LOGIN_SUCCESS")
    print(f"SESSION_SAVED: {session_path}")
    print("FollowCheck can now reuse this saved authenticated session on normal startup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
