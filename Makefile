.PHONY: install test lint run-api run-web migrate compose-up e0-verify

install:
	python3 -m pip install -U pip
	python3 -m pip install -e ".[dev]"
	cd apps/web && npm install

lint:
	ruff check packages apps/api apps/workers tests
	cd apps/web && npm run lint

test:
	mkdir -p data
	PYTHONPATH=packages:apps pytest -q

run-api:
	mkdir -p data
	PYTHONPATH=packages:apps uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

run-web:
	cd apps/web && npm run dev -- --port 3000

migrate:
	mkdir -p data
	PYTHONPATH=packages:apps alembic upgrade head

compose-up:
	docker compose -f deploy/compose/docker-compose.yml up -d

e0-verify: install lint test
	@echo "E0 regression gate passed"

e6-verify: test
	cd apps/web && npm run build
	@echo "E6 regression gate passed"
