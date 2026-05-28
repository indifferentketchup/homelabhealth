"""Drive the workspace provider+model picker end-to-end:

1. Create a fresh test workspace (unbound).
2. Open its detail page in headless Chromium.
3. Pick provider + model in the new picker, Save -> 200, fresh GET shows the binding.
4. POST a real chat message to a chat in that workspace -> server resolves the
   workspace's provider and starts streaming a real LLM reply. Assert the
   stream contains at least one content chunk.
5. Clear provider+model via the picker, Save -> 200.
6. POST another chat message -> expect HTTP 400 with the verbatim spec string
   "No provider configured for this workspace. Open Settings -> Workspace to pick one."

Run from project root:
    /tmp/pw-venv/bin/python backend/scripts/verify_workspace_provider_picker.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

UI_URL = os.environ.get("UI_URL", "http://localhost:9604")
API_URL = os.environ.get("API_URL", "http://localhost:9600")
LLAMA_SWAP_URL = os.environ.get("LLAMA_SWAP_URL", "")
EXPECTED_CHAT_MODEL = os.environ.get("EXPECTED_CHAT_MODEL", "qwen3.6-35b-a3b-mxfp4")

if not LLAMA_SWAP_URL:
    print("SKIP: LLAMA_SWAP_URL must be set for workspace provider picker tests.")
    sys.exit(0)

EVID_DIR = Path("/tmp/step8-evidence")
EVID_DIR.mkdir(parents=True, exist_ok=True)


# All SQL the script uses is constant (no user-input interpolation). Workspace
# and provider IDs flow through psql via -v variable substitution; UUIDs are
# validated by uuid.UUID() before they reach psql.
_SQL_CLEANUP_WS_UNBIND = (
    "UPDATE workspaces SET provider_id = NULL, model = NULL "
    "WHERE provider_id IN (SELECT id FROM providers WHERE name LIKE 'step8-%');"
)
_SQL_CLEANUP_WS_DELETE = "DELETE FROM workspaces WHERE name LIKE 'step8-%';"
_SQL_CLEANUP_PROVIDERS_DELETE = "DELETE FROM providers WHERE name LIKE 'step8-%';"
# Phase 0+: this script navigates to /workspaces/{id}, which is gated by
# RequireSetup. If setup_complete is FALSE, the gate redirects to /settings
# before the selector waits resolve and the test times out. Every UI verify
# script that navigates into gated routes owns its precondition.
_SQL_SATISFY_SETUP_GATE = (
    "UPDATE system_profile SET setup_complete = TRUE WHERE id = 1;"
)


def _psql(args: list[str]) -> str:
    cmd = ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh"] + args
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def cleanup_db() -> None:
    _psql(["-c", _SQL_CLEANUP_WS_UNBIND])
    _psql(["-c", _SQL_CLEANUP_WS_DELETE])
    _psql(["-c", _SQL_CLEANUP_PROVIDERS_DELETE])
    _psql(["-c", _SQL_SATISFY_SETUP_GATE])


def api_get(path: str) -> dict:
    """GET helper using urllib (no f-string SQL anywhere)."""
    with urllib.request.urlopen(f"{API_URL}{path}") as resp:
        return json.loads(resp.read())


def fetch_ws_binding(workspace_id: str) -> str:
    """Return the workspace's '<provider_id> / <model>' string via the API."""
    uuid.UUID(workspace_id)
    body = api_get(f"/api/workspaces/{workspace_id}")
    pid = body.get("provider_id") or "<null>"
    mdl = body.get("model") or "<null>"
    return f"{pid} / {mdl}"


def workspace_is_unbound(workspace_id: str) -> bool:
    uuid.UUID(workspace_id)
    body = api_get(f"/api/workspaces/{workspace_id}")
    return body.get("provider_id") in (None, "") and (body.get("model") in (None, ""))


def api_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API_URL}{path}",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def banner(s: str) -> None:
    print(f"\n-- {s} --")


def passlog(label: str) -> None:
    print(f"  PASS  {label}")


def failbail(label: str, detail: str = "") -> None:
    print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
    raise SystemExit(1)


