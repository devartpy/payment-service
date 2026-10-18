.DEFAULT_GOAL := help

COMPOSE := docker compose
UV := uv run --locked

.PHONY: help up down restart build infra-up migration upgrade lint fmt test ci

help: ## Show available commands
	@echo up          - build and start API and PostgreSQL
	@echo down        - stop containers, keep database data
	@echo restart     - restart existing containers
	@echo build       - build the API image
	@echo infra-up    - start PostgreSQL and wait for readiness
	@echo migration   - generate a revision, pass m=revision_name
	@echo upgrade     - rebuild the API and apply migrations
	@echo lint fmt    - check or format Python code
	@echo test ci     - run tests or all checks plus image build

up: ## Build and start API and PostgreSQL
	$(COMPOSE) up -d --build --wait

down: ## Stop containers without deleting database data
	$(COMPOSE) down

restart: ## Restart existing containers
	$(COMPOSE) restart

build: ## Build the API image
	$(COMPOSE) build api

infra-up: ## Start PostgreSQL and wait for readiness
	$(COMPOSE) up -d --wait db

migration: ## Generate a migration: make migration m=init_tables
	$(if $(strip $(m)),,$(error Set migration name: make migration m=init_tables))
	$(MAKE) infra-up
	$(UV) alembic revision --autogenerate -m "$(m)"

upgrade: up ## Rebuild with current revisions and upgrade the database
	$(COMPOSE) exec -T api alembic upgrade head

lint: ## Check Python code and formatting
	$(UV) ruff check .
	$(UV) ruff format --check .

fmt: ## Fix lint findings and format Python code
	$(UV) ruff check --fix .
	$(UV) ruff format .

test: ## Run tests in the local development environment
	$(UV) pytest

ci: lint test build ## Run checks and build the API image
