# =============================================================================
# KOTODAMA - Makefile
# =============================================================================
# Technical Specification v2.0 Final - All Phases 0-9
# =============================================================================

.PHONY: help setup dev test build deploy backup clean lint migrate docker-up docker-down logs

# -----------------------------------------------------------------------------
# COLORS & HELPERS
# -----------------------------------------------------------------------------
COLOR_RESET=\033[0m
COLOR_GREEN=\033[32m
COLOR_YELLOW=\033[33m
COLOR_BLUE=\033[34m

help:
@echo "$(COLOR_BLUE)Kotodama - Modular Multi-Agent Game Generation Service$(COLOR_RESET)"
@echo ""
@echo "Usage: make [target]"
@echo ""
@echo "Targets:"
@echo "  $(COLOR_GREEN)setup$(COLOR_RESET)       Initial project setup (install deps, init DB)"
@echo "  $(COLOR_GREEN)dev$(COLOR_RESET)         Start development environment"
@echo "  $(COLOR_GREEN)test$(COLOR_RESET)        Run all tests"
@echo "  $(COLOR_GREEN)build$(COLOR_RESET)       Build production Docker images"
@echo "  $(COLOR_GREEN)deploy$(COLOR_RESET)      Deploy to production"
@echo "  $(COLOR_GREEN)backup$(COLOR_RESET)      Create database and storage backup"
@echo "  $(COLOR_GREEN)clean$(COLOR_RESET)       Clean build artifacts and caches"
@echo "  $(COLOR_GREEN)lint$(COLOR_RESET)        Run linters (black, ruff, mypy)"
@echo "  $(COLOR_GREEN)migrate$(COLOR_RESET)     Run database migrations"
@echo "  $(COLOR_GREEN)docker-up$(COLOR_RESET)   Start all Docker services"
@echo "  $(COLOR_GREEN)docker-down$(COLOR_RESET) Stop all Docker services"
@echo "  $(COLOR_GREEN)logs$(COLOR_RESET)        View service logs"

# -----------------------------------------------------------------------------
# SETUP
# -----------------------------------------------------------------------------
setup:
@echo "$(COLOR_GREEN)Setting up Kotodama...$(COLOR_RESET)"
@echo "Installing Python dependencies..."
pip install -r requirements.txt
@echo "Installing frontend dependencies..."
cd frontend && npm install
@echo "Creating .env file..."
cp -n .env.example .env || true
@echo "Starting infrastructure..."
make docker-up-infra
@echo "Waiting for services to be ready..."
sleep 10
@echo "Running database migrations..."
make migrate
@echo "$(COLOR_GREEN)Setup complete!$(COLOR_RESET)"

# -----------------------------------------------------------------------------
# DEVELOPMENT
# -----------------------------------------------------------------------------
dev:
@echo "$(COLOR_GREEN)Starting development environment...$(COLOR_RESET)"
docker-compose up -d postgres minio redis ollama
@echo "Waiting for services..."
sleep 5
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

dev-full:
@echo "$(COLOR_GREEN)Starting full development stack...$(COLOR_RESET)"
docker-compose up -d
cd frontend && npm run dev

# -----------------------------------------------------------------------------
# TESTING
# -----------------------------------------------------------------------------
test:
@echo "$(COLOR_GREEN)Running tests...$(COLOR_RESET)"
pytest tests/ -v --cov=backend --cov-report=html

test-unit:
pytest tests/unit/ -v

test-integration:
pytest tests/integration/ -v

test-e2e:
pytest tests/e2e/ -v

# -----------------------------------------------------------------------------
# BUILD
# -----------------------------------------------------------------------------
build:
@echo "$(COLOR_GREEN)Building production images...$(COLOR_RESET)"
docker-compose -f docker-compose.yml build

build-backend:
docker build -f docker/Dockerfile.backend -t kotodama-backend:latest .

build-frontend:
cd frontend && docker build -f ../docker/Dockerfile.frontend -t kotodama-frontend:latest .

# -----------------------------------------------------------------------------
# DEPLOYMENT
# -----------------------------------------------------------------------------
deploy:
@echo "$(COLOR_GREEN)Deploying to production...$(COLOR_RESET)"
docker-compose -f docker-compose.prod.yml up -d --build

deploy-staging:
@echo "$(COLOR_GREEN)Deploying to staging...$(COLOR_RESET)"
docker-compose -f docker-compose.staging.yml up -d --build

# -----------------------------------------------------------------------------
# BACKUP
# -----------------------------------------------------------------------------
backup:
@echo "$(COLOR_GREEN)Creating backup...$(COLOR_RESET)"
@mkdir -p backups
docker exec kotodama-postgres pg_dump -U kotodama kotodama > backups/db_$(shell date +%Y%m%d_%H%M%S).sql
docker exec kotodama-minio mc alias set myminio http://localhost:9000 kotodama_admin kotodama_minio_secret_k8s_key_2026
docker exec kotodama-minio mc mirror --recursive myminio/kotodama-assets backups/minio_assets_$(shell date +%Y%m%d_%H%M%S)

restore:
@echo "$(COLOR_GREEN)Restoring from backup...$(COLOR_RESET)"
@echo "Specify BACKUP_FILE=path/to/backup.sql"
docker exec -i kotodama-postgres psql -U kotodama -d kotodama < $(BACKUP_FILE)

# -----------------------------------------------------------------------------
# CLEANUP
# -----------------------------------------------------------------------------
clean:
@echo "$(COLOR_GREEN)Cleaning build artifacts...$(COLOR_RESET)"
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
rm -rf build/ dist/ .pytest_cache/ .coverage htmlcov/
rm -rf frontend/.next/ frontend/node_modules/
docker-compose down -v

clean-workspace:
@echo "$(COLOR_GREEN)Cleaning workspace data...$(COLOR_RESET)"
rm -rf workspace/projects/* workspace/builds/*

# -----------------------------------------------------------------------------
# LINTING
# -----------------------------------------------------------------------------
lint:
@echo "$(COLOR_GREEN)Running linters...$(COLOR_RESET)"
black --check backend/
ruff check backend/
mypy backend/

lint-fix:
@echo "$(COLOR_GREEN)Fixing lint issues...$(COLOR_RESET)"
black backend/
ruff check --fix backend/

format:
black backend/

# -----------------------------------------------------------------------------
# DATABASE MIGRATIONS
# -----------------------------------------------------------------------------
migrate:
@echo "$(COLOR_GREEN)Running database migrations...$(COLOR_RESET)"
alembic upgrade head

migrate-down:
@echo "$(COLOR_GREEN)Rolling back migration...$(COLOR_RESET)"
alembic downgrade -1

migrate-status:
@echo "$(COLOR_GREEN)Migration status...$(COLOR_RESET)"
alembic current

# -----------------------------------------------------------------------------
# DOCKER SERVICES
# -----------------------------------------------------------------------------
docker-up:
docker-compose up -d

docker-up-infra:
docker-compose up -d postgres minio redis ollama

docker-down:
docker-compose down

docker-logs:
docker-compose logs -f

logs:
docker-compose logs -f

restart:
docker-compose restart

ps:
docker-compose ps

# -----------------------------------------------------------------------------
# GODOT
# -----------------------------------------------------------------------------
godot-test:
@echo "$(COLOR_GREEN)Running Godot headless tests...$(COLOR_RESET)"
docker exec kotodama-godot godot --headless --path /godot/core --quit

godot-export-web:
@echo "$(COLOR_GREEN)Exporting to Web...$(COLOR_RESET)"
docker exec kotodama-godot godot --headless --path /godot/core --export-debug "Web" /godot/workspace/builds/web/export.pck

godot-export-android:
@echo "$(COLOR_GREEN)Exporting to Android...$(COLOR_RESET)"
docker exec kotodama-godot godot --headless --path /godot/core --export-debug "Android" /godot/workspace/builds/android/export.apk

# -----------------------------------------------------------------------------
# OLLAMA MODELS
# -----------------------------------------------------------------------------
ollama-pull:
@echo "$(COLOR_GREEN)Pulling Ollama models...$(COLOR_RESET)"
docker exec kotodama-ollama ollama pull qwen2.5-coder:32b
docker exec kotodama-ollama ollama pull qwen2.5:32b
docker exec kotodama-ollama ollama pull nomic-embed-text

ollama-list:
docker exec kotodama-ollama ollama list

# -----------------------------------------------------------------------------
# MINIO
# -----------------------------------------------------------------------------
minio-console:
@echo "$(COLOR_GREEN)Opening MinIO Console...$(COLOR_RESET)"
@echo "http://localhost:9001 (admin / kotodama_minio_secret_k8s_key_2026)"

minio-create-buckets:
@echo "$(COLOR_GREEN)Creating MinIO buckets...$(COLOR_RESET)"
docker exec kotodama-minio mc alias set myminio http://localhost:9000 kotodama_admin kotodama_minio_secret_k8s_key_2026
docker exec kotodama-minio mc mb myminio/kotodama-assets --ignore-existing
docker exec kotodama-minio mc mb myminio/kotodama-builds --ignore-existing
