#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p /shared/tmux
chown agent:agent /shared/tmux
# TODO(hygiene): 0770 + agent:agent works today because boolab_api runs as
# root and reaches the socket via CAP_DAC_OVERRIDE. When boolab_api is
# de-rooted, replace with (a) pin boolab_api to UID 1000, or
# (c) a shared supplementary group. Do NOT widen to 0666.
chmod 0770 /shared/tmux
exec su agent -c 'tmux -S /shared/tmux/default start-server && tail -f /dev/null'
