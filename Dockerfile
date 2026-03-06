FROM python:3.12-slim

# System packages needed for zoneinfo / tzdata
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source
COPY app/ ./app/

# Ensure data dir exists at build time (will be overridden by volume)
RUN mkdir -p data

# Run as non-root
RUN addgroup --system app && adduser --system --ingroup app app && \
    chown -R app:app /app
USER app

CMD ["python", "-m", "app.main", "run"]

# Health check: status file must be fresh (< 120 s old) and ready=true
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python - <<'EOF'
import json, sys, time, os
p = os.environ.get("STATUS_FILE_PATH", "data/status.json")
try:
    d = json.load(open(p))
except Exception:
    sys.exit(1)
if not d.get("ready"):
    sys.exit(1)
last = d.get("last_keepalive_at") or d.get("started_at")
if last:
    import datetime
    try:
        age = time.time() - datetime.datetime.fromisoformat(last.replace("Z","+00:00")).timestamp()
        if age > 120:
            sys.exit(1)
    except Exception:
        pass
sys.exit(0)
EOF
