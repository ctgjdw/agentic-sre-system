COMPOSE := docker compose

.PHONY: up up-fake down logs ps test test-ui lint lint-ui migrate smoke e2e provision holmes-check live-check

up:
	$(COMPOSE) --profile live --profile ui up -d --build

up-fake:
	$(COMPOSE) --profile fake --profile ui up -d --build

down:
	$(COMPOSE) --profile fake --profile live --profile ui down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test:
	cd gateway && uv run pytest -q
	$(MAKE) test-ui

test-ui:
	cd ui && npm test

lint:
	cd gateway && uv run ruff check .
	$(MAKE) lint-ui

lint-ui:
	cd ui && npm run lint

migrate:
	cd gateway && uv run alembic upgrade head

smoke:
	SRE_MODELS_PROFILE=fake SRE_HOLMES_URL=http://fake-holmes:5050 \
	SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm \
	$(COMPOSE) --profile fake up -d --build
	cd gateway && uv run python ../scripts/smoke.py

e2e:
	# Fresh DB: the fake scripts drive exactly one case per gateway lifetime, so a
	# clean slate (no persisted open cases relaunched on boot) is required for a
	# deterministic run. `-v` drops the postgres volume before bringing the stack up.
	$(COMPOSE) --profile fake --profile live --profile ui down -v
	SRE_MODELS_PROFILE=fake SRE_HOLMES_URL=http://fake-holmes:5050 \
	SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm \
	$(COMPOSE) --profile fake --profile ui up -d --build
	cd ui && npx playwright test --config e2e/playwright.config.ts

holmes-check:
	curl -s -X POST localhost:5050/api/chat \
	  -H 'Content-Type: application/json' \
	  -d '{"ask": "Domain: metrics\nUsing PromQL, report the value of the `up` metric and how many series are up.", "model": "vertex_ai/gemini-2.5-pro"}' \
	  | python3 -m json.tool | head -80

live-check:
	cd gateway && uv run python ../scripts/live_check.py
