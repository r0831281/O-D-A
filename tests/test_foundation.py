"""File-backed persistence, command atomicity and domain safety contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from threading import Barrier

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from nexus import schema as s
from nexus.config import Settings
from nexus.domain import (
    Evidence,
    FingerprintManifest,
    NexusError,
    SourceIdentity,
    TaskState,
    canonical_hash,
    guard_transition,
)
from nexus.services import Foundation
from nexus.storage import Database, migrate


@pytest.fixture
def setup(tmp_path):
    settings = Settings(state_dir=tmp_path.resolve() / "state")
    db = Database(settings)
    migrate(db)
    user_id = s.new_id()
    with db.write() as connection:
        connection.execute(
            sa.insert(s.users).values(
                id=user_id,
                identity="test-operator",
                display_name="Test operator",
            )
        )
    service = Foundation(db)
    task = service.fixture(user_id, "fixture", s.new_id())
    yield settings, db, service, user_id, task
    db.close()


def counts(db):
    with db.read() as connection:
        return {
            table.name: connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
            for table in (
                s.tasks,
                s.task_holds,
                s.command_receipts,
                s.audit_events,
                s.outbox_events,
            )
        }


def test_empty_migration_is_repeatable_and_matches_schema(tmp_path):
    settings = Settings(state_dir=tmp_path.resolve() / "fresh")
    db = Database(settings)
    try:
        migrate(db)
        migrate(db)
        with db.read() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) == set(s.metadata.tables) | {"alembic_version"}
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0001_foundation"
            )
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            for table in s.metadata.tables.values():
                assert {column["name"] for column in inspector.get_columns(table.name)} == set(
                    table.c.keys()
                )
                indexed = {
                    name
                    for index in inspector.get_indexes(table.name)
                    for name in index["column_names"]
                }
                for foreign_key in table.foreign_keys:
                    assert foreign_key.parent.name in indexed
    finally:
        db.close()


def test_sqlite_connection_policy_and_transactional_ddl(setup):
    settings, db, *_ = setup
    for _ in range(2):
        with db.read() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert (
                connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
                == settings.busy_timeout_ms
            )
            assert connection.in_transaction()
    with pytest.raises(RuntimeError, match="injected"):
        with db.write() as connection:
            connection.exec_driver_sql("CREATE TABLE rollback_probe (id INTEGER PRIMARY KEY)")
            raise RuntimeError("injected")
    with db.read() as connection:
        assert "rollback_probe" not in sa.inspect(connection).get_table_names()


def test_failed_initial_migration_rolls_back_schema_and_revision(tmp_path):
    db = Database(Settings(state_dir=tmp_path.resolve() / "failed-migration"))

    def fail_table(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("CREATE TABLE tasks"):
            raise RuntimeError("migration injected failure")

    sa.event.listen(db.engine, "before_cursor_execute", fail_table)
    try:
        with pytest.raises(RuntimeError, match="migration injected failure"):
            migrate(db)
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", fail_table)
    try:
        with db.read() as connection:
            assert sa.inspect(connection).get_table_names() == []
        migrate(db)
        with db.read() as connection:
            assert "tasks" in sa.inspect(connection).get_table_names()
    finally:
        db.close()


@pytest.mark.parametrize(
    "values",
    [
        {"project_id": "missing-project"},
        {"state": "invented"},
        {"version": 0},
        {"title": ""},
    ],
)
def test_migrated_task_constraints_reject_invalid_rows(setup, values):
    _, db, _, _, task = setup
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(
                sa.update(s.tasks).where(s.tasks.c.id == task["task_id"]).values(**values)
            )
    with db.read() as connection:
        row = (
            connection.execute(sa.select(s.tasks).where(s.tasks.c.id == task["task_id"]))
            .mappings()
            .one()
        )
        assert row["state"] == "imported" and row["version"] == 1


@pytest.mark.parametrize(
    "values",
    [
        {"state": "leased"},
        {"state": "running", "lease_owner": "worker"},
        {"lease_epoch": -1},
        {"attempts": 4, "max_attempts": 3},
        {"kind": "implementation"},
    ],
)
def test_migrated_job_constraints_reject_invalid_lease_shapes(setup, values):
    _, db, service, user_id, task = setup
    job = service.enqueue(user_id, "job", task["task_id"], s.new_id())
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(
                sa.update(s.execution_jobs)
                .where(s.execution_jobs.c.id == job["job_id"])
                .values(**values)
            )


@pytest.mark.parametrize(
    "values",
    [
        {"relative_path": "../escape"},
        {"relative_path": "/absolute"},
        {"byte_count": -1},
        {"schema_version": 2},
    ],
)
def test_artifact_constraints_are_in_migration(setup, values):
    _, db, *_ = setup
    body = dict(
        content_hash="a" * 64,
        media_type="text/plain",
        byte_count=0,
        relative_path="blobs/a",
        sensitivity="private",
        schema_version=1,
    )
    body.update(values)
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(sa.insert(s.artifacts).values(**body))


def test_source_identity_is_instance_scoped_and_unique(setup):
    _, db, *_ = setup
    with db.write() as connection:
        first, second = s.new_id(), s.new_id()
        for source_id, tenant in [(first, "tenant-a"), (second, "tenant-b")]:
            connection.execute(
                sa.insert(s.external_sources).values(
                    id=source_id,
                    adapter_id="test-provider",
                    instance_identity=tenant,
                    config_hash="a" * 64,
                )
            )
            connection.execute(
                sa.insert(s.external_items).values(
                    source_id=source_id,
                    remote_type="task",
                    remote_id="42",
                    display_key="KEY-1",
                )
            )
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(
                sa.insert(s.external_items).values(
                    source_id=first,
                    remote_type="task",
                    remote_id="42",
                    display_key="RENAMED",
                )
            )
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(
                sa.insert(s.external_sources).values(
                    adapter_id="test-provider",
                    instance_identity="tenant-a",
                    config_hash="a" * 64,
                )
            )


def test_active_source_cannot_be_claimed_by_another_task(setup):
    _, db, service, user_id, task = setup
    other = service.fixture(user_id, "other-task", s.new_id())
    with db.read() as connection:
        item_id = connection.execute(
            sa.select(s.task_sources.c.external_item_id).where(
                s.task_sources.c.task_id == task["task_id"],
            )
        ).scalar_one()
    with pytest.raises(IntegrityError):
        with db.write() as connection:
            connection.execute(
                sa.insert(s.task_sources).values(
                    task_id=other["task_id"],
                    external_item_id=item_id,
                    relation="same_work",
                    role="secondary",
                    confirmed_by_id=user_id,
                    active=True,
                )
            )


def test_utc_instants_round_trip_and_naive_values_fail(setup):
    _, db, _, user_id, _ = setup
    instant = datetime(2030, 4, 3, 12, 13, 14, 123456, tzinfo=timezone(timedelta(hours=2)))
    with db.write() as connection:
        connection.execute(
            sa.update(s.users).where(s.users.c.id == user_id).values(updated_at=instant)
        )
    with db.read() as connection:
        found = connection.execute(
            sa.select(s.users.c.updated_at).where(s.users.c.id == user_id)
        ).scalar_one()
        assert found == instant.astimezone(UTC)
        assert found.tzinfo is UTC
        raw = connection.exec_driver_sql(
            "SELECT updated_at FROM users WHERE id = ?", (user_id,)
        ).scalar_one()
        assert raw == "2030-04-03T10:13:14.123456Z"
    with pytest.raises(StatementError):
        with db.write() as connection:
            connection.execute(
                sa.update(s.users)
                .where(s.users.c.id == user_id)
                .values(updated_at=instant.replace(tzinfo=None))
            )


# Contract cases come from DATA_MODEL.md, including later edges that public commands cannot use.
ALLOWED = [
    ("imported", "needs_clarification", {Evidence.CLARIFICATION}),
    ("imported", "ready_for_planning", {Evidence.ANALYSIS}),
    ("needs_clarification", "ready_for_planning", {Evidence.ANALYSIS, Evidence.CONDITIONS}),
    ("ready_for_planning", "planning", {Evidence.CLAIM}),
    ("planning", "plan_review", {Evidence.PLAN}),
    ("planning", "needs_clarification", {Evidence.CLARIFICATION}),
    ("plan_review", "ready_for_planning", {Evidence.CHANGES}),
    ("plan_review", "approved", {Evidence.GRANT}),
    ("approved", "implementing", {Evidence.START}),
    ("approved", "plan_review", {Evidence.STALE}),
    ("implementing", "implementation_review", {Evidence.CANDIDATE}),
    ("implementation_review", "completed", {Evidence.ACCEPTANCE}),
    ("implementation_review", "plan_review", {Evidence.CHANGES}),
    ("completed", "imported", {Evidence.REOPEN}),
]


@pytest.mark.parametrize("current,target,facts", ALLOWED)
def test_allowed_transition_requires_all_evidence(current, target, facts):
    guard_transition(TaskState(current), TaskState(target), frozenset(facts))
    for missing in facts:
        with pytest.raises(NexusError, match="missing_evidence"):
            guard_transition(TaskState(current), TaskState(target), frozenset(facts - {missing}))


@pytest.mark.parametrize(
    "current,target",
    [
        pair
        for pair in product(TaskState, repeat=2)
        if (pair[0].value, pair[1].value) not in {(a, b) for a, b, _ in ALLOWED}
    ],
)
def test_forbidden_edges_cannot_be_unlocked_by_facts(current, target):
    with pytest.raises(NexusError, match="forbidden_transition"):
        guard_transition(current, target, frozenset(Evidence))


@pytest.mark.parametrize(
    "current,target,facts",
    [
        case
        for case in ALLOWED
        if case[1] in {"ready_for_planning", "planning", "approved", "implementing", "completed"}
    ],
)
def test_holds_block_progress_despite_valid_evidence(current, target, facts):
    with pytest.raises(NexusError, match="task_on_hold"):
        guard_transition(TaskState(current), TaskState(target), frozenset(facts), has_hold=True)


def manifest(**updates):
    data = dict(
        source=SourceIdentity(
            adapter_id="provider", instance_identity="tenant-a", remote_type="task", remote_id="42"
        ),
        requirements_hash="a" * 64,
        config_hash="b" * 64,
        repository_commits=("repo-a:full-commit", "repo-b:full-commit"),
    )
    data.update(updates)
    return FingerprintManifest(**data)


def test_canonical_hash_and_fingerprint_materiality():
    assert canonical_hash({"b": 2, "a": "e\u0301"}) == canonical_hash({"a": "é", "b": 2})
    base = manifest()
    assert (
        manifest(repository_commits=tuple(reversed(base.repository_commits))).fingerprint
        == base.fingerprint
    )
    assert manifest(config_hash="c" * 64).fingerprint != base.fingerprint
    assert manifest(requirements_hash="d" * 64).fingerprint != base.fingerprint
    assert (
        manifest(
            source=SourceIdentity(
                adapter_id="provider",
                instance_identity="tenant-b",
                remote_type="task",
                remote_id="42",
            )
        ).fingerprint
        != base.fingerprint
    )
    with pytest.raises(ValueError):
        canonical_hash({"cost": 0.1})
    with pytest.raises(ValueError):
        canonical_hash({"é": 1, "e\u0301": 2})


@pytest.mark.parametrize(
    "updates", [{"schema_version": 2}, {"approved": True}, {"config_hash": "short"}]
)
def test_fingerprint_contract_rejects_unsupported_or_unknown_fields(updates):
    with pytest.raises(ValidationError):
        manifest(**updates)


def test_command_replay_conflicting_bodies_and_principal_scope(setup):
    _, db, service, user_id, task = setup
    before = counts(db)
    assert service.fixture(user_id, "fixture", s.new_id()) == task
    assert counts(db) == before
    with pytest.raises(NexusError, match="idempotency_conflict"):
        service.enqueue(user_id, "fixture", task["task_id"], s.new_id())
    assert counts(db) == before
    second_user = s.new_id()
    with db.write() as connection:
        connection.execute(
            sa.insert(s.users).values(id=second_user, identity="second", display_name="Second")
        )
    second = service.fixture(second_user, "fixture", s.new_id())
    assert second["task_id"] != task["task_id"]


def test_same_key_concurrent_commands_commit_one_result(setup):
    _, db, service, user_id, _ = setup
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return service.fixture(user_id, "concurrent", s.new_id())

    before = counts(db)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    after = counts(db)
    assert all(
        after[name] == value + (0 if name == "task_holds" else 1) for name, value in before.items()
    )


def test_stale_version_and_concurrent_transition_cas(setup):
    _, db, service, user_id, task = setup
    barrier = Barrier(2)

    def change(index):
        barrier.wait(timeout=5)
        try:
            return service.transition(
                user_id,
                f"change-{index}",
                task["task_id"],
                1,
                TaskState.NEEDS_CLARIFICATION,
                s.new_id(),
            )
        except NexusError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(change, range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("stale_version") == 1
    with db.read() as connection:
        assert (
            connection.execute(
                sa.select(s.tasks.c.version).where(s.tasks.c.id == task["task_id"])
            ).scalar_one()
            == 2
        )
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(s.task_holds)).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    "target", [TaskState.READY_FOR_PLANNING, TaskState.APPROVED, TaskState.IMPLEMENTING]
)
def test_public_commands_cannot_activate_future_capabilities(setup, target):
    _, db, service, user_id, task = setup
    before = counts(db)
    with pytest.raises(NexusError):
        service.transition(user_id, "future", task["task_id"], 1, target, s.new_id())
    assert counts(db) == before


@pytest.mark.parametrize(
    "stage",
    ["after_mutation", "before_outbox", "after_outbox", "before_receipt", "after_receipt"],
)
def test_command_mutation_audit_outbox_receipt_roll_back_together(setup, stage):
    _, db, service, user_id, task = setup
    before = counts(db)

    def operation(connection):
        connection.execute(
            sa.update(s.tasks)
            .where(s.tasks.c.id == task["task_id"])
            .values(title="Must roll back", version=2)
        )
        if stage == "after_mutation":
            raise RuntimeError("injected")
        return {"task_id": task["task_id"]}, "test.mutation", task["task_id"], 2, {}

    def intercept(connection, cursor, statement, parameters, context, executemany):
        if stage == "before_outbox" and statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("injected")
        if stage == "before_receipt" and statement.startswith("INSERT INTO command_receipts"):
            raise RuntimeError("injected")

    def after_execute(connection, cursor, statement, parameters, context, executemany):
        if stage == "after_receipt" and statement.startswith("INSERT INTO command_receipts"):
            # The receipt has reached SQLite; the surrounding transaction must undo it too.
            raise RuntimeError("injected")

    def after_event(connection):
        if stage == "after_outbox":
            raise RuntimeError("injected")

    sa.event.listen(db.engine, "before_cursor_execute", intercept)
    sa.event.listen(db.engine, "after_cursor_execute", after_execute)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            service.command(
                user_id,
                "rollback",
                {"operation": "test"},
                s.new_id(),
                operation,
                after_event=after_event,
            )
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", intercept)
        sa.event.remove(db.engine, "after_cursor_execute", after_execute)
    assert counts(db) == before
    with db.read() as connection:
        row = (
            connection.execute(sa.select(s.tasks).where(s.tasks.c.id == task["task_id"]))
            .mappings()
            .one()
        )
        assert row["version"] == 1 and row["title"] != "Must roll back"


def test_busy_database_fails_without_partial_command(setup):
    settings, db, _, user_id, _ = setup
    contender = Database(settings.model_copy(update={"busy_timeout_ms": 20}))
    before = counts(db)
    try:
        with db.write():
            with pytest.raises(OperationalError):
                Foundation(contender).fixture(user_id, "locked", s.new_id())
        assert counts(db) == before
    finally:
        contender.close()


def test_sqlite_full_rolls_back_mutation_and_journals(setup):
    _, db, service, user_id, task = setup
    before = counts(db)

    def fill(connection):
        connection.execute(
            sa.update(s.tasks)
            .where(s.tasks.c.id == task["task_id"])
            .values(title="Must not persist", version=2)
        )
        pages = connection.exec_driver_sql("PRAGMA page_count").scalar_one()
        connection.exec_driver_sql(f"PRAGMA max_page_count={int(pages)}")
        connection.exec_driver_sql("CREATE TABLE full_probe (payload BLOB)")
        connection.exec_driver_sql("INSERT INTO full_probe VALUES (zeroblob(1048576))")
        raise AssertionError("SQLite page limit should have rejected the allocation")

    with pytest.raises(OperationalError, match="database or disk is full"):
        service.command(user_id, "disk-full", {"operation": "disk-full"}, s.new_id(), fill)
    assert counts(db) == before
    with db.read() as connection:
        assert (
            connection.execute(
                sa.select(s.tasks.c.version).where(s.tasks.c.id == task["task_id"])
            ).scalar_one()
            == 1
        )
        assert "full_probe" not in sa.inspect(connection).get_table_names()
