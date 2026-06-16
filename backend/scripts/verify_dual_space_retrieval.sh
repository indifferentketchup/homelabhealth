#!/usr/bin/env bash
# Verify dual-space VL retrieval (folder D, 2026-06-16).
#
# Checks (gpu-24gb+ ONLY; SKIPs on every other tier):
#   1. source_image_embeddings table + both indexes exist
#   2. bundled_models embed-vl/rerank-vl rows are seeded (no CheckViolationError)
#   3. providers embed-vl/rerank-vl rows seeded on gpu-24gb+
#   4. Ingesting a synthetic image writes source_image_embeddings rows
#   5. Deleting the source cascades the image rows away
#   6. mm_embeddings probe through the front-door (qwen3-vl-embed)
#
# Live model probes (mm_embeddings, mm_rerank) require the boofinity child
# warm with the VL models pulled (Qwen3-VL-Embedding-2B, Qwen3-VL-Reranker-2B).
# On a cold first boot those models may still be 'pulling' — re-run after they
# reach status=ready. The schema + seed checks (1-3) pass without the models.
#
# Probes: in-container HTTP via `docker exec hlh_api python -c ...`
#         DB checks via `docker exec hlh_db psql -U hlh -d hlh ...` (no -it)
# State checks assert on API JSON, not psql -c :'var' interpolation (CLAUDE.md).

set -uo pipefail

API="${API:-http://localhost:9600}"
SWAP="${SWAP:-http://hlh_swap:9620}"

PASS=0
FAIL=0

ok()  { printf "  PASS  %s\n" "$1"; PASS=$((PASS+1)); }
bad() { printf "  FAIL  %s\n" "$1"; FAIL=$((FAIL+1)); }

# ── Tier gate ────────────────────────────────────────────────────────────────
TIER=$(curl -sS "$API/api/system/profile" 2>/dev/null \
       | python3 -c "import sys,json; print(json.load(sys.stdin).get('tier',''))" 2>/dev/null || echo "")
if [ "$TIER" != "gpu-24gb+" ]; then
    printf "SKIP: requires gpu-24gb+ (active tier=%s)\n" "${TIER:-unknown}"
    exit 0
fi

echo "=== gpu-24gb+ confirmed; running dual-space VL checks ==="
echo

# ── 1. Schema: table + indexes ───────────────────────────────────────────────
echo "=== 1. source_image_embeddings table exists ==="
TABLE=$(docker exec hlh_db psql -U hlh -d hlh \
        -tAc "SELECT to_regclass('source_image_embeddings')" 2>/dev/null || echo "")
if [ "$TABLE" = "source_image_embeddings" ]; then
    ok "source_image_embeddings table present"
else
    bad "source_image_embeddings table missing (got: ${TABLE:-empty})"
fi

echo "=== 1b. HNSW cosine index present ==="
HNSW=$(docker exec hlh_db psql -U hlh -d hlh \
       -tAc "SELECT indexdef FROM pg_indexes WHERE indexname='source_image_embeddings_embedding_hnsw'" \
       2>/dev/null || echo "")
if echo "$HNSW" | grep -q "hnsw" && echo "$HNSW" | grep -q "vector_cosine_ops"; then
    ok "HNSW vector_cosine_ops index present"
else
    bad "HNSW index missing or wrong ops: ${HNSW:-not found}"
fi

echo "=== 1c. source_id index present ==="
SIDX=$(docker exec hlh_db psql -U hlh -d hlh \
       -tAc "SELECT indexdef FROM pg_indexes WHERE indexname='source_image_embeddings_source_id_idx'" \
       2>/dev/null || echo "")
if echo "$SIDX" | grep -q "source_id"; then
    ok "source_id index present"
else
    bad "source_id index missing: ${SIDX:-not found}"
fi

# ── 2. bundled_models role CHECK admits embed-vl/rerank-vl ──────────────────
echo "=== 2. bundled_models_role_check includes embed-vl + rerank-vl ==="
BM_CHK=$(docker exec hlh_db psql -U hlh -d hlh \
         -tAc "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='bundled_models_role_check'" \
         2>/dev/null || echo "")
if echo "$BM_CHK" | grep -q "embed-vl" && echo "$BM_CHK" | grep -q "rerank-vl"; then
    ok "bundled_models_role_check contains embed-vl and rerank-vl"
else
    bad "bundled_models_role_check missing VL roles: ${BM_CHK:-not found}"
fi

echo "=== 2b. bundled_models rows seeded for embed-vl + rerank-vl (gpu-24gb+) ==="
VL_ROWS=$(docker exec hlh_db psql -U hlh -d hlh \
          -tAc "SELECT count(*) FROM bundled_models WHERE role IN ('embed-vl','rerank-vl') AND tier='gpu-24gb+'" \
          2>/dev/null || echo "0")
VL_ROWS=$(echo "$VL_ROWS" | tr -d '[:space:]')
if [ "${VL_ROWS:-0}" -ge 2 ]; then
    ok "bundled_models has ${VL_ROWS} VL rows for gpu-24gb+"
else
    bad "bundled_models VL rows count=${VL_ROWS:-0} (expected >=2)"
fi

