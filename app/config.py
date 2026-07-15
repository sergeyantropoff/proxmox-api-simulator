"""Typed application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = "proxmox-api-simulator"
    app_host: str = "0.0.0.0"  # noqa: S104 - the container must accept external traffic
    app_port: int = Field(default=8006, ge=1, le=65535)
    database_url: SecretStr = SecretStr(
        "postgresql://proxmox:proxmox@localhost:5432/proxmox_simulator"
    )
    db_pool_min_size: int = Field(default=1, ge=1, le=100)
    db_pool_max_size: int = Field(default=10, ge=1, le=100)
    db_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    db_command_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"
    contract_snapshot: Path | None = None
    compatibility_evidence: Path | None = None
    contract_fallback: Literal["error", "schema-default", "fixture"] = "error"
    catalog_artifact_url_6: str = "https://pve.proxmox.com/pve-docs-6/api-viewer/apidoc.js"
    catalog_artifact_url_7: str = "https://pve.proxmox.com/pve-docs-7/api-viewer/apidoc.js"
    catalog_artifact_url_8: str = "https://pve.proxmox.com/pve-docs-8/api-viewer/apidoc.js"
    catalog_artifact_url_9: str = "https://pve.proxmox.com/pve-docs/api-viewer/apidoc.js"
    ticket_signing_key: SecretStr = SecretStr("development-only-signing-key-change-me")
    task_worker_concurrency: int = Field(default=2, ge=1, le=32)
    task_lease_seconds: float = Field(default=30.0, gt=1, le=300)
    simulation_time_scale: float = Field(default=10.0, gt=0, le=10000)

    def catalog_artifact_urls(self) -> dict[int, str]:
        return {
            6: self.catalog_artifact_url_6,
            7: self.catalog_artifact_url_7,
            8: self.catalog_artifact_url_8,
            9: self.catalog_artifact_url_9,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the immutable process configuration."""

    return Settings()
