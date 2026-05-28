FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.* uvicorn[standard]==0.32.* docker==7.*

# Templates baked into image; bootstrap.py writes them into hlh_config volume
# on first run so other containers can read them.
COPY templates /app/templates

COPY bootstrap.py /app/bootstrap.py
COPY app.py /app/app.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 9620
CMD ["/app/entrypoint.sh"]
