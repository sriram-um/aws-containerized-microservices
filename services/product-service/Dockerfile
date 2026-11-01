# syntax=docker/dockerfile:1
# Multi-stage build: dependencies are installed into a virtualenv in the builder stage; the
# runtime stage copies only that venv and the application code (no pip cache, no build files).
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

# ---------- builder ----------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
# Production dependencies only (test tools live in requirements-dev.txt)
RUN pip install -r requirements.txt \
 && pip uninstall -y pip   # the venv's own pip (~13 MB) isn't needed at runtime

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
COPY product_service ./product_service
USER app
EXPOSE 3000
# Used by `docker run`/compose. ECS ignores it: the task definition declares its own healthCheck.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=2)"]
# Exec form: uvicorn is PID 1 and receives SIGTERM from ECS for a graceful shutdown.
# --proxy-headers: trust X-Forwarded-* from the ALB.
CMD ["uvicorn", "product_service.main:app", "--host", "0.0.0.0", "--port", "3000", "--proxy-headers", "--forwarded-allow-ips", "*"]
