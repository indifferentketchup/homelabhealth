FROM python:3.12-slim
WORKDIR /app

# Bootstrap-only tool: just needs the Docker SDK. (The FastAPI vision-lifecycle
# server was removed in v1.2.11 along with MedSigLIP.)
RUN pip install --no-cache-dir docker==7.*

# Templates baked into image; bootstrap.py writes them into hlh_config volume
# on first run so other containers can read them.
COPY templates /app/templates

COPY bootstrap.py /app/bootstrap.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
