# hlh_swap - combined inference front-door image.
#
# Carries three binaries: llama-swap (entrypoint + process manager),
# llama-server (chat / tasks / mmproj child), and boofinity (embed / rerank / VL
# child, already installed in the boofinity base). llama-swap forks the other
# two as child PROCESSES inside this one container; there is no Docker socket
# and no sibling-container lifecycle.
#
# CPU variant (default):
#   docker build -f hlh_swap/Dockerfile \
#     --build-arg BOOFINITY_BASE=ghcr.io/indifferentketchup/boofinity:0.1.0-cpu \
#     --build-arg LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-b9660 \
#     -t ghcr.io/indifferentketchup/hlh-swap:0.1.0-cpu .
#
# CUDA variant:
#   docker build -f hlh_swap/Dockerfile \
#     --build-arg BOOFINITY_BASE=ghcr.io/indifferentketchup/boofinity:0.1.0-cuda \
#     --build-arg LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda-b9660 \
#     -t ghcr.io/indifferentketchup/hlh-swap:0.1.0-cuda .

ARG BOOFINITY_BASE=ghcr.io/indifferentketchup/boofinity:0.1.0-cpu
ARG LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-b9660
ARG LLAMA_SWAP_IMAGE=ghcr.io/mostlygeek/llama-swap:v226

FROM ${LLAMA_CPP_IMAGE}  AS llamacpp
FROM ${LLAMA_SWAP_IMAGE} AS llamaswap

FROM ${BOOFINITY_BASE} AS final

# llama.cpp ships its shared libs in /app without ldconfig entries; carry them
# and point LD_LIBRARY_PATH at /app (CLAUDE.md read_only exception). The
# llama-server binary and its .so set both live under /app in the llama.cpp
# server image; the llama-swap binary is /app/llama-swap in mostlygeek's image.
COPY --from=llamacpp  /app/llama-server  /usr/local/bin/llama-server
COPY --from=llamacpp  /app/*.so          /app/
COPY --from=llamaswap /app/llama-swap    /usr/local/bin/llama-swap

ENV LD_LIBRARY_PATH=/app \
    HOME=/cache \
    HF_HOME=/cache \
    HF_HUB_OFFLINE=1

ENTRYPOINT ["/usr/local/bin/llama-swap"]
