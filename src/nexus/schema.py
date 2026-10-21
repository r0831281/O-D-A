"""Phase 1 persistence contracts; domain policy lives in application services."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Canonical UTC text on SQLite; refuse ambiguous naive instants."""

    impl = sa.String(27)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware UTC instant is required")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def process_result_value(self, value: str | None, dialect):
        return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def identity_columns():
    return [sa.Column("id", sa.String(36), primary_key=True, default=new_id)]


def mutable_columns():
    return [
        *identity_columns(),
        sa.Column("created_at", UTCDateTime(), nullable=False, default=utcnow),
        sa.Column("updated_at", UTCDateTime(), nullable=False, default=utcnow),
        sa.Column("version", sa.Integer, nullable=False, default=1),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    ]


def immutable_columns():
    return [
        *identity_columns(),
        sa.Column("created_at", UTCDateTime(), nullable=False, default=utcnow),
    ]


users = sa.Table(
    "users",
    metadata,
    *mutable_columns(),
    sa.Column("identity", sa.String(128), nullable=False, unique=True),
    sa.Column("display_name", sa.String(256), nullable=False),
    sa.Column(
        "active",
        sa.Boolean(name="boolean_value", create_constraint=True),
        nullable=False,
        default=True,
    ),
    sa.CheckConstraint("length(identity) > 0", name="nonempty_identity"),
)
projects = sa.Table(
    "projects",
    metadata,
    *mutable_columns(),
    sa.Column("slug", sa.String(128), nullable=False, unique=True),
    sa.Column("name", sa.String(256), nullable=False),
    sa.Column("timezone", sa.String(128), nullable=False, default="Europe/Brussels"),
    sa.Column("config", sa.JSON, nullable=False, default=dict),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.CheckConstraint("length(slug) > 0", name="nonempty_slug"),
    sa.CheckConstraint("length(config_hash) = 64", name="hash_length"),
)
repositories = sa.Table(
    "repositories",
    metadata,
    *mutable_columns(),
    sa.Column("canonical_root", sa.Text, nullable=False, unique=True),
    sa.Column("origin_identity", sa.Text, nullable=False),
    sa.Column("default_branch", sa.String(256), nullable=False),
    sa.Column(
        "enabled",
        sa.Boolean(name="boolean_value", create_constraint=True),
        nullable=False,
        default=False,
    ),
)
project_repositories = sa.Table(
    "project_repositories",
    metadata,
    *mutable_columns(),
    sa.Column("project_id", sa.ForeignKey("projects.id"), nullable=False, index=True),
    sa.Column("repository_id", sa.ForeignKey("repositories.id"), nullable=False, index=True),
    sa.Column("role", sa.String(128), nullable=False),
    sa.Column("branch", sa.String(256), nullable=False),
    sa.UniqueConstraint("project_id", "repository_id", "role"),
)
external_sources = sa.Table(
    "external_sources",
    metadata,
    *mutable_columns(),
    sa.Column("adapter_id", sa.String(128), nullable=False),
    sa.Column("instance_identity", sa.String(512), nullable=False),
    sa.Column("config_version", sa.Integer, nullable=False, default=1),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("adapter_id", "instance_identity"),
    sa.CheckConstraint("config_version = 1", name="supported_config_version"),
    sa.CheckConstraint("length(config_hash) = 64", name="hash_length"),
    sa.CheckConstraint(
        "length(adapter_id) > 0 AND length(instance_identity) > 0", name="nonempty_identity"
    ),
)
external_items = sa.Table(
    "external_items",
    metadata,
    *mutable_columns(),
    sa.Column("source_id", sa.ForeignKey("external_sources.id"), nullable=False, index=True),
    sa.Column("remote_type", sa.String(128), nullable=False),
    sa.Column("remote_id", sa.String(512), nullable=False),
    sa.Column("display_key", sa.String(512), nullable=False),
    sa.UniqueConstraint("source_id", "remote_type", "remote_id"),
    sa.CheckConstraint(
        "length(remote_type) > 0 AND length(remote_id) > 0", name="nonempty_identity"
    ),
)

