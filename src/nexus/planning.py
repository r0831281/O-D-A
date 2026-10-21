"""Phase 2 typed configuration, activation and restart-safe source sync services."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus import schema as s
from nexus.domain import NexusError, canonical_hash, tuple_json_arrays
from nexus.profiles import LinkStatus, PlanningProfileConfig, resolve_route
from nexus.schema import new_id, utcnow
from nexus.services import record_event
from nexus.sources import SourceAdapter, SourceFailure, SourceItem, SourcePage, parse_ics
from nexus.storage import Database


def _dict(row: Any) -> dict[str, Any] | None:
    return None if row is None else dict(row._mapping)


def _planning_order(item: dict) -> tuple[str, str]:
    return (
        str(item.get("start_date", item.get("start_utc", ""))),
        str(item.get("allocation_id", item.get("uid", ""))),
    )


class PlanningService:
    def __init__(self, database: Database):
        self.db = database

    def save_connection(
        self,
        adapter_id: str,
        instance_identity: str,
        config: dict,
        secret_refs: tuple[str, ...],
        adapter_build: str,
    ) -> dict:
        if config.get("schema_version", 1) != 1 or config.get("adapter_id") != adapter_id:
            raise NexusError("connection_schema_invalid", 422)
        if any(
            key.lower() in {"token", "password", "secret", "api_key", "authorization"}
            for key in config
        ):
            raise NexusError("credential_in_configuration", 422)
        if not secret_refs or any(
            not value.startswith("env:NEXUS_SECRET_") for value in secret_refs
        ):
            raise NexusError("secret_reference_invalid", 422)
        if config.get("secret_ref") not in secret_refs:
            raise NexusError("secret_reference_missing", 422)
        config_hash = canonical_hash(config)
        with self.db.write() as conn:
            source = conn.execute(
                select(s.external_sources).where(
                    s.external_sources.c.adapter_id == adapter_id,
                    s.external_sources.c.instance_identity == instance_identity,
                )
            ).first()
            if source is None:
                source_id = new_id()
                conn.execute(
                    s.external_sources.insert().values(
                        id=source_id,
                        adapter_id=adapter_id,
                        instance_identity=instance_identity,
                        config_version=1,
                        config_hash=config_hash,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                        version=1,
                    )
                )
                revision = 1
            else:
                source_data = dict(source._mapping)
                source_id = source_data["id"]
                revision = (
                    conn.execute(
                        select(sa.func.max(s.connection_revisions.c.revision)).where(
                            s.connection_revisions.c.source_id == source_id
                        )
                    ).scalar_one_or_none()
                    or 0
                ) + 1
                conn.execute(
                    s.external_sources.update()
                    .where(s.external_sources.c.id == source_id)
                    .values(
                        config_hash=config_hash,
                        version=source_data["version"] + 1,
                        updated_at=utcnow(),
                    )
                )
            revision_id = new_id()
            conn.execute(
                s.connection_revisions.insert().values(
                    id=revision_id,
                    source_id=source_id,
                    revision=revision,
                    schema_version=1,
                    adapter_build=adapter_build,
                    config=config,
                    secret_refs=list(secret_refs),
                    config_hash=config_hash,
                    created_at=utcnow(),
                )
            )
        return {
            "source_id": source_id,
            "connection_revision_id": revision_id,
            "revision": revision,
            "config_hash": config_hash,
            "secret_refs": list(secret_refs),
        }

    def import_ics(self, calendar_id: str, timezone: str, content: str) -> dict:
        if not 1 <= len(calendar_id) <= 128 or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in calendar_id
        ):
            raise NexusError("calendar_id_invalid", 422)
        events = parse_ics(content, timezone)
        config = {
            "schema_version": 1,
            "adapter_id": "ics-local-v1",
            "calendar_id": calendar_id,
            "timezone": timezone,
            "source": "local_file",
        }
        digest = canonical_hash({"config": config, "content_hash": canonical_hash(content)})
        with self.db.write() as conn:
            source = conn.execute(
                select(s.external_sources).where(
                    s.external_sources.c.adapter_id == "ics-local-v1",
                    s.external_sources.c.instance_identity == f"local-calendar:{calendar_id}",
                )
            ).first()
            if source is None:
                source_id = new_id()
                conn.execute(
                    s.external_sources.insert().values(
                        id=source_id,
                        adapter_id="ics-local-v1",
                        instance_identity=f"local-calendar:{calendar_id}",
                        config_version=1,
                        config_hash=digest,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                        version=1,
                    )
                )
                revision_number = 1
            else:
                source_data = dict(source._mapping)
                source_id = source_data["id"]
                conn.execute(
                    s.external_sources.update()
                    .where(s.external_sources.c.id == source_id)
                    .values(
                        config_hash=digest, updated_at=utcnow(), version=source_data["version"] + 1
                    )
                )
                revision_number = (
                    conn.execute(
                        sa.select(sa.func.max(s.connection_revisions.c.revision)).where(
                            s.connection_revisions.c.source_id == source_id
                        )
                    ).scalar_one_or_none()
                    or 0
                ) + 1
            revision_id = new_id()
            conn.execute(
                s.connection_revisions.insert().values(
                    id=revision_id,
                    source_id=source_id,
                    revision=revision_number,
                    schema_version=1,
                    adapter_build="nexus-ics-local-1",
                    config=config,
                    secret_refs=[],
                    config_hash=digest,
                    created_at=utcnow(),
                )
            )
            conn.execute(
                s.connection_test_runs.insert().values(
                    id=new_id(),
                    connection_revision_id=revision_id,
                    profile_revision_id=None,
                    test_kind="read",
                    status="passed",
                    config_hash=digest,
                    adapter_build="nexus-ics-local-1",
                    result={"local_file_parsed": True, "simulated": True},
                    expires_at=utcnow() + timedelta(minutes=15),
                    created_at=utcnow(),
                )
            )
            existing = set(
                conn.execute(
                    select(s.external_items.c.remote_id).where(
                        s.external_items.c.source_id == source_id,
                        s.external_items.c.remote_type == "ics.event",
                    )
                )
                .scalars()
                .all()
            )
        items = tuple(
            SourceItem.build(
                adapter_id="ics-local-v1",
                remote_type="ics.event",
                remote_id=f"{event['uid']}|{event['occurrence_key']}",
                display_key=str(event.get("summary") or event["uid"]),
                normalized=event,
            )
            for event in events
        )
        current = {item.remote_id for item in items}
        missing = tuple(("ics.event", remote_id) for remote_id in sorted(existing - current))

        class IcsPages:
            adapter_id = "ics-local-v1"
            build = "nexus-ics-local-1"

            def fetch_page(inner_self, cursor):
                offset = int(cursor or 0)
                page_items = items[offset : offset + 100]
                next_offset = (
                    offset + len(page_items) if offset + len(page_items) < len(items) else None
                )
                complete = next_offset is None
                return SourcePage(
                    f"offset:{offset}",
                    page_items,
                    str(next_offset) if next_offset is not None else None,
                    complete,
                    missing if complete else (),
                )

        query_hash = canonical_hash({"calendar_id": calendar_id, "timezone": timezone})
        engine = SyncEngine(self.db)
        run_id = engine.start(revision_id, "events", query_hash)
        sync_result = engine.execute(run_id, "events", query_hash, IcsPages())
        return {
            "simulated": True,
            "calendar_id": calendar_id,
            "connection_revision_id": revision_id,
            "event_count": len(items),
            "deleted_count": len(missing),
            "sync": sync_result,
        }

    def queue_manual_sync(
        self,
        actor_id: str,
        connection_revision_id: str,
        stream_key: str,
        query_hash: str,
        idempotency_key: str,
    ) -> dict:
        if (
            not 1 <= len(stream_key) <= 200
            or len(query_hash) != 64
            or not 1 <= len(idempotency_key) <= 200
        ):
            raise NexusError("sync_request_invalid", 422)
        body = {
            "connection_revision_id": connection_revision_id,
            "stream_key": stream_key,
            "query_hash": query_hash,
        }
        request_hash = canonical_hash(body)
        with self.db.write() as conn:
            prior = conn.execute(
                select(s.manual_sync_requests).where(
                    s.manual_sync_requests.c.actor_id == actor_id,
                    s.manual_sync_requests.c.idempotency_key == idempotency_key,
                )
            ).first()
            if prior:
                row = dict(prior._mapping)
                if row["request_hash"] != request_hash:
                    raise NexusError("idempotency_conflict", 409)
                return {
                    "request_id": row["id"],
                    "status": row["status"],
                    "sync_run_id": row["sync_run_id"],
                }
            if (
                conn.execute(
                    select(s.connection_revisions.c.id).where(
                        s.connection_revisions.c.id == connection_revision_id
                    )
                ).first()
                is None
            ):
                raise NexusError("connection_revision_missing", 404)
            request_id = new_id()
            conn.execute(
                s.manual_sync_requests.insert().values(
                    id=request_id,
                    connection_revision_id=connection_revision_id,
                    actor_id=actor_id,
                    stream_key=stream_key,
                    query_hash=query_hash,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    status="queued",
                    sync_run_id=None,
                    created_at=utcnow(),
                )
            )
            record_event(
                conn,
                "source_sync.queued",
                request_id,
                1,
                actor_id,
                new_id(),
                {"connection_revision_id": connection_revision_id, "stream_key": stream_key},
            )
        return {"request_id": request_id, "status": "queued", "sync_run_id": None}

    def run_manual_sync(self, request_id: str, adapter: SourceAdapter) -> dict:
        with self.db.write() as conn:
            row = conn.execute(
                select(s.manual_sync_requests).where(s.manual_sync_requests.c.id == request_id)
            ).first()
            if row is None:
                raise NexusError("sync_request_missing", 404)
            data = dict(row._mapping)
            if data["status"] == "succeeded":
                return {
                    "request_id": request_id,
                    "status": "succeeded",
                    "sync_run_id": data["sync_run_id"],
                }
            if data["sync_run_id"] is None:
                revision = conn.execute(
                    select(s.connection_revisions).where(
                        s.connection_revisions.c.id == data["connection_revision_id"]
                    )
                ).first()
                if revision is None:
                    raise NexusError("connection_revision_missing", 404)
                revision_data = dict(revision._mapping)
                cursor = conn.execute(
                    select(s.source_cursors).where(
                        s.source_cursors.c.source_id == revision_data["source_id"],
                        s.source_cursors.c.stream_key == data["stream_key"],
                    )
                ).first()
                cursor_data = dict(cursor._mapping) if cursor else None
                start_cursor = (
                    cursor_data["cursor"]
                    if cursor_data and cursor_data["query_hash"] == data["query_hash"]
                    else None
                )
                generation = (
                    conn.execute(
                        sa.select(sa.func.max(s.sync_runs.c.generation)).where(
                            s.sync_runs.c.source_id == revision_data["source_id"]
                        )
                    ).scalar_one_or_none()
                    or 0
                )
                run_id = new_id()
                conn.execute(
                    s.sync_runs.insert().values(
                        id=run_id,
                        source_id=revision_data["source_id"],
                        connection_revision_id=data["connection_revision_id"],
                        generation=generation + 1,
                        status="running",
                        cursor_before=start_cursor,
                        cursor_after=start_cursor,
                        page_count=0,
                        created_at=utcnow(),
                    )
                )
                conn.execute(
                    s.manual_sync_requests.update()
                    .where(s.manual_sync_requests.c.id == request_id)
                    .values(sync_run_id=run_id)
                )
            else:
                run_id = data["sync_run_id"]
            conn.execute(
                s.manual_sync_requests.update()
                .where(s.manual_sync_requests.c.id == request_id)
                .values(status="running")
            )
        engine = SyncEngine(self.db)
        try:
            result = engine.execute(run_id, data["stream_key"], data["query_hash"], adapter)
        except SourceFailure:
            with self.db.write() as conn:
                conn.execute(
                    s.manual_sync_requests.update()
                    .where(s.manual_sync_requests.c.id == request_id)
                    .values(status="failed")
                )
            raise
        with self.db.write() as conn:
            conn.execute(
                s.manual_sync_requests.update()
                .where(s.manual_sync_requests.c.id == request_id)
                .values(status="succeeded")
            )
        return {"request_id": request_id, **result}

    def save_profile(self, config: PlanningProfileConfig) -> dict:
        payload = config.model_dump(mode="json")
        digest = config.config_hash
        with self.db.write() as conn:
            profile = conn.execute(
                select(s.planning_profiles).where(s.planning_profiles.c.slug == config.slug)
            ).first()
            if profile is None:
                profile_id, revision = new_id(), 1
                conn.execute(
                    s.planning_profiles.insert().values(
                        id=profile_id,
                        slug=config.slug,
                        active_revision_id=None,
                        created_at=utcnow(),
                        updated_at=utcnow(),
                        version=1,
                    )
                )
            else:
                profile_data = dict(profile._mapping)
                profile_id = profile_data["id"]
                latest = conn.execute(
                    sa.select(sa.func.max(s.planning_profile_revisions.c.revision)).where(
                        s.planning_profile_revisions.c.profile_id == profile_id
                    )
                ).scalar_one_or_none()
                revision = (latest or 0) + 1
            expected_revisions = {
                config.schedule_connection_revision_id,
                config.jira_connection_revision_id,
                *config.odoo_connection_revision_ids,
                *config.optional_calendar_connection_revision_ids,
            }
            found_revisions = (
                set(
                    conn.execute(
                        select(s.connection_revisions.c.id).where(
                            s.connection_revisions.c.id.in_(expected_revisions)
                        )
                    )
                    .scalars()
                    .all()
                )
                if expected_revisions
                else set()
            )
            if found_revisions != expected_revisions:
                raise NexusError("profile_connection_revision_missing", 422)
            revision_configs = {
                row["id"]: row["config"]
                for row in conn.execute(
                    select(s.connection_revisions.c.id, s.connection_revisions.c.config).where(
                        s.connection_revisions.c.id.in_(expected_revisions)
                    )
                )
                .mappings()
                .all()
            }
            schedule_config = revision_configs[config.schedule_connection_revision_id]
            jira_config = revision_configs[config.jira_connection_revision_id]
            if (
                schedule_config.get("adapter_id") != "tempo-cloud-planner-v1"
                or schedule_config.get("allocated_account_id") != config.allocated_account_id
            ):
                raise NexusError("schedule_authority_or_account_mismatch", 422)
            if jira_config.get("adapter_id") != "jira-cloud-v1":
                raise NexusError("jira_work_item_connection_required", 422)
            configured_jira_fields = set(jira_config.get("fields", ()))
            required_jira_fields = {
                field
                for rule in config.rules
                for field in (
                    *rule.acceptance_field_ids,
                    *((rule.field_id,) if rule.field_id else ()),
                    *((rule.odoo_link_field,) if rule.odoo_link_field else ()),
                )
            }
            if not required_jira_fields <= configured_jira_fields:
                raise NexusError("jira_profile_fields_not_configured", 422)
            for instance in config.odoo_instances:
                connection_config = revision_configs.get(instance.connection_revision_id, {})
                configured_host = urlsplit(str(connection_config.get("base_url", ""))).hostname
                if (
                    connection_config.get("adapter_id")
                    not in {"odoo-17-read-v1", "odoo-18-read-v1", "odoo-19-read-v1"}
                    or connection_config.get("database") != instance.database
                    or configured_host != instance.host
                ):
                    raise NexusError("odoo_instance_mapping_mismatch", 422)
                if not set(instance.company_ids) <= set(
                    connection_config.get("company_ids", ())
                ) or not set(instance.project_ids) <= set(connection_config.get("project_ids", ())):
                    raise NexusError("odoo_scope_mapping_mismatch", 422)
            for rule in config.rules:
                project_exists = conn.execute(
                    select(s.projects.c.id).where(s.projects.c.id == rule.nexus_project_id)
                ).first()
                bindings = conn.execute(
                    select(s.project_repositories.c.id, s.repositories.c.enabled)
                    .select_from(
                        s.project_repositories.join(
                            s.repositories,
                            s.repositories.c.id == s.project_repositories.c.repository_id,
                        )
                    )
                    .where(
                        s.project_repositories.c.project_id == rule.nexus_project_id,
                        s.project_repositories.c.id.in_(rule.repository_binding_ids),
                    )
                ).all()
                if project_exists is None or len(bindings) != len(rule.repository_binding_ids):
                    raise NexusError("local_project_repository_mapping_missing", 422)
                if any(not row.enabled for row in bindings):
                    raise NexusError("local_repository_mapping_disabled", 422)
            revision_id = new_id()
            conn.execute(
                s.planning_profile_revisions.insert().values(
                    id=revision_id,
                    profile_id=profile_id,
                    revision=revision,
                    schema_version=1,
                    config=payload,
                    config_hash=digest,
                    created_at=utcnow(),
                )
            )
            conn.execute(
                s.profile_connections.insert().values(
                    id=new_id(),
                    profile_revision_id=revision_id,
                    connection_revision_id=config.schedule_connection_revision_id,
                    role="schedule",
                    created_at=utcnow(),
                )
            )
            conn.execute(
                s.profile_connections.insert().values(
                    id=new_id(),
                    profile_revision_id=revision_id,
                    connection_revision_id=config.jira_connection_revision_id,
                    role="work_items",
                    created_at=utcnow(),
                )
            )
            for ref in config.odoo_connection_revision_ids:
                conn.execute(
                    s.profile_connections.insert().values(
                        id=new_id(),
                        profile_revision_id=revision_id,
                        connection_revision_id=ref,
                        role="requirements",
                        created_at=utcnow(),
                    )
                )
            for ref in config.optional_calendar_connection_revision_ids:
                conn.execute(
                    s.profile_connections.insert().values(
                        id=new_id(),
                        profile_revision_id=revision_id,
                        connection_revision_id=ref,
                        role="context_calendar",
                        created_at=utcnow(),
                    )
                )
        return {
            "profile_id": profile_id,
            "profile_revision_id": revision_id,
            "revision": revision,
            "config_hash": digest,
        }

    def resolve_task(
        self, profile_revision_id: str, jira_external_item_id: str, actor_id: str
    ) -> dict:
        """Persist one exact Jira identity and its current configured source evidence."""
        now = utcnow()
        with self.db.write() as conn:
            revision = conn.execute(
                select(s.planning_profile_revisions).where(
                    s.planning_profile_revisions.c.id == profile_revision_id
                )
            ).first()
            if revision is None:
                raise NexusError("profile_revision_missing", 404)
            revision_data = dict(revision._mapping)
            active = conn.execute(
                select(s.planning_profiles.c.active_revision_id).where(
                    s.planning_profiles.c.id == revision_data["profile_id"]
                )
            ).scalar_one()
            if active != profile_revision_id:
                raise NexusError("profile_revision_not_active", 409)
            config = PlanningProfileConfig.model_validate(
                tuple_json_arrays(revision_data["config"])
            )
            jira_connection = (
                conn.execute(
                    select(s.connection_revisions).where(
                        s.connection_revisions.c.id == config.jira_connection_revision_id
                    )
                )
                .mappings()
                .one()
            )
            jira_item = (
                conn.execute(
                    select(s.external_items).where(
                        s.external_items.c.id == jira_external_item_id,
                        s.external_items.c.source_id == jira_connection["source_id"],
                        s.external_items.c.remote_type == "jira.issue",
                    )
                )
                .mappings()
                .first()
            )
            if jira_item is None:
                raise NexusError("jira_source_item_missing", 404)
            jira_snapshot = (
                conn.execute(
                    select(s.external_item_snapshots)
                    .where(s.external_item_snapshots.c.external_item_id == jira_external_item_id)
                    .order_by(s.external_item_snapshots.c.revision.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if jira_snapshot is None or jira_snapshot["visibility"] != "visible":
                raise NexusError("jira_source_item_not_visible", 409)
            normalized = jira_snapshot["normalized"]
            custom_fields = normalized.get("custom_fields", {})
            issue_fields = {
                "project": {"id": normalized.get("project_id")},
                "issuetype": {"name": normalized.get("issue_type")},
                "summary": normalized.get("title"),
                "description": normalized.get("description"),
                "assignee": {"accountId": normalized.get("assignee")}
                if normalized.get("assignee")
                else None,
                **(custom_fields if isinstance(custom_fields, dict) else {}),
            }
            issue = {
                "id": jira_item["remote_id"],
                "key": jira_item["display_key"],
                "fields": issue_fields,
            }
            odoo_evidence: dict[str, str | None] = {"item_id": None, "snapshot_id": None}

            def fetch_odoo(instance_identity: str, task_id: int):
                instance = next(
                    (
                        item
                        for item in config.odoo_instances
                        if f"{item.host}/{item.database}" == instance_identity
                    ),
                    None,
                )
                if instance is None:
                    return LinkStatus.INVALID, None
                odoo_connection = (
                    conn.execute(
                        select(s.connection_revisions).where(
                            s.connection_revisions.c.id == instance.connection_revision_id
                        )
                    )
                    .mappings()
                    .one()
                )
                item = (
                    conn.execute(
                        select(s.external_items).where(
                            s.external_items.c.source_id == odoo_connection["source_id"],
                            s.external_items.c.remote_type == "odoo.project_task",
                            s.external_items.c.remote_id == str(task_id),
                        )
                    )
                    .mappings()
                    .first()
                )
                if item is None:
                    return LinkStatus.MISSING, None
                odoo_evidence["item_id"] = item["id"]
                snapshot = (
                    conn.execute(
                        select(s.external_item_snapshots)
                        .where(s.external_item_snapshots.c.external_item_id == item["id"])
                        .order_by(s.external_item_snapshots.c.revision.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if snapshot is None:
                    odoo_evidence["item_id"] = None
                    return LinkStatus.MISSING, None
                odoo_evidence["snapshot_id"] = snapshot["id"]
                if snapshot["visibility"] != "visible":
                    return LinkStatus.INACCESSIBLE, None
                return LinkStatus.RESOLVED, snapshot["normalized"]

            route = resolve_route(
                config,
                issue,
                allocated_account_id=config.allocated_account_id,
                fetch_odoo=fetch_odoo,
            )
            if route.category is None:
                return {
                    "task_id": None,
                    "status": route.status,
                    "route": route.model_dump(mode="json"),
                }
            rule = next(item for item in config.rules if item.category == route.category)
            project = conn.execute(
                select(s.projects.c.id).where(s.projects.c.id == rule.nexus_project_id)
            ).first()
            bindings = conn.execute(
                select(s.project_repositories.c.id, s.repositories.c.enabled)
                .select_from(
                    s.project_repositories.join(
                        s.repositories,
                        s.repositories.c.id == s.project_repositories.c.repository_id,
                    )
                )
                .where(
                    s.project_repositories.c.project_id == rule.nexus_project_id,
                    s.project_repositories.c.id.in_(rule.repository_binding_ids),
                )
            ).all()
            if project is None or len(bindings) != len(rule.repository_binding_ids):
                raise NexusError("local_project_repository_mapping_missing", 409)
            if any(not row.enabled for row in bindings):
                raise NexusError("local_repository_mapping_disabled", 409)

            if route.requirements_source == "jira":
                requirements_item_id = jira_item["id"]
                requirements_snapshot_id = jira_snapshot["id"]
            else:
                requirements_item_id = odoo_evidence["item_id"]
                requirements_snapshot_id = odoo_evidence["snapshot_id"]

            schedule_connection = (
                conn.execute(
                    select(s.connection_revisions).where(
                        s.connection_revisions.c.id == config.schedule_connection_revision_id
                    )
                )
                .mappings()
                .one()
            )
            allocation_evidence = []
            allocations = (
                conn.execute(
                    select(s.planning_allocations, s.external_items)
                    .select_from(
                        s.planning_allocations.join(
                            s.external_items,
                            s.external_items.c.id == s.planning_allocations.c.external_item_id,
                        )
                    )
                    .where(
                        s.external_items.c.source_id == schedule_connection["source_id"],
                        s.external_items.c.remote_type == "tempo.allocation",
                        s.planning_allocations.c.item_kind == "jira_issue",
                        s.planning_allocations.c.item_id == jira_item["remote_id"],
                        s.planning_allocations.c.allocated_account_id
                        == config.allocated_account_id,
                        s.planning_allocations.c.status == "active",
                    )
                )
                .mappings()
                .all()
            )
            for allocation in allocations:
                snapshot = (
                    conn.execute(
                        select(s.external_item_snapshots)
                        .where(
                            s.external_item_snapshots.c.external_item_id
                            == allocation["external_item_id"]
                        )
                        .order_by(s.external_item_snapshots.c.revision.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if snapshot and snapshot["visibility"] == "visible":
                    allocation_evidence.append(
                        {
                            "allocation_id": allocation["id"],
                            "snapshot_id": snapshot["id"],
                            "external_item_id": allocation["external_item_id"],
                            "raw_hash": snapshot["raw_hash"],
                        }
                    )
            requirements_snapshot = (
                conn.execute(
                    select(s.external_item_snapshots).where(
                        s.external_item_snapshots.c.id == requirements_snapshot_id
                    )
                )
                .mappings()
                .first()
                if requirements_snapshot_id
                else None
            )
            requirements_hash = canonical_hash(
                route.requirements if route.requirements is not None else {}
            )
            route_json = route.model_dump(mode="json")
            manifest = {
                "algorithm": "phase2-route-fingerprint-v1",
                "profile_revision_id": profile_revision_id,
                "profile_hash": revision_data["config_hash"],
                "jira_item_id": jira_item["id"],
                "jira_snapshot_id": jira_snapshot["id"],
                "jira_raw_hash": jira_snapshot["raw_hash"],
                "requirements_item_id": requirements_item_id,
                "requirements_snapshot_id": requirements_snapshot_id,
                "requirements_raw_hash": requirements_snapshot["raw_hash"]
                if requirements_snapshot
                else None,
                "requirements_hash": requirements_hash,
                "local_project_id": rule.nexus_project_id,
                "repository_mapping_ref": rule.repository_mapping_ref,
                "repository_binding_ids": list(rule.repository_binding_ids),
                "allocations": allocation_evidence,
                "route": route_json,
            }
            fingerprint = canonical_hash(manifest)
            resolution_hash = canonical_hash(manifest)
            task_source = (
                conn.execute(
                    select(s.task_sources, s.tasks)
                    .select_from(
                        s.task_sources.join(s.tasks, s.tasks.c.id == s.task_sources.c.task_id)
                    )
                    .where(
                        s.task_sources.c.external_item_id == jira_item["id"],
                        s.task_sources.c.active.is_(True),
                        s.task_sources.c.role == "primary",
                    )
                )
                .mappings()
                .first()
            )
            title = str(normalized.get("title") or jira_item["display_key"])
            if task_source:
                task_id = task_source["task_id"]
                task_row = (
                    conn.execute(select(s.tasks).where(s.tasks.c.id == task_id)).mappings().one()
                )
                if task_row["project_id"] != rule.nexus_project_id:
                    raise NexusError("canonical_project_remap_requires_review", 409)
                version = task_row["version"]
                if task_row["fingerprint"] != fingerprint or task_row["title"] != title:
                    version += 1
                    conn.execute(
                        s.tasks.update()
                        .where(s.tasks.c.id == task_id)
                        .values(
                            title=title,
                            fingerprint=fingerprint,
                            fingerprint_algorithm="phase2-route-fingerprint-v1",
                            version=version,
                            updated_at=now,
                        )
                    )
            else:
                task_id, version = new_id(), 1
                conn.execute(
                    s.tasks.insert().values(
                        id=task_id,
                        project_id=rule.nexus_project_id,
                        title=title,
                        state="needs_clarification" if route.status == "blocked" else "imported",
                        fingerprint=fingerprint,
                        fingerprint_algorithm="phase2-route-fingerprint-v1",
                        created_at=now,
                        updated_at=now,
                        version=version,
                    )
                )
                conn.execute(
                    s.task_sources.insert().values(
                        id=new_id(),
                        task_id=task_id,
                        external_item_id=jira_item["id"],
                        relation="same_work",
                        role="primary",
                        confirmed_by_id=actor_id,
                        active=True,
                        created_at=now,
                        updated_at=now,
                        version=1,
                    )
                )
            fingerprint_revision = conn.execute(
                select(s.task_fingerprint_revisions.c.id).where(
                    s.task_fingerprint_revisions.c.task_id == task_id,
                    s.task_fingerprint_revisions.c.fingerprint == fingerprint,
                    s.task_fingerprint_revisions.c.algorithm == "phase2-route-fingerprint-v1",
                )
            ).first()
            if fingerprint_revision is None:
                conn.execute(
                    s.task_fingerprint_revisions.insert().values(
                        id=new_id(),
                        task_id=task_id,
                        algorithm="phase2-route-fingerprint-v1",
                        fingerprint=fingerprint,
                        manifest=manifest,
                        content_hash=canonical_hash(manifest),
                        reason="source_resolution",
                        created_at=now,
                    )
                )
            resolution = conn.execute(
                select(s.planning_task_resolutions.c.id).where(
                    s.planning_task_resolutions.c.task_id == task_id,
                    s.planning_task_resolutions.c.resolution_hash == resolution_hash,
                )
            ).scalar_one_or_none()
            if resolution is None:
                old_blockers = (
                    conn.execute(
                        select(s.planning_task_resolutions.c.blockers)
                        .where(s.planning_task_resolutions.c.task_id == task_id)
                        .order_by(s.planning_task_resolutions.c.created_at.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    or []
                )
                resolution = new_id()
                conn.execute(
                    s.planning_task_resolutions.insert().values(
                        id=resolution,
                        task_id=task_id,
                        profile_revision_id=profile_revision_id,
                        jira_item_id=jira_item["id"],
                        jira_snapshot_id=jira_snapshot["id"],
                        requirements_source=route.requirements_source,
                        requirements_item_id=requirements_item_id,
                        requirements_snapshot_id=requirements_snapshot_id,
                        category=route.category,
                        status=route.status,
                        blockers=list(route.blockers),
                        repository_mapping_ref=rule.repository_mapping_ref,
                        repository_binding_ids=list(rule.repository_binding_ids),
                        route_trace=route_json,
                        requirements_hash=requirements_hash,
                        resolution_hash=resolution_hash,
                        created_at=now,
                    )
                )
                for allocation in allocation_evidence:
                    exists = conn.execute(
                        select(s.planning_task_allocations.c.id).where(
                            s.planning_task_allocations.c.resolution_id == resolution,
                            s.planning_task_allocations.c.allocation_id
                            == allocation["allocation_id"],
                            s.planning_task_allocations.c.allocation_snapshot_id
                            == allocation["snapshot_id"],
                        )
                    ).first()
                    if exists is None:
                        conn.execute(
                            s.planning_task_allocations.insert().values(
                                id=new_id(),
                                task_id=task_id,
                                resolution_id=resolution,
                                allocation_id=allocation["allocation_id"],
                                allocation_snapshot_id=allocation["snapshot_id"],
                                created_at=now,
                            )
                        )
                resolved_blockers = set(old_blockers) - set(route.blockers)
                if resolved_blockers:
                    conn.execute(
                        s.task_holds.update()
                        .where(
                            s.task_holds.c.task_id == task_id,
                            s.task_holds.c.reason.in_(resolved_blockers),
                            s.task_holds.c.resolved_at.is_(None),
                        )
                        .values(
                            resolved_at=now,
                            resolver_id=actor_id,
                            updated_at=now,
                            version=s.task_holds.c.version + 1,
                        )
                    )
                if route.status == "blocked":
                    for reason in route.blockers:
                        open_hold = conn.execute(
                            select(s.task_holds.c.id).where(
                                s.task_holds.c.task_id == task_id,
                                s.task_holds.c.reason == reason,
                                s.task_holds.c.resolved_at.is_(None),
                            )
                        ).first()
                        if open_hold is None:
                            conn.execute(
                                s.task_holds.insert().values(
                                    id=new_id(),
                                    task_id=task_id,
                                    reason=reason,
                                    opened_at=now,
                                    resolved_at=None,
                                    resolver_id=None,
                                    created_at=now,
                                    updated_at=now,
                                    version=1,
                                )
                            )
                record_event(
                    conn,
                    "task.source_resolution",
                    task_id,
                    version,
                    actor_id,
                    new_id(),
                    {"resolution_id": resolution, "status": route.status},
                )
            return {
                "task_id": task_id,
                "resolution_id": resolution,
                "profile_revision_id": profile_revision_id,
                "status": route.status,
                "blockers": list(route.blockers),
                "requirements_source": route.requirements_source,
                "allocation_count": len(allocation_evidence),
                "fingerprint": fingerprint,
                "route": route_json,
            }

    def record_test(
        self,
        *,
        connection_revision_id: str | None,
        profile_revision_id: str | None,
        test_kind: str,
        status: str,
        config_hash: str,
        adapter_build: str,
        result: dict,
        ttl_seconds: int = 900,
    ) -> str:
        if status not in {"passed", "failed", "blocked"} or test_kind not in {
            "discovery",
            "read",
            "preview",
        }:
            raise NexusError("test_record_invalid", 422)
        run_id = new_id()
        with self.db.write() as conn:
            conn.execute(
                s.connection_test_runs.insert().values(
                    id=run_id,
                    connection_revision_id=connection_revision_id,
                    profile_revision_id=profile_revision_id,
                    test_kind=test_kind,
                    status=status,
                    config_hash=config_hash,
                    adapter_build=adapter_build,
                    result=result,
                    expires_at=utcnow() + timedelta(seconds=ttl_seconds),
                    created_at=utcnow(),
                )
            )
        return run_id

    def preview(
        self, profile_revision_id: str, cases: tuple[dict, ...], *, fetch_odoo=None
    ) -> dict:
        with self.db.read() as conn:
            row = conn.execute(
                select(s.planning_profile_revisions).where(
                    s.planning_profile_revisions.c.id == profile_revision_id
                )
            ).first()
        if row is None:
            raise NexusError("profile_revision_missing", 404)
        config = PlanningProfileConfig.model_validate(
            tuple_json_arrays(dict(row._mapping)["config"])
        )
        results: list[dict] = []
        for case in cases:
            allocation = case.get("allocation", {})
            issue = case.get("jira_issue", {})
            if not isinstance(allocation, dict) or not isinstance(issue, dict):
                raise NexusError("preview_case_invalid", 422)
            route = resolve_route(
                config,
                issue,
                allocated_account_id=str(allocation.get("account_id", "")),
                fetch_odoo=fetch_odoo,
            )
            results.append(
                {
                    "allocation_id": allocation.get("id"),
                    "route": route.model_dump(mode="json"),
                    "effort": _allocation_effort(allocation),
                }
            )
        complete = all(case.get("source_reads_succeeded", True) for case in cases)
        result = {
            "complete": complete,
            "profile_revision_id": profile_revision_id,
            "profile_hash": config.config_hash,
            "case_count": len(results),
            "cases": results,
            "blocked_count": sum(item["route"]["status"] == "blocked" for item in results),
        }
        test_id = self.record_test(
            connection_revision_id=None,
            profile_revision_id=profile_revision_id,
            test_kind="preview",
            status="passed" if complete else "failed",
            config_hash=config.config_hash,
            adapter_build="nexus-profile-router-1",
            result=result,
        )
        result["preview_test_id"] = test_id
        return result

    def activate(
        self,
        profile_revision_id: str,
        actor_id: str,
        *,
        preview_test_id: str,
        require_connection_test: bool = True,
    ) -> dict:
        now = utcnow()
        activation_id = new_id()
        with self.db.write() as conn:
            revision = conn.execute(
                select(s.planning_profile_revisions).where(
                    s.planning_profile_revisions.c.id == profile_revision_id
                )
            ).first()
            if revision is None:
                raise NexusError("profile_revision_missing", 404)
            data = dict(revision._mapping)
            profile = conn.execute(
                select(s.planning_profiles).where(s.planning_profiles.c.id == data["profile_id"])
            ).first()
            profile_data = dict(profile._mapping)
            preview = conn.execute(
                select(s.connection_test_runs).where(
                    s.connection_test_runs.c.id == preview_test_id,
                    s.connection_test_runs.c.profile_revision_id == profile_revision_id,
                    s.connection_test_runs.c.test_kind == "preview",
                    s.connection_test_runs.c.status == "passed",
                    s.connection_test_runs.c.config_hash == data["config_hash"],
                    s.connection_test_runs.c.expires_at > now,
                )
            ).first()
            if preview is None or not dict(preview._mapping)["result"].get("complete"):
                raise NexusError("fresh_complete_preview_required", 409)
            refs = (
                conn.execute(
                    select(s.profile_connections.c.connection_revision_id).where(
                        s.profile_connections.c.profile_revision_id == profile_revision_id
                    )
                )
                .scalars()
                .all()
            )
            if require_connection_test:
                for ref in refs:
                    passed = conn.execute(
                        select(s.connection_test_runs.c.id).where(
                            s.connection_test_runs.c.connection_revision_id == ref,
                            s.connection_test_runs.c.test_kind == "read",
                            s.connection_test_runs.c.status == "passed",
                            s.connection_test_runs.c.expires_at > now,
                        )
                    ).first()
                    if passed is None:
                        raise NexusError("fresh_connection_test_required", 409)
            prior_revision = profile_data["active_revision_id"]
            prior_activation = conn.execute(
                select(s.profile_activations.c.id)
                .where(s.profile_activations.c.profile_id == data["profile_id"])
                .order_by(s.profile_activations.c.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            conn.execute(
                s.planning_profiles.update()
                .where(
                    s.planning_profiles.c.id == data["profile_id"],
                    s.planning_profiles.c.version == profile_data["version"],
                )
                .values(
                    active_revision_id=profile_revision_id,
                    version=profile_data["version"] + 1,
                    updated_at=now,
                )
            )
            evidence = {
                "preview_test_id": preview_test_id,
                "connection_test_revision_ids": refs,
                "profile_hash": data["config_hash"],
                "invalidates_prior_bindings": True,
            }
            conn.execute(
                s.profile_activations.insert().values(
                    id=activation_id,
                    profile_id=data["profile_id"],
                    profile_revision_id=profile_revision_id,
                    actor_id=actor_id,
                    operation="activate",
                    prior_activation_id=prior_activation,
                    evidence=evidence,
                    created_at=now,
                )
            )
            conn.execute(
                s.profile_binding_invalidations.insert().values(
                    id=new_id(),
                    profile_id=data["profile_id"],
                    prior_revision_id=prior_revision,
                    new_revision_id=profile_revision_id,
                    activation_id=activation_id,
                    reason="profile_activation",
                    created_at=now,
                )
            )
            record_event(
                conn,
                "profile.activated",
                activation_id,
                1,
                actor_id,
                new_id(),
                {"profile_revision_id": profile_revision_id, "invalidates_prior_bindings": True},
            )
        return {
            "activation_id": activation_id,
            "profile_revision_id": profile_revision_id,
            "operation": "activate",
            "invalidated_prior_bindings": True,
        }

    def rollback(self, profile_id: str, target_revision_id: str, actor_id: str) -> dict:
        now, activation_id = utcnow(), new_id()
        with self.db.write() as conn:
            profile = conn.execute(
                select(s.planning_profiles).where(s.planning_profiles.c.id == profile_id)
            ).first()
            target = conn.execute(
                select(s.planning_profile_revisions).where(
                    s.planning_profile_revisions.c.id == target_revision_id,
                    s.planning_profile_revisions.c.profile_id == profile_id,
                )
            ).first()
            if profile is None or target is None:
                raise NexusError("rollback_target_missing", 404)
            profile_data, target_data = dict(profile._mapping), dict(target._mapping)
            if profile_data["active_revision_id"] == target_revision_id:
                raise NexusError("rollback_target_already_active", 409)
            prior_activation = conn.execute(
                select(s.profile_activations)
                .where(s.profile_activations.c.profile_id == profile_id)
                .order_by(s.profile_activations.c.created_at.desc())
                .limit(1)
            ).first()
            prior_id = dict(prior_activation._mapping)["id"] if prior_activation else None
            conn.execute(
                s.planning_profiles.update()
                .where(
                    s.planning_profiles.c.id == profile_id,
                    s.planning_profiles.c.version == profile_data["version"],
                )
                .values(
                    active_revision_id=target_revision_id,
                    version=profile_data["version"] + 1,
                    updated_at=now,
                )
            )
            conn.execute(
                s.profile_activations.insert().values(
                    id=activation_id,
                    profile_id=profile_id,
                    profile_revision_id=target_revision_id,
                    actor_id=actor_id,
                    operation="rollback",
                    prior_activation_id=prior_id,
                    evidence={
                        "profile_hash": target_data["config_hash"],
                        "resync_required": True,
                        "invalidates_prior_bindings": True,
                    },
                    created_at=now,
                )
            )
            conn.execute(
                s.profile_binding_invalidations.insert().values(
                    id=new_id(),
                    profile_id=profile_id,
                    prior_revision_id=profile_data["active_revision_id"],
                    new_revision_id=target_revision_id,
                    activation_id=activation_id,
                    reason="profile_rollback",
                    created_at=now,
                )
            )
            record_event(
                conn,
                "profile.rolled_back",
                activation_id,
                1,
                actor_id,
                new_id(),
                {"target_revision_id": target_revision_id, "resync_required": True},
            )
        return {
            "activation_id": activation_id,
            "profile_revision_id": target_revision_id,
            "operation": "rollback",
            "resync_required": True,
            "invalidated_prior_bindings": True,
        }

    def materialize_day(
        self,
        profile_revision_id: str,
        day: date,
        *,
        freshness: dict,
        allocations: tuple[dict, ...],
        schedules: tuple[dict, ...],
    ) -> dict:
        with self.db.read() as conn:
            revision = conn.execute(
                select(s.planning_profile_revisions).where(
                    s.planning_profile_revisions.c.id == profile_revision_id
                )
            ).first()
        if revision is None:
            raise NexusError("profile_revision_missing", 404)
        config = PlanningProfileConfig.model_validate(
            tuple_json_arrays(dict(revision._mapping)["config"])
        )
        entries: list[dict] = []
        for allocation in allocations:
            start = date.fromisoformat(allocation["start_date"])
            end = date.fromisoformat(allocation["end_date_exclusive"])
            if start <= day < end:
                entry = {**allocation, "kind": "capacity", "exact_start": None}
                entries.append(entry)
        for schedule in schedules:
            if schedule.get("cancelled"):
                continue
            if schedule.get("all_day_start"):
                if (
                    date.fromisoformat(schedule["all_day_start"])
                    <= day
                    < date.fromisoformat(schedule["all_day_end_exclusive"])
                ):
                    entries.append({**schedule, "kind": "calendar", "all_day": True})
            else:
                start_utc = datetime.fromisoformat(schedule["start_utc"])
                end_utc = datetime.fromisoformat(schedule["end_utc"])
                local_day = start_utc.astimezone(
                    __import__("zoneinfo").ZoneInfo(config.timezone)
                ).date()
                end_day = (
                    (end_utc - timedelta(microseconds=1))
                    .astimezone(__import__("zoneinfo").ZoneInfo(config.timezone))
                    .date()
                )
                if local_day <= day <= end_day:
                    entries.append({**schedule, "kind": "calendar", "all_day": False})
        entries.sort(
            key=lambda item: (
                0 if item["kind"] == "capacity" else 1,
                str(item.get("start_date", item.get("start_utc", item.get("all_day_start", "")))),
                str(item.get("allocation_id", item.get("uid", ""))),
            )
        )
        fresh = {source: bool(value) for source, value in freshness.items()}
        result = {
            "local_date": day.isoformat(),
            "timezone": config.timezone,
            "profile_revision_id": profile_revision_id,
            "freshness": fresh,
            "status": "fresh" if all(fresh.values()) else "stale",
            "entries": entries,
            "deadlines_are_separate": True,
        }
        generated_at = utcnow()
        with self.db.write() as conn:
            current = conn.execute(
                select(s.daily_views).where(
                    s.daily_views.c.profile_revision_id == profile_revision_id,
                    s.daily_views.c.local_date == day,
                    s.daily_views.c.timezone == config.timezone,
                )
            ).first()
            values = {
                "profile_revision_id": profile_revision_id,
                "local_date": day,
                "timezone": config.timezone,
                "generated_at": generated_at,
                "freshness": fresh,
                "entries": entries,
                "updated_at": generated_at,
            }
            if current:
                row = dict(current._mapping)
                conn.execute(
                    s.daily_views.update()
                    .where(s.daily_views.c.id == row["id"])
                    .values(**values, version=row["version"] + 1)
                )
            else:
                conn.execute(
                    s.daily_views.insert().values(
                        id=new_id(), created_at=generated_at, version=1, **values
                    )
                )
        return result

    def materialize_window(
        self,
        profile_revision_id: str,
        start: date,
        days: int,
        *,
        freshness: dict,
        allocations: tuple[dict, ...],
        schedules: tuple[dict, ...],
    ) -> dict:
        if not 1 <= days <= 60:
            raise NexusError("planning_window_invalid", 422)
        daily = [
            self.materialize_day(
                profile_revision_id,
                start + timedelta(days=offset),
                freshness=freshness,
                allocations=allocations,
                schedules=schedules,
            )
            for offset in range(days)
        ]
        upcoming = []
        carry_over = []
        for entry in (item for day in daily for item in day["entries"]):
            if entry["kind"] == "capacity":
                if date.fromisoformat(entry["start_date"]) < start:
                    carry_over.append(entry)
            elif not entry.get("all_day"):
                if (
                    datetime.fromisoformat(entry["start_utc"])
                    .astimezone(ZoneInfo(daily[0]["timezone"]))
                    .date()
                    > start
                ):
                    upcoming.append(entry)
        carry_over = list({item["allocation_id"]: item for item in carry_over}.values())
        upcoming = list({item.get("uid", item["start_utc"]): item for item in upcoming}.values())
        return {
            "start_date": start.isoformat(),
            "end_date_exclusive": (start + timedelta(days=days)).isoformat(),
            "days": daily,
            "upcoming": sorted(upcoming, key=_planning_order),
            "carry_over": sorted(carry_over, key=_planning_order),
            "status": "fresh" if all(day["status"] == "fresh" for day in daily) else "stale",
        }

    def read_window(self, profile_revision_id: str, start: date, days: int) -> dict:
        if not 1 <= days <= 60:
            raise NexusError("planning_window_invalid", 422)
        end = start + timedelta(days=days)
        with self.db.read() as conn:
            rows = (
                conn.execute(
                    select(s.daily_views)
                    .where(
                        s.daily_views.c.profile_revision_id == profile_revision_id,
                        s.daily_views.c.local_date >= start,
                        s.daily_views.c.local_date < end,
                    )
                    .order_by(s.daily_views.c.local_date)
                )
                .mappings()
                .all()
            )
        if len(rows) != days:
            raise NexusError("planning_window_incomplete", 404)
        daily = []
        for row in rows:
            freshness = {key: bool(value) for key, value in row["freshness"].items()}
            daily.append(
                {
                    "local_date": row["local_date"].isoformat(),
                    "timezone": row["timezone"],
                    "profile_revision_id": profile_revision_id,
                    "status": "fresh" if all(freshness.values()) else "stale",
                    "freshness": freshness,
                    "entries": row["entries"],
                    "deadlines_are_separate": True,
                    "generated_at": row["generated_at"].isoformat(),
                }
            )
        timezone = ZoneInfo(daily[0]["timezone"])
        upcoming = []
        carry_over = []
        for entry in (item for day in daily for item in day["entries"]):
            if entry["kind"] == "capacity" and date.fromisoformat(entry["start_date"]) < start:
                carry_over.append(entry)
            elif entry["kind"] == "calendar" and not entry.get("all_day"):
                local_start = datetime.fromisoformat(entry["start_utc"]).astimezone(timezone)
                if local_start.date() > start:
                    upcoming.append(entry)
        carry_over = list({item["allocation_id"]: item for item in carry_over}.values())
        upcoming = list({item.get("uid", item["start_utc"]): item for item in upcoming}.values())
        return {
            "start_date": start.isoformat(),
            "end_date_exclusive": end.isoformat(),
            "days": daily,
            "upcoming": sorted(upcoming, key=_planning_order),
            "carry_over": sorted(carry_over, key=_planning_order),
            "status": "fresh" if all(day["status"] == "fresh" for day in daily) else "stale",
        }


def _allocation_effort(allocation: dict) -> dict:
    if isinstance(allocation.get("daily_effort"), dict):
        return {"precision": "exact_daily", "daily_effort": allocation["daily_effort"]}
    if isinstance(allocation.get("effort_seconds"), int) and allocation["effort_seconds"] >= 0:
        return {
            "precision": "period_total",
            "total_seconds": allocation["effort_seconds"],
            "daily_seconds": None,
        }
    return {"precision": "date_only", "total_seconds": None, "daily_seconds": None}


class SyncEngine:
    """Bounded page commits; only a complete run advances the successful cursor."""

    def __init__(self, database: Database, max_pages: int = 100):
        if not 1 <= max_pages <= 1000:
            raise ValueError("max_pages must be bounded")
        self.db, self.max_pages = database, max_pages

    def start(self, connection_revision_id: str, stream_key: str, query_hash: str) -> str:
        with self.db.write() as conn:
            revision = conn.execute(
                select(s.connection_revisions).where(
                    s.connection_revisions.c.id == connection_revision_id
                )
            ).first()
            if revision is None:
                raise NexusError("connection_revision_missing", 404)
            revision_data = dict(revision._mapping)
            cursor = conn.execute(
                select(s.source_cursors).where(
                    s.source_cursors.c.source_id == revision_data["source_id"],
                    s.source_cursors.c.stream_key == stream_key,
                )
            ).first()
            cursor_data = dict(cursor._mapping) if cursor else None
            if cursor_data and cursor_data["query_hash"] != query_hash:
                # A changed query is a new stream identity; don't reuse incompatible cursors.
                cursor_before = None
            else:
                cursor_before = cursor_data["cursor"] if cursor_data else None
            generation = (
                conn.execute(
                    sa.select(sa.func.max(s.sync_runs.c.generation)).where(
                        s.sync_runs.c.source_id == revision_data["source_id"]
                    )
                ).scalar_one_or_none()
                or 0
            )
            run_id = new_id()
            conn.execute(
                s.sync_runs.insert().values(
                    id=run_id,
                    source_id=revision_data["source_id"],
                    connection_revision_id=connection_revision_id,
                    generation=generation + 1,
                    status="running",
                    cursor_before=cursor_before,
                    cursor_after=cursor_before,
                    page_count=0,
                    created_at=utcnow(),
                )
            )
        return run_id

    def execute(
        self, run_id: str, stream_key: str, query_hash: str, adapter: SourceAdapter
    ) -> dict:
        with self.db.read() as conn:
            run_row = conn.execute(select(s.sync_runs).where(s.sync_runs.c.id == run_id)).first()
        if run_row is None:
            raise NexusError("sync_run_missing", 404)
        run = dict(run_row._mapping)
        if run["status"] not in {"running", "retry_wait", "failed"}:
            raise NexusError("sync_run_not_resumable", 409)
        if run["retry_at"] is not None and run["retry_at"] > utcnow():
            raise NexusError("source_retry_not_before", 429)
        cursor = run["cursor_after"]
        pages = run["page_count"]
        with self.db.write() as conn:
            conn.execute(
                s.sync_runs.update()
                .where(s.sync_runs.c.id == run_id)
                .values(status="running", error_code=None)
            )
        try:
            while pages < self.max_pages:
                page = adapter.fetch_page(cursor)
                self._apply_page(run, page, pages + 1)
                pages += 1
                cursor = page.next_cursor
                if page.complete:
                    with self.db.write() as conn:
                        conn.execute(
                            s.sync_runs.update()
                            .where(s.sync_runs.c.id == run_id)
                            .values(
                                status="succeeded",
                                cursor_after=cursor,
                                page_count=pages,
                                finished_at=utcnow(),
                            )
                        )
                        conn.execute(
                            sqlite_insert(s.source_cursors)
                            .values(
                                id=new_id(),
                                source_id=run["source_id"],
                                stream_key=stream_key,
                                cursor=cursor,
                                query_hash=query_hash,
                                generation=run["generation"],
                                last_success_at=utcnow(),
                                created_at=utcnow(),
                                updated_at=utcnow(),
                                version=1,
                            )
                            .on_conflict_do_update(
                                index_elements=["source_id", "stream_key"],
                                set_={
                                    "cursor": cursor,
                                    "query_hash": query_hash,
                                    "generation": run["generation"],
                                    "last_success_at": utcnow(),
                                    "updated_at": utcnow(),
                                    "version": s.source_cursors.c.version + 1,
                                },
                            )
                        )
                    return {
                        "run_id": run_id,
                        "status": "succeeded",
                        "page_count": pages,
                        "cursor": cursor,
                    }
                if not page.next_cursor:
                    raise SourceFailure("pagination_cursor_missing", 502)
            raise SourceFailure("sync_page_budget_exceeded", 429)
        except SourceFailure as exc:
            retryable = exc.code in {
                "rate_limited",
                "provider_unavailable",
                "provider_timeout_or_network_error",
            }
            delay = exc.retry_after if exc.retry_after is not None else min(30, 2 ** min(pages, 5))
            with self.db.write() as conn:
                conn.execute(
                    s.sync_runs.update()
                    .where(s.sync_runs.c.id == run_id)
                    .values(
                        status="retry_wait" if retryable else "failed",
                        cursor_after=cursor,
                        page_count=pages,
                        error_code=exc.code,
                        retry_at=utcnow() + timedelta(seconds=delay) if retryable else None,
                        finished_at=utcnow(),
                    )
                )
            raise

    def _apply_page(self, run: dict, page: SourcePage, page_number: int) -> None:
        now = utcnow()
        with self.db.write() as conn:
            existing_page = conn.execute(
                select(s.sync_pages.c.id).where(
                    s.sync_pages.c.sync_run_id == run["id"],
                    s.sync_pages.c.page_key == page.key,
                )
            ).first()
            if existing_page:
                conn.execute(
                    s.sync_runs.update()
                    .where(s.sync_runs.c.id == run["id"])
                    .values(cursor_after=page.next_cursor, page_count=page_number)
                )
                return
            page_hash = canonical_hash([item.raw_hash for item in page.items])
            conn.execute(
                s.sync_pages.insert().values(
                    id=new_id(),
                    sync_run_id=run["id"],
                    page_key=page.key,
                    page_hash=page_hash,
                    next_cursor=page.next_cursor,
                    created_at=now,
                )
            )
            revision_row = conn.execute(
                select(s.connection_revisions.c.source_id).where(
                    s.connection_revisions.c.id == run["connection_revision_id"]
                )
            ).first()
            source_id = revision_row[0]
            for item in page.items:
                row = conn.execute(
                    select(s.external_items).where(
                        s.external_items.c.source_id == source_id,
                        s.external_items.c.remote_type == item.remote_type,
                        s.external_items.c.remote_id == item.remote_id,
                    )
                ).first()
                if row is None:
                    item_id = new_id()
                    conn.execute(
                        s.external_items.insert().values(
                            id=item_id,
                            source_id=source_id,
                            remote_type=item.remote_type,
                            remote_id=item.remote_id,
                            display_key=item.display_key,
                            created_at=now,
                            updated_at=now,
                            version=1,
                        )
                    )
                    revision = 1
                    latest_hash = None
                else:
                    item_data = dict(row._mapping)
                    item_id, latest_hash = item_data["id"], None
                    latest = conn.execute(
                        select(s.external_item_snapshots)
                        .where(s.external_item_snapshots.c.external_item_id == item_id)
                        .order_by(s.external_item_snapshots.c.revision.desc())
                        .limit(1)
                    ).first()
                    latest_data = dict(latest._mapping) if latest else None
                    latest_hash = latest_data["raw_hash"] if latest_data else None
                    revision = (latest_data["revision"] if latest_data else 0) + (
                        latest_hash != item.raw_hash
                    )
                    if item_data["display_key"] != item.display_key:
                        conn.execute(
                            s.external_items.update()
                            .where(s.external_items.c.id == item_id)
                            .values(
                                display_key=item.display_key,
                                updated_at=now,
                                version=item_data["version"] + 1,
                            )
                        )
                snapshot_id = None
                if latest_hash != item.raw_hash:
                    snapshot_id = new_id()
                    conn.execute(
                        s.external_item_snapshots.insert().values(
                            id=snapshot_id,
                            external_item_id=item_id,
                            sync_run_id=run["id"],
                            revision=revision,
                            provider_revision=item.revision,
                            provider_modified_at=item.modified_at,
                            raw_hash=item.raw_hash,
                            normalized=dict(item.normalized),
                            visibility=item.visibility,
                            created_at=now,
                        )
                    )
                if item.remote_type == "tempo.allocation":
                    self._upsert_allocation(conn, item, item_id, snapshot_id, now)
                elif item.remote_type == "ics.event":
                    self._upsert_schedule(conn, item, item_id, now)
            for remote_type, remote_id in page.deleted_items:
                row = conn.execute(
                    select(s.external_items).where(
                        s.external_items.c.source_id == source_id,
                        s.external_items.c.remote_type == remote_type,
                        s.external_items.c.remote_id == remote_id,
                    )
                ).first()
                if row is None:
                    continue
                item_id = dict(row._mapping)["id"]
                latest = (
                    conn.execute(
                        select(s.external_item_snapshots.c.revision)
                        .where(s.external_item_snapshots.c.external_item_id == item_id)
                        .order_by(s.external_item_snapshots.c.revision.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    or 0
                )
                conn.execute(
                    s.external_item_snapshots.insert().values(
                        id=new_id(),
                        external_item_id=item_id,
                        sync_run_id=run["id"],
                        revision=latest + 1,
                        provider_revision="explicit-tombstone",
                        provider_modified_at=None,
                        raw_hash=canonical_hash({"visibility": "deleted", "remote_id": remote_id}),
                        normalized={},
                        visibility="deleted",
                        created_at=now,
                    )
                )
                if remote_type == "tempo.allocation":
                    conn.execute(
                        s.planning_allocations.update()
                        .where(s.planning_allocations.c.external_item_id == item_id)
                        .values(
                            status="deleted",
                            updated_at=now,
                            version=s.planning_allocations.c.version + 1,
                        )
                    )
                elif remote_type == "ics.event":
                    conn.execute(
                        s.schedules.update()
                        .where(s.schedules.c.external_item_id == item_id)
                        .values(
                            cancelled=True,
                            updated_at=now,
                            version=s.schedules.c.version + 1,
                        )
                    )
            conn.execute(
                s.sync_runs.update()
                .where(s.sync_runs.c.id == run["id"])
                .values(cursor_after=page.next_cursor, page_count=page_number)
            )

    @staticmethod
    def _upsert_allocation(
        conn, item: SourceItem, item_id: str, snapshot_id: str | None, now: datetime
    ):
        data = item.normalized
        try:
            start = date.fromisoformat(str(data["start_date"]))
            end = date.fromisoformat(str(data["end_date_exclusive"]))
        except (KeyError, ValueError):
            return
        allocated = conn.execute(
            select(s.planning_allocations).where(
                s.planning_allocations.c.external_item_id == item_id
            )
        ).first()
        values = {
            "external_item_id": item_id,
            "allocated_account_id": str(data.get("account_id") or "unknown"),
            "resource_type": str(data.get("resource_type") or "unknown"),
            "item_kind": "jira_issue"
            if data.get("issue_id")
            else "project"
            if data.get("project_id")
            else "generic",
            "item_id": str(data.get("issue_id") or data.get("project_id") or "") or None,
            "start_date": start,
            "end_date_exclusive": end,
            "timezone": str(data.get("timezone") or "UTC"),
            "native_daily_seconds": data.get("seconds_per_day")
            if isinstance(data.get("seconds_per_day"), int)
            else None,
            "precision": "exact_daily"
            if isinstance(data.get("daily_effort"), dict)
            else "period_total"
            if isinstance(data.get("effort_seconds"), int)
            else "date_only",
            "status": "cancelled"
            if str(data.get("status", "")).lower() == "cancelled"
            else "active",
            "updated_at": now,
        }
        if allocated:
            row = dict(allocated._mapping)
            conn.execute(
                s.planning_allocations.update()
                .where(s.planning_allocations.c.id == row["id"])
                .values(**values, version=row["version"] + 1)
            )
            allocation_id = row["id"]
        else:
            allocation_id = new_id()
            conn.execute(
                s.planning_allocations.insert().values(
                    id=allocation_id, created_at=now, version=1, **values
                )
            )
        daily = data.get("daily_effort")
        conn.execute(
            delete(s.allocation_days).where(s.allocation_days.c.allocation_id == allocation_id)
        )
        if isinstance(daily, dict) and snapshot_id:
            for day_text, seconds in daily.items():
                if not isinstance(seconds, int) or seconds < 0:
                    raise SourceFailure("tempo_effort_invalid", 502)
                local_day = date.fromisoformat(str(day_text))
                present = conn.execute(
                    select(s.allocation_days.c.id).where(
                        s.allocation_days.c.allocation_id == allocation_id,
                        s.allocation_days.c.local_date == local_day,
                    )
                ).first()
                values_day = {
                    "planned_seconds": seconds,
                    "precision": "exact_daily",
                    "snapshot_id": snapshot_id,
                }
                if present:
                    conn.execute(
                        s.allocation_days.update()
                        .where(s.allocation_days.c.id == present[0])
                        .values(**values_day)
                    )
                else:
                    conn.execute(
                        s.allocation_days.insert().values(
                            id=new_id(),
                            allocation_id=allocation_id,
                            local_date=local_day,
                            exact_start=None,
                            created_at=now,
                            **values_day,
                        )
                    )

    @staticmethod
    def _upsert_schedule(conn, item: SourceItem, item_id: str, now: datetime):
        data = item.normalized
        all_day = "all_day_start" in data
        values = {
            "external_item_id": item_id,
            "occurrence_key": str(data["occurrence_key"]),
            "uid": str(data["uid"]),
            "timezone": str(data["timezone"]),
            "cancelled": bool(data.get("cancelled")),
            "revision_hash": item.raw_hash,
            "updated_at": now,
        }
        if all_day:
            values.update(
                all_day_start=date.fromisoformat(str(data["all_day_start"])),
                all_day_end_exclusive=date.fromisoformat(str(data["all_day_end_exclusive"])),
                start_utc=None,
                end_utc=None,
            )
        else:
            values.update(
                start_utc=datetime.fromisoformat(str(data["start_utc"])),
                end_utc=datetime.fromisoformat(str(data["end_utc"])),
                all_day_start=None,
                all_day_end_exclusive=None,
            )
        existing = conn.execute(
            select(s.schedules).where(
                s.schedules.c.external_item_id == item_id,
                s.schedules.c.occurrence_key == str(data["occurrence_key"]),
            )
        ).first()
        if existing:
            row = dict(existing._mapping)
            conn.execute(
                s.schedules.update()
                .where(s.schedules.c.id == row["id"])
                .values(**values, version=row["version"] + 1)
            )
        else:
            conn.execute(
                s.schedules.insert().values(id=new_id(), created_at=now, version=1, **values)
            )
