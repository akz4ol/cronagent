# CronAgent Makefile
# Common commands for development and deployment

.PHONY: help install dev test lint format build run daemon clean docker-build docker-up docker-down docker-logs docker-shell prod-up prod-down

# Default target
help:
	@echo "CronAgent Development Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install      Install dependencies"
	@echo "  make dev          Install with dev dependencies"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linters"
	@echo "  make format       Format code"
	@echo ""
	@echo "Running:"
	@echo "  make run          Run interactive agent"
	@echo "  make daemon       Run scheduler daemon"
	@echo ""
	@echo "Docker (Development):"
	@echo "  make docker-build Build Docker image"
	@echo "  make docker-up    Start containers"
	@echo "  make docker-down  Stop containers"
	@echo "  make docker-logs  View logs"
	@echo "  make docker-shell Shell into container"
	@echo ""
	@echo "Docker (Production):"
	@echo "  make prod-up      Start production stack"
	@echo "  make prod-down    Stop production stack"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        Clean build artifacts"

# ============================================================
# Development
# ============================================================

install:
	pip install -e .

dev:
	pip install -e ".[all]"

test:
	pytest tests/ -v --cov=cronagent --cov-report=term-missing

lint:
	ruff check src/
	mypy src/cronagent/

format:
	ruff format src/
	ruff check --fix src/

# ============================================================
# Running
# ============================================================

run:
	cronagent agent

daemon:
	cronagent daemon

init:
	cronagent init

status:
	cronagent status

# ============================================================
# Docker Development
# ============================================================

docker-build:
	docker compose build

docker-up:
	docker compose up -d
	@echo "CronAgent started. View logs with: make docker-logs"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f cronagent

docker-shell:
	docker compose exec cronagent /bin/bash

docker-restart:
	docker compose restart cronagent

docker-clean:
	docker compose down -v --rmi local

# ============================================================
# Docker Production
# ============================================================

prod-up:
	docker compose --profile production up -d
	@echo "Production stack started"
	@echo "  CronAgent: http://localhost:8080"
	@echo "  PostgreSQL: localhost:5432"
	@echo "  Redis: localhost:6379"

prod-down:
	docker compose --profile production down

prod-logs:
	docker compose --profile production logs -f

prod-status:
	docker compose --profile production ps

# ============================================================
# Monitoring (Optional)
# ============================================================

monitoring-up:
	docker compose --profile monitoring up -d
	@echo "Monitoring started"
	@echo "  Prometheus: http://localhost:9090"
	@echo "  Grafana: http://localhost:3000"

monitoring-down:
	docker compose --profile monitoring down

# ============================================================
# Cleanup
# ============================================================

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

clean-docker:
	docker compose down -v --rmi all --remove-orphans

clean-all: clean clean-docker
