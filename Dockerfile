# Build the web client here so `docker build .` works from a clean checkout with no prior
# `npm run build` (#111). Pinned to the native BUILDPLATFORM so that, during a multi-arch buildx
# build, vite runs on the build host instead of under slow QEMU emulation — the emitted bundle is
# static and architecture-independent, so it is safe to reuse across every target platform.
FROM --platform=$BUILDPLATFORM node:22-slim AS client-builder

WORKDIR /client

# Install dependencies first so this layer is cached unless the manifests change. .npmrc is copied
# too: it sets legacy-peer-deps, without which npm ci fails on a peer-dependency conflict.
COPY client/package.json client/package-lock.json client/.npmrc ./
RUN npm ci

# Then the source, and build. VITE_APIURL matches the CI build so the API is served under /api/v1.
COPY client/ ./
RUN echo "VITE_APIURL=/api/v1" > .env.production && npm run build

FROM python:3.14-slim-trixie AS python-builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1
ENV UV_PYTHON_DOWNLOADS=0

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    python3-dev \
    libpq-dev \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip install --no-cache-dir uv

# The NFC extra is installed on every platform. On 32-bit ARM the lockfile
# resolves cbor2 to the C-based 5.x line (6.x is a Rust extension with no armv7
# wheel); CBOR2_BUILD_C_EXTENSION=false makes it build as pure Python so no
# extra toolchain is needed for it. The flag is ignored by cbor2 6.x on
# amd64/arm64, which install from prebuilt wheels.
ENV CBOR2_BUILD_C_EXTENSION=false

# Install dependencies
WORKDIR /home/app/spoolman
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --extra nfc

# Copy and install app
COPY migrations /home/app/spoolman/migrations
COPY spoolman /home/app/spoolman/spoolman
COPY alembic.ini README.md uv.lock pyproject.toml /home/app/spoolman/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra nfc

FROM python:3.14-slim-trixie AS python-runner

LABEL org.opencontainers.image.title="Spoolman NG"
LABEL org.opencontainers.image.source=https://github.com/sherrmann/Spoolman-NG
LABEL org.opencontainers.image.description="Spoolman NG - a community-maintained continuation of Spoolman. Keep track of your inventory of 3D-printer filament spools."
LABEL org.opencontainers.image.licenses=MIT

# Install gosu for privilege dropping and libusb for NFC reader support.
# libstdc++6 (C++ runtime, see the LD_PRELOAD note below) and libpq5 (libpq for
# psycopg2/PostgreSQL, which has no armv7 wheel and is compiled from source) are
# needed by the 32-bit ARM image; on amd64/arm64 they come in via prebuilt wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    libusb-1.0-0 \
    libstdc++6 \
    libpq5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# greenlet (required by SQLAlchemy's async engine on every backend) has no armv7
# wheel, so on 32-bit ARM it is compiled from source — and setuptools links the
# extension with gcc, leaving libstdc++.so.6 out of the .so's NEEDED list even
# though it uses libstdc++ C++ ABI symbols. That makes greenlet fail to import
# with "undefined symbol: _ZTVN10__cxxabiv120__si_class_type_infoE", aborting
# startup before the API comes up. Preload libstdc++ by SONAME (resolved per-arch
# via ldconfig) so the symbols are available. No-op on amd64/arm64, where greenlet
# installs from a correctly linked wheel.
ENV LD_PRELOAD=libstdc++.so.6

# Add local user so we don't run as root
RUN useradd -u 1000 -U app \
    && mkdir -p /home/app/.local/share/spoolman \
    && chown -R app:app /home/app/.local/share/spoolman

# Copy the client bundle built in the client-builder stage above (#111).
COPY --chown=app:app --from=client-builder /client/dist /home/app/spoolman/client/dist

# Copy built app
COPY --chown=app:app --from=python-builder /home/app/spoolman /home/app/spoolman

COPY entrypoint.sh /home/app/spoolman/entrypoint.sh
RUN chmod +x /home/app/spoolman/entrypoint.sh

WORKDIR /home/app/spoolman

ENV PATH="/home/app/spoolman/.venv/bin:${PATH}"
# Arbitrary-UID runs (--user, OpenShift) get no passwd entry and would inherit
# HOME=/, making platformdirs resolve the data dir under / and crash on mkdir.
# Pin HOME so the data dir always resolves to the documented mount point (#239).
ENV HOME=/home/app

ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_DATE=${BUILD_DATE}

# Write GIT_COMMIT and BUILD_DATE to a build.txt file
RUN echo "GIT_COMMIT=${GIT_COMMIT}" > build.txt \
    && echo "BUILD_DATE=${BUILD_DATE}" >> build.txt

# Run command
EXPOSE 8000

# Add healthcheck to verify the API is responsive using the internal Python interpreter
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import os, urllib.request; \
    port = os.getenv('SPOOLMAN_PORT', '8000'); \
    base = os.getenv('SPOOLMAN_BASE_PATH', '').strip('/'); \
    path = f'/{base}/api/v1/health'.replace('//', '/'); \
    urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=5)" || exit 1

ENTRYPOINT ["/home/app/spoolman/entrypoint.sh"]
