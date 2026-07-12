COMPOSE := docker compose

.PHONY: up up-fake down logs ps test lint migrate smoke provision

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
