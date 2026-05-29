#!/usr/bin/env bash
#
# homelabhealth GPU enabler — makes Docker able to pass an NVIDIA GPU into
# containers. Run ONCE on the host (not in a container):
#
#   curl -fsSL https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/enable-gpu.sh | sudo bash
#
# This installs the NVIDIA Container Toolkit and registers the nvidia runtime
# with Docker. It does NOT install the GPU driver — on WSL that comes from the
# NVIDIA driver on Windows; on bare Linux install your distro's NVIDIA driver
# first. Verify with `nvidia-smi` before running this.
#
set -euo pipefail

err() { echo "error: $*" >&2; exit 1; }
note() { echo "→ $*"; }

[ "$(id -u)" -eq 0 ] || err "run as root (use: sudo bash) — this installs a package and reconfigures Docker."

command -v docker >/dev/null 2>&1 || err "docker not found on PATH."

# WSL exposes nvidia-smi under /usr/lib/wsl/lib, which sudo's secure_path drops
# from PATH — so without this the check fails as root even though the GPU works.
[ -d /usr/lib/wsl/lib ] && export PATH="$PATH:/usr/lib/wsl/lib"

command -v nvidia-smi >/dev/null 2>&1 || err "nvidia-smi not found. Install the GPU driver first (on WSL: the NVIDIA driver on Windows)."

note "Host GPU visible:"
nvidia-smi -L || err "nvidia-smi failed — the host can't see the GPU. Fix the driver before continuing."

command -v apt-get >/dev/null 2>&1 || err "this script supports apt-based distros (Debian/Ubuntu/WSL). For others see: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"

note "Adding NVIDIA Container Toolkit repo…"
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list

note "Installing nvidia-container-toolkit…"
apt-get update -qq
apt-get install -y -qq nvidia-container-toolkit

note "Registering the nvidia runtime with Docker…"
nvidia-ctk runtime configure --runtime=docker

note "Restarting Docker…"
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet docker 2>/dev/null; then
  systemctl restart docker
elif command -v service >/dev/null 2>&1; then
  service docker restart || err "could not restart docker. If you use Docker Desktop, restart it from Windows instead, then re-run the verify step."
else
  err "couldn't find a way to restart docker. Restart it manually, then run the verify step."
fi

note "Verifying Docker can pass the GPU…"
if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L; then
  echo
  echo "✅ GPU is available to Docker. Now (re)run the homelabhealth installer:"
  echo "   docker rm -f hlh_api hlh_chat hlh_ui 2>/dev/null || true"
  echo "   curl -fsSL https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/install.sh | bash"
else
  err "Docker still can't pass the GPU. If you're on Docker Desktop, ensure WSL integration + a recent version; otherwise see the toolkit install guide."
fi
