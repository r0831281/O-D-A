"""Frozen Phase 2 schema for typed connections, profiles and source sync."""

import sqlalchemy as sa
from alembic import op

revision = "0002_source_sync"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

ID = sa.String(36)
UTC = sa.String(27)


def upgrade():
    op.create_table(
        "connection_revisions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("source_id", ID, sa.ForeignKey("external_sources.id"), nullable=False),
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
    op.create_table(
        "planning_profiles",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("active_revision_id", ID, sa.ForeignKey("planning_profile_revisions.id")),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    )
    op.create_table(
        "planning_profile_revisions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("profile_id", ID, sa.ForeignKey("planning_profiles.id"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("profile_id", "revision"),
        sa.CheckConstraint("revision >= 1 AND schema_version = 1", name="revision_schema"),
        sa.CheckConstraint("length(config_hash) = 64", name="config_hash_length"),
    )
    op.create_table(
        "profile_connections",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column(
            "profile_revision_id",
            ID,
            sa.ForeignKey("planning_profile_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "connection_revision_id", ID, sa.ForeignKey("connection_revisions.id"), nullable=False
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.UniqueConstraint("profile_revision_id", "connection_revision_id", "role"),
        sa.CheckConstraint(
            "role IN ('schedule','context_calendar','work_items','requirements')", name="known_role"
        ),
    )
    op.create_table(
        "connection_test_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("connection_revision_id", ID, sa.ForeignKey("connection_revisions.id")),
        sa.Column("profile_revision_id", ID, sa.ForeignKey("planning_profile_revisions.id")),
        sa.Column("test_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("adapter_build", sa.String(128), nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("expires_at", UTC, nullable=False),
        sa.CheckConstraint("status IN ('passed','failed','blocked')", name="known_status"),
    )
    op.create_table(
        "profile_activations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("profile_id", ID, sa.ForeignKey("planning_profiles.id"), nullable=False),
        sa.Column(
            "profile_revision_id",
            ID,
            sa.ForeignKey("planning_profile_revisions.id"),
            nullable=False,
        ),
        sa.Column("actor_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("prior_activation_id", ID, sa.ForeignKey("profile_activations.id")),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.CheckConstraint("operation IN ('activate','rollback')", name="known_operation"),
    )
    op.create_table(
        "profile_binding_invalidations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("profile_id", ID, sa.ForeignKey("planning_profiles.id"), nullable=False),
        sa.Column("prior_revision_id", ID, sa.ForeignKey("planning_profile_revisions.id")),
        sa.Column(
            "new_revision_id", ID, sa.ForeignKey("planning_profile_revisions.id"), nullable=False
        ),
        sa.Column(
            "activation_id",
            ID,
            sa.ForeignKey("profile_activations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("reason", sa.String(64), nullable=False),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("source_id", ID, sa.ForeignKey("external_sources.id"), nullable=False),
        sa.Column(
            "connection_revision_id", ID, sa.ForeignKey("connection_revisions.id"), nullable=False
        ),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cursor_before", sa.Text),
        sa.Column("cursor_after", sa.Text),
        sa.Column("page_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("retry_at", UTC),
        sa.Column("finished_at", UTC),
        sa.UniqueConstraint("source_id", "generation"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','retry_wait')", name="known_status"
        ),
    )
    op.create_table(
        "source_cursors",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("source_id", ID, sa.ForeignKey("external_sources.id"), nullable=False),
        sa.Column("stream_key", sa.String(200), nullable=False),
        sa.Column("cursor", sa.Text),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("last_success_at", UTC),
        sa.UniqueConstraint("source_id", "stream_key"),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    )
    op.create_table(
        "manual_sync_requests",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column(
            "connection_revision_id", ID, sa.ForeignKey("connection_revisions.id"), nullable=False
        ),
        sa.Column("actor_id", ID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("stream_key", sa.String(200), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("sync_run_id", ID, sa.ForeignKey("sync_runs.id")),
        sa.UniqueConstraint("actor_id", "idempotency_key"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="known_status"
        ),
    )
    op.create_table(
        "sync_pages",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("sync_run_id", ID, sa.ForeignKey("sync_runs.id"), nullable=False),
        sa.Column("page_key", sa.String(512), nullable=False),
        sa.Column("page_hash", sa.String(64), nullable=False),
        sa.Column("next_cursor", sa.Text),
        sa.UniqueConstraint("sync_run_id", "page_key"),
    )
    op.create_table(
        "external_item_snapshots",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("external_item_id", ID, sa.ForeignKey("external_items.id"), nullable=False),
        sa.Column("sync_run_id", ID, sa.ForeignKey("sync_runs.id"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("provider_revision", sa.String(256)),
        sa.Column("provider_modified_at", UTC),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("normalized", sa.JSON, nullable=False),
        sa.Column("visibility", sa.String(24), nullable=False),
        sa.UniqueConstraint("external_item_id", "revision"),
        sa.CheckConstraint(
            "visibility IN ('visible','inaccessible','deleted','unknown')", name="visibility"
        ),
    )
    op.create_table(
        "planning_allocations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "external_item_id", ID, sa.ForeignKey("external_items.id"), nullable=False, unique=True
        ),
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
            "native_daily_seconds IS NULL OR native_daily_seconds >= 0",
            name="nonnegative_daily_effort",
        ),
        sa.CheckConstraint(
            "precision IN ('exact_daily','period_total','date_only')", name="known_precision"
        ),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    )
    op.create_table(
        "allocation_days",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("allocation_id", ID, sa.ForeignKey("planning_allocations.id"), nullable=False),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("planned_seconds", sa.Integer),
        sa.Column("exact_start", UTC),
        sa.Column("precision", sa.String(32), nullable=False),
        sa.Column("snapshot_id", ID, sa.ForeignKey("external_item_snapshots.id"), nullable=False),
        sa.UniqueConstraint("allocation_id", "local_date"),
        sa.CheckConstraint(
            "planned_seconds IS NULL OR planned_seconds >= 0", name="nonnegative_effort"
        ),
    )
    op.create_table(
        "schedules",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("external_item_id", ID, sa.ForeignKey("external_items.id"), nullable=False),
        sa.Column("occurrence_key", sa.String(512), nullable=False),
        sa.Column("uid", sa.String(512), nullable=False),
        sa.Column("start_utc", UTC),
        sa.Column("end_utc", UTC),
        sa.Column("all_day_start", sa.Date),
        sa.Column("all_day_end_exclusive", sa.Date),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("cancelled", sa.Boolean, nullable=False),
        sa.Column("revision_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("external_item_id", "occurrence_key"),
        sa.CheckConstraint(
            "((start_utc IS NOT NULL AND end_utc IS NOT NULL AND all_day_start IS NULL AND all_day_end_exclusive IS NULL AND end_utc > start_utc) OR (start_utc IS NULL AND end_utc IS NULL AND all_day_start IS NOT NULL AND all_day_end_exclusive IS NOT NULL AND all_day_end_exclusive > all_day_start))",
            name="timed_xor_all_day",
        ),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    )
    op.create_table(
        "daily_views",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "profile_revision_id",
            ID,
            sa.ForeignKey("planning_profile_revisions.id"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("generated_at", UTC, nullable=False),
        sa.Column("freshness", sa.JSON, nullable=False),
        sa.Column("entries", sa.JSON, nullable=False),
        sa.UniqueConstraint("profile_revision_id", "local_date", "timezone"),
        sa.CheckConstraint("version >= 1", name="positive_version"),
        sa.CheckConstraint("updated_at >= created_at", name="ordered_timestamps"),
    )
    op.create_table(
        "planning_task_resolutions",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "profile_revision_id",
            ID,
            sa.ForeignKey("planning_profile_revisions.id"),
            nullable=False,
        ),
        sa.Column("jira_item_id", ID, sa.ForeignKey("external_items.id"), nullable=False),
        sa.Column(
            "jira_snapshot_id", ID, sa.ForeignKey("external_item_snapshots.id"), nullable=False
        ),
        sa.Column("requirements_source", sa.String(16), nullable=False),
        sa.Column("requirements_item_id", ID, sa.ForeignKey("external_items.id")),
        sa.Column("requirements_snapshot_id", ID, sa.ForeignKey("external_item_snapshots.id")),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("blockers", sa.JSON, nullable=False),
        sa.Column("repository_mapping_ref", sa.String(256), nullable=False),
        sa.Column("repository_binding_ids", sa.JSON, nullable=False),
        sa.Column("route_trace", sa.JSON, nullable=False),
        sa.Column("requirements_hash", sa.String(64), nullable=False),
        sa.Column("resolution_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("task_id", "resolution_hash"),
        sa.CheckConstraint(
            "requirements_source IN ('jira','odoo')", name="known_requirements_source"
        ),
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
    op.create_table(
        "planning_task_allocations",
        sa.Column("id", ID, primary_key=True),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column(
            "resolution_id", ID, sa.ForeignKey("planning_task_resolutions.id"), nullable=False
        ),
        sa.Column("allocation_id", ID, sa.ForeignKey("planning_allocations.id"), nullable=False),
        sa.Column(
            "allocation_snapshot_id",
            ID,
            sa.ForeignKey("external_item_snapshots.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("resolution_id", "allocation_id", "allocation_snapshot_id"),
    )
    indexes = {
        "connection_revisions": ("source_id",),
        "planning_profiles": ("active_revision_id",),
        "planning_profile_revisions": ("profile_id",),
        "profile_connections": ("profile_revision_id", "connection_revision_id"),
        "connection_test_runs": ("connection_revision_id", "profile_revision_id"),
        "profile_activations": (
            "profile_id",
            "profile_revision_id",
            "actor_id",
            "prior_activation_id",
        ),
        "profile_binding_invalidations": (
            "profile_id",
            "prior_revision_id",
            "new_revision_id",
            "activation_id",
        ),
        "sync_runs": ("source_id", "connection_revision_id"),
        "source_cursors": ("source_id",),
        "manual_sync_requests": ("connection_revision_id", "actor_id", "sync_run_id"),
        "sync_pages": ("sync_run_id",),
        "external_item_snapshots": ("external_item_id", "sync_run_id"),
        "planning_allocations": ("external_item_id",),
        "allocation_days": ("allocation_id", "snapshot_id"),
        "schedules": ("external_item_id",),
        "daily_views": ("profile_revision_id",),
        "planning_task_resolutions": (
            "task_id",
            "profile_revision_id",
            "jira_item_id",
            "jira_snapshot_id",
            "requirements_item_id",
            "requirements_snapshot_id",
        ),
        "planning_task_allocations": (
            "task_id",
            "resolution_id",
            "allocation_id",
            "allocation_snapshot_id",
        ),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.execute("UPDATE planning_profiles SET active_revision_id = NULL")
    indexes = (
        ("planning_task_allocations", "allocation_id"),
        ("planning_task_allocations", "resolution_id"),
        ("planning_task_allocations", "task_id"),
        ("planning_task_allocations", "allocation_snapshot_id"),
        ("planning_task_resolutions", "jira_item_id"),
        ("planning_task_resolutions", "jira_snapshot_id"),
        ("planning_task_resolutions", "requirements_item_id"),
        ("planning_task_resolutions", "requirements_snapshot_id"),
        ("planning_task_resolutions", "profile_revision_id"),
        ("planning_task_resolutions", "task_id"),
        ("daily_views", "profile_revision_id"),
        ("schedules", "external_item_id"),
        ("allocation_days", "snapshot_id"),
        ("allocation_days", "allocation_id"),
        ("planning_allocations", "external_item_id"),
        ("external_item_snapshots", "sync_run_id"),
        ("external_item_snapshots", "external_item_id"),
        ("sync_pages", "sync_run_id"),
        ("manual_sync_requests", "sync_run_id"),
        ("manual_sync_requests", "actor_id"),
        ("manual_sync_requests", "connection_revision_id"),
        ("source_cursors", "source_id"),
        ("sync_runs", "connection_revision_id"),
        ("sync_runs", "source_id"),
        ("profile_binding_invalidations", "activation_id"),
        ("profile_binding_invalidations", "new_revision_id"),
        ("profile_binding_invalidations", "prior_revision_id"),
        ("profile_binding_invalidations", "profile_id"),
        ("profile_activations", "prior_activation_id"),
        ("profile_activations", "actor_id"),
        ("profile_activations", "profile_revision_id"),
        ("profile_activations", "profile_id"),
        ("connection_test_runs", "profile_revision_id"),
        ("connection_test_runs", "connection_revision_id"),
        ("profile_connections", "connection_revision_id"),
        ("profile_connections", "profile_revision_id"),
        ("planning_profile_revisions", "profile_id"),
        ("planning_profiles", "active_revision_id"),
        ("connection_revisions", "source_id"),
    )
    for table, column in indexes:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
    for table in (
        "planning_task_allocations",
        "planning_task_resolutions",
        "daily_views",
        "schedules",
        "allocation_days",
        "planning_allocations",
        "external_item_snapshots",
        "sync_pages",
        "manual_sync_requests",
        "source_cursors",
        "sync_runs",
        "profile_binding_invalidations",
        "profile_activations",
        "connection_test_runs",
        "profile_connections",
        "planning_profile_revisions",
        "planning_profiles",
        "connection_revisions",
    ):
        op.drop_table(table)
