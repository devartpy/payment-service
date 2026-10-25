.DEFAULT_GOAL := help

COMPOSE := docker compose
UV := uv run --locked

.PHONY: help up down restart build infra-up migration upgrade lint fmt test ci

help: ## Show available commands
	@echo up          - build images, apply migrations, start all services
	@echo down        - stop containers, keep database data
	@echo restart     - restart existing containers
	@echo build       - build the API image
	@echo infra-up    - start PostgreSQL and RabbitMQ, wait for readiness
	@echo migration   - generate a revision, pass m=revision_name
	@echo upgrade     - build the API image and apply migrations
	@echo lint fmt    - check or format Python code
	@echo test ci     - run tests or all checks plus image build

up: infra-up ## Build, migrate and start all services
	$(COMPOSE) build
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) up -d --wait

down: ## Stop containers without deleting database data
	$(COMPOSE) down

restart: ## Restart existing containers
	$(COMPOSE) restart

build: ## Build the API image
	$(COMPOSE) build api

infra-up: ## Start PostgreSQL and RabbitMQ, wait for readiness
	$(COMPOSE) up -d --wait db rabbitmq

migration: ## Generate a migration: make migration m=init_tables
	$(if $(strip $(m)),,$(error Set migration name: make migration m=init_tables))
	$(MAKE) infra-up
	$(UV) alembic revision --autogenerate -m "$(m)"

upgrade: infra-up ## Build API image and apply migrations before starting the app
	$(COMPOSE) build api
	$(COMPOSE) run --rm api alembic upgrade head

lint: ## Check Python code and formatting
	$(UV) ruff check .
	$(UV) ruff format --check .

fmt: ## Fix lint findings and format Python code
	$(UV) ruff check --fix .
	$(UV) ruff format .

test: ## Run tests in the local development environment
	$(UV) pytest

ci: lint test build ## Run checks and build the API image
