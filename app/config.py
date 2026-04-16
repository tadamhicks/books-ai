from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    database_url: str = Field(
        default="postgresql+asyncpg://books:books@localhost:5432/books",
        description="SQLAlchemy async connection string",
    )
    bedrock_region: str = Field(default="us-west-2")
    bedrock_model_id: str = Field(default="mistral.mistral-large-2402-v1:0")
    bedrock_timeout_seconds: float = Field(default=15.0)
    otlp_endpoint: str = Field(
        default="groundcover-sensor.groundcover.svc.cluster.local:4317",
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="OTLP exporter endpoint (prefer host:port for gRPC)",
    )
    otlp_insecure: bool = Field(
        default=True,
        validation_alias="OTEL_EXPORTER_OTLP_INSECURE",
        description="Whether OTLP exporter should use insecure (plaintext) gRPC",
    )
    service_name: str = Field(default="books-api")
    service_version: str = Field(
        default="0.3.0",
        validation_alias="SERVICE_VERSION",
        description="Semantic version exposed as service.version resource attribute",
    )


settings = Settings()

