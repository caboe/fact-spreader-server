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
# Astro telemetry writes outside the workspace and is irrelevant in tests and builds.
export ASTRO_TELEMETRY_DISABLED := 1
COMPOSE := docker compose
WEB := web
SITE := site
API_KEY_FILE := .local/api-key
EVAL_API_KEY_FILE ?= .local/eval-api-key

.PHONY: install fmt fmt-check lint typecheck test test-integration migrate migrate-check \
	openapi openapi-check compose-check web-install web-check web-e2e site-install site-check \
	verify stack-up \
	stack-down stack-logs bootstrap seed-fixtures stack-smoke spend clean \
	eval-check eval-recorded eval-live backup backup-test clean-start-test schemathesis

install:
	mkdir -p $(UV_CACHE_DIR) $(BUILDX_CONFIG)
	cd $(BACKEND) && uv sync --frozen
	cd $(WEB) && pnpm install --frozen-lockfile
	cd $(SITE) && pnpm install --frozen-lockfile --store-dir $(CURDIR)/.local/pnpm-store

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

site-install:
	cd $(SITE) && pnpm install --frozen-lockfile --store-dir $(CURDIR)/.local/pnpm-store

# Build the handbook, check its links, then compose and check the public site tree.
site-check:
	cd $(SITE) && pnpm check
	cd $(SITE) && pnpm build
	cd $(SITE) && pnpm check:links
	cd $(SITE) && pnpm build:public
	cd $(SITE) && pnpm check:links:public

verify: fmt-check lint typecheck test test-integration migrate-check openapi-check compose-check web-check site-check

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

backup:
	./scripts/backup.sh

backup-test:
	./scripts/backup-test.sh

clean-start-test:
	./scripts/clean-start-test.sh

schemathesis:
	@test -f "$(EVAL_API_KEY_FILE)" || (echo "missing $(EVAL_API_KEY_FILE); see docs/EVALUATION.md" && exit 2)
	cd $(BACKEND) && uv run schemathesis run http://127.0.0.1:8000/openapi.json \
		--base-url http://127.0.0.1:8000 \
		-H "Authorization: Bearer $$(cat ../$(EVAL_API_KEY_FILE))" \
		--exclude-method POST --exclude-method PUT --exclude-method PATCH --exclude-method DELETE \
		--checks all --hypothesis-max-examples 20 --workers 4 --experimental=openapi-3.1

eval-check:
	cd $(BACKEND) && uv run python -m app.tools.eval --set ../tests/eval/claims.jsonl --check-only

eval-recorded:
	cd $(BACKEND) && uv run python -m app.tools.eval --set ../tests/eval/claims.jsonl \
		--predictions ../tests/eval/predictions.baseline.jsonl

eval-live:
	@test -f "$(EVAL_API_KEY_FILE)" || (echo "missing $(EVAL_API_KEY_FILE); create a key with: docker compose exec -T backend python -m app.cli create-api-key --email <admin> --name eval-live > $(EVAL_API_KEY_FILE)" && exit 2)
	cd $(BACKEND) && uv run python -m app.tools.eval --live --set ../tests/eval/claims.jsonl \
		--api-key-file ../$(EVAL_API_KEY_FILE) --out ../tests/eval/predictions.baseline.jsonl

clean:
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
