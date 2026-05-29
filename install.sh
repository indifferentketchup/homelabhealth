#!/usr/bin/env bash
#
# homelabhealth installer — brings up the whole stack with one command.
#
#   curl -fsSL https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/install.sh | bash
#
# All it does is run the orchestra bootstrap container, which creates the
# network/volumes/secrets, pulls every image, and starts the stack. When it
# finishes it prints the URL to open (default http://localhost:9604).
#
set -euo pipefail

IMAGE="${HLH_ORCHESTRA_IMAGE:-ghcr.io/indifferentketchup/hlh_orchestra:latest}"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is not installed or not on PATH." >&2
  echo "Install Docker first: https://docs.docker.com/engine/install/" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: cannot talk to the Docker daemon (is it running? do you need sudo?)." >&2
  exit 1
fi

echo "→ Starting homelabhealth…"

# Only request a TTY when we actually have one. Piped execution
# (curl … | bash) has no terminal on stdin, and `docker run -it` errors
# with "cannot attach stdin to a TTY-enabled container" in that case.
TTY_FLAGS=""
if [ -t 0 ] && [ -t 1 ]; then
  TTY_FLAGS="-it"
fi

exec docker run --rm $TTY_FLAGS \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HLH_BOOTSTRAP=1 \
  "$IMAGE"
