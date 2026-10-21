# Development verification only. This does not implement a NEXUS runtime sandbox.
FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    HOME=/tmp/nexus-home

WORKDIR /app
COPY verification/uv-bootstrap.txt /tmp/uv-bootstrap.txt
COPY verification/build-requirements.txt /tmp/build-requirements.txt
RUN pip install --require-hashes --only-binary=:all: -r /tmp/uv-bootstrap.txt
COPY pyproject.toml uv.lock ./
# Install only hash-pinned third-party wheels before any repository code is copied.
# The project backend runs later, non-root and offline in the hardened container.
RUN uv export --frozen --no-emit-project --format requirements-txt -o /tmp/dependencies.txt && \
    uv pip install --system --require-hashes --only-binary=:all: -r /tmp/dependencies.txt && \
    uv pip install --system --require-hashes --only-binary=:all: -r /tmp/build-requirements.txt && \
    rm -rf /root/.cache
COPY src ./src
COPY tests ./tests
COPY verification/run.sh ./verification/run.sh
COPY verification/verify_package.py ./verification/verify_package.py
RUN chmod -R a-w /app
USER 65532:65532
CMD ["sh", "/app/verification/run.sh"]
