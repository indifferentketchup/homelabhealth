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

# Install the hlhstart / hlhupdate convenience commands so the operator has
# them after a one-shot install. Best-effort: needs a writable /usr/local/bin
# or passwordless sudo; skipped (with a hint) otherwise — never blocks the install.
RAW="${HLH_RAW_BASE:-https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main}"
BIN_DIR="/usr/local/bin"

_install_cmd() {  # $1 = command name
  local name="$1" tmp="/tmp/$1.$$"
  curl -fsSL "$RAW/$name" -o "$tmp" 2>/dev/null || return 1
  if [ -w "$BIN_DIR" ]; then
    mv "$tmp" "$BIN_DIR/$name" && chmod +x "$BIN_DIR/$name" && return 0
  elif sudo -n true 2>/dev/null; then
    sudo mv "$tmp" "$BIN_DIR/$name" && sudo chmod +x "$BIN_DIR/$name" && return 0
  fi
  rm -f "$tmp"
  return 1
}

if _install_cmd hlhstart && _install_cmd hlhupdate; then
  echo "→ Installed 'hlhstart' and 'hlhupdate' to $BIN_DIR"
else
  echo "→ (Skipped installing hlhstart/hlhupdate — need a writable $BIN_DIR or sudo."
  echo "   Add them later with the curl lines in the README.)"
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
  "$IMAGE"
