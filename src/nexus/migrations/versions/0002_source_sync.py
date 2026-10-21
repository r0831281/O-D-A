"""Phase 2 typed connection/profile revisions and source synchronization."""

from alembic import op

from nexus import schema

revision = "0002_source_sync"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

TABLES = (
    "connection_revisions",
    "planning_profiles",
    "planning_profile_revisions",
    "profile_connections",
    "connection_test_runs",
    "profile_activations",
    "profile_binding_invalidations",
    "sync_runs",
    "source_cursors",
    "manual_sync_requests",
    "sync_pages",
    "external_item_snapshots",
    "planning_allocations",
    "allocation_days",
    "schedules",
    "daily_views",
)


def upgrade():
    bind = op.get_bind()
    for name in TABLES:
        schema.metadata.tables[name].create(bind=bind, checkfirst=False)


def downgrade():
    bind = op.get_bind()
    for name in reversed(TABLES):
        schema.metadata.tables[name].drop(bind=bind, checkfirst=False)
