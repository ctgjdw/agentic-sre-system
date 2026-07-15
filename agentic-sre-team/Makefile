COMPOSE := docker compose

.PHONY: up up-fake down logs ps test lint migrate smoke provision holmes-check live-check

up:
	$(COMPOSE) up -d --build

up-fake:
	$(COMPOSE) --profile fake up -d --build

down:
	$(COMPOSE) --profile fake down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test:
	cd gateway && uv run pytest -q

lint:
	cd gateway && uv run ruff check .

migrate:
	cd gateway && uv run alembic upgrade head

smoke:
	SRE_MODELS_PROFILE=fake SRE_HOLMES_URL=http://fake-holmes:5050 \
	SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm \
	$(COMPOSE) --profile fake up -d --build
	cd gateway && uv run python ../scripts/smoke.py

holmes-check:
	curl -s -X POST localhost:5050/api/chat \
	  -H 'Content-Type: application/json' \
	  -d '{"ask": "Domain: metrics\nUsing PromQL, report the value of the `up` metric and how many series are up.", "model": "vertex_ai/gemini-2.5-pro"}' \
	  | python3 -m json.tool | head -80

live-check:
	cd gateway && uv run python ../scripts/live_check.py
