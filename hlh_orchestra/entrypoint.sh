#!/bin/sh
# Entrypoint: in bootstrap mode, run bootstrap then start FastAPI.
# In normal (compose) mode, skip bootstrap and just run FastAPI.
set -e
exec uvicorn app:app --host 0.0.0.0 --port 9620 --log-level info
