#!/usr/bin/env bash
# Verify boofinity text embed + rerank through the llama-swap front-door
# (folder C, boofinity-model-pulls-rebind, 2026-06-16).
#
#   1. POST http://hlh_swap:9620/v1/embeddings {model:qwen3-embed} -> 1024-vector
#   2. POST http://hlh_swap:9620/v1/rerank     {model:qwen3-reranker} -> results
#      carry integer `index` + numeric `relevance_score`
#   3. bundled_models embed + rerank rows reach status=ready via the Models API
#
# Probes run inside hlh_api (no curl there): docker exec hlh_api python -c ...
# State checks hit the API and assert on JSON, never psql -c.
#
# Requires the bundled stack up (hlh_swap reachable, boofinity child warm). On a
# cold first boot the embed/rerank rows may still be 'pulling' — re-run after the
# snapshot completes.

set -uo pipefail

API="${API:-http://localhost:9600}"
SWAP="${SWAP:-http://hlh_swap:9620}"

PASS=0
FAIL=0

ok()   { printf "  PASS  %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  FAIL  %s\n" "$1"; FAIL=$((FAIL+1)); }

echo "=== 1. Front-door embed probe (1024-len) ==="
if docker exec hlh_api python -c "
import asyncio, httpx, sys
async def main():
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post('${SWAP}/v1/embeddings',
                          json={'model':'qwen3-embed','input':['test']})
        r.raise_for_status()
        emb = r.json()['data'][0]['embedding']
        assert isinstance(emb, list) and len(emb) == 1024, f'len={len(emb)}'
asyncio.run(main())
"; then ok "embeddings returns a 1024-length vector"; else bad "embeddings probe (1024-len)"; fi

echo "=== 2. Front-door rerank probe (index + relevance_score) ==="
if docker exec hlh_api python -c "
import asyncio, httpx
async def main():
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post('${SWAP}/v1/rerank',
                          json={'model':'qwen3-reranker','query':'chest pain',
                                'documents':['unrelated','cardiac note'],
                                'return_documents':False})
        r.raise_for_status()
        res = r.json()['results']
        assert res, 'no results'
        assert isinstance(res[0]['index'], int), 'index not int'
        assert isinstance(res[0]['relevance_score'], (int, float)), 'score not numeric'
asyncio.run(main())
"; then ok "rerank results carry integer index + numeric relevance_score"; else bad "rerank probe"; fi

echo "=== 3. bundled_models embed + rerank rows reach status=ready (Models API) ==="
MODELS_JSON=$(curl -sS "$API/api/models" 2>/dev/null || echo '{}')
echo "$MODELS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
rows = data if isinstance(data, list) else data.get('items', data.get('models', []))
def status_for(role):
    for r in rows:
        if r.get('role') == role:
            return r.get('status')
    return None
emb, rrk = status_for('embed'), status_for('rerank')
print(f'  embed status={emb!r}  rerank status={rrk!r}')
assert emb == 'ready', f'embed not ready: {emb}'
assert rrk == 'ready', f'rerank not ready: {rrk}'
" && ok "embed + rerank bundled rows are ready" || bad "embed/rerank rows not ready (may still be pulling on first boot)"

echo
printf "%s passed, %s failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
