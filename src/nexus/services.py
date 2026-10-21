"""Short atomic control-plane commands. No external I/O or execution authority."""

from collections.abc import Callable

from sqlalchemy import insert, select, update

from nexus import schema as s
from nexus.domain import (
    Evidence,
    FingerprintManifest,
    NexusError,
    SourceIdentity,
    TaskState,
    canonical_hash,
    guard_transition,
)


def record_event(
    connection,
    event_type: str,
    entity_id: str,
    entity_version: int,
    user_id: str | None,
    correlation_id: str,
    payload: dict,
) -> None:
    """Insert both journals using the caller's transaction and safe event DTO."""
    audit_id, event_id = s.new_id(), s.new_id()
    now = s.utcnow()
    common = dict(
        event_type=event_type,
        entity_id=entity_id,
        entity_version=entity_version,
        correlation_id=correlation_id,
        payload=payload,
        created_at=now,
    )
    connection.execute(
        insert(s.audit_events).values(
            id=audit_id,
            user_id=user_id,
            content_hash=canonical_hash(common_to_json(common)),
            **common,
        )
    )
    connection.execute(
        insert(s.outbox_events).values(
            id=event_id,
            audit_id=audit_id,
            content_hash=canonical_hash(common_to_json(common)),
            **common,
        )
    )


def common_to_json(value: dict) -> dict:
    return {
        key: item.isoformat() if hasattr(item, "isoformat") else item for key, item in value.items()
    }


