#!/usr/bin/env python3
"""Verify durable streaming Phase A end-to-end.

Usage: python backend/scripts/verify_durable_streaming.py [--base-url http://localhost:9600]

1. Checks the feature flag is enabled.
2. Sends a message → expects 202.
3. Polls until complete (120s timeout).
4. Verifies content is non-empty and no thought leak.
5. Tests stop → cancelled status.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

OK = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
errors = []


def log(ok: bool, msg: str) -> None:
    mark = OK if ok else FAIL
    print(f"  {mark} {msg}")
    if not ok:
        errors.append(msg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:9600")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(timeout=httpx.Timeout(30.0))

    # --- Auth ---
    print("Auth...")
    r = client.get(f"{base}/api/auth/me")
    if r.status_code == 401:
        r = client.post(f"{base}/api/auth/login", json={"username": "admin", "password": "admin"})
        if r.status_code != 200:
            print(f"  {FAIL} Login failed: {r.status_code}")
            sys.exit(1)
        cookie = r.cookies.get("hlh_session")
        if cookie:
            client.cookies.set("hlh_session", cookie)
    log(True, "authenticated")

    # --- Check flag ---
    print("\nChecking durable_streaming_enabled flag...")
    r = client.get(f"{base}/api/settings/durable-streaming")
    flag = r.json().get("enabled", False)
    if not flag:
        print(f"  {FAIL} durable_streaming_enabled is false.")
        print("    Enable: docker exec hlh_db psql -U hlh -d hlh -c "
              "\"UPDATE global_settings SET value='true' WHERE key='durable_streaming_enabled';\"")
        sys.exit(1)
    log(True, f"flag enabled={flag}")

    # --- Find workspace + create chat ---
    print("\nSetup...")
    r = client.get(f"{base}/api/workspaces/")
    workspaces = r.json()
    if not workspaces:
        print(f"  {FAIL} No workspaces found")
        sys.exit(1)
    ws_id = workspaces[0]["id"]
    log(True, f"workspace={ws_id}")

    r = client.post(f"{base}/api/chats/", json={"workspace_id": ws_id})
    chat = r.json()
    chat_id = chat["id"]
    log(True, f"chat={chat_id}")

    # --- Test 1: Send → 202 ---
    print("\nTest 1: Durable send → 202...")
    r = client.post(f"{base}/api/chats/{chat_id}/messages",
                    json={"content": "Say hello in one sentence."})
    log(r.status_code == 202, f"status={r.status_code} (expected 202)")
    body = r.json()
    assist_id = body.get("assistant_message_id")
    log(bool(assist_id), f"assistant_message_id={assist_id}")
    log(body.get("status") == "streaming", f"status={body.get('status')}")

    # --- Test 2: Poll until complete ---
    print("\nTest 2: Poll until complete (120s timeout)...")
    deadline = time.monotonic() + 120
    final_status = None
    final_content = ""
    while time.monotonic() < deadline:
        time.sleep(2)
        r = client.get(f"{base}/api/chats/{chat_id}/messages")
        items = r.json().get("items", [])
        target = next((m for m in items if m["id"] == assist_id), None)
        if target is None:
            continue
        final_status = target.get("status")
        final_content = target.get("content", "")
        print(f"    poll: status={final_status} content_len={len(final_content)}")
        if final_status in ("complete", "failed", "cancelled"):
            break

    log(final_status == "complete", f"final status={final_status}")
    log(len(final_content) > 0, f"content length={len(final_content)}")
    log("<thought>" not in final_content.lower(), "no thought leak in content")

    # --- Test 3: Stop ---
    print("\nTest 3: Stop endpoint...")
    r2 = client.post(f"{base}/api/chats/", json={"workspace_id": ws_id})
    chat2_id = r2.json()["id"]
    r2 = client.post(f"{base}/api/chats/{chat2_id}/messages",
                     json={"content": "Write a long essay about health."})
    if r2.status_code == 202:
        time.sleep(1)
        rs = client.post(f"{base}/api/chats/{chat2_id}/stop")
        log(rs.status_code == 200, f"stop status={rs.status_code}")
        time.sleep(2)
        r2m = client.get(f"{base}/api/chats/{chat2_id}/messages")
        items2 = r2m.json().get("items", [])
        assist2 = next((m for m in items2 if m["role"] == "assistant"), None)
        if assist2:
            log(assist2["status"] in ("cancelled", "complete"),
                f"after stop: status={assist2['status']}")
        else:
            log(False, "no assistant message found after stop")
    else:
        log(False, f"expected 202 for stop test, got {r2.status_code}")

    # --- Test 4: 409 on double send ---
    print("\nTest 4: 409 on double send...")
    r3 = client.post(f"{base}/api/chats/", json={"workspace_id": ws_id})
    chat3_id = r3.json()["id"]
    r3a = client.post(f"{base}/api/chats/{chat3_id}/messages",
                      json={"content": "First message."})
    if r3a.status_code == 202:
        r3b = client.post(f"{base}/api/chats/{chat3_id}/messages",
                          json={"content": "Second message while first streaming."})
        log(r3b.status_code == 409, f"double send status={r3b.status_code} (expected 409)")
        # Clean up
        client.post(f"{base}/api/chats/{chat3_id}/stop")
    else:
        log(False, f"expected 202, got {r3a.status_code}")

    # --- Summary ---
    print(f"\n{'='*40}")
    if errors:
        print(f"{FAIL} {len(errors)} failure(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"{OK} All checks passed")


if __name__ == "__main__":
    main()
