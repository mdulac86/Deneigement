# Relais météo du bureau (MétéoMédia + Weather Underground) pour un NAS Synology.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "beautifulsoup4>=4.12,<5"
ENV TZ=America/Toronto PYTHONUNBUFFERED=1
COPY run.py /app/run.py
CMD ["python", "/app/run.py"]
