"""Installed-wheel acceptance driver. Execute only in the hardened verification container."""

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def run(arguments, *, directory, environment=None, timeout=240):
    subprocess.run(arguments, cwd=directory, env=environment, check=True, timeout=timeout)


def installed_probe(prefix):
    """A separate isolated interpreter must resolve NEXUS inside the fresh venv."""
    import nexus

    prefix = Path(prefix).resolve()
    if not Path(nexus.__file__).resolve().is_relative_to(prefix):
        raise RuntimeError("installed_package_provenance_failed")
    if importlib.metadata.version("nexus-control") != nexus.__version__:
        raise RuntimeError("installed_package_version_failed")
    for name in ("nexus.api", "nexus.cli", "nexus.storage", "nexus.worker"):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(prefix):
            raise RuntimeError("installed_module_provenance_failed")
    migrations = importlib.resources.files("nexus.migrations")
    for resource in ("env.py", "versions/0001_foundation.py", "versions/0002_source_sync.py"):
        if not migrations.joinpath(resource).is_file():
            raise RuntimeError("installed_migration_resource_missing")

    from nexus.config import Settings
    from nexus.storage import Database, migrate

    with tempfile.TemporaryDirectory(prefix="nexus-package-state-") as temporary:
        state = Path(temporary).resolve() / "state"
        database = Database(Settings(state_dir=state))
        try:
            migrate(database)
            migrate(database)
        finally:
            database.close()
        completed = subprocess.run(
            [str(prefix / "bin/nexus"), "--state-dir", str(state), "doctor"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        if json.loads(completed.stdout) != {
            "integrity": "ok",
            "foreign_key_errors": 0,
            "journal_mode": "wal",
            "execution": "disabled",
        }:
            raise RuntimeError("installed_entrypoint_migration_failed")
    if Path(temporary).exists():
        raise RuntimeError("installed_probe_cleanup_failed")
    print(json.dumps({"installed_import": True, "packaged_migrations": True, "entrypoint": True}))


def main():
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("non_root_linux_verification_required")
    if len(sys.argv) == 3 and sys.argv[1] == "--installed-probe":
        installed_probe(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--demo-only", action="store_true")
    selected.add_argument("--tests-only", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nexus-package-") as temporary:
        root = Path(temporary).resolve()
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("NEXUS_") and key not in {"PYTHONPATH", "VIRTUAL_ENV"}
        }
        environment.update(
            SOURCE_DATE_EPOCH="1704067200",
            UV_OFFLINE="1",
            UV_CACHE_DIR=str(root / "cache"),
            UV_PYTHON_DOWNLOADS="never",
        )
        wheels = []
        for name in ("first", "second"):
            output = root / name
            run(
                [
                    "uv",
                    "build",
                    "/app",
                    "--wheel",
                    "--no-build-isolation",
                    "--offline",
                    "--no-cache",
                    "--python",
                    sys.executable,
                    "--out-dir",
                    str(output),
                ],
                directory=root,
                environment=environment,
                timeout=120,
            )
            built = list(output.glob("*.whl"))
            if len(built) != 1:
                raise RuntimeError("expected_one_project_wheel")
            wheels.append(built[0])
        hashes = [hashlib.sha256(wheel.read_bytes()).hexdigest() for wheel in wheels]
        if hashes[0] != hashes[1]:
            raise RuntimeError("wheel_build_not_reproducible")
        prefix = root / "installed"
        # The image contains pinned third parties only, never an installed NEXUS.
        # Reuse those immutable dependencies; provenance checks reject source fallback.
        venv.EnvBuilder(with_pip=False, system_site_packages=True).create(prefix)
        python = str(prefix / "bin/python")
        run(
            ["uv", "pip", "install", "--offline", "--no-deps", "--python", python, str(wheels[0])],
            directory=root,
            environment=environment,
            timeout=60,
        )
        run(
            [python, "-I", __file__, "--installed-probe", str(prefix)],
            directory=root,
            environment=environment,
        )
        if not args.demo_only:
            run(
                [python, "-I", "-m", "pytest", "-p", "no:cacheprovider", "/app/tests"],
                directory=root,
                environment=environment,
            )
        if not args.tests_only:
            run([str(prefix / "bin/nexus"), "demo"], directory=root, environment=environment)
        print(json.dumps({"reproducible_wheel_sha256": hashes[0], "source_fallback": False}))
    if Path(temporary).exists():
        raise RuntimeError("package_verification_cleanup_failed")


if __name__ == "__main__":
    main()
