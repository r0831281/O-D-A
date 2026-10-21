"""Persistent fenced no-op worker. Nothing in this module executes user code."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update

from nexus import schema as s
from nexus.domain import NexusError
from nexus.services import record_event


@dataclass(frozen=True)
class Lease:
    job_id: str
    owner: str
    epoch: int


class Worker:
    def __init__(self, database, lease_seconds: int = 60):
        if not 1 <= lease_seconds <= 600:
            raise ValueError("invalid lease duration")
        self.db = database
        self.lease_seconds = lease_seconds

    def claim(self, owner: str, *, now: datetime | None = None) -> Lease | None:
        if not owner or len(owner) > 128:
            raise ValueError("invalid worker owner")
        with self.db.write() as connection:
            now = now or s.utcnow()
            job = (
                connection.execute(
                    select(s.execution_jobs)
                    .where(
                        s.execution_jobs.c.kind == "fixture_noop",
                        s.execution_jobs.c.attempts < s.execution_jobs.c.max_attempts,
                        or_(
                            and_(
                                s.execution_jobs.c.state.in_(["queued", "retry_wait"]),
                                s.execution_jobs.c.not_before <= now,
                            ),
                            and_(
                                s.execution_jobs.c.state.in_(["leased", "running"]),
                                s.execution_jobs.c.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(
                        s.execution_jobs.c.priority.desc(),
                        s.execution_jobs.c.not_before,
                        s.execution_jobs.c.id,
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if job is None:
                return None
            epoch, version = job["lease_epoch"] + 1, job["version"] + 1
            result = connection.execute(
                update(s.execution_jobs)
                .where(
                    s.execution_jobs.c.id == job["id"],
                    s.execution_jobs.c.version == job["version"],
                )
                .values(
                    state="leased",
                    lease_owner=owner,
                    lease_epoch=epoch,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    attempts=job["attempts"] + 1,
                    version=version,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise NexusError("claim_conflict")
            record_event(
                connection,
                "job.claimed",
                job["id"],
                version,
                None,
                s.new_id(),
                {"lease_epoch": epoch, "recovered": job["state"] in {"leased", "running"}},
            )
            return Lease(job["id"], owner, epoch)

    def _mutate(self, lease: Lease, action: str, *, now: datetime | None = None) -> None:
        with self.db.write() as connection:
            now = now or s.utcnow()
            job = (
                connection.execute(
                    select(s.execution_jobs).where(
                        s.execution_jobs.c.id == lease.job_id,
                        s.execution_jobs.c.kind == "fixture_noop",
                        s.execution_jobs.c.state.in_(["leased", "running"]),
                        s.execution_jobs.c.lease_owner == lease.owner,
                        s.execution_jobs.c.lease_epoch == lease.epoch,
                        s.execution_jobs.c.lease_expires_at > now,
                    )
                )
                .mappings()
                .first()
            )
            if job is None:
                raise NexusError("lost_lease")
            values = {"updated_at": now, "version": job["version"] + 1}
            if action == "heartbeat":
                values["lease_expires_at"] = now + timedelta(seconds=self.lease_seconds)
            elif action == "start":
                if job["state"] != "leased":
                    raise NexusError("forbidden_job_transition")
                values["state"] = "running"
            elif action in {"release", "finalize"}:
                if action == "finalize" and job["state"] != "running":
                    raise NexusError("forbidden_job_transition")
                values.update(
                    state=(
                        "succeeded"
                        if action == "finalize"
                        else "failed"
                        if job["attempts"] >= job["max_attempts"]
                        else "queued"
                    ),
                    lease_owner=None,
                    lease_expires_at=None,
                )
            else:
                raise ValueError("unknown worker mutation")
            changed = connection.execute(
                update(s.execution_jobs)
                .where(
                    s.execution_jobs.c.id == lease.job_id,
                    s.execution_jobs.c.version == job["version"],
                    s.execution_jobs.c.lease_epoch == lease.epoch,
                    s.execution_jobs.c.lease_owner == lease.owner,
                    s.execution_jobs.c.lease_expires_at > now,
                )
                .values(**values)
            )
            if changed.rowcount != 1:
                raise NexusError("lost_lease")
            record_event(
                connection,
                "job." + action,
                lease.job_id,
                values["version"],
                None,
                s.new_id(),
                {"lease_epoch": lease.epoch},
            )

    def heartbeat(self, lease: Lease, *, now: datetime | None = None) -> None:
        self._mutate(lease, "heartbeat", now=now)

    def start(self, lease: Lease, *, now: datetime | None = None) -> None:
        self._mutate(lease, "start", now=now)

    def release(self, lease: Lease, *, now: datetime | None = None) -> None:
        self._mutate(lease, "release", now=now)

    def finalize(self, lease: Lease, *, now: datetime | None = None) -> None:
        self._mutate(lease, "finalize", now=now)

    def reconcile(self, *, now: datetime | None = None) -> int:
        """Only exhausted expired fixture jobs need failure; other no-ops are reclaimable."""
        with self.db.write() as connection:
            now = now or s.utcnow()
            jobs = (
                connection.execute(
                    select(s.execution_jobs).where(
                        s.execution_jobs.c.kind == "fixture_noop",
                        s.execution_jobs.c.state.in_(["leased", "running"]),
                        s.execution_jobs.c.lease_expires_at <= now,
                        s.execution_jobs.c.attempts >= s.execution_jobs.c.max_attempts,
                    )
                )
                .mappings()
                .all()
            )
            for job in jobs:
                connection.execute(
                    update(s.execution_jobs)
                    .where(
                        s.execution_jobs.c.id == job["id"],
                        s.execution_jobs.c.version == job["version"],
                    )
                    .values(
                        state="failed",
                        lease_owner=None,
                        lease_expires_at=None,
                        version=job["version"] + 1,
                        updated_at=now,
                    )
                )
                record_event(
                    connection,
                    "job.exhausted",
                    job["id"],
                    job["version"] + 1,
                    None,
                    s.new_id(),
                    {"lease_epoch": job["lease_epoch"]},
                )
            return len(jobs)

    def run_once(self, owner: str, *, handler=None) -> Lease | None:
        self.reconcile()
        lease = self.claim(owner)
        if lease is None:
            return None
        self.start(lease)
        # A test may block here: there is no session/transaction held during work.
        if handler is not None:
            handler()
        self.finalize(lease)
        return lease
