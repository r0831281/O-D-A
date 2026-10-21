"""Explicit local operator surfaces; no automatic fixtures, scheduling or services."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from nexus import schema as s
from nexus.auth import issue_pairing
from nexus.config import Settings
from nexus.domain import NexusError, TaskState
from nexus.logging import configure_logging, safe_log
from nexus.planning import PlanningService, SyncEngine
from nexus.profiles import LinkStatus, PlanningProfileConfig
from nexus.services import Foundation
from nexus.sources import (
    JiraCloudAdapter,
    JiraConfig,
    OdooConfig,
    OdooReadAdapter,
    SourceFailure,
    TempoCloudAdapter,
    TempoConfig,
    parse_ics,
    registered_adapters,
)
from nexus.storage import Database, migrate
from nexus.transports import HttpsJsonTransport, OdooRpcTransport, resolve_secret
from nexus.worker import Worker


def _operator(db: Database) -> str:
    with db.read() as connection:
        value = connection.execute(
            select(s.users.c.id).where(
                s.users.c.identity == "local-operator",
                s.users.c.active.is_(True),
            )
        ).scalar_one_or_none()
        if value is None:
            raise NexusError("pairing_required", 401)
        return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus")
    parser.add_argument("--state-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("pair")
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--key", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("task_id")
    enqueue.add_argument("--key", required=True)
    transition = sub.add_parser("transition")
    transition.add_argument("task_id")
    transition.add_argument("target", choices=[state.value for state in TaskState])
    transition.add_argument("--expected-version", type=int, required=True)
    transition.add_argument("--key", required=True)
    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("worker-once")
    sub.add_parser("serve")
    sub.add_parser("demo")
    sub.add_parser("source-discovery")
    connection = sub.add_parser("connection-draft")
    connection.add_argument("adapter", choices=["jira-cloud-v1", "tempo-cloud-planner-v1", "odoo-17-read-v1", "odoo-18-read-v1", "odoo-19-read-v1"])
    connection.add_argument("config_file", type=Path)
    connection.add_argument("--adapter-build", default="nexus-source-contract-1")
    test = sub.add_parser("connection-test")
    test.add_argument("connection_revision_id")
    profile = sub.add_parser("profile-draft")
    profile.add_argument("config_file", type=Path)
    preview = sub.add_parser("profile-preview")
    preview.add_argument("profile_revision_id")
    preview.add_argument("cases_file", type=Path)
    activate = sub.add_parser("profile-activate")
    activate.add_argument("profile_revision_id")
    activate.add_argument("preview_test_id")
    rollback = sub.add_parser("profile-rollback")
    rollback.add_argument("profile_id")
    rollback.add_argument("profile_revision_id")
    sync = sub.add_parser("source-sync")
    sync.add_argument("connection_revision_id")
    sync.add_argument("stream_key")
    sync.add_argument("query_hash")
    sync_request = sub.add_parser("source-sync-request")
    sync_request.add_argument("request_id")
    day = sub.add_parser("planning-day")
    day.add_argument("profile_revision_id")
    day.add_argument("local_date", type=date.fromisoformat)
    day.add_argument("fixture_file", type=Path)
    calendar = sub.add_parser("calendar-import")
    calendar.add_argument("ics_file", type=Path)
    calendar.add_argument("--timezone", default="Europe/Brussels")
    return parser


def _json_file(path: Path) -> object:
    if path.stat().st_size > 2_000_000:
        raise NexusError("input_file_too_large", 422)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise NexusError("input_file_invalid", 422) from None


def _source_adapter(adapter_id: str, config: dict):
    secret = resolve_secret(str(config["secret_ref"]))
    if adapter_id == "jira-cloud-v1":
        typed = JiraConfig.model_validate(config)
        return JiraCloudAdapter(typed, HttpsJsonTransport(typed.site_url, secret, adapter="jira"))
    if adapter_id == "tempo-cloud-planner-v1":
        typed = TempoConfig.model_validate(config)
        return TempoCloudAdapter(typed, HttpsJsonTransport(typed.base_url, secret, adapter="tempo"))
    if adapter_id.startswith("odoo-"):
        typed = OdooConfig.model_validate(config)
        if typed.odoo_major == 19:
            transport = HttpsJsonTransport(typed.base_url, secret, adapter="odoo19")
        else:
            transport = OdooRpcTransport(typed.base_url, typed.database, typed.login, secret)
        return OdooReadAdapter(typed, transport)
    raise NexusError("adapter_unavailable", 422)


def demonstration() -> dict:
    """Credential-free demo using real CLI processes and an automatically removed private DB.

    Execute in the verification sandbox: this function is an acceptance demonstration.
    It never points at the user's normal state directory.
    """
    with tempfile.TemporaryDirectory(prefix="nexus-demo-") as temporary:
        state = Path(temporary).resolve() / "state"
        settings = Settings(state_dir=state)
        db = Database(settings)
        migrate(db)
        issue_pairing(db, settings)  # Explicit bootstrap, token never printed by demo.
        db.close()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "PYTHONPATH", "SYSTEMROOT", "LANG", "LC_ALL"}
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["HOME"] = str(Path(temporary).resolve())

        def run(*arguments: str, expected_code: int = 0) -> dict:
            completed = subprocess.run(
                [sys.executable, "-m", "nexus.cli", "--state-dir", str(state), *arguments],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if completed.returncode != expected_code:
                raise NexusError("demonstration_failed", 500)
            return json.loads(completed.stdout)

        first = run("fixture", "--key", "demo-task")
        repeated = run("fixture", "--key", "demo-task")
        if first != repeated:
            raise NexusError("demonstration_idempotency_failed", 500)
        task_id = first["task_id"]
        enqueued = run("enqueue", task_id, "--key", "demo-job")
        worker = run("worker-once")
        if worker != {"job_id": enqueued["job_id"], "state": "succeeded"}:
            raise NexusError("demonstration_completion_failed", 500)
        invalid = run(
            "transition",
            task_id,
            "completed",
            "--expected-version",
            "1",
            "--key",
            "invalid",
            expected_code=2,
        )
        changed = run(
            "transition",
            task_id,
            "needs_clarification",
            "--expected-version",
            "1",
            "--key",
            "clarify",
        )
        stale = run(
            "transition",
            task_id,
            "needs_clarification",
            "--expected-version",
            "1",
            "--key",
            "stale",
            expected_code=2,
        )
        if (
            invalid.get("error", {}).get("code") != "forbidden_transition"
            or stale.get("error", {}).get("code") != "stale_version"
        ):
            raise NexusError("demonstration_rejection_failed", 500)
        status = run("status")  # New interpreter, fresh connection: restart persistence.
        doctor = run("doctor")
        if (
            changed != {"task_id": task_id, "state": "needs_clarification", "version": 2}
            or len(status["tasks"]) != 1
            or status["tasks"][0]["id"] != task_id
            or status["tasks"][0]["state"] != changed["state"]
            or status["tasks"][0]["version"] != changed["version"]
            or len(status["jobs"]) != 1
            or status["jobs"][0]["id"] != enqueued["job_id"]
            or status["jobs"][0]["task_id"] != task_id
            or status["jobs"][0]["state"] != "succeeded"
            or status["jobs"][0]["kind"] != "fixture_noop"
            or status["jobs"][0]["version"] <= enqueued["version"]
        ):
            raise NexusError("demonstration_persistence_failed", 500)
        audit = [
            (event["event_type"], event["entity_id"], event["entity_version"])
            for event in status["audit"]
        ]
        outbox = [
            (event["event_type"], event["entity_id"], event["entity_version"])
            for event in status["outbox"]
        ]
        if (
            not audit
            or audit != outbox
            or ("fixture.created", task_id, 1) not in audit
            or ("task.transitioned", task_id, changed["version"]) not in audit
            or ("job.finalize", enqueued["job_id"], status["jobs"][0]["version"]) not in audit
        ):
            raise NexusError("demonstration_journal_failed", 500)
        if (
            doctor.get("integrity") != "ok"
            or doctor.get("foreign_key_errors") != 0
            or doctor.get("journal_mode") != "wal"
            or doctor.get("execution") != "disabled"
        ):
            raise NexusError("demonstration_integrity_failed", 500)
        result = {
            "simulated": True,
            "temporary_state": True,
            "restarted_processes": True,
            "idempotency_replay": first == repeated,
            "task": changed,
            "job_id": enqueued["job_id"],
            "invalid_transition": invalid,
            "stale_version": stale,
            "doctor": doctor,
            "audit": status["audit"],
            "outbox": status["outbox"],
        }
    if Path(temporary).exists():
        raise NexusError("demonstration_cleanup_failed", 500)
    result["temporary_state_removed"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    correlation_id = s.new_id()
    db = None
    try:
        args = _parser().parse_args(argv)
        if args.command == "demo":
            result = demonstration()
        else:
            settings = Settings(**({"state_dir": args.state_dir} if args.state_dir else {}))
            db = Database(settings)
            service = Foundation(db)
            planning = PlanningService(db)
            if args.command == "source-discovery":
                result = {"adapters": list(registered_adapters()), "credentials_required": False,
                          "live_status": "not_tested"}
            elif args.command == "connection-draft":
                config = _json_file(args.config_file)
                if not isinstance(config, dict) or config.get("adapter_id") != args.adapter:
                    raise NexusError("connection_schema_invalid", 422)
                if args.adapter.startswith("odoo-"):
                    major = int(args.adapter.split("-")[1])
                    config = {**config, "odoo_major": major}
                    typed = OdooConfig.model_validate(config)
                    instance_identity = f"{typed.base_url}/{typed.database}"
                elif args.adapter == "jira-cloud-v1":
                    typed = JiraConfig.model_validate(config)
                    instance_identity = typed.site_url
                else:
                    typed = TempoConfig.model_validate(config)
                    instance_identity = f"{typed.base_url}/{typed.product_id}"
                config = {**typed.model_dump(mode="json"), "adapter_id": args.adapter}
                result = planning.save_connection(args.adapter, instance_identity,
                    config, (typed.secret_ref,), args.adapter_build)
            elif args.command == "connection-test":
                with db.read() as connection:
                    row = connection.execute(select(s.connection_revisions).where(
                        s.connection_revisions.c.id == args.connection_revision_id)).first()
                if row is None:
                    raise NexusError("connection_revision_missing", 404)
                revision = dict(row._mapping)
                source = _source_adapter(revision["config"]["adapter_id"], revision["config"])
                try:
                    evidence = dict(source.read_test())
                    status = "blocked" if evidence.get("provider_verification") == "account_probe_required" else "passed"
                except SourceFailure as exc:
                    evidence, status = {"error_code": exc.code, "retry_after_seconds": exc.retry_after}, "blocked" if exc.status in {424, 403} else "failed"
                result_id = planning.record_test(connection_revision_id=args.connection_revision_id,
                    profile_revision_id=None, test_kind="read", status=status,
                    config_hash=revision["config_hash"], adapter_build=revision["adapter_build"], result=evidence)
                result = {"test_run_id": result_id, "status": status, "evidence": evidence}
            elif args.command == "profile-draft":
                raw = _json_file(args.config_file)
                result = planning.save_profile(PlanningProfileConfig.model_validate(raw))
            elif args.command == "profile-preview":
                raw = _json_file(args.cases_file)
                if not isinstance(raw, list):
                    raise NexusError("preview_cases_invalid", 422)
                cases = tuple(raw)
                def fetch_fixture(instance, record_id):
                    for case in cases:
                        fixture = case.get("odoo_fixture", {})
                        if fixture.get("identity") == f"{instance}:project.task:{record_id}":
                            return LinkStatus(fixture.get("status", "inaccessible")), fixture.get("task")
                    return LinkStatus.INACCESSIBLE, None
                result = planning.preview(args.profile_revision_id, cases, fetch_odoo=fetch_fixture)
                result["simulated"] = True
            elif args.command == "profile-activate":
                result = planning.activate(args.profile_revision_id, _operator(db), preview_test_id=args.preview_test_id)
            elif args.command == "profile-rollback":
                result = planning.rollback(args.profile_id, args.profile_revision_id, _operator(db))
            elif args.command == "source-sync":
                with db.read() as connection:
                    row = connection.execute(select(s.connection_revisions).where(
                        s.connection_revisions.c.id == args.connection_revision_id)).first()
                if row is None:
                    raise NexusError("connection_revision_missing", 404)
                revision = dict(row._mapping)
                adapter = _source_adapter(revision["config"]["adapter_id"], revision["config"])
                engine = SyncEngine(db)
                run_id = engine.start(args.connection_revision_id, args.stream_key, args.query_hash)
                result = engine.execute(run_id, args.stream_key, args.query_hash, adapter)
            elif args.command == "source-sync-request":
                with db.read() as connection:
                    request = connection.execute(select(s.manual_sync_requests).where(
                        s.manual_sync_requests.c.id == args.request_id)).first()
                    if request is None:
                        raise NexusError("sync_request_missing", 404)
                    request_data = dict(request._mapping)
                    revision_row = connection.execute(select(s.connection_revisions).where(
                        s.connection_revisions.c.id == request_data["connection_revision_id"])).first()
                if revision_row is None:
                    raise NexusError("connection_revision_missing", 404)
                revision = dict(revision_row._mapping)
                adapter = _source_adapter(revision["config"]["adapter_id"], revision["config"])
                result = planning.run_manual_sync(args.request_id, adapter)
            elif args.command == "planning-day":
                raw = _json_file(args.fixture_file)
                if not isinstance(raw, dict):
                    raise NexusError("planning_fixture_invalid", 422)
                result = planning.materialize_day(args.profile_revision_id, args.local_date,
                    freshness=raw.get("freshness", {}), allocations=tuple(raw.get("allocations", [])),
                    schedules=tuple(raw.get("schedules", [])))
                result["simulated"] = True
            elif args.command == "calendar-import":
                events = parse_ics(args.ics_file.read_text(encoding="utf-8"), args.timezone)
                result = {"simulated": True, "event_count": len(events), "events": events}
            elif args.command == "migrate":
                migrate(db)
                result = {"migration": "0002_source_sync"}
            elif args.command == "pair":
                # The capability goes only to explicit local operator stdout, never logs.
                result = {
                    "pairing_token": issue_pairing(db, settings),
                    "expires_in_seconds": settings.pairing_seconds,
                }
            elif args.command == "fixture":
                result = service.fixture(_operator(db), args.key, correlation_id)
            elif args.command == "enqueue":
                result = service.enqueue(_operator(db), args.key, args.task_id, correlation_id)
            elif args.command == "transition":
                if args.expected_version < 1:
                    raise NexusError("invalid_version", 422)
                result = service.transition(
                    _operator(db),
                    args.key,
                    args.task_id,
                    args.expected_version,
                    TaskState(args.target),
                    correlation_id,
                )
            elif args.command == "status":
                result = service.status()
            elif args.command == "doctor":
                with db.read() as connection:
                    result = {
                        "integrity": connection.execute(text("PRAGMA integrity_check")).scalar(),
                        "foreign_key_errors": len(
                            connection.execute(text("PRAGMA foreign_key_check")).all()
                        ),
                        "journal_mode": connection.execute(text("PRAGMA journal_mode")).scalar(),
                        "execution": "disabled",
                    }
            elif args.command == "worker-once":
                worker = Worker(db, settings.lease_seconds)
                lease = worker.run_once("local-noop-" + s.new_id())
                result = {
                    "job_id": lease.job_id if lease else None,
                    "state": "succeeded" if lease else "idle",
                }
            elif args.command == "serve":
                import uvicorn

                from nexus.api import create_app

                origin = urlsplit(settings.origin)
                uvicorn.run(
                    create_app(settings),
                    host=origin.hostname,
                    port=origin.port,
                    access_log=False,
                    log_level="critical",
                    proxy_headers=False,
                )
                return 0
            else:
                raise NexusError("unknown_command", 422)
        print(json.dumps(result, separators=(",", ":")))
        safe_log("command", correlation_id, 200)
        return 0
    except NexusError as exc:
        print(json.dumps({"error": {"code": exc.code, "correlation_id": correlation_id}}))
        safe_log("command", correlation_id, exc.status)
        return 2
    except (ValidationError, ValueError):
        print(
            json.dumps(
                {"error": {"code": "configuration_invalid", "correlation_id": correlation_id}}
            )
        )
        safe_log("configuration_error", correlation_id, 422)
        return 2
    except (SQLAlchemyError, OSError):
        print(
            json.dumps({"error": {"code": "storage_unavailable", "correlation_id": correlation_id}})
        )
        safe_log("storage_error", correlation_id, 503)
        return 2
    except Exception:
        print(json.dumps({"error": {"code": "internal_error", "correlation_id": correlation_id}}))
        safe_log("command", correlation_id, 500)
        return 2
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
