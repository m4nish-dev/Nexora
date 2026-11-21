# syntax=docker/dockerfile:1

# ---- build stage: resolve and install dependencies into an isolated venv ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt /tmp/requirements.txt
# Trim the runtime venv: no bytecode (~110 MB; compiled lazily in memory at startup), no installer
# tooling, and no LiteLLM proxy admin-UI static bundle (we use the SDK, never the proxy server).
RUN pip install --no-compile -r /tmp/requirements.txt \
 && pip uninstall -y -q pip setuptools wheel \
 && find /opt/venv -type d -name "__pycache__" -prune -exec rm -r {} + \
 && rm -r /opt/venv/lib/python3.12/site-packages/litellm/proxy/_experimental/out

# ---- test stage (`make test` without a local venv): runtime deps + pytest + tests ----
# Not part of the runtime image: `docker compose` builds the final stage only.
FROM python:3.12-slim AS test
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pytest.ini ./
COPY app ./app
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q", "-rs"]

# ---- runtime stage: slim image with only the venv and application code ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    DATABASE_URL=sqlite:////data/app.db \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    PORT=8000
RUN useradd --create-home --uid 10001 nexora \
 && mkdir -p /data && chown nexora:nexora /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=nexora:nexora app ./app
USER nexora
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4).status == 200 else 1)"
# Single worker on purpose: the LiteLLM cache and the per-session locks live in process memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
