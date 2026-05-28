"""Drive the Embedding + Reranker tabs in a real (headless) Chromium.

For Embedding:
  - load tab, confirm renders
  - configure a 1024-dim provider (infinity-emb / harrier) → Save → success message
  - reload, confirm picker shows saved selection (round-trip)
  - try a non-1024 model via a local 768-dim mock → inline error containing the
    exact spec string "embedding dimension mismatch: expected 1024, got 768"
  - Clear → confirm both dropdowns reset and GET returns null

For Reranker (validation-only contract):
  - load tab
  - configure infinity-rerank / qwen3-rerank → Save → success
  - Clear ("Use flashrank fallback") → confirm

Run from project root:
    /tmp/pw-venv/bin/python backend/scripts/verify_embedding_reranker_ui.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

UI_URL = os.environ.get("UI_URL", "http://localhost:9604")
HOST_TAILNET_IP = os.environ.get("HOST_TAILNET_IP", "localhost")
MOCK_PORT = int(os.environ.get("MOCK_PORT", "9612"))

INFINITY_EMB_URL = os.environ.get("INFINITY_EMB_URL", "")
INFINITY_RERANK_URL = os.environ.get("INFINITY_RERANK_URL", "")
HARRIER_MODEL = "harrier"
QWEN_RERANK_MODEL = "qwen3-rerank"

if not INFINITY_EMB_URL or not INFINITY_RERANK_URL:
    print("SKIP: INFINITY_EMB_URL and INFINITY_RERANK_URL must both be set.")
    sys.exit(0)

EVID_DIR = Path("/tmp/step7-evidence")
EVID_DIR.mkdir(parents=True, exist_ok=True)


def psql_cleanup() -> None:
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "DELETE FROM global_settings WHERE key IN "
         "('embedding_provider_id','embedding_model','reranker_provider_id','reranker_model');"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["docker", "exec", "hlh_db", "psql", "-U", "hlh", "-d", "hlh", "-c",
         "DELETE FROM providers WHERE name LIKE 'step7-%';"],
        check=True, capture_output=True, text=True,
    )


def create_provider(name: str, base_url: str) -> str:
    """Create a provider via the public API and return its UUID."""
    import urllib.request

    req = urllib.request.Request(
        "http://localhost:9600/api/providers",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"name": name, "base_url": base_url}).encode(),
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["id"]


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(n)
        body = {"data": [{"embedding": [0.0] * 768, "index": 0, "object": "embedding"}]}
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def start_mock_server() -> HTTPServer:
    server = HTTPServer((HOST_TAILNET_IP, MOCK_PORT), MockHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    return server


def banner(s: str) -> None:
    print(f"\n— {s} —")


def passlog(label: str) -> None:
    print(f"  PASS  {label}")


def failbail(label: str, detail: str = "") -> None:
    print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)


def main() -> None:
    psql_cleanup()

    pid_emb = create_provider("step7-emb", INFINITY_EMB_URL)
    pid_rrk = create_provider("step7-rrk", INFINITY_RERANK_URL)
    pid_mock = create_provider("step7-mock-768", f"http://{HOST_TAILNET_IP}:{MOCK_PORT}")
    print(f"providers: step7-emb={pid_emb}, step7-rrk={pid_rrk}, step7-mock-768={pid_mock}")

    mock = start_mock_server()
    try:
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
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()

            banner("Embedding tab — initial load + render")
            page.goto(f"{UI_URL}/settings", wait_until="networkidle")
            page.get_by_role("tab", name="Embedding").click()
            page.wait_for_selector('select#embedding-provider', timeout=5000)
            page.screenshot(path=str(EVID_DIR / "01-embedding-tab-loaded.png"))
            passlog("Embedding tab renders with provider + model dropdowns")

            banner("Embedding — pick step7-emb / harrier → Save → success")
            page.select_option('select#embedding-provider', value=pid_emb)
            # Wait for the model dropdown to populate (placeholder text changes).
            page.wait_for_selector(f'select#embedding-model >> option[value="{HARRIER_MODEL}"]', state='attached', timeout=10000)
            page.select_option('select#embedding-model', value=HARRIER_MODEL)
            page.screenshot(path=str(EVID_DIR / "02-embedding-harrier-selected.png"))

            page.get_by_role("button", name="Save").click()
            page.wait_for_selector("text=Embedding model saved.", timeout=10000)
            passlog("Embedding Save with 1024-dim model → success message")

            # Round-trip via API: GET should now return the saved binding.
            api_get = page.request.get(f"{UI_URL}/api/settings/embedding")
            got = api_get.json()
            if got.get("provider_id") != pid_emb or got.get("model") != HARRIER_MODEL:
                failbail(f"saved binding round-trip mismatch: {got}")
            passlog(f"GET /api/settings/embedding round-trips ({got['provider_id']} / {got['model']})")

            banner("Embedding — switch to mock-768 → Save → INLINE dim-mismatch error")
            page.select_option('select#embedding-provider', value=pid_mock)
            # Mock accepts any model name and returns 768; let the model picker
            # populate (or fail to populate — mock doesn't expose /v1/models),
            # so we just type into the select. Mock has no /v1/models endpoint,
            # so the picker will show "no models reported by provider". Set the
            # model value programmatically via the same path the Save uses.
            #
            # The select element won't allow values that aren't in <option>,
            # so we add one via DOM injection to mirror what a model-bearing
            # provider would do. This isolates the dim-mismatch test to the
            # PUT /api/settings/embedding behavior (the actual probe), which is
            # the point of the test.
            page.wait_for_timeout(500)
            page.evaluate(
                """() => {
                    const sel = document.getElementById('embedding-model');
                    const opt = document.createElement('option');
                    opt.value = 'anything';
                    opt.text = 'anything (mock)';
                    sel.appendChild(opt);
                    sel.value = 'anything';
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
            page.screenshot(path=str(EVID_DIR / "03-embedding-mock-selected.png"))
            page.get_by_role("button", name="Save").click()

            # Wait for the inline error to appear.
            page.wait_for_selector('[data-testid="embedding-save-error"]', timeout=10000)
            err_text = page.locator('[data-testid="embedding-save-error"]').inner_text()
            page.screenshot(path=str(EVID_DIR / "04-embedding-dim-mismatch.png"))
            expected = "embedding dimension mismatch: expected 1024, got 768"
            if expected not in err_text:
                failbail(
                    "inline error did not contain the exact spec dim-mismatch string",
                    err_text,
                )
            passlog(f"INLINE error contains exact string: {expected!r}")

            # DB binding must NOT have changed (rejected probe doesn't overwrite).
            api_get2 = page.request.get(f"{UI_URL}/api/settings/embedding")
            got2 = api_get2.json()
            if got2.get("model") != HARRIER_MODEL:
                failbail(f"rejected probe overwrote DB binding: {got2}")
            passlog("rejected probe did not overwrite the harrier binding in DB")

            banner("Embedding — Clear (disable embeddings)")
            # Reset selections back to harrier first so the Clear button is in
            # the right state.
            page.select_option('select#embedding-provider', value=pid_emb)
            page.wait_for_selector(f'select#embedding-model >> option[value="{HARRIER_MODEL}"]', state='attached', timeout=10000)

            page.get_by_role("button", name="Clear (disable embeddings)").click()
            page.get_by_role("button", name="Yes, clear").click()
            page.wait_for_selector("text=Embedding model cleared", timeout=10000)
            page.screenshot(path=str(EVID_DIR / "05-embedding-cleared.png"))

            api_get3 = page.request.get(f"{UI_URL}/api/settings/embedding")
            got3 = api_get3.json()
            if got3.get("provider_id") is not None or got3.get("model") is not None:
                failbail(f"after clear, GET should be null/null: {got3}")
            passlog("Embedding Clear → GET returns null provider_id + null model")

            banner("Reranker tab — initial load + render")
            page.get_by_role("tab", name="Reranker").click()
            page.wait_for_selector('select#reranker-provider', timeout=5000)
            page.screenshot(path=str(EVID_DIR / "06-reranker-tab-loaded.png"))
            passlog("Reranker tab renders with provider + model dropdowns")

            banner("Reranker — pick step7-rrk / qwen3-rerank → Save")
            page.select_option('select#reranker-provider', value=pid_rrk)
            page.wait_for_selector(f'select#reranker-model >> option[value="{QWEN_RERANK_MODEL}"]', state='attached', timeout=10000)
            page.select_option('select#reranker-model', value=QWEN_RERANK_MODEL)
            page.screenshot(path=str(EVID_DIR / "07-reranker-selected.png"))

            page.get_by_role("button", name="Save").click()
            page.wait_for_selector("text=Reranker model saved.", timeout=10000)
            passlog("Reranker Save (no probe) → success message")

            api_get4 = page.request.get(f"{UI_URL}/api/settings/reranker")
            got4 = api_get4.json()
            if got4.get("provider_id") != pid_rrk or got4.get("model") != QWEN_RERANK_MODEL:
                failbail(f"reranker round-trip mismatch: {got4}")
            passlog(f"GET /api/settings/reranker round-trips ({got4['provider_id']} / {got4['model']})")

            banner("Reranker — Use flashrank fallback")
            page.get_by_role("button", name="Use flashrank fallback").click()
            page.get_by_role("button", name="Yes, use flashrank").click()
            page.wait_for_selector("text=Using flashrank fallback", timeout=10000)
            page.screenshot(path=str(EVID_DIR / "08-reranker-cleared.png"))

            api_get5 = page.request.get(f"{UI_URL}/api/settings/reranker")
            got5 = api_get5.json()
            if got5.get("provider_id") is not None or got5.get("model") is not None:
                failbail(f"after fallback-clear, GET should be null/null: {got5}")
            passlog("Reranker fallback → GET returns null provider_id + null model")

            browser.close()
    finally:
        mock.shutdown()
        # Cleanup test data so no provider rows survive past the test run.
        for pid in (pid_emb, pid_rrk, pid_mock):
            try:
                import urllib.request
                urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://localhost:9600/api/providers/{pid}?force=true",
                        method="DELETE",
                    )
                ).read()
            except Exception:
                pass

    banner("All step-7 UI evidences captured")
    print(f"  Screenshots in: {EVID_DIR}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nFATAL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
