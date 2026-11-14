from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Pydantic v2 style: uses ``model_config = SettingsConfigDict(...)`` instead of
    the deprecated nested ``class Config``. Passwords and model names are kept in
    sync with ``.env`` / ``docker-compose.yml`` for local runs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Kotodama"
    app_version: str = "0.1.0"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = (
        "postgresql+asyncpg://kotodama:kotodama_secret_k8s_key_2026@postgres:5432/kotodama"
    )
    postgres_user: str = "kotodama"
    postgres_password: str = "kotodama_secret_k8s_key_2026"
    postgres_db: str = "kotodama"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # PGVector for Lore RAG
    pgvector_dimension: int = 768

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "kotodama_admin"
    minio_secret_key: str = "kotodama_minio_secret_k8s_key_2026"
    minio_bucket_assets: str = "kotodama-assets"
    minio_bucket_builds: str = "kotodama-builds"
    minio_secure: bool = False

    # Ollama / LLM (local inference)
    # Ollama работает нативно в WSL2; из контейнеров доступ через host.docker.internal
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_code_model: str = Field(
        default="qwen2.5-coder:32b",
        validation_alias=AliasChoices("ollama_code_model", "LLM_CODE_MODEL"),
    )
    ollama_design_model: str = Field(
        default="qwen2.5:32b",
        validation_alias=AliasChoices("ollama_design_model", "LLM_DESIGN_MODEL"),
    )
    ollama_embedding_model: str = Field(
        default="nomic-embed-text",
        validation_alias=AliasChoices("ollama_embedding_model", "LLM_EMBEDDING_MODEL"),
    )

    # LLM backend selection for services/llm_client.py:
    #   "auto"    -> openai-compatible if OPENAI_API_KEY/LLM_API_KEY is set, else ollama
    #   "ollama"  -> native Ollama server (OLLAMA_BASE_URL)
    #   "openai"  -> any OpenAI-compatible endpoint (OPENAI_BASE_URL + OPENAI_API_KEY)
    llm_backend: str = Field(
        default="auto",
        validation_alias=AliasChoices("llm_backend", "LLM_BACKEND"),
    )
    openai_base_url: str = Field(
        default="http://localhost:8000/v1",
        validation_alias=AliasChoices("openai_base_url", "OPENAI_BASE_URL", "LLM_BASE_URL"),
    )
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY", "LLM_API_KEY"),
    )
    openai_model: str = Field(
        default="",
        validation_alias=AliasChoices("openai_model", "OPENAI_MODEL", "LLM_MODEL"),
    )

    # LLM tuning
    llm_temperature_code: float = 0.15
    llm_temperature_design: float = 0.6
    llm_max_tokens: int = Field(
        default=4096,
        validation_alias=AliasChoices("llm_max_tokens", "LLM_MAX_TOKENS"),
    )
    # Max output tokens for code-generating roles (coder/architect/qa).
    llm_code_max_tokens: int = Field(
        default=16384,
        validation_alias=AliasChoices("llm_code_max_tokens", "LLM_CODE_MAX_TOKENS"),
    )
    llm_context_window: int = 32768
    llm_timeout_seconds: float = Field(
        default=300.0,
        validation_alias=AliasChoices("llm_timeout_seconds", "AGENT_TIMEOUT_SECONDS"),
    )
    llm_max_repair_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("llm_max_repair_retries", "AGENT_RETRY_COUNT"),
    )

    # GPU configuration (AMD Ryzen AI Max+ 395 / Radeon 8060S, unified memory in WSL2)
    gpu_vendor: str = "AMD"
    gpu_model: str = "Radeon 8060S (RDNA 3.5)"
    gpu_vram_gb: int = 128  # unified memory shared with the CPU
    gpu_backend: str = "rocm"  # Options: "rocm", "vulkan", "cuda", "cpu"

    # Stable Diffusion (sd_webui_url kept as the internal name; env var is STABLE_DIFFUSION_URL)
    sd_webui_url: str = Field(
        default="http://localhost:7860",
        validation_alias=AliasChoices("sd_webui_url", "STABLE_DIFFUSION_URL", "SD_WEBUI_URL"),
    )
    sd_default_steps: int = Field(
        default=20,
        validation_alias=AliasChoices("sd_default_steps", "STABLE_DIFFUSION_STEPS"),
    )
    sd_default_width: int = Field(
        default=512,
        validation_alias=AliasChoices("sd_default_width", "STABLE_DIFFUSION_WIDTH"),
    )
    sd_default_height: int = Field(
        default=512,
        validation_alias=AliasChoices("sd_default_height", "STABLE_DIFFUSION_HEIGHT"),
    )

    # Fal.ai
    fal_ai_key: str | None = None
    fal_api_key: str | None = None  # Alias for consistency

    # Replicate
    replicate_api_key: str | None = None

    # Image Generation Provider
    image_gen_provider: str = "local"  # Options: "local", "fal", "replicate"

    # JWT
    jwt_secret_key: str = Field(
        default="kotodama_jwt_secret_key_change_in_production_2026_local_dev",
        validation_alias=AliasChoices("jwt_secret_key", "SECRET_KEY"),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Godot Headless
    godot_headless_path: str = Field(
        default="/usr/local/bin/godot",
        validation_alias=AliasChoices("godot_headless_path", "GODOT_HEADLESS_PATH"),
    )
    godot_export_preset: str = "Web"

    # Workspace
    workspace_root: str = Field(
        default="./workspace_instances",
        validation_alias=AliasChoices("workspace_root", "WORKSPACE_ROOT"),
    )
    max_workspace_size_mb: int = 500

    # Credits and Pricing
    credits_per_simple_game: int = 10
    credits_per_complex_game: int = 25
    credits_per_epic_quest: int = 15
    credits_per_full_rpg_dialogue: int = 15

    # Rate Limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_generations_per_hour: int = 5


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
