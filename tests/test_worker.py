"""Claims, recovery and fencing against a real local SQLite file."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier, Event

import pytest
import sqlalchemy as sa

from nexus import schema as s
from nexus.config import Settings
from nexus.domain import NexusError
from nexus.services import Foundation
from nexus.storage import Database, migrate
from nexus.worker import Lease, Worker


@pytest.fixture
def queued(tmp_path):
    settings = Settings(state_dir=tmp_path.resolve() / "state")
    db = Database(settings)
    migrate(db)
    user_id = s.new_id()
    with db.write() as connection:
        connection.execute(
            sa.insert(s.users).values(id=user_id, identity="operator", display_name="Operator")
        )
    service = Foundation(db)
    task = service.fixture(user_id, "fixture", s.new_id())
    job = service.enqueue(user_id, "enqueue", task["task_id"], s.new_id())
    yield settings, db, service, user_id, task, job
    db.close()


def job_row(db, job_id):
    with db.read() as connection:
        return (
            connection.execute(sa.select(s.execution_jobs).where(s.execution_jobs.c.id == job_id))
            .mappings()
            .one()
        )


def test_two_concurrent_claimers_receive_one_lease(queued):
    _, db, *_ = queued
    barrier = Barrier(2)
    now = s.utcnow() + timedelta(seconds=1)

    def claim(owner):
        barrier.wait(timeout=5)
        return Worker(db).claim(owner, now=now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-a", "worker-b"]))
    assert sum(lease is not None for lease in results) == 1
    lease = next(lease for lease in results if lease is not None)
    row = job_row(db, lease.job_id)
    assert row["lease_epoch"] == 1 and row["attempts"] == 1 and row["state"] == "leased"


@pytest.mark.parametrize("operation", ["heartbeat", "start", "release", "finalize"])
@pytest.mark.parametrize("mismatch", ["owner", "epoch", "expired"])
def test_all_worker_mutations_are_fenced(queued, operation, mismatch):
    _, db, *_ = queued
    worker = Worker(db, lease_seconds=10)
    now = s.utcnow() + timedelta(seconds=1)
    lease = worker.claim("original", now=now)
    assert lease is not None
    if operation == "finalize":
        worker.start(lease, now=now)
    supplied = Lease(
        lease.job_id,
        "impostor" if mismatch == "owner" else lease.owner,
        lease.epoch + 1 if mismatch == "epoch" else lease.epoch,
    )
    before = dict(job_row(db, lease.job_id))
    at = now + timedelta(seconds=10) if mismatch == "expired" else now
    with pytest.raises(NexusError, match="lost_lease"):
        getattr(worker, operation)(supplied, now=at)
    assert dict(job_row(db, lease.job_id)) == before


def test_lease_expiry_is_checked_after_acquiring_the_write_transaction(queued, monkeypatch):
    _, db, *_ = queued
    worker = Worker(db, lease_seconds=10)
    now = s.utcnow() + timedelta(seconds=1)
    lease = worker.claim("worker", now=now)
    assert lease is not None
    clock = [now]
    original_write = db.write

    @contextmanager
    def delayed_write():
        with original_write() as connection:
            # Simulate the wall clock advancing while BEGIN IMMEDIATE waits for a writer.
            clock[0] = now + timedelta(seconds=11)
            yield connection

    monkeypatch.setattr(db, "write", delayed_write)
    monkeypatch.setattr(s, "utcnow", lambda: clock[0])
    with pytest.raises(NexusError, match="lost_lease"):
        worker.heartbeat(lease)


def test_expired_noop_recovers_after_restart_with_new_epoch(queued):
    settings, db, _, _, _, job = queued
    now = s.utcnow() + timedelta(seconds=1)
    original = Worker(db, lease_seconds=10)
    lease = original.claim("original", now=now)
    assert lease is not None
    original.start(lease, now=now)
    db.close()
    restarted_db = Database(settings)
    try:
        restarted = Worker(restarted_db, lease_seconds=10)
        next_lease = restarted.claim("replacement", now=now + timedelta(seconds=11))
        assert next_lease is not None and next_lease.job_id == job["job_id"]
        assert next_lease.epoch == lease.epoch + 1
        with pytest.raises(NexusError, match="lost_lease"):
            original.finalize(lease, now=now + timedelta(seconds=12))
        restarted.start(next_lease, now=now + timedelta(seconds=12))
        restarted.finalize(next_lease, now=now + timedelta(seconds=13))
        row = job_row(restarted_db, job["job_id"])
        assert row["state"] == "succeeded" and row["attempts"] == 2
        assert row["lease_owner"] is None and row["lease_expires_at"] is None
    finally:
        restarted_db.close()


def test_heartbeat_extends_lease_release_queues_and_fences_prior_owner(queued):
    _, db, *_ = queued
    worker = Worker(db, lease_seconds=10)
    now = s.utcnow() + timedelta(seconds=1)
    lease = worker.claim("worker", now=now)
    assert lease is not None
    worker.heartbeat(lease, now=now + timedelta(seconds=9))
    assert worker.claim("other", now=now + timedelta(seconds=11)) is None
    worker.release(lease, now=now + timedelta(seconds=12))
    assert job_row(db, lease.job_id)["state"] == "queued"
    next_lease = worker.claim("other", now=now + timedelta(seconds=13))
    assert next_lease is not None and next_lease.epoch == lease.epoch + 1
    with pytest.raises(NexusError, match="lost_lease"):
        worker.heartbeat(lease, now=now + timedelta(seconds=14))


def test_exhausted_expired_noop_is_failed_once(queued):
    _, db, _, _, _, job = queued
    with db.write() as connection:
        connection.execute(
            sa.update(s.execution_jobs)
            .where(s.execution_jobs.c.id == job["job_id"])
            .values(max_attempts=1)
        )
    worker = Worker(db, lease_seconds=10)
    now = s.utcnow() + timedelta(seconds=1)
    lease = worker.claim("worker", now=now)
    assert lease is not None
    assert worker.reconcile(now=now + timedelta(seconds=11)) == 1
    assert worker.reconcile(now=now + timedelta(seconds=12)) == 0
    assert worker.claim("replacement", now=now + timedelta(seconds=12)) is None
    row = job_row(db, lease.job_id)
    assert row["state"] == "failed" and row["lease_owner"] is None


def test_finalize_requires_running_and_terminal_job_cannot_be_reclaimed(queued):
    _, db, *_ = queued
    worker = Worker(db)
    now = s.utcnow() + timedelta(seconds=1)
    lease = worker.claim("worker", now=now)
    assert lease is not None
    with pytest.raises(NexusError, match="forbidden_job_transition"):
        worker.finalize(lease, now=now)
    worker.start(lease, now=now)
    worker.finalize(lease, now=now)
    assert worker.claim("worker", now=now + timedelta(days=1)) is None


def test_slow_work_holds_no_database_transaction(queued):
    _, db, service, user_id, task, _ = queued
    entered, finish = Event(), Event()

    def handler():
        entered.set()
        assert finish.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(Worker(db).run_once, "worker", handler=handler)
        try:
            assert entered.wait(timeout=5)
            command = executor.submit(
                service.enqueue, user_id, "during-work", task["task_id"], s.new_id()
            )
            assert command.result(timeout=2)["state"] == "queued"
        finally:
            finish.set()
        lease = running.result(timeout=5)
    assert lease is not None and job_row(db, lease.job_id)["state"] == "succeeded"
