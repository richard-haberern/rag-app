# syntax=docker/dockerfile:1

# ---- builder: create a venv with all deps + the app baked in ----
FROM python:3.12-slim AS builder

# All subsequent pip/python calls use this venv (PATH trick), so the final
# stage only needs to copy /opt/venv.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/pip pip install --upgrade pip

WORKDIR /app

# 1) Manifest first. The heavy dependency install (torch, sentence-transformers, ...)
#    is cached and only re-runs when pyproject.toml changes, not on source edits.
#    setuptools' packages.find needs the package dir to exist, so we install against
#    an empty stub here; the real source is baked in the next layer.
#    The pip cache mount is safe here: this whole stage is discarded except for
#    /opt/venv, so caching downloaded wheels costs nothing in the final image and
#    speeds up rebuilds after any pyproject.toml edit.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir -p src/rag_app && touch src/rag_app/__init__.py && pip install .

# 2) Real source last. --force-reinstall because the version (0.1.0) is unchanged,
#    so without it pip treats the package as already satisfied and would ship the
#    empty stub. --no-deps keeps the cached dependency layer above untouched.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps --force-reinstall .

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
