# =============================================================================
# KOTODAMA - Makefile (Windows-friendly, UTF-8, tabs only)
# =============================================================================
# Technical Specification v2.0 Final - All Phases 0-9
# Примечание: ANSI escape-коды цветов убраны (не работают в Windows PowerShell),
# все recipe-строки начинаются с НАСТОЯЩИХ табов.
# =============================================================================

.PHONY: help setup dev dev-backend dev-frontend test build deploy backup clean lint migrate \
        docker-up docker-down docker-up-infra logs ollama-pull minio-create-buckets

# -----------------------------------------------------------------------------
# HELP
# -----------------------------------------------------------------------------
help:
	@echo "Kotodama - Modular Multi-Agent Game Generation Service"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  setup                Initial project setup (install deps, init DB)"
	@echo "  dev                  Start development environment (infra + backend)"
	@echo "  dev-backend          Start backend only (uvicorn --reload)"
	@echo "  dev-frontend         Start frontend dev server (npm run dev)"
	@echo "  test                 Run all tests"
	@echo "  build                Build production Docker images"
	@echo "  deploy               Deploy to production"
	@echo "  backup               Create database and storage backup"
	@echo "  clean                Clean build artifacts and caches"
	@echo "  lint                 Run linters (black, ruff, mypy)"
	@echo "  migrate              Run database migrations"
	@echo "  docker-up            Start all Docker services"
	@echo "  docker-up-infra      Start infrastructure only (postgres, minio, redis)"
	@echo "  docker-down          Stop all Docker services"
	@echo "  logs                 View service logs"
	@echo "  ollama-pull          Pull LLM models into native WSL2 Ollama (outside Docker)"
	@echo "  minio-create-buckets Create MinIO buckets (kotodama-assets, kotodama-builds)"

# -----------------------------------------------------------------------------
# SETUP
# -----------------------------------------------------------------------------
setup:
	@echo "Setting up Kotodama..."
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Creating .env file..."
	cp -n .env.example .env || true
	@echo "Starting infrastructure..."
	$(MAKE) docker-up-infra
	@echo "Waiting for services to be ready..."
	sleep 10
	@echo "Running database migrations..."
	$(MAKE) migrate
	@echo "Setup complete!"

# -----------------------------------------------------------------------------
# DEVELOPMENT
# -----------------------------------------------------------------------------
dev:
	@echo "Starting development environment..."
	docker compose up -d postgres minio redis
	@echo "Waiting for services..."
	sleep 5
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

dev-backend:
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev-full:
	docker compose up -d
	cd frontend && npm run dev

# -----------------------------------------------------------------------------
# TESTING
# -----------------------------------------------------------------------------
test:
	@echo "Running tests..."
	pytest tests/ -v --cov=backend --cov-report=html

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# -----------------------------------------------------------------------------
# BUILD & DEPLOY
# -----------------------------------------------------------------------------
build:
	@echo "Building production Docker images..."
	docker compose build backend frontend nginx

deploy:
	@echo "Deploying to production..."
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

backup:
	@echo "Creating backup..."
	docker exec kotodama-postgres pg_dump -U kotodama kotodama > backup_$(shell date +%Y%m%d_%H%M%S).sql
	docker run --rm --network kotodama_kotodama-network -v $(PWD):/backup minio/mc \
		sh -c "mc alias set local http://minio:9000 kotodama_admin kotodama_minio_secret_k8s_key_2026 && mc cp --recursive local/kotodama-assets /backup/minio_backup/ || true"

clean:
	@echo "Cleaning build artifacts..."
	rm -rf frontend/.next frontend/node_modules/.cache
	rm -rf __pycache__ backend/**/__pycache__
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

lint:
	@echo "Running linters..."
	ruff check backend/ godot_core/
	black --check backend/ godot_core/
	mypy backend/

# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------
migrate:
	@echo "Running database migrations..."
	alembic upgrade head

migrate-new:
	@echo "Creating new migration..."
	alembic revision --autogenerate -m "$(msg)"

# -----------------------------------------------------------------------------
# DOCKER
# -----------------------------------------------------------------------------
docker-up:
	docker compose up -d

docker-up-infra:
	docker compose up -d postgres minio redis

docker-down:
	docker compose down

logs:
	docker compose logs -f --tail=100

# -----------------------------------------------------------------------------
# AI MODELS / STORAGE
# -----------------------------------------------------------------------------
ollama-pull:
	@echo "Pulling models into native WSL2 Ollama (LLM runs outside Docker for AMD ROCm GPU access)..."
	ollama pull nomic-embed-text
	ollama pull qwen2.5-coder:32b
	ollama pull qwen2.5:32b
	@echo "Locally available models:"
	ollama list

minio-create-buckets:
	@echo "Creating MinIO buckets..."
	docker exec kotodama-minio sh -c "mc alias set local http://localhost:9000 kotodama_admin kotodama_minio_secret_k8s_key_2026 && mc mb -p local/kotodama-assets local/kotodama-builds || true"
