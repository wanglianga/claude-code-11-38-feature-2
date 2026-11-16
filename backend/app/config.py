import os


class Settings:
    """应用配置：全部支持环境变量覆盖，默认指向本容器内置 PostgreSQL。"""

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/epv",
    )
    JWT_SECRET: str = os.getenv("JWT_SECRET", "epv-dev-secret-change-me")
    JWT_ALG: str = "HS256"
    TOKEN_TTL_HOURS: int = int(os.getenv("TOKEN_TTL_HOURS", "12"))
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")


settings = Settings()
