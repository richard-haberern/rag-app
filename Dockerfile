# syntax=docker/dockerfile:1

# ---- builder: create a venv with all deps + the app baked in, via uv ----
FROM python:3.12-slim AS builder

# uv binary from the official image, pinned (not :latest) for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /uvx /bin/

# UV_PROJECT_ENVIRONMENT: put the project venv where the final stage expects it
#   (uv's default is /app/.venv), so the final stage's copy/PATH stay unchanged.
# UV_PYTHON_DOWNLOADS=0: use this image's Python 3.12, never fetch a separate one.
# UV_COMPILE_BYTECODE=1: precompile .pyc for faster container cold-start.
# UV_LINK_MODE=copy: copy out of the cache mount (hardlinks can't cross its filesystem).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 1) Deps only. The heavy install (torch, sentence-transformers, ...) is cached and
#    only re-runs when uv.lock / pyproject.toml change, not on source edits.
#    --no-install-project installs dependencies without the project itself (replaces
#    the old empty-stub hack); --no-dev drops the dev group (pytest/ruff/mypy);
#    --frozen installs exactly what uv.lock pins and errors if it's stale.
#    The manifests are bind-mounted (not COPYed into a layer); the uv cache mount is
#    discarded from the final image, so it costs nothing there and speeds rebuilds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# 2) Real source last, then install the project itself on top of the cached deps.
#    --no-editable bakes the built package into /opt/venv (no editable link back to
#    /app/src), so the final stage keeps copying only the venv and needs no source tree.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-editable

# ---- final: slim runtime, just the venv ----
FROM python:3.12-slim AS final

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY ./static ./static
COPY alembic.ini ./
COPY alembic ./alembic
# alembic reads [tool.alembic] (script_location, version_locations) from pyproject.toml
# alongside alembic.ini -- it isn't duplicated into alembic.ini itself. Also, without a
# WORKDIR set, `alembic` invoked bare (docker compose run --rm api alembic ...) can't
# find alembic.ini at all since its cwd defaults to /.
COPY pyproject.toml ./
ENV PATH="/opt/venv/bin:$PATH"
ENV STATIC_DIR="/app/static"
EXPOSE 8000
CMD ["uvicorn", "rag_app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
