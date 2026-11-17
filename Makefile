# Fact Spreader — Phase 1
#
# The target commands are fixed in IMPLEMENT.md §1.1 and §15. `web-check` joins
# `verify` in Phase 7, when the SvelteKit app exists.
SHELL := /bin/bash
BACKEND := backend

# Keep uv and buildx state inside the workspace. This also makes the build work in
# sandboxed environments that cannot write to ~/.cache or ~/.docker.
export UV_CACHE_DIR := $(CURDIR)/.local/uv-cache
export BUILDX_CONFIG := $(CURDIR)/.local/buildx
export TESTCONTAINERS_RYUK_DISABLED := true
COMPOSE := docker compose
WEB := web
API_KEY_FILE := .local/api-key

.PHONY: install fmt fmt-check lint typecheck test test-integration migrate migrate-check \
	openapi openapi-check compose-check web-install web-check web-e2e verify stack-up \
	stack-down stack-logs bootstrap seed-fixtures stack-smoke spend clean

install:
	mkdir -p $(UV_CACHE_DIR) $(BUILDX_CONFIG)
	cd $(BACKEND) && uv sync --frozen

fmt:
	cd $(BACKEND) && uv run ruff format .

fmt-check:
	cd $(BACKEND) && uv run ruff format --check .

lint:
	cd $(BACKEND) && uv run ruff check .

typecheck:
	cd $(BACKEND) && uv run mypy app

test:
	cd $(BACKEND) && uv run pytest -m "not integration and not live"

test-integration:
	cd $(BACKEND) && uv run pytest -m "integration and not live"

migrate:
	$(COMPOSE) exec -T backend alembic upgrade head

migrate-check:
	cd $(BACKEND) && uv run python -m app.tools.migrate_check

openapi:
	cd $(BACKEND) && uv run python -m app.tools.export_openapi

openapi-check:
	cd $(BACKEND) && uv run python -m app.tools.export_openapi --check

compose-check:
	$(COMPOSE) config -q
	cd $(BACKEND) && uv run python -m app.tools.check_compose

web-install:
	cd $(WEB) && pnpm install --frozen-lockfile --store-dir $(CURDIR)/.local/pnpm-store

web-check:
	cd $(WEB) && pnpm check && pnpm build
	cd $(WEB) && pnpm gen:api
	git diff --exit-code -- $(WEB)/src/lib/openapi.d.ts

web-e2e:
	cd $(WEB) && pnpm test:e2e

verify: fmt-check lint typecheck test test-integration migrate-check openapi-check compose-check web-check

stack-up:
	$(COMPOSE) up -d --build

stack-down:
	$(COMPOSE) down

stack-logs:
	$(COMPOSE) logs -f --tail=200

bootstrap:
	$(COMPOSE) exec -T backend python -m app.cli bootstrap --print-api-key > $(API_KEY_FILE)
	@echo "API key written to $(API_KEY_FILE) (gitignored); value not printed."

seed-fixtures:
	$(COMPOSE) exec -T backend python -m app.cli seed-fixtures --approve

stack-smoke:
	cd $(BACKEND) && uv run python -m app.tools.smoke --api-key-file ../$(API_KEY_FILE)

spend:
	$(COMPOSE) exec -T backend python -m app.cli spend

retention:
	$(COMPOSE) exec -T backend python -m app.cli retention

clean:
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
