"""Settings read from environment variables (set by docker compose locally, by the ECS task definition in AWS)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_sslmode: str
    app_version: str

    @property
    def conninfo(self) -> str:
        # connect_timeout keeps a request from hanging when the database is unreachable
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} "
            f"sslmode={self.db_sslmode} connect_timeout=3"
        )


def load_settings() -> Settings:
    return Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=os.environ.get("DB_NAME", "products"),
        db_user=os.environ.get("DB_USER", "postgres"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        # "prefer": TLS when the server offers it (RDS PostgreSQL 15+ requires it), plain locally
        db_sslmode=os.environ.get("DB_SSLMODE", "prefer"),
        app_version=os.environ.get("APP_VERSION", "local"),
    )