# Phase 2 source, connection and planning-profile state. Revisions and evidence
# are append-only; active pointers are projections that may be changed by an
# explicit local operator command.
connection_revisions = sa.Table(
    "connection_revisions",
    metadata,
    *immutable_columns(),
    sa.Column("source_id", sa.ForeignKey("external_sources.id"), nullable=False, index=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("adapter_build", sa.String(128), nullable=False),
    sa.Column("config", sa.JSON, nullable=False),
    sa.Column("secret_refs", sa.JSON, nullable=False),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("source_id", "revision"),
    sa.CheckConstraint("revision >= 1 AND schema_version = 1", name="revision_schema"),
    sa.CheckConstraint("length(config_hash) = 64", name="config_hash_length"),
)
planning_profiles = sa.Table(
    "planning_profiles",
    metadata,
    *mutable_columns(),
    sa.Column("slug", sa.String(128), nullable=False, unique=True),
    sa.Column("active_revision_id", sa.ForeignKey("planning_profile_revisions.id")),
)
planning_profile_revisions = sa.Table(
    "planning_profile_revisions",
    metadata,
    *immutable_columns(),
    sa.Column("profile_id", sa.ForeignKey("planning_profiles.id"), nullable=False, index=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("config", sa.JSON, nullable=False),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("profile_id", "revision"),
    sa.CheckConstraint("revision >= 1 AND schema_version = 1", name="revision_schema"),
    sa.CheckConstraint("length(config_hash) = 64", name="config_hash_length"),
)
profile_connections = sa.Table(
    "profile_connections",
    metadata,
    *immutable_columns(),
    sa.Column(
        "profile_revision_id", sa.ForeignKey("planning_profile_revisions.id"), nullable=False
    ),
    sa.Column("connection_revision_id", sa.ForeignKey("connection_revisions.id"), nullable=False),
    sa.Column("role", sa.String(40), nullable=False),
    sa.UniqueConstraint("profile_revision_id", "connection_revision_id", "role"),
    sa.CheckConstraint(
        "role IN ('schedule','context_calendar','work_items','requirements')", name="known_role"
    ),
)
connection_test_runs = sa.Table(
    "connection_test_runs",
    metadata,
    *immutable_columns(),
    sa.Column("connection_revision_id", sa.ForeignKey("connection_revisions.id"), index=True),
    sa.Column("profile_revision_id", sa.ForeignKey("planning_profile_revisions.id"), index=True),
    sa.Column("test_kind", sa.String(40), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.Column("adapter_build", sa.String(128), nullable=False),
    sa.Column("result", sa.JSON, nullable=False),
    sa.Column("expires_at", UTCDateTime(), nullable=False),
    sa.CheckConstraint("status IN ('passed','failed','blocked')", name="known_status"),
)
profile_activations = sa.Table(
    "profile_activations",
    metadata,
    *immutable_columns(),
    sa.Column("profile_id", sa.ForeignKey("planning_profiles.id"), nullable=False, index=True),
    sa.Column(
        "profile_revision_id", sa.ForeignKey("planning_profile_revisions.id"), nullable=False
    ),
    sa.Column("actor_id", sa.ForeignKey("users.id"), nullable=False),
    sa.Column("operation", sa.String(16), nullable=False),
    sa.Column("prior_activation_id", sa.ForeignKey("profile_activations.id")),
    sa.Column("evidence", sa.JSON, nullable=False),
    sa.CheckConstraint("operation IN ('activate','rollback')", name="known_operation"),
)
profile_binding_invalidations = sa.Table(
    "profile_binding_invalidations",
    metadata,
    *immutable_columns(),
    sa.Column("profile_id", sa.ForeignKey("planning_profiles.id"), nullable=False, index=True),
    sa.Column("prior_revision_id", sa.ForeignKey("planning_profile_revisions.id")),
    sa.Column("new_revision_id", sa.ForeignKey("planning_profile_revisions.id"), nullable=False),
    sa.Column(
        "activation_id", sa.ForeignKey("profile_activations.id"), nullable=False, unique=True
    ),
    sa.Column("reason", sa.String(64), nullable=False),
)
sync_runs = sa.Table(
    "sync_runs",
    metadata,
    *immutable_columns(),
    sa.Column("source_id", sa.ForeignKey("external_sources.id"), nullable=False, index=True),
    sa.Column("connection_revision_id", sa.ForeignKey("connection_revisions.id"), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("cursor_before", sa.Text),
    sa.Column("cursor_after", sa.Text),
    sa.Column("page_count", sa.Integer, nullable=False, default=0),
    sa.Column("error_code", sa.String(64)),
    sa.Column("retry_at", UTCDateTime()),
    sa.Column("finished_at", UTCDateTime()),
    sa.UniqueConstraint("source_id", "generation"),
    sa.CheckConstraint(
        "status IN ('running','succeeded','failed','retry_wait')", name="known_status"
    ),
)
source_cursors = sa.Table(
    "source_cursors",
    metadata,
    *mutable_columns(),
    sa.Column("source_id", sa.ForeignKey("external_sources.id"), nullable=False),
    sa.Column("stream_key", sa.String(200), nullable=False),
    sa.Column("cursor", sa.Text),
    sa.Column("query_hash", sa.String(64), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False, default=0),
    sa.Column("last_success_at", UTCDateTime()),
    sa.UniqueConstraint("source_id", "stream_key"),
)
manual_sync_requests = sa.Table(
    "manual_sync_requests",
    metadata,
    *immutable_columns(),
    sa.Column(
        "connection_revision_id",
        sa.ForeignKey("connection_revisions.id"),
        nullable=False,
        index=True,
    ),
    sa.Column("actor_id", sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("stream_key", sa.String(200), nullable=False),
    sa.Column("query_hash", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("sync_run_id", sa.ForeignKey("sync_runs.id")),
    sa.UniqueConstraint("actor_id", "idempotency_key"),
    sa.CheckConstraint("status IN ('queued','running','succeeded','failed')", name="known_status"),
)
sync_pages = sa.Table(
    "sync_pages",
    metadata,
    *immutable_columns(),
    sa.Column("sync_run_id", sa.ForeignKey("sync_runs.id"), nullable=False, index=True),
    sa.Column("page_key", sa.String(512), nullable=False),
    sa.Column("page_hash", sa.String(64), nullable=False),
    sa.Column("next_cursor", sa.Text),
    sa.UniqueConstraint("sync_run_id", "page_key"),
)
external_item_snapshots = sa.Table(
    "external_item_snapshots",
    metadata,
    *immutable_columns(),
    sa.Column("external_item_id", sa.ForeignKey("external_items.id"), nullable=False, index=True),
    sa.Column("sync_run_id", sa.ForeignKey("sync_runs.id"), nullable=False, index=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("provider_revision", sa.String(256)),
    sa.Column("provider_modified_at", UTCDateTime()),
    sa.Column("raw_hash", sa.String(64), nullable=False),
    sa.Column("normalized", sa.JSON, nullable=False),
    sa.Column("visibility", sa.String(24), nullable=False),
    sa.UniqueConstraint("external_item_id", "revision"),
    sa.CheckConstraint(
        "visibility IN ('visible','inaccessible','deleted','unknown')", name="visibility"
    ),
)
planning_allocations = sa.Table(
    "planning_allocations",
    metadata,
    *mutable_columns(),
    sa.Column("external_item_id", sa.ForeignKey("external_items.id"), nullable=False, unique=True),
    sa.Column("allocated_account_id", sa.String(256), nullable=False),
    sa.Column("resource_type", sa.String(32), nullable=False),
    sa.Column("item_kind", sa.String(40), nullable=False),
    sa.Column("item_id", sa.String(256)),
    sa.Column("start_date", sa.Date, nullable=False),
    sa.Column("end_date_exclusive", sa.Date, nullable=False),
    sa.Column("native_daily_seconds", sa.Integer),
    sa.Column("timezone", sa.String(128), nullable=False),
    sa.Column("precision", sa.String(32), nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.CheckConstraint("end_date_exclusive > start_date", name="ordered_dates"),
    sa.CheckConstraint(
        "native_daily_seconds IS NULL OR native_daily_seconds >= 0", name="nonnegative_daily_effort"
    ),
    sa.CheckConstraint(
        "precision IN ('exact_daily','period_total','date_only')", name="known_precision"
    ),
)
allocation_days = sa.Table(
    "allocation_days",
    metadata,
    *immutable_columns(),
    sa.Column(
        "allocation_id", sa.ForeignKey("planning_allocations.id"), nullable=False, index=True
    ),
    sa.Column("local_date", sa.Date, nullable=False),
    sa.Column("planned_seconds", sa.Integer),
    sa.Column("exact_start", UTCDateTime()),
    sa.Column("precision", sa.String(32), nullable=False),
    sa.Column("snapshot_id", sa.ForeignKey("external_item_snapshots.id"), nullable=False),
    sa.UniqueConstraint("allocation_id", "local_date"),
    sa.CheckConstraint(
        "planned_seconds IS NULL OR planned_seconds >= 0", name="nonnegative_effort"
    ),
)
schedules = sa.Table(
    "schedules",
    metadata,
    *mutable_columns(),
    sa.Column("external_item_id", sa.ForeignKey("external_items.id"), nullable=False),
    sa.Column("occurrence_key", sa.String(512), nullable=False),
    sa.Column("uid", sa.String(512), nullable=False),
    sa.Column("start_utc", UTCDateTime()),
    sa.Column("end_utc", UTCDateTime()),
    sa.Column("all_day_start", sa.Date),
    sa.Column("all_day_end_exclusive", sa.Date),
    sa.Column("timezone", sa.String(128), nullable=False),
    sa.Column("cancelled", sa.Boolean, nullable=False, default=False),
    sa.Column("revision_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("external_item_id", "occurrence_key"),
    sa.CheckConstraint(
        "((start_utc IS NOT NULL AND end_utc IS NOT NULL AND all_day_start IS NULL "
        "AND all_day_end_exclusive IS NULL AND end_utc > start_utc) OR "
        "(start_utc IS NULL AND end_utc IS NULL AND all_day_start IS NOT NULL "
        "AND all_day_end_exclusive IS NOT NULL AND all_day_end_exclusive > all_day_start))",
        name="timed_xor_all_day",
    ),
)
daily_views = sa.Table(
    "daily_views",
    metadata,
    *mutable_columns(),
    sa.Column(
        "profile_revision_id", sa.ForeignKey("planning_profile_revisions.id"), nullable=False
    ),
    sa.Column("local_date", sa.Date, nullable=False),
    sa.Column("timezone", sa.String(128), nullable=False),
    sa.Column("generated_at", UTCDateTime(), nullable=False),
    sa.Column("freshness", sa.JSON, nullable=False),
    sa.Column("entries", sa.JSON, nullable=False),
    sa.UniqueConstraint("profile_revision_id", "local_date", "timezone"),
)
planning_task_resolutions = sa.Table(
    "planning_task_resolutions",
    metadata,
    *immutable_columns(),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), nullable=False, index=True),
    sa.Column(
        "profile_revision_id", sa.ForeignKey("planning_profile_revisions.id"), nullable=False
    ),
    sa.Column("jira_item_id", sa.ForeignKey("external_items.id"), nullable=False, index=True),
    sa.Column("jira_snapshot_id", sa.ForeignKey("external_item_snapshots.id"), nullable=False),
    sa.Column("requirements_source", sa.String(16), nullable=False),
    sa.Column("requirements_item_id", sa.ForeignKey("external_items.id")),
    sa.Column("requirements_snapshot_id", sa.ForeignKey("external_item_snapshots.id")),
    sa.Column("category", sa.String(32), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("blockers", sa.JSON, nullable=False),
    sa.Column("repository_mapping_ref", sa.String(256), nullable=False),
    sa.Column("repository_binding_ids", sa.JSON, nullable=False),
    sa.Column("route_trace", sa.JSON, nullable=False),
    sa.Column("requirements_hash", sa.String(64), nullable=False),
    sa.Column("resolution_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("task_id", "resolution_hash"),
    sa.CheckConstraint("requirements_source IN ('jira','odoo')", name="known_requirements_source"),
    sa.CheckConstraint("status IN ('ready','blocked')", name="known_status"),
    sa.CheckConstraint(
        "(requirements_source = 'jira' AND requirements_item_id IS NOT NULL "
        "AND requirements_snapshot_id IS NOT NULL) OR "
        "(requirements_source = 'odoo' AND "
        "((requirements_item_id IS NULL AND requirements_snapshot_id IS NULL) OR "
        "(requirements_item_id IS NOT NULL AND requirements_snapshot_id IS NOT NULL)))",
        name="requirements_snapshot_pair",
    ),
)
planning_task_allocations = sa.Table(
    "planning_task_allocations",
    metadata,
    *immutable_columns(),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), nullable=False, index=True),
    sa.Column(
        "resolution_id", sa.ForeignKey("planning_task_resolutions.id"), nullable=False, index=True
    ),
    sa.Column(
        "allocation_id", sa.ForeignKey("planning_allocations.id"), nullable=False, index=True
    ),
    sa.Column(
        "allocation_snapshot_id",
        sa.ForeignKey("external_item_snapshots.id"),
        nullable=False,
    ),
    sa.UniqueConstraint("resolution_id", "allocation_id", "allocation_snapshot_id"),
)
TASK_STATES = (
    "imported",
    "needs_clarification",
    "ready_for_planning",
    "planning",
    "plan_review",
    "approved",
    "implementing",
    "implementation_review",
    "completed",
)
JOB_STATES = (
    "queued",
    "leased",
    "running",
    "waiting",
    "retry_wait",
    "succeeded",
    "failed",
    "cancelled",
    "uncertain",
)
tasks = sa.Table(
    "tasks",
    metadata,
    *mutable_columns(),
    sa.Column("project_id", sa.ForeignKey("projects.id"), nullable=False, index=True),
    sa.Column("title", sa.String(1024), nullable=False),
    sa.Column("state", sa.String(32), nullable=False, default="imported"),
    sa.Column("fingerprint", sa.String(64), nullable=False, index=True),
    sa.Column("fingerprint_algorithm", sa.String(128), nullable=False),
    sa.CheckConstraint(
        "state IN (" + ",".join(repr(x) for x in TASK_STATES) + ")", name="known_state"
    ),
    sa.CheckConstraint("length(title) > 0", name="nonempty_title"),
    sa.CheckConstraint("length(fingerprint) = 64", name="fingerprint_length"),
)
sa.Index("ix_tasks_project_state", tasks.c.project_id, tasks.c.state)
task_sources = sa.Table(
    "task_sources",
    metadata,
    *mutable_columns(),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), nullable=False, index=True),
    sa.Column("external_item_id", sa.ForeignKey("external_items.id"), nullable=False, index=True),
    sa.Column("relation", sa.String(16), nullable=False),
    sa.Column("role", sa.String(16), nullable=False),
    sa.Column("confirmed_by_id", sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column(
        "active",
        sa.Boolean(name="boolean_value", create_constraint=True),
        nullable=False,
        default=True,
    ),
    sa.UniqueConstraint("task_id", "external_item_id"),
    sa.CheckConstraint("relation IN ('same_work','context')", name="known_relation"),
    sa.CheckConstraint("role IN ('primary','secondary')", name="known_role"),
)
sa.Index(
    "uq_task_sources_active_item",
    task_sources.c.external_item_id,
    unique=True,
    sqlite_where=task_sources.c.active.is_(True),
    postgresql_where=task_sources.c.active.is_(True),
)
sa.Index(
    "uq_task_sources_active_primary",
    task_sources.c.task_id,
    unique=True,
    sqlite_where=sa.and_(task_sources.c.active.is_(True), task_sources.c.role == "primary"),
    postgresql_where=sa.and_(task_sources.c.active.is_(True), task_sources.c.role == "primary"),
)
task_fingerprint_revisions = sa.Table(
    "task_fingerprint_revisions",
    metadata,
    *immutable_columns(),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), nullable=False, index=True),
    sa.Column("algorithm", sa.String(128), nullable=False),
    sa.Column("fingerprint", sa.String(64), nullable=False),
    sa.Column("manifest", sa.JSON, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("reason", sa.String(128), nullable=False),
    sa.UniqueConstraint("task_id", "fingerprint", "algorithm"),
    sa.CheckConstraint(
        "length(fingerprint) = 64 AND length(content_hash) = 64", name="hash_lengths"
    ),
)
task_holds = sa.Table(
    "task_holds",
    metadata,
    *mutable_columns(),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), nullable=False, index=True),
    sa.Column("reason", sa.String(128), nullable=False),
    sa.Column("opened_at", UTCDateTime(), nullable=False, default=utcnow),
    sa.Column("resolved_at", UTCDateTime()),
    sa.Column("resolver_id", sa.ForeignKey("users.id"), index=True),
    sa.CheckConstraint(
        "(resolved_at IS NULL AND resolver_id IS NULL) OR "
        "(resolved_at IS NOT NULL AND resolver_id IS NOT NULL AND resolved_at >= opened_at)",
        name="resolution_evidence",
    ),
)
artifacts = sa.Table(
    "artifacts",
    metadata,
    *immutable_columns(),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("media_type", sa.String(128), nullable=False),
    sa.Column("byte_count", sa.BigInteger, nullable=False),
    sa.Column("relative_path", sa.Text, nullable=False),
    sa.Column("sensitivity", sa.String(32), nullable=False),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.UniqueConstraint("content_hash", "media_type"),
    sa.CheckConstraint("length(content_hash) = 64", name="hash_length"),
    sa.CheckConstraint("byte_count >= 0", name="nonnegative_size"),
    sa.CheckConstraint("schema_version = 1", name="supported_schema_version"),
    sa.CheckConstraint(
        "length(relative_path) > 0 AND substr(relative_path,1,1) != '/' "
        "AND instr(relative_path,'..') = 0",
        name="relative_path",
    ),
    sa.CheckConstraint(
        "sensitivity IN ('public','private','restricted')", name="known_sensitivity"
    ),
)
execution_jobs = sa.Table(
    "execution_jobs",
    metadata,
    *mutable_columns(),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("task_id", sa.ForeignKey("tasks.id"), index=True),
    sa.Column("state", sa.String(32), nullable=False, default="queued"),
    sa.Column("priority", sa.Integer, nullable=False, default=0),
    sa.Column("not_before", UTCDateTime(), nullable=False, default=utcnow),
    sa.Column("attempts", sa.Integer, nullable=False, default=0),
    sa.Column("max_attempts", sa.Integer, nullable=False, default=3),
    sa.Column("lease_owner", sa.String(128)),
    sa.Column("lease_expires_at", UTCDateTime()),
    sa.Column("lease_epoch", sa.Integer, nullable=False, default=0),
    sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True),
    sa.CheckConstraint("kind = 'fixture_noop'", name="fixture_kind_only"),
    sa.CheckConstraint(
        "state IN (" + ",".join(repr(x) for x in JOB_STATES) + ")", name="known_state"
    ),
    sa.CheckConstraint(
        "attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts", name="attempt_range"
    ),
    sa.CheckConstraint("lease_epoch >= 0", name="nonnegative_epoch"),
    sa.CheckConstraint(
        "(state IN ('leased','running') AND lease_owner IS NOT NULL "
        "AND length(lease_owner)>0 AND lease_expires_at IS NOT NULL AND lease_epoch > 0) "
        "OR (state NOT IN ('leased','running') AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        name="lease_shape",
    ),
)
sa.Index(
    "ix_execution_jobs_claim",
    execution_jobs.c.state,
    execution_jobs.c.not_before,
    execution_jobs.c.priority,
)
sa.Index("ix_execution_jobs_lease_expiry", execution_jobs.c.lease_expires_at)
command_receipts = sa.Table(
    "command_receipts",
    metadata,
    *immutable_columns(),
    sa.Column("user_id", sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.Column("command_key", sa.String(256), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("response", sa.JSON, nullable=False),
    sa.UniqueConstraint("user_id", "command_key"),
    sa.CheckConstraint("length(command_key)>0 AND length(request_hash)=64", name="key_hash_shape"),
)
audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("id", sa.String(36), nullable=False, unique=True, default=new_id),
    sa.Column("user_id", sa.ForeignKey("users.id"), index=True),
    sa.Column("event_type", sa.String(128), nullable=False),
    sa.Column("entity_id", sa.String(36), nullable=False, index=True),
    sa.Column("entity_version", sa.Integer, nullable=False),
    sa.Column("correlation_id", sa.String(36), nullable=False, index=True),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("created_at", UTCDateTime(), nullable=False, default=utcnow),
    sa.CheckConstraint("entity_version >= 1", name="positive_entity_version"),
    sa.CheckConstraint("length(content_hash)=64", name="hash_length"),
    sqlite_autoincrement=True,
)
outbox_events = sa.Table(
    "outbox_events",
    metadata,
    sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("id", sa.String(36), nullable=False, unique=True, default=new_id),
    sa.Column("audit_id", sa.ForeignKey("audit_events.id"), nullable=False, index=True),
    sa.Column("event_type", sa.String(128), nullable=False),
    sa.Column("entity_id", sa.String(36), nullable=False, index=True),
    sa.Column("entity_version", sa.Integer, nullable=False),
    sa.Column("correlation_id", sa.String(36), nullable=False, index=True),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("created_at", UTCDateTime(), nullable=False, default=utcnow),
    sa.CheckConstraint("entity_version >= 1", name="positive_entity_version"),
    sa.CheckConstraint("length(content_hash)=64", name="hash_length"),
    sqlite_autoincrement=True,
)
pairing_tokens = sa.Table(
    "pairing_tokens",
    metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("expires_at", UTCDateTime(), nullable=False),
    sa.Column("user_id", sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.CheckConstraint("length(token_hash)=64", name="hash_length"),
)
sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("csrf_hash", sa.String(64), nullable=False),
    sa.Column("expires_at", UTCDateTime(), nullable=False),
    sa.Column("user_id", sa.ForeignKey("users.id"), nullable=False, index=True),
    sa.CheckConstraint("length(token_hash)=64 AND length(csrf_hash)=64", name="hash_lengths"),
)
