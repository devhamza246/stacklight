COMPOSE_DEV = docker compose -p stacklight-dev -f docker-compose.yml -f docker-compose.dev.yml

# Node runs only in Docker; nothing is installed on the host. Files stay owned by the current user.
NODE_IMG = node:22-slim
NODE_RUN = docker run --rm --user $$(id -u):$$(id -g) -e HOME=/tmp -e npm_config_cache=/app/.npm-cache \
	-v "$(CURDIR)/frontend":/app -w /app $(NODE_IMG)

.PHONY: up down dev-db test seed eval eval-retrieval web-lock web-install web-test web-typecheck web-build web-dev e2e e2e-screens
# Regenerate package-lock.json after editing package.json (exact versions are pinned there).
web-lock:
	$(NODE_RUN) npm install --package-lock-only
web-install:
	$(NODE_RUN) npm ci
web-test:
	$(NODE_RUN) npm test
web-typecheck:
	$(NODE_RUN) npm run typecheck
web-build:
	$(NODE_RUN) npm run build
# Vite dev server on http://127.0.0.1:5173 proxying /api to 127.0.0.1:8000 (host networking). Start the API with
# `cd backend && .venv/bin/uvicorn app.api.main:app --port 8000`. Override with API_TARGET=http://host:port
web-dev:
	docker run --rm -it --network host --user $$(id -u):$$(id -g) -e HOME=/tmp -e npm_config_cache=/app/.npm-cache \
		-e API_TARGET=$${API_TARGET:-http://127.0.0.1:8000} -v "$(CURDIR)/frontend":/app -w /app $(NODE_IMG) npm run dev
# Browser end-to-end tests: the real FastAPI app with a stubbed LLM (backend/tests/e2e/server.py).
e2e: web-build dev-db
	cd backend && .venv/bin/pytest -m e2e tests/e2e -v
# Same, and rewrites docs/ui/screens/*.png (desktop/mobile x light/dark).
e2e-screens: web-build dev-db
	cd backend && E2E_SCREENSHOTS=1 .venv/bin/pytest -m e2e tests/e2e -v
up:
	docker compose up -d --build
down:
	docker compose down
dev-db:
	$(COMPOSE_DEV) up -d --wait postgres redis
test: dev-db
	cd backend && .venv/bin/pytest -v
seed: dev-db
	cd backend && .venv/bin/python -m app.cli seed
EVAL = cd backend && PYTHONPATH=.. .venv/bin/python -m
# Seeding is idempotent (unchanged files are skipped), so it only does work on an empty DB.
eval: seed
	$(EVAL) evals.run --pipeline naive
	$(EVAL) evals.run --pipeline hybrid
	$(EVAL) evals.report
eval-retrieval: seed
	$(EVAL) evals.run --pipeline naive --retrieval-only
	$(EVAL) evals.run --pipeline hybrid --retrieval-only
	$(EVAL) evals.report ../evals/results/naive.retrieval.json ../evals/results/hybrid.retrieval.json
