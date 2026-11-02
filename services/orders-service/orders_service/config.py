"""Settings from environment variables (set by the ECS task definition)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    table_name: str
    region: str
    user_pool_id: str
    app_client_id: str
    app_version: str

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        # Served by the cognito-idp service endpoint (reachable through the VPC interface endpoint),
        # not by a user pool domain
        return f"{self.issuer}/.well-known/jwks.json"


def load_settings() -> Settings:
    return Settings(
        table_name=os.environ.get("TABLE_NAME", "orders"),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        user_pool_id=os.environ.get("USER_POOL_ID", "us-east-1_local"),
        app_client_id=os.environ.get("APP_CLIENT_ID", "local-client"),
        app_version=os.environ.get("APP_VERSION", "local"),
    )
