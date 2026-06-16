# Tasks: boofinity-image-pipeline

**Date:** 2026-06-16

A1 (publish) and A2/A3/A4 (pins) are independent and may run in either order,
but the verification task X3 (`docker buildx imagetools inspect`) requires A1.6
(publish) to have completed.

---

## A1 - Publish the boofinity GHCR image (boofinity repo)

These tasks are performed in `indifferentketchup/boofinity`, not homelabhealth.

> Left to operator (2026-06-16): A1.0-A1.10 (boofinity-repo CI workflow, GHCR
> build/push, visibility flip, multi-arch confirmation) and X3 (digest inspect,
> requires A1.6 publish) cannot be done from the homelabhealth editing session and
> remain unchecked.

- [ ] A1.0 Confirm the build ref is `ik-main` (the branch carrying the VL /
      `causal_lm` commits), or a tag cut from it, NOT `origin/main`. Cut the
      `v0.1.0` tag from `ik-main`. Pushing / merging `ik-main` and cutting the tag
      in `indifferentketchup/boofinity` is an operator prerequisite for this folder
      (it cannot be done from homelabhealth). Building from `origin/main` would
      publish an image that 404s `/mm_embeddings` / `/mm_rerank`.
- [ ] A1.1 In the boofinity repo, add `.github/workflows/publish-image.yml` with
      a two-leg matrix: `cpu` builds `libs/boofinity/Dockerfile.cpu_auto`, `cuda`
      builds `libs/boofinity/Dockerfile.nvidia_auto`. Build each leg from the
      `ik-main` ref (per A1.0).
- [ ] A1.2 Set the workflow trigger to push of tag `v0.1.0` plus
      `workflow_dispatch`. Confirm it does NOT trigger on every commit.
- [ ] A1.3 Add `permissions: { packages: write }` and a `docker/login-action`
      step against `ghcr.io` using `${{ github.actor }}` and
      `${{ secrets.GITHUB_TOKEN }}`.
- [ ] A1.4 Tag the cpu leg `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` and
      the cuda leg `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda`. Confirm the
      `0.1.0` matches boofinity `pyproject.toml` version.
- [ ] A1.5 Confirm each Dockerfile's build-time smoke check
      (`boofinity v2 --preload-only --no-model-warmup`) passes in the runner and
      `ENTRYPOINT ["boofinity"]` on port 7997 is set.
- [ ] A1.6 Push the `v0.1.0` tag in the boofinity repo and confirm both legs
      complete green in the Actions run.
- [ ] A1.7 Flip both package visibilities to public at
      `github.com/users/indifferentketchup/packages/container/boofinity/settings`.
- [ ] A1.8 Verify unauthenticated pull: on a host with no `docker login ghcr.io`,
      run `docker pull ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` and confirm
      no auth error.
- [ ] A1.9 Verify the published image was built from the VL-bearing ref: run the
      `0.1.0-cuda` image with the GPU command and POST to `/v1/mm_rerank` (and
      `/v1/mm_embeddings`); confirm neither 404s. A 404 means the image was built
      from a ref without the VL / `causal_lm` commits (wrong build ref, A1.0) -
      do NOT mark the publish shippable until the routes resolve.
- [ ] A1.10 Confirm the cpu publish architecture: inspect the manifest
      (`docker buildx imagetools inspect ghcr.io/indifferentketchup/boofinity:0.1.0-cpu`)
      for a `linux/arm64` entry. If multi-arch (`amd64` + `arm64`), `apple-mlx`
      pulls natively. If `amd64`-only, note in the CHANGELOG (X5) that `apple-mlx`
      runs the cpu image under emulation (perf caveat) and flag arm64 as
      unconfirmed/unbuilt.

**Acceptance criteria:** Both tags exist, are public, pull without auth, serve the
`mm_` routes (built from `ik-main`), and their architecture coverage is recorded
(multi-arch or amd64-only-with-emulation-caveat).

---

## A2 - Rewrite image_config.py pins (homelabhealth)

- [x] A2.1 In `backend/services/image_config.py:18-19`, replace
      `LLAMA_CPP_VERSION = "b9628"` with `LLAMA_CPP_VERSION = "b9660"`.
- [x] A2.2 In the same constant block, remove `INFINITY_VERSION = "0.0.77"` and
      add `BOOFINITY_VERSION = "0.1.0"` and `LLAMA_SWAP_VERSION = "v226"`.
- [x] A2.3 In `TIER_IMAGE_MAP` (`image_config.py:30-79`), rewrite the
      `infer_image` for `cpu-min`, `cpu-std`, `apple-mlx`, and `external` to
      `f"ghcr.io/indifferentketchup/boofinity:{BOOFINITY_VERSION}-cpu"`.
- [x] A2.4 Rewrite the `infer_image` for `gpu-4gb`, `gpu-8gb`, `gpu-16gb`, and
      `gpu-24gb+` to
      `f"ghcr.io/indifferentketchup/boofinity:{BOOFINITY_VERSION}-cuda"`.
- [x] A2.5 Leave every `chat_image` and `models_max` field unchanged. Confirm
      `chat_image` still interpolates `{LLAMA_CPP_VERSION}`.
