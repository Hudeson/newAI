.PHONY: install test lint run-api migrate compose-up e0-verify

install:
	python3 -m pip install -U pip
	python3 -m pip install -e ".[dev]"

lint:
	ruff check packages apps tests

test:
	mkdir -p data
	pytest -q

run-api:
	mkdir -p data
	PYTHONPATH=packages:apps uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

migrate:
	mkdir -p data
	PYTHONPATH=packages:apps alembic upgrade head

compose-up:
	docker compose -f deploy/compose/docker-compose.yml up -d

e0-verify: install lint test
	@echo "E0 regression gate passed"
