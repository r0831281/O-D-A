"""Allowlisted structured logging. Never serialize requests, exceptions or SQL."""

import json
import logging

logger = logging.getLogger("nexus")


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for name in ("uvicorn.access", "sqlalchemy.engine", "alembic"):
        logging.getLogger(name).disabled = True


def safe_log(event: str, correlation_id: str, status: int | None = None) -> None:
    # Callers supply fixed event names and validated/generated UUID correlations only.
    if event not in {"request", "command", "configuration_error", "storage_error", "worker"}:
        event = "command"
    payload = {"event": event, "correlation_id": correlation_id}
    if status is not None:
        payload["status"] = status
    logger.info(json.dumps(payload, separators=(",", ":")))
