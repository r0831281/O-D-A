"""Migrations use an explicit caller-owned connection, never ambient settings."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Run migrations through the NEXUS CLI")
context.configure(connection=connection, target_metadata=None, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
