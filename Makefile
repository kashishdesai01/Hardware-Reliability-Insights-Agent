COMPOSE ?= docker-compose

.PHONY: setup lint test seed-smoke seed-full api worker eval web docker-up docker-down

setup:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest --cov=hria --cov-report=term-missing

seed-smoke:
	uv run hria-generate --profile smoke --seed 4471 --load

seed-full:
	uv run hria-generate --profile full --seed 4471 --load

api:
	uv run uvicorn hria.api.main:app --reload --port 8000

worker:
	uv run arq hria.worker.WorkerSettings

eval:
	uv run hria-eval --cases hria/evals/cases

web:
	cd web && npm run dev

docker-up:
	$(COMPOSE) up --build

docker-down:
	$(COMPOSE) down
