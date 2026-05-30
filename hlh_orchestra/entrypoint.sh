#!/bin/sh
# The orchestra is a one-shot bootstrap tool: create/repair the whole stack and
# exit. The vision-lifecycle FastAPI server was removed in v1.2.11 (MedSigLIP
# dropped; MedGemma vision is served on demand by the hlh_chat router), so there
# is no long-running process here. Launched via the install.sh `docker run` one-liner.
set -e
exec python /app/bootstrap.py