class Foundation:
    def __init__(self, database):
        self.db = database

    def command(
        self,
        user_id: str,
        key: str,
        body: dict,
        correlation_id: str,
        operation: Callable,
        *,
        after_event: Callable | None = None,
    ) -> dict:
        """A receipt scopes an exact operation/body to an authenticated operator.

        after_event is an internal fault-injection seam, never an HTTP parameter.
        BEGIN IMMEDIATE serializes same-key races without uniqueness-error retries.
        """
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise NexusError("invalid_idempotency_key", 422)
        request_hash = canonical_hash(body)
        with self.db.write() as connection:
            principal = connection.execute(
                select(s.users.c.id).where(s.users.c.id == user_id, s.users.c.active.is_(True))
            ).first()
            if principal is None:
                raise NexusError("unauthenticated", 401)
            receipt = (
                connection.execute(
                    select(s.command_receipts).where(
                        s.command_receipts.c.user_id == user_id,
                        s.command_receipts.c.command_key == key,
                    )
                )
                .mappings()
                .first()
            )
            if receipt:
                if receipt["request_hash"] != request_hash:
                    raise NexusError("idempotency_conflict")
                return receipt["response"]
            response, event_type, entity_id, version, event_payload = operation(connection)
            record_event(
                connection, event_type, entity_id, version, user_id, correlation_id, event_payload
            )
            if after_event is not None:
                after_event(connection)
            connection.execute(
                insert(s.command_receipts).values(
                    id=s.new_id(),
                    user_id=user_id,
                    command_key=key,
                    request_hash=request_hash,
                    response=response,
                )
            )
            return response

    def fixture(self, user_id: str, key: str, correlation_id: str) -> dict:
        def create(connection):
            config = {"schema_version": 1, "timezone": "Europe/Brussels", "simulated": True}
            config_hash = canonical_hash(config)
            project = connection.execute(
                select(s.projects.c.id).where(s.projects.c.slug == "synthetic-foundation")
            ).scalar_one_or_none()
            if project is None:
                project = s.new_id()
                connection.execute(
                    insert(s.projects).values(
                        id=project,
                        slug="synthetic-foundation",
                        name="Synthetic foundation",
                        timezone="Europe/Brussels",
                        config=config,
                        config_hash=config_hash,
                    )
                )
            source = connection.execute(
                select(s.external_sources.c.id).where(
                    s.external_sources.c.adapter_id == "fixture",
                    s.external_sources.c.instance_identity == "synthetic-local",
                )
            ).scalar_one_or_none()
            if source is None:
                source = s.new_id()
                connection.execute(
                    insert(s.external_sources).values(
                        id=source,
                        adapter_id="fixture",
                        instance_identity="synthetic-local",
                        config_version=1,
                        config_hash=config_hash,
                    )
                )
            task_id, item_id = s.new_id(), s.new_id()
            manifest = FingerprintManifest(
                source=SourceIdentity(
                    adapter_id="fixture",
                    instance_identity="synthetic-local",
                    remote_type="task",
                    remote_id=task_id,
                ),
                requirements_hash=canonical_hash({"requirements": "Synthetic no-op only"}),
                config_hash=config_hash,
            )
            data = manifest.model_dump(mode="json")
            connection.execute(
                insert(s.external_items).values(
                    id=item_id,
                    source_id=source,
                    remote_type="task",
                    remote_id=task_id,
                    display_key="SIMULATED",
                )
            )
            connection.execute(
                insert(s.tasks).values(
                    id=task_id,
                    project_id=project,
                    title="Synthetic foundation task (simulated)",
                    state=TaskState.IMPORTED.value,
                    fingerprint=manifest.fingerprint,
                    fingerprint_algorithm="nexus-fingerprint-v1",
                )
            )
            connection.execute(
                insert(s.task_sources).values(
                    id=s.new_id(),
                    task_id=task_id,
                    external_item_id=item_id,
                    relation="same_work",
                    role="primary",
                    confirmed_by_id=user_id,
                    active=True,
                )
            )
            connection.execute(
                insert(s.task_fingerprint_revisions).values(
                    id=s.new_id(),
                    task_id=task_id,
                    algorithm="nexus-fingerprint-v1",
                    fingerprint=manifest.fingerprint,
                    manifest=data,
                    content_hash=canonical_hash(data),
                    reason="explicit_fixture",
                )
            )
            result = {"task_id": task_id, "project_id": project, "state": "imported", "version": 1}
            return result, "fixture.created", task_id, 1, {"simulated": True}

        return self.command(
            user_id, key, {"schema_version": 1, "operation": "fixture"}, correlation_id, create
        )

    def transition(
        self,
        user_id: str,
        key: str,
        task_id: str,
        expected_version: int,
        target: TaskState,
        correlation_id: str,
    ) -> dict:
        target = TaskState(target)

        def change(connection):
            task = (
                connection.execute(select(s.tasks).where(s.tasks.c.id == task_id))
                .mappings()
                .first()
            )
            if task is None:
                raise NexusError("task_not_found", 404)
            if task["version"] != expected_version:
                raise NexusError("stale_version")
            current = TaskState(task["state"])
            # Every future edge is disabled here, even if a caller invents evidence.
            if target != TaskState.NEEDS_CLARIFICATION:
                guard_transition(current, target)
                raise NexusError("capability_unavailable")
            guard_transition(current, target, frozenset({Evidence.CLARIFICATION}))
            now = s.utcnow()
            changed = connection.execute(
                update(s.tasks)
                .where(
                    s.tasks.c.id == task_id,
                    s.tasks.c.version == expected_version,
                )
                .values(state=target.value, version=expected_version + 1, updated_at=now)
            )
            if changed.rowcount != 1:
                raise NexusError("stale_version")
            connection.execute(
                insert(s.task_holds).values(
                    id=s.new_id(),
                    task_id=task_id,
                    reason="operator_clarification",
                    opened_at=now,
                )
            )
            result = {"task_id": task_id, "state": target.value, "version": expected_version + 1}
            return (
                result,
                "task.transitioned",
                task_id,
                expected_version + 1,
                {
                    "from": current.value,
                    "to": target.value,
                },
            )

        return self.command(
            user_id,
            key,
            {
                "schema_version": 1,
                "operation": "transition",
                "task_id": task_id,
                "expected_version": expected_version,
                "target": target.value,
            },
            correlation_id,
            change,
        )

    def enqueue(self, user_id: str, key: str, task_id: str, correlation_id: str) -> dict:
        def create(connection):
            if (
                connection.execute(select(s.tasks.c.id).where(s.tasks.c.id == task_id)).first()
                is None
            ):
                raise NexusError("task_not_found", 404)
            job_id = s.new_id()
            connection.execute(
                insert(s.execution_jobs).values(
                    id=job_id,
                    kind="fixture_noop",
                    task_id=task_id,
                    state="queued",
                    idempotency_key=canonical_hash({"principal": user_id, "key": key}),
                    priority=0,
                    not_before=s.utcnow(),
                    attempts=0,
                    max_attempts=3,
                    lease_epoch=0,
                )
            )
            result = {"job_id": job_id, "state": "queued", "version": 1}
            return result, "job.enqueued", job_id, 1, {"kind": "fixture_noop", "task_id": task_id}

        return self.command(
            user_id,
            key,
            {
                "schema_version": 1,
                "operation": "enqueue",
                "kind": "fixture_noop",
                "task_id": task_id,
            },
            correlation_id,
            create,
        )

    def status(self) -> dict:
        with self.db.read() as connection:
            # Explicit column allowlists keep pairing/session/credential data out of projections.
            tasks = (
                connection.execute(
                    select(
                        s.tasks.c.id,
                        s.tasks.c.project_id,
                        s.tasks.c.title,
                        s.tasks.c.state,
                        s.tasks.c.version,
                        s.tasks.c.fingerprint,
                    ).order_by(s.tasks.c.created_at, s.tasks.c.id)
                )
                .mappings()
                .all()
            )
            jobs = (
                connection.execute(
                    select(
                        s.execution_jobs.c.id,
                        s.execution_jobs.c.task_id,
                        s.execution_jobs.c.kind,
                        s.execution_jobs.c.state,
                        s.execution_jobs.c.version,
                        s.execution_jobs.c.lease_epoch,
                        s.execution_jobs.c.attempts,
                    ).order_by(s.execution_jobs.c.created_at, s.execution_jobs.c.id)
                )
                .mappings()
                .all()
            )
            audit = (
                connection.execute(
                    select(
                        s.audit_events.c.id,
                        s.audit_events.c.event_type,
                        s.audit_events.c.entity_id,
                        s.audit_events.c.entity_version,
                    ).order_by(s.audit_events.c.sequence)
                )
                .mappings()
                .all()
            )
            outbox = (
                connection.execute(
                    select(
                        s.outbox_events.c.sequence,
                        s.outbox_events.c.id,
                        s.outbox_events.c.event_type,
                        s.outbox_events.c.entity_id,
                        s.outbox_events.c.entity_version,
                    ).order_by(s.outbox_events.c.sequence)
                )
                .mappings()
                .all()
            )
            return {
                "tasks": [dict(row) for row in tasks],
                "jobs": [dict(row) for row in jobs],
                "audit": [dict(row) for row in audit],
                "outbox": [dict(row) for row in outbox],
            }