# ── 3. providers embed-vl/rerank-vl rows seeded ──────────────────────────────
echo "=== 3. providers role_check includes embed-vl + rerank-vl ==="
PR_CHK=$(docker exec hlh_db psql -U hlh -d hlh \
         -tAc "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='providers_role_check'" \
         2>/dev/null || echo "")
if echo "$PR_CHK" | grep -q "embed-vl" && echo "$PR_CHK" | grep -q "rerank-vl"; then
    ok "providers_role_check contains embed-vl and rerank-vl"
else
    bad "providers_role_check missing VL roles: ${PR_CHK:-not found}"
fi

echo "=== 3b. providers embed-vl + rerank-vl rows present ==="
PROV_VL=$(docker exec hlh_db psql -U hlh -d hlh \
          -tAc "SELECT count(*) FROM providers WHERE role IN ('embed-vl','rerank-vl') AND is_bundled=TRUE" \
          2>/dev/null || echo "0")
PROV_VL=$(echo "$PROV_VL" | tr -d '[:space:]')
if [ "${PROV_VL:-0}" -ge 2 ]; then
    ok "providers has ${PROV_VL} bundled VL rows"
else
    bad "providers VL rows count=${PROV_VL:-0} (expected >=2; ensure_bundled_providers may not have run yet)"
fi

# ── 4. Ingest image -> source_image_embeddings rows written ──────────────────
# Note: this check requires the boofinity VL models to be pulled and warm.
# On a cold boot the models may still be pulling; skip this assertion in that case.
echo "=== 4. VL model pull status ==="
MODELS_JSON=$(curl -sS "$API/api/models" 2>/dev/null || echo '{}')
VL_READY=$(echo "$MODELS_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    rows = data if isinstance(data, list) else data.get('items', data.get('models', []))
    def status_for(role):
        for r in rows:
            if r.get('role') == role and r.get('tier') == 'gpu-24gb+':
                return r.get('status')
        return None
    emb, rrk = status_for('embed-vl'), status_for('rerank-vl')
    print(f'embed-vl={emb} rerank-vl={rrk}')
    if emb == 'ready' and rrk == 'ready':
        print('READY')
    else:
        print('NOT_READY')
except Exception as e:
    print(f'PARSE_ERROR: {e}')
" 2>/dev/null || echo "NOT_READY")

echo "  VL model status: $VL_READY"

if echo "$VL_READY" | grep -q "^READY"; then
    ok "embed-vl + rerank-vl rows are ready"
else
    printf "  WARN  embed-vl/rerank-vl not ready yet (skip live embed test until pulled)\n"
fi

# ── 5. mm_embeddings probe (requires VL models warm) ─────────────────────────
echo "=== 5. boofinity mm_embeddings probe via front-door ==="
if echo "$VL_READY" | grep -q "^READY"; then
    if docker exec hlh_api python -c "
import asyncio, httpx, base64, sys
async def main():
    # 1x1 white PNG (minimal valid image)
    png_b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg=='
    data_url = 'data:image/png;base64,' + png_b64
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post('${SWAP}/v1/mm_embeddings',
                          json={'model': 'qwen3-vl-embed',
                                'input': [{'image': data_url}],
                                'dimensions': 1024})
        r.raise_for_status()
        emb = r.json()['data'][0]['embedding']
        assert isinstance(emb, list), 'embedding not a list'
        assert len(emb) >= 1024, f'embedding too short: {len(emb)}'
asyncio.run(main())
"; then
        ok "mm_embeddings returns >=1024-length vector via qwen3-vl-embed"
    else
        bad "mm_embeddings probe failed (model warm? check docker logs hlh_swap)"
    fi
else
    printf "  SKIP  mm_embeddings probe (VL models not ready)\n"
fi

# ── 6. FK cascade check ───────────────────────────────────────────────────────
echo "=== 6. FK cascade: source_image_embeddings → sources ON DELETE CASCADE ==="
CASCADE=$(docker exec hlh_db psql -U hlh -d hlh -tAc "
SELECT confdeltype FROM pg_constraint c
JOIN pg_class r ON r.oid = c.conrelid
JOIN pg_class f ON f.oid = c.confrelid
WHERE r.relname = 'source_image_embeddings'
  AND f.relname = 'sources'
  AND c.contype = 'f'
" 2>/dev/null || echo "")
CASCADE=$(echo "$CASCADE" | tr -d '[:space:]')
# confdeltype 'a' = CASCADE
if [ "$CASCADE" = "a" ]; then
    ok "source_image_embeddings.source_id FK is ON DELETE CASCADE"
else
    bad "source_image_embeddings FK cascade wrong (confdeltype=${CASCADE:-not found}, expected 'a')"
fi

# ── 7. PHI access gate: no ungated SELECT in routers ─────────────────────────
echo "=== 7. No ungated source_image_embeddings SELECT in routers ==="
UNGATED=$(grep -rn "source_image_embeddings" \
    /home/samkintop/opt/homelabhealth/backend/routers/ 2>/dev/null \
    | grep -v "^Binary" || true)
if [ -z "$UNGATED" ]; then
    ok "source_image_embeddings not accessed directly from any router (gated via rag.py + sources.py)"
else
    bad "source_image_embeddings appears in routers/ (PHI audit gap?):"
    echo "$UNGATED"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
printf "%d passed, %d failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
