"""Typed local configuration and private, symlink-free state paths."""

import os
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", extra="forbid", hide_input_in_errors=True
    )

    schema_version: Literal[1] = 1
    state_dir: Path = Path.home() / ".local" / "share" / "nexus"
    timezone: str = "Europe/Brussels"
    origin: str = "http://127.0.0.1:8765"
    busy_timeout_ms: int = Field(default=5000, ge=1, le=30000)
    session_seconds: int = Field(default=43200, ge=1, le=86400)
    pairing_seconds: int = Field(default=300, ge=1, le=600)
    lease_seconds: int = Field(default=60, ge=1, le=600)

    @field_validator("schema_version", mode="before")
    @classmethod
    def supported_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("unsupported schema version")
        return value

    @field_validator("state_dir")
    @classmethod
    def absolute_state(cls, value: Path) -> Path:
        if not value.is_absolute() or ".." in value.parts:
            raise ValueError("state directory must be an absolute normalized path")
        return value

    @field_validator("origin")
    @classmethod
    def loopback_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            raise ValueError("origin must be an exact HTTP loopback origin with a port")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "nexus.db"

    def prepare_state(self) -> None:
        # Resolve existing ancestors before creating anything. Never follow a state symlink.
        for path in [*reversed(self.state_dir.parents), self.state_dir]:
            if path.is_symlink():
                raise ValueError("state path cannot contain symlinks")
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.state_dir.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("state directory must be owned by the current user")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("state directory permissions must be 0700")
        for path in self.state_dir.iterdir():
            if path.name in {"nexus.db", "nexus.db-wal", "nexus.db-shm"}:
                file_info = path.lstat()
                if (
                    not stat.S_ISREG(file_info.st_mode)
                    or file_info.st_uid != os.getuid()
                    or file_info.st_nlink != 1
                    or stat.S_IMODE(file_info.st_mode) & 0o077
                ):
                    raise ValueError("database files must be private regular files")
