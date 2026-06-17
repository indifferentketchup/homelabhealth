"""Drive the Providers UI in a real (headless) Chromium and capture the three
evidences requested for step 6:

  1. Network-tab evidence: POST /api/providers payload (clear key going to backend)
     + response ("***") + a follow-up GET /api/providers/:id ("***").
  2. The "leave blank to keep" edit flow: load an existing provider, save without
     touching the key field, confirm the PATCH body has no `api_key` AND that a
     fresh GET still shows "***" AND that POST /test still succeeds.
  3. Force-delete flow: pre-bind a workspace to the provider via SQL (since the
     workspace picker doesn't exist until step 8), attempt Delete, expect 409
     with dependency counts surfaced in the UI, then force-delete -> 204, and
     verify workspaces.provider_id was nulled.

Run from project root:
    /tmp/pw-venv/bin/python backend/scripts/verify_providers_ui.py

Exits 0 on success, non-zero on any failed assertion. Captures screenshots,
network transcripts, and DB checks into /tmp/step6-evidence/.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

UI_URL = os.environ.get("UI_URL", "http://localhost:9604")
LLAMA_SWAP_URL = os.environ.get("LLAMA_SWAP_URL", "")
CLEAR_KEY = "sk-STEP6-ZZZTESTREDACT-clearvalue-12345"

if not LLAMA_SWAP_URL:
    print("SKIP: LLAMA_SWAP_URL must be set for providers UI tests.")
    sys.exit(0)

EVID_DIR = Path("/tmp/step6-evidence")
EVID_DIR.mkdir(parents=True, exist_ok=True)


def psql_tac(sql: str, *params: str) -> str:
    """psql -tAc helper. Uses positional arg list to subprocess.run; no shell."""
    cmd = [
        "docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-tAc", sql,
    ]
    for p in params:
        cmd.extend(["-v", p])
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def psql_set_workspace_binding(workspace_name: str, provider_id: str | None, model: str | None) -> None:
    """Bind / unbind a workspace by name. Inputs are validated:
       - workspace_name: must be 'smoke-test' (the only workspace this script touches).
       - provider_id: parsed through uuid.UUID() so a malformed value can't slip through.
       - model: literal string from this script (never user input)."""
    if workspace_name != "smoke-test":
        raise ValueError(f"this script only manipulates the 'smoke-test' workspace, got {workspace_name!r}")
    if provider_id is not None:
        uuid.UUID(provider_id)  # raises if malformed
    pid_lit = "NULL" if provider_id is None else f"'{provider_id}'::uuid"
    model_lit = "NULL" if model is None else "'" + model.replace("'", "''") + "'"
    sql = (
        f"UPDATE workspaces SET provider_id = {pid_lit}, model = {model_lit} "
        f"WHERE name = 'smoke-test';"
    )
    cmd = [
        "docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c", sql,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def psql_delete_step6_providers() -> None:
    """Idempotent cleanup of any leftover step6-* provider rows."""
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "UPDATE workspaces SET provider_id = NULL, model = NULL "
         "WHERE provider_id IN (SELECT id FROM providers WHERE name LIKE 'step6-%');"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "DELETE FROM providers WHERE name LIKE 'step6-%';"],
        check=True, capture_output=True, text=True,
    )


def cleanup_db() -> None:
    psql_delete_step6_providers()
    psql_set_workspace_binding("smoke-test", None, None)


def banner(s: str) -> None:
    print(f"\n -  {s}  - ")


def passlog(label: str) -> None:
    print(f"  PASS  {label}")


def failbail(label: str, detail: str = "") -> None:
    print(f"  FAIL  {label}" + (f"  -  {detail}" if detail else ""))
    raise SystemExit(1)


def main() -> None:
    cleanup_db()

    _chrome_env = os.environ.get("CHROMIUM_PATH", "")
    chrome_path = Path(_chrome_env) if _chrome_env else None
    if not chrome_path or not chrome_path.exists():
        for candidate in (shutil.which("chromium"), shutil.which("google-chrome")):
            if candidate:
                chrome_path = Path(candidate)
                break
    if not chrome_path or not chrome_path.exists():
        failbail("playwright chromium binary not found; set CHROMIUM_PATH env var")

    network_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(chrome_path), headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})

        def on_response(resp):
            url = resp.url
            if "/api/providers" not in url:
                return
            req = resp.request
            try:
                req_body = req.post_data
            except Exception:
                req_body = None
            try:
                resp_body = "" if resp.status == 204 else resp.text()
            except Exception:
                resp_body = ""
            network_log.append({
                "method": req.method,
                "url": url,
                "status": resp.status,
                "request_body": req_body,
                "response_body": resp_body,
            })

        context.on("response", on_response)
        page = context.new_page()

        banner("Navigate to /settings and switch to the Providers tab")
        page.goto(f"{UI_URL}/settings", wait_until="networkidle")
        page.screenshot(path=str(EVID_DIR / "01-settings-loaded.png"))

        page.get_by_role("tab", name="Providers").click()
        # Don't depend on empty state  -  other test data may exist. Just confirm
        # the tab content actually rendered (Add button is unique to this tab).
        page.wait_for_selector('button:has-text("Add provider")', timeout=5000)
        page.screenshot(path=str(EVID_DIR / "02-providers-tab-loaded.png"))
        passlog("Providers tab is reachable and rendered")

        banner("Add a provider  -  capture POST payload + response")
        page.get_by_role("button", name="Add provider").click()
        page.fill('input#provider-name', "step6-llamacpp")
        page.fill('input#provider-base-url', LLAMA_SWAP_URL)
        page.fill('input#provider-api-key', CLEAR_KEY)
        page.screenshot(path=str(EVID_DIR / "03-add-modal-filled.png"))
        page.get_by_role("button", name="Add provider").last.click()
        page.wait_for_selector('td:has-text("step6-llamacpp")', timeout=10000)
        page.screenshot(path=str(EVID_DIR / "04-row-created.png"))

        posts = [n for n in network_log if n["method"] == "POST" and n["url"].endswith("/api/providers")]
        if not posts:
            failbail("no POST /api/providers captured")
        post = posts[-1]
        if post["status"] != 201:
            failbail("POST /api/providers did not return 201", str(post["status"]))
        passlog("POST /api/providers -> 201")

        if not post["request_body"] or CLEAR_KEY not in post["request_body"]:
            failbail("POST request body did not contain clear api_key", (post["request_body"] or "")[:200])
        passlog("POST request body contains the clear api_key (browser -> backend)")

        if CLEAR_KEY in post["response_body"]:
            failbail("LEAK: POST response body contained the clear api_key", post["response_body"][:200])
        if '"api_key":"***"' not in post["response_body"]:
            failbail('POST response did not contain api_key:"***"', post["response_body"][:200])
        passlog('POST response body has api_key:"***" and NO plaintext key')

        (EVID_DIR / "post-providers-payload.json").write_text(post["request_body"])
        (EVID_DIR / "post-providers-response.json").write_text(post["response_body"])

        provider_id = json.loads(post["response_body"])["id"]

        banner("Follow-up GET /api/providers/{id}")
        api_get = page.request.get(f"{UI_URL}/api/providers/{provider_id}")
        get_body = api_get.text()
        (EVID_DIR / "get-providers-id-response.json").write_text(get_body)
        if api_get.status != 200:
            failbail("GET /api/providers/{id} did not return 200", str(api_get.status))
        if CLEAR_KEY in get_body:
            failbail("LEAK: GET /api/providers/{id} contained the clear api_key", get_body[:200])
        if '"api_key":"***"' not in get_body:
            failbail('GET /api/providers/{id} did not contain api_key:"***"', get_body[:200])
        passlog('GET /api/providers/{id} -> 200 with api_key:"***", no plaintext leak')

        banner("Edit flow  -  save without touching the API key field")
        netlog_before = len(network_log)

        page.get_by_role("button", name="Edit").click()
        key_input = page.locator('input#provider-api-key')
        if key_input.input_value() != "":
            failbail("Edit modal's api_key field should be empty on open")
        passlog("Edit modal opens with api_key field BLANK (placeholder hint visible)")
        page.screenshot(path=str(EVID_DIR / "05-edit-modal-blank-key.png"))

        page.locator('input#provider-name').fill("step6-llamacpp-renamed")
        page.get_by_role("button", name="Save").click()
        page.wait_for_selector('td:has-text("step6-llamacpp-renamed")', timeout=10000)
        passlog("Edit submit completed without typing in the key field")

        patches = [
            n for n in network_log[netlog_before:]
            if n["method"] == "PATCH" and f"/api/providers/{provider_id}" in n["url"]
        ]
        if not patches:
            failbail("no PATCH /api/providers/{id} captured during edit-save")
        patch = patches[-1]
        if patch["status"] != 200:
            failbail("PATCH did not return 200", str(patch["status"]))
        patch_body = json.loads(patch["request_body"] or "{}")
        if "api_key" in patch_body:
            failbail("PATCH body contains api_key  -  frontend should OMIT it when field is blank",
                     json.dumps(patch_body))
        passlog("PATCH body omits api_key entirely (preserve behavior verified)")
        (EVID_DIR / "patch-edit-preserve-payload.json").write_text(patch["request_body"] or "")

        api_get2 = page.request.get(f"{UI_URL}/api/providers/{provider_id}")
        get_body2 = api_get2.text()
        if '"api_key":"***"' not in get_body2:
            failbail("after blank-edit-save, GET no longer shows api_key:\"***\"", get_body2[:200])
        passlog('Fresh GET after blank-edit-save still shows api_key:"***"')

        api_test = page.request.post(f"{UI_URL}/api/providers/{provider_id}/test")
        test_body = api_test.json()
        if not test_body.get("ok"):
            failbail("POST /test failed after blank-edit-save", json.dumps(test_body))
        passlog(f"POST /test succeeds after blank-edit-save (ok:true, {len(test_body.get('models', []))} models)")
        (EVID_DIR / "post-test-after-preserve.json").write_text(json.dumps(test_body, indent=2))

        banner("Force-delete flow  -  bind workspace via SQL, then delete via UI")
        psql_set_workspace_binding("smoke-test", provider_id, "dummy-bound-model")
        bound = psql_tac(
            "SELECT provider_id::text || ' / ' || model FROM workspaces WHERE name = 'smoke-test';"
        )
        if provider_id not in bound:
            failbail("workspace did not bind to provider in SQL", bound)
        passlog(f"SQL: workspace 'smoke-test' bound to provider_id={provider_id} / model='dummy-bound-model'")

        netlog_before = len(network_log)
        page.get_by_role("button", name="Delete").click()
        page.get_by_role("button", name="Delete").last.click()
        page.wait_for_selector("text=is in use", timeout=10000)
        page.wait_for_selector("text=1 workspace bound to this provider", timeout=5000)
        page.screenshot(path=str(EVID_DIR / "06-delete-409-dialog.png"))

        first_dels = [
            n for n in network_log[netlog_before:]
            if n["method"] == "DELETE" and f"/api/providers/{provider_id}" in n["url"]
        ]
        if not first_dels:
            failbail("no DELETE request captured for first delete attempt")
        first_del = first_dels[0]
        if first_del["status"] != 409:
            failbail(f"first DELETE expected 409, got {first_del['status']}")
        if '"workspaces":1' not in first_del["response_body"]:
            failbail("409 response missing workspaces:1", first_del["response_body"][:200])
        passlog("DELETE without force -> 409 with references shown in UI dialog")
        (EVID_DIR / "delete-409-response.json").write_text(first_del["response_body"])

        netlog_before = len(network_log)
        page.get_by_role("button", name="Force delete (clears references)").click()
        page.wait_for_selector('td:has-text("step6-llamacpp-renamed")', state="detached", timeout=10000)
        page.screenshot(path=str(EVID_DIR / "07-after-force-delete.png"))

        forces = [
            n for n in network_log[netlog_before:]
            if n["method"] == "DELETE" and f"/api/providers/{provider_id}" in n["url"]
        ]
        if not forces:
            failbail("no DELETE request captured for force-delete")
        force = forces[0]
        if force["status"] != 204:
            failbail(f"force-DELETE expected 204, got {force['status']}")
        if "?force=true" not in force["url"]:
            failbail("force-DELETE URL missing ?force=true", force["url"])
        passlog("Force-delete -> 204 with ?force=true on the URL")

        bound_after = psql_tac(
            "SELECT (provider_id IS NULL) AND (model IS NULL OR model = '') FROM workspaces WHERE name = 'smoke-test';"
        )
        if bound_after != "t":
            failbail("workspace provider_id/model not nulled after force-delete", bound_after)
        passlog("workspace.provider_id AND workspace.model both nulled after cascade")

        browser.close()

    (EVID_DIR / "network-log.json").write_text(json.dumps(network_log, indent=2))

    banner("All step-6 browser evidences captured")
    print(f"  Screenshots + JSON in: {EVID_DIR}")
    print(f"  Network log entries: {len(network_log)} (filtered to /api/providers)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nFATAL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
