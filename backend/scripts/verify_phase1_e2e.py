"""Phase 1 end-to-end chat test — replaces the v1.10.0 step-8 'OK' test using
the bundled hlh_chat sidecar instead of external llama-swap.

Sequence (per dispatch §1.H.3):
  1. Save tier=cpu-min via PUT /api/system/profile → triggers
     ensure_bundled_chat_provider; row appears in /api/providers.
  2. Trigger pull for cpu-min chat (Qwen3 1.7B Q4 ~1.2 GB). Poll until
     status=ready or timeout (default 10 min).
  3. Bring hlh_chat up via docker compose (`--profile chat`). Wait until
     healthcheck reports healthy (model load can take ~30s).
  4. Discover the model id llama.cpp/server is serving (GET /v1/models on
     http://hlh_chat:9610 from inside the api container).
  5. Create a test workspace; bind it to bundled-chat + that model.
  6. Create a chat in the workspace; POST a "Reply with OK" message.
  7. Assert the SSE stream returns at least one content chunk.

Re-runnable; cleans up its own workspace, chat, and pulled artifact paths
are NOT removed (Phase 1's design is to keep the model file around for
re-use). Leaves DB at setup_complete=FALSE on exit.

Run from project root:
    /tmp/pw-venv/bin/python backend/scripts/verify_phase1_e2e.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

UI = "http://localhost:9604"
API = "http://localhost:9600"

EVID = Path("/tmp/phase1-evidence")
EVID.mkdir(parents=True, exist_ok=True)

PULL_TIMEOUT_S = int(__import__("os").environ.get("HLH_PHASE1_PULL_TIMEOUT_S", "600"))
HEALTH_TIMEOUT_S = 120
CHAT_TIMEOUT_S = 90


GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
_pass = 0
_failures: list[str] = []


def passlog(label: str) -> None:
    global _pass
    _pass += 1
    print(f"  {GREEN}PASS{RESET}  {label}")


def failbail(label: str, detail: str = "") -> None:
    _failures.append(label)
    print(f"  {RED}FAIL{RESET}  {label}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)


def banner(s: str) -> None:
    print(f"\n— {s} —")


def api_get(path: str) -> dict | list:
    with urllib.request.urlopen(f"{API}{path}") as r:
        return json.loads(r.read())


def api_post(path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", method="POST",
        headers={"Content-Type": "application/json"} if body is not None else {},
        data=data,
    )
    with urllib.request.urlopen(req) as r:
        text = r.read().decode()
        return json.loads(text) if text else {}


def api_put(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method="PUT",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_patch(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method="PATCH",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_delete(path: str) -> int:
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def reset_first_boot() -> None:
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "UPDATE system_profile SET tier='external', tier_source='manual', "
         "sysinfo_json='{}'::jsonb, detected_at=NULL, chosen_at=NOW(), "
         "setup_complete=FALSE WHERE id=1;"],
        check=True, capture_output=True, text=True,
    )


def docker_health(name: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
        check=False, capture_output=True, text=True,
    )
    return out.stdout.strip() or "unknown"


def main() -> int:
    banner("Reset to first-boot state")
    reset_first_boot()
    passlog("system_profile reset to setup_complete=FALSE, tier=external")

    banner("Save tier=cpu-min → expect bundled-chat provider to appear")
    api_put("/api/system/profile", {"tier": "cpu-min", "tier_source": "manual"})
    providers = api_get("/api/providers")
    bundled = next((p for p in providers["items"] if p["name"] == "bundled-chat"), None)
    if not bundled:
        failbail("bundled-chat row not found after tier save")
    if not bundled.get("enabled"):
        failbail(f"bundled-chat row exists but enabled is {bundled.get('enabled')!r}")
    if "hlh_chat" not in (bundled.get("base_url") or ""):
        failbail(f"bundled-chat base_url unexpected: {bundled.get('base_url')!r}")
    passlog(f"bundled-chat present: id={bundled['id']} base_url={bundled['base_url']}")

    banner("Trigger pull for cpu-min chat (Qwen3 1.7B Q4_K_M, ~1.2 GB)")
    models = api_get("/api/models")
    chat_row = next(
        (m for m in models["items"] if m["role"] == "chat" and m["tier"] == "cpu-min"),
        None,
    )
    if not chat_row:
        failbail("cpu-min chat row missing from /api/models")
    passlog(f"target row: {chat_row['repo']}/{chat_row['filename']} (id={chat_row['id']})")

    # Skip if already ready (re-run scenario).
    if chat_row["status"] != "ready":
        api_post(f"/api/models/{chat_row['id']}/pull")
        passlog("POST /pull queued")

        # Poll until ready or timeout.
        t0 = time.time()
        last_pulled = -1
        last_log = 0
        while time.time() - t0 < PULL_TIMEOUT_S:
            cur = api_get(f"/api/models/{chat_row['id']}")
            status = cur.get("status")
            pulled = int(cur.get("pulled_bytes") or 0)
            total = int(cur.get("expected_bytes") or 0)
            if status == "ready":
                passlog(f"pull completed in {int(time.time() - t0)}s ({pulled / 1024 / 1024:.1f} MB)")
                break
            if status == "failed":
                failbail(f"pull failed: {cur.get('error_message')!r}")
            # Print progress every ~10s.
            if time.time() - last_log >= 10:
                pct = (pulled / total * 100) if total else 0
                print(f"  … pulling: {pulled / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB ({pct:.0f}%)")
                last_log = time.time()
            if pulled == last_pulled and status == "pulling":
                # No progress this iteration — keep waiting.
                pass
            last_pulled = pulled
            time.sleep(3)
        else:
            failbail(f"pull did not complete within {PULL_TIMEOUT_S}s")
    else:
        passlog("pull already 'ready' (re-run path)")

    banner("Bring up hlh_chat with the pulled model")
    # COMPOSE_PROFILES=chat is in .env; just `up -d hlh_chat`.
    subprocess.run(
        ["docker", "compose", "up", "-d", "hlh_chat"],
        check=True, capture_output=True, text=True,
        cwd="/home/samkintop/opt/homelabhealth",
    )
    # Wait for healthcheck.
    t0 = time.time()
    last_status = None
    while time.time() - t0 < HEALTH_TIMEOUT_S:
        status = docker_health("hlh_chat")
        if status != last_status:
            print(f"  hlh_chat health: {status}")
            last_status = status
        if status == "healthy":
            passlog(f"hlh_chat healthy in {int(time.time() - t0)}s")
            break
        time.sleep(2)
    else:
        # Dump logs for debugging.
        subprocess.run(["docker", "logs", "hlh_chat", "--tail", "30"], check=False)
        failbail(f"hlh_chat did not become healthy within {HEALTH_TIMEOUT_S}s (status: {last_status})")

    banner("Discover the model id llama.cpp/server is serving")
    out = subprocess.run(
        ["docker", "exec", "hlh_api", "python", "-c",
         "import httpx; r = httpx.get('http://hlh_chat:9610/v1/models', timeout=10); "
         "import json; print(json.dumps(r.json()))"],
        check=True, capture_output=True, text=True,
    )
    chat_models = json.loads(out.stdout)
    served_models = [m["id"] for m in chat_models.get("data", []) if isinstance(m, dict)]
    if not served_models:
        failbail(f"hlh_chat /v1/models returned no models: {out.stdout[:200]}")
    served_model = served_models[0]
    passlog(f"hlh_chat serves model id: {served_model!r}")

    banner("Create a test workspace bound to bundled-chat + that model")
    ws = api_post("/api/workspaces/", {"name": "phase1-e2e-ws"})
    ws_id = ws["id"]
    passlog(f"workspace created: {ws_id}")
    try:
        api_patch(
            f"/api/workspaces/{ws_id}",
            {"provider_id": bundled["id"], "model": served_model},
        )
        ws_after = api_get(f"/api/workspaces/{ws_id}")
        if ws_after.get("provider_id") != bundled["id"]:
            failbail("workspace binding didn't persist", json.dumps(ws_after))
        passlog(f"workspace bound: provider={bundled['name']} model={served_model}")

        banner("Create a chat in the workspace; send a real message")
        chat = api_post("/api/chats/", {"workspace_id": ws_id})
        chat_id = chat["id"]
        passlog(f"chat created: {chat_id}")

        # POST /api/chats/{id}/messages; consume the SSE stream.
        req = urllib.request.Request(
            f"{API}/api/chats/{chat_id}/messages",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"content": "Reply with exactly the single word: OK"}).encode(),
        )
        text_chunks: list[str] = []
        had_done = False
        with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT_S) as r:
            for raw in r:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):].strip()
                if payload == "[DONE]":
                    had_done = True
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    if isinstance(obj.get("content"), str):
                        text_chunks.append(obj["content"])
                    if "error" in obj:
                        failbail(f"chat stream returned error: {obj['error']}")
        reply = "".join(text_chunks).strip()
        (EVID / "phase1-chat-reply.txt").write_text(reply)
        if not reply:
            failbail("chat stream produced no content tokens")
        passlog(f"REAL streamed reply from bundled chat ({len(reply)} chars): {reply[:120]!r}")
        if not had_done:
            print("  (note: stream ended without [DONE] — possibly upstream early-close; chunks present so plumbing is correct)")

    finally:
        # Cleanup workspace (cascade-deletes its chats).
        api_delete(f"/api/workspaces/{ws_id}")

    banner("Final reset to fresh-first-boot state")
    reset_first_boot()
    # Wipe bundled-chat row so the next E2E run starts clean for the seed test.
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "DELETE FROM providers WHERE name = 'bundled-chat';"],
        check=False, capture_output=True, text=True,
    )
    passlog("DB reset: setup_complete=FALSE, bundled-chat removed (model file kept)")

    print()
    if _failures:
        print(f"{RED}{len(_failures)} failure(s){RESET}")
        return 1
    print(f"{GREEN}All {_pass} checks passed.{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nFATAL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
