# ---- builder: create a venv with all deps + the app baked in ----
FROM python:3.12-slim AS builder

# All subsequent pip/python calls use this venv (PATH trick), so the final
# stage only needs to copy /opt/venv.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /app

# 1) Manifest first. The heavy dependency install (torch, sentence-transformers, ...)
#    is cached and only re-runs when pyproject.toml changes, not on source edits.
#    setuptools' packages.find needs the package dir to exist, so we install against
#    an empty stub here; the real source is baked in the next layer.
COPY pyproject.toml ./
RUN mkdir -p src/rag_app && touch src/rag_app/__init__.py \
    && pip install --no-cache-dir .

# 2) Real source last. --force-reinstall because the version (0.1.0) is unchanged,
#    so without it pip treats the package as already satisfied and would ship the
#    empty stub. --no-deps keeps the cached dependency layer above untouched.
COPY src ./src
RUN pip install --no-cache-dir --no-deps --force-reinstall .

# ---- final: slim runtime, just the venv ----
FROM python:3.12-slim AS final

COPY --from=builder /opt/venv /opt/venv
COPY ./static /app/static
ENV PATH="/opt/venv/bin:$PATH"
ENV STATIC_DIR="/app/static"
EXPOSE 8000
CMD ["uvicorn", "rag_app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
