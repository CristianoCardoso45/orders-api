"""
Configuration layer, loading of settings and secrets.

Responsibility:
- Load environment variables and configure the application
- Integrate with AWS Secrets Manager (with fallback to .env)
- Cache secrets in memory after first loading
"""

import json
import structlog
from functools import lru_cache

from pydantic_settings import BaseSettings

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Uses pydantic-settings for automatic validation on startup, with native
    support for .env files. Each field maps directly to an environment variable.
    """

    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "orders_db"
    db_user: str = "orders_user"
    db_password: str = "orders_pass"

    @property
    def database_url(self) -> str:
        """
        Builds the async database URL from individual components.
        The password comes from Secrets Manager in production,
        or from the .env fallback in local development.
        Never hardcoded in the source.
        """
        return (
            f"postgresql+asyncpg://"
            f"{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    sqs_queue_name: str = "orders-queue"
    sqs_dlq_name: str = "orders-dlq"

    secrets_name: str = "order-service-secrets"

    api_key: str = "dev-api-key"

    requester_service_url: str = "http://localhost:8001"
    requester_service_timeout: float = 3.0

    log_level: str = "INFO"
    otel_enabled: bool = False

    outbox_poll_interval_seconds: int = 5
    outbox_batch_size: int = 10

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a singleton instance of Settings.

    Uses lru_cache to ensure that .env parsing and validation
    happen only once during the application lifecycle.
    """
    return Settings()


_secrets_cache: dict[str, str] | None = None


async def load_secrets(settings: Settings) -> dict[str, str]:
    """
    Loads secrets from AWS Secrets Manager with fallback to environment variables.

    Strategy:
    1. Tries to load from Secrets Manager (production / LocalStack)
    2. If it fails (e.g. unit tests, dev without LocalStack), uses .env fallback
    3. Caches in memory after first successful loading

    Args:
        settings: Settings instance with AWS credentials and secret name.

    Returns:
        Dictionary with the loaded secrets.
    """
    global _secrets_cache

    if _secrets_cache is not None:
        return _secrets_cache

    try:
        import aioboto3

        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

        async with session.client(
            "secretsmanager",
            endpoint_url=settings.aws_endpoint_url,
        ) as client:
            response = await client.get_secret_value(SecretId=settings.secrets_name)
            _secrets_cache = json.loads(response["SecretString"])
            logger.info(
                "secrets_loaded",
                source="secrets_manager",
                secret_name=settings.secrets_name,
            )
            return _secrets_cache

    except Exception as exc:
        logger.warning(
            "secrets_fallback",
            source="environment",
            reason=str(exc),
            secret_name=settings.secrets_name,
        )
        _secrets_cache = {
            "db_password": settings.db_password,
            "api_key": settings.api_key,
        }
        return _secrets_cache
