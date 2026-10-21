"""Acceptance uses separate interpreters, never an in-memory DB or shared session."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nexus import cli
from nexus.domain import NexusError


def invoke(state, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("NEXUS_")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "nexus.cli", "--state-dir", str(state), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return completed, json.loads(completed.stdout)


def test_migrate_fixture_worker_restart_and_safe_failures(tmp_path):
    state = tmp_path.resolve() / "private"
    result, migrated = invoke(state, "migrate")
    assert result.returncode == 0 and migrated["migration"] == "0002_source_sync"
    result, pairing = invoke(state, "pair")
    assert result.returncode == 0
    token = pairing["pairing_token"]
    assert token not in result.stderr
    result, task = invoke(state, "fixture", "--key", "one")
    assert result.returncode == 0
    result, replay = invoke(state, "fixture", "--key", "one")
    assert task == replay
    result, job = invoke(state, "enqueue", task["task_id"], "--key", "job")
    assert result.returncode == 0
    result, worker = invoke(state, "worker-once")
    assert result.returncode == 0 and worker["job_id"] == job["job_id"]
    result, status = invoke(state, "status")
    assert result.returncode == 0
    assert len(status["tasks"]) == len(status["jobs"]) == 1
    assert status["jobs"][0]["state"] == "succeeded"
    assert len(status["audit"]) == len(status["outbox"])
    result, invalid = invoke(
        state, "transition", task["task_id"], "completed", "--expected-version", "1", "--key", "bad"
    )
    assert result.returncode == 2
    assert invalid["error"]["code"] == "forbidden_transition"
    result, changed = invoke(
        state,
        "transition",
        task["task_id"],
        "needs_clarification",
        "--expected-version",
        "1",
        "--key",
        "change",
    )
    assert result.returncode == 0 and changed["version"] == 2
    result, stale = invoke(
        state,
        "transition",
        task["task_id"],
        "needs_clarification",
        "--expected-version",
        "1",
        "--key",
        "stale",
    )
    assert result.returncode == 2 and stale["error"]["code"] == "stale_version"
    result, doctor = invoke(state, "doctor")
    assert result.returncode == 0 and doctor["integrity"] == "ok"
    assert doctor["foreign_key_errors"] == 0 and doctor["journal_mode"] == "wal"
    assert state.stat().st_mode & 0o777 == 0o700
    assert (state / "nexus.db").stat().st_mode & 0o777 == 0o600


def test_temporary_demo_is_explicit_and_process_backed(tmp_path):
    unused = tmp_path.resolve() / "must-not-be-created"
    result, demo = invoke(unused, "demo")
    assert result.returncode == 0
    assert demo["simulated"] is True and demo["restarted_processes"] is True
    assert demo["idempotency_replay"] is True
    assert demo["invalid_transition"]["error"]["code"] == "forbidden_transition"
    assert demo["stale_version"]["error"]["code"] == "stale_version"
    assert demo["temporary_state_removed"] is True
    assert not unused.exists()


@pytest.mark.parametrize(
    "fault,expected_error",
    [
        ("invalid", "demonstration_rejection_failed"),
        ("stale", "demonstration_rejection_failed"),
        ("doctor", "demonstration_integrity_failed"),
    ],
)
def test_demo_rejects_false_evidence_and_cleans_up(monkeypatch, fault, expected_error):
    original_run = subprocess.run
    original_temporary_directory = cli.tempfile.TemporaryDirectory
    directories = []

    def track_directory(*args, **kwargs):
        directory = original_temporary_directory(*args, **kwargs)
        directories.append(Path(directory.name))
        return directory

    def corrupt_evidence(arguments, **kwargs):
        completed = original_run(arguments, **kwargs)
        command = arguments[5]
        if command == "transition" and arguments[-1] == fault:
            payload = json.loads(completed.stdout)
            payload["error"]["code"] = "storage_unavailable"
            completed.stdout = json.dumps(payload)
        elif command == "doctor" and fault == "doctor":
            payload = json.loads(completed.stdout)
            payload["integrity"] = "corrupt"
            completed.stdout = json.dumps(payload)
        return completed

    monkeypatch.setattr(cli.tempfile, "TemporaryDirectory", track_directory)
    monkeypatch.setattr(cli.subprocess, "run", corrupt_evidence)
    with pytest.raises(NexusError) as rejected:
        cli.demonstration()
    assert rejected.value.code == expected_error
    assert len(directories) == 1
    assert not directories[0].exists()
    assert str(directories[0]) not in str(rejected.value)


def test_invalid_config_does_not_echo_input(tmp_path):
    # A normal CLI parser accepts the path; typed settings reject it safely.
    completed, result = invoke("relative-secret-marker", "migrate")
    assert completed.returncode == 2
    assert result["error"]["code"] == "configuration_invalid"
    assert "relative-secret-marker" not in completed.stdout + completed.stderr