def main() -> None:
    cleanup_db()

    provider = api_post("/api/providers", {"name": "step8-llamacpp", "base_url": LLAMA_SWAP_URL})
    provider_id = provider["id"]
    uuid.UUID(provider_id)
    print(f"provider: step8-llamacpp = {provider_id}")

    workspace = api_post("/api/workspaces/", {"name": "step8-test-ws"})
    workspace_id = workspace["id"]
    uuid.UUID(workspace_id)
    print(f"workspace: step8-test-ws = {workspace_id}")

    if workspace.get("provider_id") not in (None, ""):
        failbail("fresh workspace already has provider_id set", str(workspace.get("provider_id")))

    chat = api_post("/api/chats/", {"workspace_id": workspace_id})
    chat_id = chat["id"]
    uuid.UUID(chat_id)
    print(f"chat: {chat_id}")

    _chrome_env = os.environ.get("CHROMIUM_PATH", "")
    chrome_path = Path(_chrome_env) if _chrome_env else None
    if not chrome_path or not chrome_path.exists():
        for candidate in (shutil.which("chromium"), shutil.which("google-chrome")):
            if candidate:
                chrome_path = Path(candidate)
                break
    if not chrome_path or not chrome_path.exists():
        failbail("playwright chromium binary not found; set CHROMIUM_PATH env var")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(chrome_path), headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 1000})
        page = context.new_page()

        banner("Open workspace detail page")
        page.goto(f"{UI_URL}/workspaces/{workspace_id}", wait_until="networkidle")
        page.wait_for_selector('select#workspace-provider', timeout=10000)
        page.screenshot(path=str(EVID_DIR / "01-workspace-detail-loaded.png"))
        passlog("Workspace detail page renders the new provider + model picker")

        banner("Pick provider + model, Save, expect success")
        page.select_option('select#workspace-provider', value=provider_id)
        page.wait_for_selector(
            f'select#workspace-model >> option[value="{EXPECTED_CHAT_MODEL}"]',
            state='attached',
            timeout=10000,
        )
        page.select_option('select#workspace-model', value=EXPECTED_CHAT_MODEL)
        page.screenshot(path=str(EVID_DIR / "02-picker-filled.png"))

        page.get_by_role("button", name="Save inference settings").click()
        page.wait_for_selector("text=Inference settings saved.", timeout=10000)
        page.screenshot(path=str(EVID_DIR / "03-saved.png"))
        passlog("Save -> success message appears")

        db_state = fetch_ws_binding(workspace_id)
        if provider_id not in db_state or EXPECTED_CHAT_MODEL not in db_state:
            failbail("workspace binding not in DB after Save", db_state)
        passlog(f"DB shows workspace bound: {db_state}")

        api_ws = page.request.get(f"{UI_URL}/api/workspaces/{workspace_id}")
        ws_body = api_ws.json()
        if ws_body.get("provider_id") != provider_id or ws_body.get("model") != EXPECTED_CHAT_MODEL:
            failbail("GET /api/workspaces/{id} doesn't reflect saved pair", json.dumps(ws_body))
        passlog("GET /api/workspaces/{id} round-trips the new pair")

        banner("Send a real chat message; backend resolves workspace provider and streams")
        send = page.request.post(
            f"{UI_URL}/api/chats/{chat_id}/messages",
            data=json.dumps({"content": "Reply with exactly the single word: OK"}),
            headers={"Content-Type": "application/json"},
            timeout=60000,
        )
        if send.status != 200:
            failbail(f"chat send did not return 200; got {send.status}", send.text()[:200])
        body = send.text()
        if "data:" not in body:
            failbail("chat send body has no SSE 'data:' chunks", body[:300])
        if '"content"' not in body:
            failbail("chat send body has no content delta -- model did not emit tokens", body[:300])
        if "[DONE]" not in body:
            failbail("chat send body did not end with [DONE]", body[-300:])
        text_chunks: list[str] = []
        for line in body.splitlines():
            if not line.startswith("data: "):
                continue
            raw = line[len("data: "):].strip()
            if raw == "[DONE]":
                break
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("content"), str):
                text_chunks.append(obj["content"])
        reply = "".join(text_chunks).strip()
        (EVID_DIR / "chat-reply.txt").write_text(reply)
        passlog(f"REAL streamed reply ({len(reply)} chars): {reply[:120]!r}")

        banner("Clear provider+model via picker, Save")
        page.reload(wait_until="networkidle")
        page.wait_for_selector('select#workspace-provider', timeout=10000)
        page.get_by_role("button", name="Clear (then Save)").click()
        page.get_by_role("button", name="Save inference settings").click()
        page.wait_for_selector('text=Provider + model cleared.', timeout=10000)
        page.screenshot(path=str(EVID_DIR / "04-cleared.png"))

        if not workspace_is_unbound(workspace_id):
            failbail("workspace pair not nulled after clear-Save")
        passlog("DB shows workspace.provider_id AND workspace.model both NULL")

        banner("Send chat on now-unbound workspace, expect exact spec error string")
        send2 = page.request.post(
            f"{UI_URL}/api/chats/{chat_id}/messages",
            data=json.dumps({"content": "anything"}),
            headers={"Content-Type": "application/json"},
            timeout=15000,
        )
        if send2.status != 400:
            failbail(f"expected 400 after clear; got {send2.status}", send2.text()[:200])
        err_body = send2.json()
        EXPECTED = "No provider configured for this workspace. Open Settings → Workspace to pick one."
        if err_body.get("detail") != EXPECTED:
            failbail(
                "chat send did not return the EXACT spec error string",
                f"got: {err_body!r}",
            )
        (EVID_DIR / "chat-send-error.json").write_text(json.dumps(err_body, indent=2))
        passlog("Chat send on unbound workspace returns the exact spec error string")

        browser.close()

    cleanup_db()
    banner("All step-8 E2E checks passed")
    print(f"  Screenshots + evidence in: {EVID_DIR}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nFATAL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
