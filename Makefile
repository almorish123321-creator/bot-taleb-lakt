# https://claude.ai/chat/341e2b6a-ecd2-4aba-924a-1f1ad3758700
.PHONY: install lint format test clean docker-build docker-run

# Variables
PYTHON = python3
VENV = .venv
BIN = $(VENV)/bin

# Installation and setup
install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	$(BIN)/pip install ruff mypy types-requests types-python-dotenv

# Linting and formatting
lint:
	$(BIN)/ruff check src/
	$(BIN)/mypy src/

format:
	$(BIN)/ruff format src/

# Testing
test:
	$(BIN)/python -m pytest tests/

# Cleaning
clean:
	rm -rf __pycache__
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .mypy_cache
	rm -rf *.session
	rm -rf *.session-journal
	find . -type d -name __pycache__ -exec rm -r {} +

# Docker commands
docker-build:
	docker-compose build

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

# Development shortcuts
dev-setup: install format lint

# Run the application
run:
	$(BIN)/python src/main.py
