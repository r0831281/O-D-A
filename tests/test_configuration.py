"""Reject unsafe paths and malformed configuration before opening persistent state."""

import os

import pytest
from pydantic import ValidationError

from nexus.config import Settings
from nexus.domain import SourceIdentity
from nexus.storage import Database


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 2])
def test_strict_versions_are_not_coerced(value):
    with pytest.raises(ValidationError):
        Settings(schema_version=value)
    with pytest.raises(ValidationError):
        SourceIdentity(
            schema_version=value,
            adapter_id="test",
            instance_identity="test",
            remote_type="task",
            remote_id="1",
        )


@pytest.mark.parametrize(
    "value",
    [
        "http://example.org:8765",
        "https://127.0.0.1:8765",
        "http://127.0.0.1",
        "http://user:password@127.0.0.1:8765",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1:8765?token=secret",
        "http://127.0.0.1:8765#fragment",
    ],
)
def test_only_exact_loopback_origins_are_configurable(value):
    with pytest.raises(ValidationError):
        Settings(origin=value)


def test_state_must_be_private_owned_directory_and_database(tmp_path):
    root = tmp_path.resolve()
    private = root / "private"
    private.mkdir(mode=0o700)
    database = Database(Settings(state_dir=private))
    database.close()
    os.chmod(private / "nexus.db", 0o644)
    with pytest.raises(ValueError):
        Database(Settings(state_dir=private))
    os.chmod(private / "nexus.db", 0o600)
    os.chmod(private, 0o755)
    with pytest.raises(ValueError):
        Database(Settings(state_dir=private))


def test_state_symlink_and_hardlinked_database_rejected(tmp_path):
    root = tmp_path.resolve()
    real = root / "real"
    real.mkdir(mode=0o700)
    alias = root / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        Database(Settings(state_dir=alias))
    database = Database(Settings(state_dir=real))
    database.close()
    os.link(real / "nexus.db", root / "hardlink")
    with pytest.raises(ValueError):
        Database(Settings(state_dir=real))


def test_unknown_configuration_and_timezone_are_rejected():
    with pytest.raises(ValidationError):
        Settings(approved=True)
    with pytest.raises(ValidationError):
        Settings(timezone="Unknown/Invalid")
