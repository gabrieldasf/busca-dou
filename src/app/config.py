from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/buscadou"
    redis_url: str = "redis://localhost:6379"
    api_secret_key: str = "change-me-in-production"  # noqa: S105
    environment: str = "development"
    debug: bool = False

    model_config = {"env_prefix": "BUSCADOU_", "env_file": ".env"}


settings = Settings()