- [x] A2.5a Remove the stale `vision` token from
      `TIER_IMAGE_MAP['gpu-24gb+'].compose_profiles` (`image_config.py:64`):
      `"bundled-gpu,vision"` -> `"bundled-gpu"`. No `vision`-profile service exists
      in `docker-compose.yml` (MedGemma vision is the chat model + mmproj, not a
      service). Leave the `write_tier_env` "preserve operator-added `vision`"
      branch (`image_config.py:123-124`) intact (it no-ops once the seed drops
      `vision`). Folder B relies on this removal.

**Acceptance:** `python3 -c "from services.image_config import TIER_IMAGE_MAP as m; assert 'vision' not in m['gpu-24gb+'].compose_profiles"` (run from `backend/`) exits 0.
- [x] A2.6 Grep gate: `grep -rn "michaelf34/infinity\|INFINITY_VERSION" backend/`
      returns zero matches.
- [x] A2.7 Run `python3 -m py_compile backend/services/image_config.py`; confirm
      exit 0.

**Acceptance criteria:** Constants present, all eight `infer_image` entries point
at the fork tag with the correct suffix, zero upstream references, compiles clean.

---

## A3 - Update .env.example (homelabhealth)

- [x] A3.1 In `.env.example` (around line 39), change the `HLH_INFER_IMAGE`
      comment from `michaelf34/infinity:0.0.77-cpu` to
      `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu`.
- [x] A3.2 In `.env.example`, change the `HLH_CHAT_IMAGE` comment from
      `server-b9628` to `server-b9660`.
- [x] A3.3 Grep gate: `grep -n "michaelf34/infinity" .env.example` returns zero
      matches. Confirm no `HLH_SWAP_IMAGE` line was added.

**Acceptance criteria:** Both comments reflect the fork tag and b9660; no
infinity string and no swap var remain.

---

## A4 - Update bootstrap.py image defaults (homelabhealth)

- [x] A4.1 In `hlh_orchestra/bootstrap.py:48`, change the `CHAT_IMAGE_CPU`
      default from `server-b9628` to `server-b9660`.
- [x] A4.2 In `hlh_orchestra/bootstrap.py:49`, change the `CHAT_IMAGE_GPU`
      default from `server-cuda-b9628` to `server-cuda-b9660`.
- [x] A4.3 Grep `hlh_orchestra/bootstrap.py` for any `michaelf34/infinity`
      default; if present, rewrite to the boofinity fork tag. Then confirm
      `grep -rn "michaelf34/infinity" hlh_orchestra/` returns zero matches.
- [x] A4.4 Read `pull_image` in `bootstrap.py` and confirm no skip-if-present
      branch was introduced (always-pull preserved per CLAUDE.md).
- [x] A4.5 Run `python3 -m py_compile hlh_orchestra/bootstrap.py`; confirm
      exit 0.

**Acceptance criteria:** Both chat defaults are b9660, no infinity string in
orchestra, pull_image still always pulls, compiles clean.

---

## X - Cross-cutting verification

- [x] X1 Run `python3 -m py_compile $(find backend -name '*.py')`; confirm no
      errors.
- [x] X2 Run the constants assertion:
      ```
      python3 -c "from services.image_config import TIER_IMAGE_MAP, BOOFINITY_VERSION, LLAMA_CPP_VERSION, LLAMA_SWAP_VERSION; \
      assert BOOFINITY_VERSION == '0.1.0'; \
      assert LLAMA_CPP_VERSION == 'b9660'; \
      assert LLAMA_SWAP_VERSION == 'v226'; \
      assert TIER_IMAGE_MAP['cpu-min'].infer_image == 'ghcr.io/indifferentketchup/boofinity:0.1.0-cpu'; \
      assert TIER_IMAGE_MAP['gpu-24gb+'].infer_image == 'ghcr.io/indifferentketchup/boofinity:0.1.0-cuda'; \
      assert 'server-b9660' in TIER_IMAGE_MAP['cpu-min'].chat_image; \
      print('OK')"
      ```
      (run from `backend/` so `services` is importable). Confirm it prints `OK`.
- [ ] X3 Verify the published image (requires A1.6):
      `docker buildx imagetools inspect ghcr.io/indifferentketchup/boofinity:0.1.0-cpu`
      succeeds and prints a digest; repeat for `:0.1.0-cuda`.
- [x] X4 Confirm homelabhealth ships no boofinity build workflow:
      `grep -rn "Dockerfile.cpu_auto\|Dockerfile.nvidia_auto" .github/` (if the
      directory exists) returns zero matches.
- [x] X5 Update `CHANGELOG.md` under `[Unreleased]` with entries for the
      boofinity image publish, the `image_config.py` pin rewrite (BOOFINITY_VERSION
      0.1.0, LLAMA_CPP_VERSION b9660, LLAMA_SWAP_VERSION v226, fork infer_image),
      and the `.env.example` / `bootstrap.py` default bumps. Note the `gpu-24gb+`
      `vision` compose-profile token removal (no `vision` service exists) and,
      if the cpu publish is `amd64`-only (per A1.10), the `apple-mlx` emulation
      perf caveat. Reference commit `9b5655b` (prior llama.cpp bump) for forensic
      continuity.

**Acceptance criteria:** All compile/assert/inspect checks pass; CHANGELOG
updated; no boofinity build workflow in homelabhealth.
