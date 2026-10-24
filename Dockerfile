# TwoWaysOut container image.
#
# Two stages so the raw Analyze Boston downloads (which include owner names and contact
# addresses) exist only in the builder. The final image gets just the preprocessed
# data/boston.sqlite, which is built from whitelisted columns.
#
# Secrets (ANTHROPIC_API_KEY, DASHBOARD_PASSWORD, SESSION_SECRET) are runtime env vars only.
# The optional Data Commons key is a BuildKit secret (id datacommons_api_key) used only by the
# builder's data step; it is never an ARG or ENV and never lands in a layer.

# ---------- builder: download + preprocess Boston data ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

COPY requirements.txt .
RUN pip install -r requirements.txt

# Preprocessing imports app.services.address_normalize, so app/ is needed here too.
COPY scripts/ scripts/
COPY app/ app/

# One RUN so the raw CSVs are fetched, used, and deleted in the same step (~450 MB download).
# The Data Commons key stays in the secret mount for this RUN only. build_data.sh reads the
# file and sets the key just for the Data Commons step. Without it, area context is skipped.
#   docker build --secret id=datacommons_api_key,src=/path/to/key -t twowaysout .
RUN --mount=type=secret,id=datacommons_api_key \
    mkdir -p data \
    && DATACOMMONS_API_KEY_FILE=/run/secrets/datacommons_api_key bash scripts/build_data.sh --python python \
    && rm -rf data/raw \
    && test -f data/boston.sqlite

# ---------- final: runtime image ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_DB_PATH=/data/app.sqlite \
    FORCE_SECURE_COOKIES=true \
    SEED_SIMULATED=0

RUN useradd --system --uid 10001 --create-home --home-dir /home/app app
WORKDIR /app

# Runtime deps only; requirements-dev.txt is never installed here.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/
# Start-up only needs the simulated-report seeder (it imports app/ only). The rest of
# scripts/ is the data pipeline, which runs in the builder.
COPY scripts/__init__.py scripts/seed_reports.py scripts/
COPY samples/ samples/
COPY docker/entrypoint.sh docker/entrypoint.sh
# Only the preprocessed DB crosses over from the builder; data/raw never does.
COPY --from=builder /build/data/boston.sqlite data/boston.sqlite

# boston.sqlite is read-only city data; /data holds the writable tenant reports DB.
RUN chmod 0755 docker/entrypoint.sh \
    && chmod 0444 data/boston.sqlite \
    && test ! -e data/raw \
    && mkdir -p /data \
    && chown app:app /data

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# The entrypoint seeds simulated reports when SEED_SIMULATED=1 and the table is empty, then execs:
#   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log --proxy-headers
#     --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
# Set FORWARDED_ALLOW_IPS to the proxy's address or range so X-Forwarded-For is trusted only
# from it (see docs/DEPLOY.md).
CMD ["/app/docker/entrypoint.sh"]
