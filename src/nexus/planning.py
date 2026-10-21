"""Phase 2 typed configuration, activation and restart-safe source sync services."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus import schema as s
from nexus.domain import NexusError, canonical_hash
from nexus.profiles import PlanningProfileConfig, RouteResult, resolve_route
from nexus.schema import new_id, utcnow
from nexus.services import record_event
from nexus.sources import SourceAdapter, SourceFailure, SourceItem, SourcePage
from nexus.storage import Database


def _dict(row: Any) -> dict[str, Any] | None:
    return None if row is None else dict(row._mapping)


class PlanningService:
    def __init__(self, database: Database):
        self.db = database

    def save_connection(self, adapter_id: str, instance_identity: str, config: dict,
                        secret_refs: tuple[str, ...], adapter_build: str) -> dict:
        if config.get("schema_version", 1) != 1 or config.get("adapter_id") != adapter_id:
            raise NexusError("connection_schema_invalid", 422)
        if any(key.lower() in {"token", "password", "secret", "api_key", "authorization"} for key in config):
            raise NexusError("credential_in_configuration", 422)
        if not secret_refs or any(not value.startswith("env:NEXUS_SECRET_") for value in secret_refs):
            raise NexusError("secret_reference_invalid", 422)
        if config.get("secret_ref") not in secret_refs:
            raise NexusError("secret_reference_missing", 422)
        config_hash = canonical_hash(config)
        with self.db.write() as conn:
            source = conn.execute(select(s.external_sources).where(
                s.external_sources.c.adapter_id == adapter_id,
                s.external_sources.c.instance_identity == instance_identity,
            )).first()
            if source is None:
                source_id = new_id()
                conn.execute(s.external_sources.insert().values(
                    id=source_id, adapter_id=adapter_id, instance_identity=instance_identity,
                    config_version=1, config_hash=config_hash, created_at=utcnow(), updated_at=utcnow(), version=1,
                ))
                revision = 1
            else:
                source_data = dict(source._mapping)
                source_id, revision = source_data["id"], source_data["config_version"] + 1
                conn.execute(s.external_sources.update().where(s.external_sources.c.id == source_id).values(
                    config_version=revision, config_hash=config_hash, version=source_data["version"] + 1,
                    updated_at=utcnow(),
                ))
            revision_id = new_id()
            conn.execute(s.connection_revisions.insert().values(
                id=revision_id, source_id=source_id, revision=revision, schema_version=1,
                adapter_build=adapter_build, config=config, secret_refs=list(secret_refs),
                config_hash=config_hash, created_at=utcnow(),
            ))
        return {"source_id": source_id, "connection_revision_id": revision_id,
                "revision": revision, "config_hash": config_hash, "secret_refs": list(secret_refs)}

    def queue_manual_sync(self, actor_id: str, connection_revision_id: str, stream_key: str,
                          query_hash: str, idempotency_key: str) -> dict:
        if not 1 <= len(stream_key) <= 200 or len(query_hash) != 64 or not 1 <= len(idempotency_key) <= 200:
            raise NexusError("sync_request_invalid", 422)
        body = {"connection_revision_id": connection_revision_id, "stream_key": stream_key,
                "query_hash": query_hash}
        request_hash = canonical_hash(body)
        with self.db.write() as conn:
            prior = conn.execute(select(s.manual_sync_requests).where(
                s.manual_sync_requests.c.actor_id == actor_id,
                s.manual_sync_requests.c.idempotency_key == idempotency_key,
            )).first()
            if prior:
                row = dict(prior._mapping)
                if row["request_hash"] != request_hash:
                    raise NexusError("idempotency_conflict", 409)
                return {"request_id": row["id"], "status": row["status"], "sync_run_id": row["sync_run_id"]}
            if conn.execute(select(s.connection_revisions.c.id).where(
                s.connection_revisions.c.id == connection_revision_id
            )).first() is None:
                raise NexusError("connection_revision_missing", 404)
            request_id = new_id()
            conn.execute(s.manual_sync_requests.insert().values(
                id=request_id, connection_revision_id=connection_revision_id, actor_id=actor_id,
                stream_key=stream_key, query_hash=query_hash, idempotency_key=idempotency_key,
                request_hash=request_hash, status="queued", sync_run_id=None, created_at=utcnow(),
            ))
            record_event(conn, "source_sync.queued", request_id, 1, actor_id, new_id(),
                         {"connection_revision_id": connection_revision_id, "stream_key": stream_key})
        return {"request_id": request_id, "status": "queued", "sync_run_id": None}

    def run_manual_sync(self, request_id: str, adapter: SourceAdapter) -> dict:
        with self.db.write() as conn:
            row = conn.execute(select(s.manual_sync_requests).where(
                s.manual_sync_requests.c.id == request_id
            )).first()
            if row is None:
                raise NexusError("sync_request_missing", 404)
            data = dict(row._mapping)
            if data["status"] == "succeeded":
                return {"request_id": request_id, "status": "succeeded", "sync_run_id": data["sync_run_id"]}
            if data["sync_run_id"] is None:
                revision = conn.execute(select(s.connection_revisions).where(
                    s.connection_revisions.c.id == data["connection_revision_id"]
                )).first()
                if revision is None:
                    raise NexusError("connection_revision_missing", 404)
                revision_data = dict(revision._mapping)
                cursor = conn.execute(select(s.source_cursors).where(
                    s.source_cursors.c.source_id == revision_data["source_id"],
                    s.source_cursors.c.stream_key == data["stream_key"],
                )).first()
                cursor_data = dict(cursor._mapping) if cursor else None
                start_cursor = cursor_data["cursor"] if cursor_data and cursor_data["query_hash"] == data["query_hash"] else None
                generation = conn.execute(sa.select(sa.func.max(s.sync_runs.c.generation)).where(
                    s.sync_runs.c.source_id == revision_data["source_id"]
                )).scalar_one_or_none() or 0
                run_id = new_id()
                conn.execute(s.sync_runs.insert().values(
                    id=run_id, source_id=revision_data["source_id"],
                    connection_revision_id=data["connection_revision_id"], generation=generation + 1,
                    status="running", cursor_before=start_cursor, cursor_after=start_cursor,
                    page_count=0, created_at=utcnow(),
                ))
                conn.execute(s.manual_sync_requests.update().where(
                    s.manual_sync_requests.c.id == request_id
                ).values(sync_run_id=run_id))
            else:
                run_id = data["sync_run_id"]
            conn.execute(s.manual_sync_requests.update().where(
                s.manual_sync_requests.c.id == request_id
            ).values(status="running"))
        engine = SyncEngine(self.db)
        try:
            result = engine.execute(run_id, data["stream_key"], data["query_hash"], adapter)
        except SourceFailure:
            with self.db.write() as conn:
                conn.execute(s.manual_sync_requests.update().where(
                    s.manual_sync_requests.c.id == request_id
                ).values(status="failed"))
            raise
        with self.db.write() as conn:
            conn.execute(s.manual_sync_requests.update().where(
                s.manual_sync_requests.c.id == request_id
            ).values(status="succeeded"))
        return {"request_id": request_id, **result}

    def save_profile(self, config: PlanningProfileConfig) -> dict:
        payload = config.model_dump(mode="json")
        digest = config.config_hash
        with self.db.write() as conn:
            profile = conn.execute(select(s.planning_profiles).where(
                s.planning_profiles.c.slug == config.slug
            )).first()
            if profile is None:
                profile_id, revision = new_id(), 1
                conn.execute(s.planning_profiles.insert().values(
                    id=profile_id, slug=config.slug, active_revision_id=None,
                    created_at=utcnow(), updated_at=utcnow(), version=1,
                ))
            else:
                profile_data = dict(profile._mapping)
                profile_id = profile_data["id"]
                latest = conn.execute(sa.select(sa.func.max(s.planning_profile_revisions.c.revision)).where(
                    s.planning_profile_revisions.c.profile_id == profile_id
                )).scalar_one_or_none()
                revision = (latest or 0) + 1
            expected_revisions = {
                config.schedule_connection_revision_id,
                config.jira_connection_revision_id,
                *config.odoo_connection_revision_ids,
                *config.optional_calendar_connection_revision_ids,
            }
            found_revisions = set(conn.execute(select(s.connection_revisions.c.id).where(
                s.connection_revisions.c.id.in_(expected_revisions)
            )).scalars().all()) if expected_revisions else set()
            if found_revisions != expected_revisions:
                raise NexusError("profile_connection_revision_missing", 422)
            revision_configs = {
                row["id"]: row["config"] for row in conn.execute(select(
                    s.connection_revisions.c.id, s.connection_revisions.c.config
                ).where(s.connection_revisions.c.id.in_(expected_revisions))).mappings().all()
            }
            schedule_config = revision_configs[config.schedule_connection_revision_id]
            jira_config = revision_configs[config.jira_connection_revision_id]
            if (schedule_config.get("adapter_id") != "tempo-cloud-planner-v1"
                    or schedule_config.get("allocated_account_id") != config.allocated_account_id):
                raise NexusError("schedule_authority_or_account_mismatch", 422)
            if jira_config.get("adapter_id") != "jira-cloud-v1":
                raise NexusError("jira_work_item_connection_required", 422)
            for instance in config.odoo_instances:
                connection_config = revision_configs.get(instance.connection_revision_id, {})
                configured_host = urlsplit(str(connection_config.get("base_url", ""))).hostname
                if (connection_config.get("adapter_id") not in {
                            "odoo-17-read-v1", "odoo-18-read-v1", "odoo-19-read-v1"}
                        or connection_config.get("database") != instance.database
                        or configured_host != instance.host):
                    raise NexusError("odoo_instance_mapping_mismatch", 422)
            revision_id = new_id()
            conn.execute(s.planning_profile_revisions.insert().values(
                id=revision_id, profile_id=profile_id, revision=revision, schema_version=1,
                config=payload, config_hash=digest, created_at=utcnow(),
            ))
            conn.execute(s.profile_connections.insert().values(
                id=new_id(), profile_revision_id=revision_id,
                connection_revision_id=config.schedule_connection_revision_id, role="schedule", created_at=utcnow(),
            ))
            conn.execute(s.profile_connections.insert().values(
                id=new_id(), profile_revision_id=revision_id,
                connection_revision_id=config.jira_connection_revision_id, role="work_items", created_at=utcnow(),
            ))
            for ref in config.odoo_connection_revision_ids:
                conn.execute(s.profile_connections.insert().values(
                    id=new_id(), profile_revision_id=revision_id, connection_revision_id=ref,
                    role="requirements", created_at=utcnow(),
                ))
            for ref in config.optional_calendar_connection_revision_ids:
                conn.execute(s.profile_connections.insert().values(
                    id=new_id(), profile_revision_id=revision_id, connection_revision_id=ref,
                    role="context_calendar", created_at=utcnow(),
                ))
        return {"profile_id": profile_id, "profile_revision_id": revision_id,
                "revision": revision, "config_hash": digest}

    def record_test(self, *, connection_revision_id: str | None, profile_revision_id: str | None,
                    test_kind: str, status: str, config_hash: str, adapter_build: str,
                    result: dict, ttl_seconds: int = 900) -> str:
        if status not in {"passed", "failed", "blocked"} or test_kind not in {"discovery", "read", "preview"}:
            raise NexusError("test_record_invalid", 422)
        run_id = new_id()
        with self.db.write() as conn:
            conn.execute(s.connection_test_runs.insert().values(
                id=run_id, connection_revision_id=connection_revision_id,
                profile_revision_id=profile_revision_id, test_kind=test_kind, status=status,
                config_hash=config_hash, adapter_build=adapter_build,
                result=result, expires_at=utcnow() + timedelta(seconds=ttl_seconds), created_at=utcnow(),
            ))
        return run_id

    def preview(self, profile_revision_id: str, cases: tuple[dict, ...], *, fetch_odoo=None) -> dict:
        with self.db.read() as conn:
            row = conn.execute(select(s.planning_profile_revisions).where(
                s.planning_profile_revisions.c.id == profile_revision_id
            )).first()
        if row is None:
            raise NexusError("profile_revision_missing", 404)
        config = PlanningProfileConfig.model_validate(dict(row._mapping)["config"])
        results: list[dict] = []
        for case in cases:
            allocation = case.get("allocation", {})
            issue = case.get("jira_issue", {})
            if not isinstance(allocation, dict) or not isinstance(issue, dict):
                raise NexusError("preview_case_invalid", 422)
            route = resolve_route(config, issue, allocated_account_id=str(allocation.get("account_id", "")),
                                  fetch_odoo=fetch_odoo)
            results.append({"allocation_id": allocation.get("id"), "route": route.model_dump(mode="json"),
                            "effort": _allocation_effort(allocation)})
        complete = all(case.get("source_reads_succeeded", True) for case in cases)
        result = {"complete": complete, "profile_revision_id": profile_revision_id,
                  "profile_hash": config.config_hash, "case_count": len(results), "cases": results,
                  "blocked_count": sum(item["route"]["status"] == "blocked" for item in results)}
        test_id = self.record_test(connection_revision_id=None, profile_revision_id=profile_revision_id,
                                   test_kind="preview", status="passed" if complete else "failed",
                                   config_hash=config.config_hash, adapter_build="nexus-profile-router-1",
                                   result=result)
        result["preview_test_id"] = test_id
        return result

    def activate(self, profile_revision_id: str, actor_id: str, *, preview_test_id: str,
                 require_connection_test: bool = True) -> dict:
        now = utcnow()
        activation_id = new_id()
        with self.db.write() as conn:
            revision = conn.execute(select(s.planning_profile_revisions).where(
                s.planning_profile_revisions.c.id == profile_revision_id
            )).first()
            if revision is None:
                raise NexusError("profile_revision_missing", 404)
            data = dict(revision._mapping)
            profile = conn.execute(select(s.planning_profiles).where(
                s.planning_profiles.c.id == data["profile_id"]
            )).first()
            profile_data = dict(profile._mapping)
            preview = conn.execute(select(s.connection_test_runs).where(
                s.connection_test_runs.c.id == preview_test_id,
                s.connection_test_runs.c.profile_revision_id == profile_revision_id,
                s.connection_test_runs.c.test_kind == "preview",
                s.connection_test_runs.c.status == "passed",
                s.connection_test_runs.c.config_hash == data["config_hash"],
                s.connection_test_runs.c.expires_at > now,
            )).first()
            if preview is None or not dict(preview._mapping)["result"].get("complete"):
                raise NexusError("fresh_complete_preview_required", 409)
            refs = conn.execute(select(s.profile_connections.c.connection_revision_id).where(
                s.profile_connections.c.profile_revision_id == profile_revision_id
            )).scalars().all()
            if require_connection_test:
                for ref in refs:
                    passed = conn.execute(select(s.connection_test_runs.c.id).where(
                        s.connection_test_runs.c.connection_revision_id == ref,
                        s.connection_test_runs.c.test_kind == "read",
                        s.connection_test_runs.c.status == "passed",
                        s.connection_test_runs.c.expires_at > now,
                    )).first()
                    if passed is None:
                        raise NexusError("fresh_connection_test_required", 409)
            prior_revision = profile_data["active_revision_id"]
            prior_activation = conn.execute(select(s.profile_activations.c.id).where(
                s.profile_activations.c.profile_id == data["profile_id"]
            ).order_by(s.profile_activations.c.created_at.desc()).limit(1)).scalar_one_or_none()
            conn.execute(s.planning_profiles.update().where(
                s.planning_profiles.c.id == data["profile_id"],
                s.planning_profiles.c.version == profile_data["version"],
            ).values(active_revision_id=profile_revision_id, version=profile_data["version"] + 1,
                     updated_at=now))
            evidence = {"preview_test_id": preview_test_id, "connection_test_revision_ids": refs,
                        "profile_hash": data["config_hash"], "invalidates_prior_bindings": True}
            conn.execute(s.profile_activations.insert().values(
                id=activation_id, profile_id=data["profile_id"], profile_revision_id=profile_revision_id,
                actor_id=actor_id, operation="activate", prior_activation_id=prior_activation,
                evidence=evidence, created_at=now,
            ))
            conn.execute(s.profile_binding_invalidations.insert().values(
                id=new_id(), profile_id=data["profile_id"], prior_revision_id=prior_revision,
                new_revision_id=profile_revision_id, activation_id=activation_id,
                reason="profile_activation", created_at=now,
            ))
            record_event(conn, "profile.activated", activation_id, 1, actor_id, new_id(),
                         {"profile_revision_id": profile_revision_id, "invalidates_prior_bindings": True})
        return {"activation_id": activation_id, "profile_revision_id": profile_revision_id,
                "operation": "activate", "invalidated_prior_bindings": True}

    def rollback(self, profile_id: str, target_revision_id: str, actor_id: str) -> dict:
        now, activation_id = utcnow(), new_id()
        with self.db.write() as conn:
            profile = conn.execute(select(s.planning_profiles).where(s.planning_profiles.c.id == profile_id)).first()
            target = conn.execute(select(s.planning_profile_revisions).where(
                s.planning_profile_revisions.c.id == target_revision_id,
                s.planning_profile_revisions.c.profile_id == profile_id,
            )).first()
            if profile is None or target is None:
                raise NexusError("rollback_target_missing", 404)
            profile_data, target_data = dict(profile._mapping), dict(target._mapping)
            if profile_data["active_revision_id"] == target_revision_id:
                raise NexusError("rollback_target_already_active", 409)
            prior_activation = conn.execute(select(s.profile_activations).where(
                s.profile_activations.c.profile_id == profile_id
            ).order_by(s.profile_activations.c.created_at.desc()).limit(1)).first()
            prior_id = dict(prior_activation._mapping)["id"] if prior_activation else None
            conn.execute(s.planning_profiles.update().where(
                s.planning_profiles.c.id == profile_id,
                s.planning_profiles.c.version == profile_data["version"],
            ).values(active_revision_id=target_revision_id, version=profile_data["version"] + 1,
                     updated_at=now))
            conn.execute(s.profile_activations.insert().values(
                id=activation_id, profile_id=profile_id, profile_revision_id=target_revision_id,
                actor_id=actor_id, operation="rollback", prior_activation_id=prior_id,
                evidence={"profile_hash": target_data["config_hash"], "resync_required": True,
                          "invalidates_prior_bindings": True}, created_at=now,
            ))
            conn.execute(s.profile_binding_invalidations.insert().values(
                id=new_id(), profile_id=profile_id, prior_revision_id=profile_data["active_revision_id"],
                new_revision_id=target_revision_id, activation_id=activation_id,
                reason="profile_rollback", created_at=now,
            ))
            record_event(conn, "profile.rolled_back", activation_id, 1, actor_id, new_id(),
                         {"target_revision_id": target_revision_id, "resync_required": True})
        return {"activation_id": activation_id, "profile_revision_id": target_revision_id,
                "operation": "rollback", "resync_required": True, "invalidated_prior_bindings": True}

    def materialize_day(self, profile_revision_id: str, day: date, *, freshness: dict,
                        allocations: tuple[dict, ...], schedules: tuple[dict, ...]) -> dict:
        with self.db.read() as conn:
            revision = conn.execute(select(s.planning_profile_revisions).where(
                s.planning_profile_revisions.c.id == profile_revision_id
            )).first()
        if revision is None:
            raise NexusError("profile_revision_missing", 404)
        config = PlanningProfileConfig.model_validate(dict(revision._mapping)["config"])
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
                if date.fromisoformat(schedule["all_day_start"]) <= day < date.fromisoformat(schedule["all_day_end_exclusive"]):
                    entries.append({**schedule, "kind": "calendar", "all_day": True})
            else:
                start_utc = datetime.fromisoformat(schedule["start_utc"])
                end_utc = datetime.fromisoformat(schedule["end_utc"])
                local_day = start_utc.astimezone(__import__("zoneinfo").ZoneInfo(config.timezone)).date()
                end_day = (end_utc - timedelta(microseconds=1)).astimezone(__import__("zoneinfo").ZoneInfo(config.timezone)).date()
                if local_day <= day <= end_day:
                    entries.append({**schedule, "kind": "calendar", "all_day": False})
        entries.sort(key=lambda item: (0 if item["kind"] == "capacity" else 1,
                                       str(item.get("start_date", item.get("start_utc", item.get("all_day_start", "")))),
                                       str(item.get("allocation_id", item.get("uid", "")))))
        fresh = {source: bool(value) for source, value in freshness.items()}
        result = {"local_date": day.isoformat(), "timezone": config.timezone,
                  "profile_revision_id": profile_revision_id, "freshness": fresh,
                  "status": "fresh" if all(fresh.values()) else "stale", "entries": entries,
                  "deadlines_are_separate": True}
        with self.db.write() as conn:
            current = conn.execute(select(s.daily_views).where(
                s.daily_views.c.profile_revision_id == profile_revision_id,
                s.daily_views.c.local_date == day,
                s.daily_views.c.timezone == config.timezone,
            )).first()
            values = {"profile_revision_id": profile_revision_id, "local_date": day,
                      "timezone": config.timezone, "generated_at": utcnow(), "freshness": fresh,
                      "entries": entries, "updated_at": utcnow()}
            if current:
                row = dict(current._mapping)
                conn.execute(s.daily_views.update().where(s.daily_views.c.id == row["id"]).values(
                    **values, version=row["version"] + 1))
            else:
                conn.execute(s.daily_views.insert().values(id=new_id(), created_at=utcnow(), version=1, **values))
        return result


def _allocation_effort(allocation: dict) -> dict:
    if isinstance(allocation.get("daily_effort"), dict):
        return {"precision": "exact_daily", "daily_effort": allocation["daily_effort"]}
    if isinstance(allocation.get("effort_seconds"), int) and allocation["effort_seconds"] >= 0:
        return {"precision": "period_total", "total_seconds": allocation["effort_seconds"], "daily_seconds": None}
    return {"precision": "date_only", "total_seconds": None, "daily_seconds": None}


class SyncEngine:
    """Bounded page commits; only a complete run advances the successful cursor."""

    def __init__(self, database: Database, max_pages: int = 100):
        if not 1 <= max_pages <= 1000:
            raise ValueError("max_pages must be bounded")
        self.db, self.max_pages = database, max_pages

    def start(self, connection_revision_id: str, stream_key: str, query_hash: str) -> str:
        with self.db.write() as conn:
            revision = conn.execute(select(s.connection_revisions).where(
                s.connection_revisions.c.id == connection_revision_id
            )).first()
            if revision is None:
                raise NexusError("connection_revision_missing", 404)
            revision_data = dict(revision._mapping)
            cursor = conn.execute(select(s.source_cursors).where(
                s.source_cursors.c.source_id == revision_data["source_id"],
                s.source_cursors.c.stream_key == stream_key,
            )).first()
            cursor_data = dict(cursor._mapping) if cursor else None
            if cursor_data and cursor_data["query_hash"] != query_hash:
                # A changed query is a new stream identity; don't reuse incompatible cursors.
                cursor_before = None
            else:
                cursor_before = cursor_data["cursor"] if cursor_data else None
            generation = conn.execute(sa.select(sa.func.max(s.sync_runs.c.generation)).where(
                s.sync_runs.c.source_id == revision_data["source_id"]
            )).scalar_one_or_none() or 0
            run_id = new_id()
            conn.execute(s.sync_runs.insert().values(
                id=run_id, source_id=revision_data["source_id"], connection_revision_id=connection_revision_id,
                generation=generation + 1, status="running", cursor_before=cursor_before,
                cursor_after=cursor_before, page_count=0, created_at=utcnow(),
            ))
        return run_id

    def execute(self, run_id: str, stream_key: str, query_hash: str, adapter: SourceAdapter) -> dict:
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
            conn.execute(s.sync_runs.update().where(s.sync_runs.c.id == run_id).values(status="running", error_code=None))
        try:
            while pages < self.max_pages:
                page = adapter.fetch_page(cursor)
                self._apply_page(run, page, pages + 1)
                pages += 1
                cursor = page.next_cursor
                if page.complete:
                    with self.db.write() as conn:
                        conn.execute(s.sync_runs.update().where(s.sync_runs.c.id == run_id).values(
                            status="succeeded", cursor_after=cursor, page_count=pages, finished_at=utcnow()))
                        conn.execute(sqlite_insert(s.source_cursors).values(
                            id=new_id(), source_id=run["source_id"], stream_key=stream_key,
                            cursor=cursor, query_hash=query_hash, generation=run["generation"],
                            last_success_at=utcnow(), created_at=utcnow(), updated_at=utcnow(), version=1,
                        ).on_conflict_do_update(index_elements=["source_id", "stream_key"], set_={
                            "cursor": cursor, "query_hash": query_hash, "generation": run["generation"],
                            "last_success_at": utcnow(), "updated_at": utcnow(),
                            "version": s.source_cursors.c.version + 1,
                        }))
                    return {"run_id": run_id, "status": "succeeded", "page_count": pages, "cursor": cursor}
                if not page.next_cursor:
                    raise SourceFailure("pagination_cursor_missing", 502)
            raise SourceFailure("sync_page_budget_exceeded", 429)
        except SourceFailure as exc:
            retryable = exc.code in {"rate_limited", "provider_unavailable", "provider_timeout_or_network_error"}
            delay = exc.retry_after if exc.retry_after is not None else min(30, 2 ** min(pages, 5))
            with self.db.write() as conn:
                conn.execute(s.sync_runs.update().where(s.sync_runs.c.id == run_id).values(
                    status="retry_wait" if retryable else "failed", cursor_after=cursor,
                    page_count=pages, error_code=exc.code,
                    retry_at=utcnow() + timedelta(seconds=delay) if retryable else None,
                    finished_at=utcnow()))
            raise

    def _apply_page(self, run: dict, page: SourcePage, page_number: int) -> None:
        now = utcnow()
        with self.db.write() as conn:
            existing_page = conn.execute(select(s.sync_pages.c.id).where(
                s.sync_pages.c.sync_run_id == run["id"], s.sync_pages.c.page_key == page.key,
            )).first()
            if existing_page:
                conn.execute(s.sync_runs.update().where(s.sync_runs.c.id == run["id"]).values(
                    cursor_after=page.next_cursor, page_count=page_number))
                return
            page_hash = canonical_hash([item.raw_hash for item in page.items])
            conn.execute(s.sync_pages.insert().values(
                id=new_id(), sync_run_id=run["id"], page_key=page.key, page_hash=page_hash,
                next_cursor=page.next_cursor, created_at=now,
            ))
            revision_row = conn.execute(select(s.connection_revisions.c.source_id).where(
                s.connection_revisions.c.id == run["connection_revision_id"]
            )).first()
            source_id = revision_row[0]
            for item in page.items:
                row = conn.execute(select(s.external_items).where(
                    s.external_items.c.source_id == source_id,
                    s.external_items.c.remote_type == item.remote_type,
                    s.external_items.c.remote_id == item.remote_id,
                )).first()
                if row is None:
                    item_id = new_id()
                    conn.execute(s.external_items.insert().values(
                        id=item_id, source_id=source_id, remote_type=item.remote_type,
                        remote_id=item.remote_id, display_key=item.display_key,
                        created_at=now, updated_at=now, version=1,
                    ))
                    revision = 1
                    latest_hash = None
                else:
                    item_data = dict(row._mapping)
                    item_id, latest_hash = item_data["id"], None
                    latest = conn.execute(select(s.external_item_snapshots).where(
                        s.external_item_snapshots.c.external_item_id == item_id
                    ).order_by(s.external_item_snapshots.c.revision.desc()).limit(1)).first()
                    latest_data = dict(latest._mapping) if latest else None
                    latest_hash = latest_data["raw_hash"] if latest_data else None
                    revision = (latest_data["revision"] if latest_data else 0) + (latest_hash != item.raw_hash)
                    if item_data["display_key"] != item.display_key:
                        conn.execute(s.external_items.update().where(s.external_items.c.id == item_id).values(
                            display_key=item.display_key, updated_at=now, version=item_data["version"] + 1))
                snapshot_id = None
                if latest_hash != item.raw_hash:
                    snapshot_id = new_id()
                    conn.execute(s.external_item_snapshots.insert().values(
                        id=snapshot_id, external_item_id=item_id, sync_run_id=run["id"],
                        revision=revision, provider_revision=item.revision, provider_modified_at=item.modified_at,
                        raw_hash=item.raw_hash, normalized=dict(item.normalized), visibility=item.visibility,
                        created_at=now,
                    ))
                if item.remote_type == "tempo.allocation":
                    self._upsert_allocation(conn, item, item_id, snapshot_id, now)
            for remote_type, remote_id in page.deleted_items:
                row = conn.execute(select(s.external_items).where(
                    s.external_items.c.source_id == source_id,
                    s.external_items.c.remote_type == remote_type,
                    s.external_items.c.remote_id == remote_id,
                )).first()
                if row is None:
                    continue
                item_id = dict(row._mapping)["id"]
                latest = conn.execute(select(s.external_item_snapshots.c.revision).where(
                    s.external_item_snapshots.c.external_item_id == item_id
                ).order_by(s.external_item_snapshots.c.revision.desc()).limit(1)).scalar_one_or_none() or 0
                conn.execute(s.external_item_snapshots.insert().values(
                    id=new_id(), external_item_id=item_id, sync_run_id=run["id"], revision=latest + 1,
                    provider_revision="explicit-tombstone", provider_modified_at=None,
                    raw_hash=canonical_hash({"visibility": "deleted", "remote_id": remote_id}),
                    normalized={}, visibility="deleted", created_at=now,
                ))
                if remote_type == "tempo.allocation":
                    conn.execute(s.planning_allocations.update().where(
                        s.planning_allocations.c.external_item_id == item_id
                    ).values(status="deleted", updated_at=now,
                             version=s.planning_allocations.c.version + 1))
            conn.execute(s.sync_runs.update().where(s.sync_runs.c.id == run["id"]).values(
                cursor_after=page.next_cursor, page_count=page_number))

    @staticmethod
    def _upsert_allocation(conn, item: SourceItem, item_id: str, snapshot_id: str | None, now: datetime):
        data = item.normalized
        try:
            start = date.fromisoformat(str(data["start_date"]))
            end = date.fromisoformat(str(data["end_date_exclusive"]))
        except (KeyError, ValueError):
            return
        allocated = conn.execute(select(s.planning_allocations).where(
            s.planning_allocations.c.external_item_id == item_id
        )).first()
        values = {"external_item_id": item_id, "allocated_account_id": str(data.get("account_id") or "unknown"),
                  "resource_type": str(data.get("resource_type") or "unknown"),
                  "item_kind": "jira_issue" if data.get("issue_id") else "project" if data.get("project_id") else "generic",
                  "item_id": str(data.get("issue_id") or data.get("project_id") or "") or None,
                  "start_date": start, "end_date_exclusive": end, "timezone": str(data.get("timezone") or "UTC"),
                  "native_daily_seconds": data.get("seconds_per_day") if isinstance(data.get("seconds_per_day"), int) else None,
                  "precision": "exact_daily" if isinstance(data.get("daily_effort"), dict) else "period_total" if isinstance(data.get("effort_seconds"), int) else "date_only",
                  "status": "cancelled" if str(data.get("status", "")).lower() == "cancelled" else "active",
                  "updated_at": now}
        if allocated:
            row = dict(allocated._mapping)
            conn.execute(s.planning_allocations.update().where(s.planning_allocations.c.id == row["id"]).values(
                **values, version=row["version"] + 1))
            allocation_id = row["id"]
        else:
            allocation_id = new_id()
            conn.execute(s.planning_allocations.insert().values(id=allocation_id, created_at=now, version=1, **values))
        daily = data.get("daily_effort")
        conn.execute(delete(s.allocation_days).where(s.allocation_days.c.allocation_id == allocation_id))
        if isinstance(daily, dict) and snapshot_id:
            for day_text, seconds in daily.items():
                if not isinstance(seconds, int) or seconds < 0:
                    raise SourceFailure("tempo_effort_invalid", 502)
                local_day = date.fromisoformat(str(day_text))
                present = conn.execute(select(s.allocation_days.c.id).where(
                    s.allocation_days.c.allocation_id == allocation_id,
                    s.allocation_days.c.local_date == local_day,
                )).first()
                values_day = {"planned_seconds": seconds, "precision": "exact_daily", "snapshot_id": snapshot_id}
                if present:
                    conn.execute(s.allocation_days.update().where(s.allocation_days.c.id == present[0]).values(**values_day))
                else:
                    conn.execute(s.allocation_days.insert().values(id=new_id(), allocation_id=allocation_id,
                        local_date=local_day, exact_start=None, created_at=now, **values_day))
