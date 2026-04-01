from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Serb v2 API"
    app_env: str = "development"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24
    algorithm: str = "HS256"
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/serbv2"
    ai_service_url: str = "http://localhost:8001"
    cors_origins: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
