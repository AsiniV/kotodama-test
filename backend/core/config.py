from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Kotodama"
    app_version: str = "0.1.0"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://kotodama:kotodama_password@localhost:5432/kotodama"
    postgres_user: str = "kotodama"
    postgres_password: str = "kotodama_password"
    postgres_db: str = "kotodama"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # PGVector for Lore RAG
    pgvector_dimension: int = 768

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "kotodama_admin"
    minio_secret_key: str = "kotodama_admin_secret"
    minio_bucket_assets: str = "kotodama-assets"
    minio_bucket_builds: str = "kotodama-builds"
    minio_secure: bool = False

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_code_model: str = "qwen2.5-coder:32b"
    ollama_design_model: str = "qwen2.5:32b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Stable Diffusion
    sd_webui_url: str = "http://localhost:7860"
    sd_default_steps: int = 20
    sd_default_width: int = 512
    sd_default_height: int = 512

    # Fal.ai
    fal_ai_key: str | None = None
    fal_api_key: str | None = None  # Alias for consistency

    # Replicate
    replicate_api_key: str | None = None

    # Image Generation Provider
    image_gen_provider: str = "local"  # Options: "local", "fal", "replicate"

    # JWT
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Godot Headless
    godot_headless_path: str = "/usr/bin/godot-headless"
    godot_export_preset: str = "Web"

    # Workspace
    workspace_root: str = "/workspace/workspace_instances"
    max_workspace_size_mb: int = 500

    # Credits and Pricing
    credits_per_simple_game: int = 10
    credits_per_complex_game: int = 25
    credits_per_epic_quest: int = 15
    credits_per_full_rpg_dialogue: int = 15

    # Rate Limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_generations_per_hour: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
