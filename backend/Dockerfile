# Build context is the REPO ROOT (see docker-compose.yml): `docker build -f backend/Dockerfile .`
# so that frontend/ and corpus/ can be copied in.

# ---- Stage 1: build the React app ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: API image (serves the built app from /srv/static) ----
FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 STATIC_DIR=/srv/static CORPUS_DIR=/srv/corpus
COPY backend/pyproject.toml ./
# Dependencies first, against a stub package, so editing app code never rebuilds the (huge) torch layer.
RUN mkdir app && touch app/__init__.py \
    && pip install --extra-index-url https://download.pytorch.org/whl/cpu . \
    && pip uninstall -y stacklight && rm -rf app build *.egg-info
COPY backend/app ./app
# Cheap: the app is imported from /srv/app (the working directory); migrations ship as package data.
RUN pip install --no-deps .
COPY --from=web /web/dist /srv/static
# The shipped sample corpus, seeded on first start. Stored sources are "corpus/<path>" (relative to /srv).
COPY corpus /srv/corpus

# Run as an unprivileged user. The home directory is writable so model downloads (Hugging Face cache) work.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app app \
    && mkdir -p /home/app/.cache/huggingface && chown -R app:app /home/app
# Model cache: compose mounts a named volume here (initialised from this directory, so uid 10001 can write).
ENV HOME=/home/app HF_HOME=/home/app/.cache/huggingface
USER app
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
