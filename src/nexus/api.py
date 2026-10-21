"""Minimal same-origin, local operator API for the foundation slice."""

from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from nexus import schema as s
from nexus.auth import (
    Principal,
    authenticate,
    check_csrf,
    exchange_pairing,
    revoke_session,
)
from nexus.config import Settings
from nexus.domain import NexusError, StrictModel, TaskState
from nexus.logging import safe_log
from nexus.planning import PlanningService
from nexus.services import Foundation
from nexus.storage import Database

COOKIE_NAME = "nexus_session"
MUTATIONS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BODY_LIMIT = 16_384


class RequestBodyLimit:
    """Bound received bytes even when Content-Length is incorrect."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in MUTATIONS:
            await self.app(scope, receive, send)
            return
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > BODY_LIMIT:
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, bounded_receive, send)


class VersionedRequest(StrictModel):
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def version_is_integer(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("unsupported schema version")
        return value


class PairRequest(VersionedRequest):
    token: str = Field(min_length=32, max_length=128)


class CommandRequest(VersionedRequest):
    pass


class TransitionRequest(CommandRequest):
    expected_version: int = Field(ge=1)
    target: str = Field(min_length=1, max_length=40)


class ManualSyncRequest(CommandRequest):
    connection_revision_id: str = Field(min_length=1, max_length=36)
    stream_key: str = Field(min_length=1, max_length=200)
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings)
    foundation = Foundation(db)
    planning = PlanningService(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        def verify_migration():
            config = Config()
            config.set_main_option("script_location", "nexus:migrations")
            expected_revision = ScriptDirectory.from_config(config).get_current_head()
            with db.read() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                if revision != expected_revision:
                    raise RuntimeError("database_migration_required")

        try:
            try:
                await run_in_threadpool(verify_migration)
            except SQLAlchemyError:
                raise RuntimeError("database_migration_required") from None
            yield
        finally:
            db.engine.dispose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db = db
    app.state.foundation = foundation
    app.state.planning = planning

    def error(request: Request, code: str, status: int) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": code, "correlation_id": request.state.correlation_id}},
            status_code=status,
        )

    async def dispatch(request: Request, call_next):
        # Catch unexpected faults inside the middleware boundary so an ASGI
        # server cannot log exception text or SQL after a safe 500 response.
        try:
            return await call_next(request)
        except NexusError as exc:
            return error(request, exc.code, exc.status)
        except HTTPException as exc:
            return error(request, "request_rejected", exc.status_code)
        except (SQLAlchemyError, OSError):
            return error(request, "storage_unavailable", 503)
        except Exception:
            return error(request, "internal_error", 500)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request.state.correlation_id = str(uuid4())
        if request.headers.get("host") != urlsplit(settings.origin).netloc:
            response = error(request, "host_invalid", 403)
        elif request.method in MUTATIONS and request.headers.get("origin") != settings.origin:
            response = error(request, "origin_invalid", 403)
        elif (
            request.method in MUTATIONS
            and request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            response = error(request, "json_required", 415)
        elif request.method in MUTATIONS:
            # A fixed bound also rejects chunked/unbounded request bodies.
            length = request.headers.get("content-length", "")
            if not length.isascii() or not length.isdigit():
                response = error(request, "content_length_required", 411)
            elif len(length) > 6 or int(length) > BODY_LIMIT:
                response = error(request, "body_too_large", 413)
            else:
                response = await dispatch(request, call_next)
        else:
            response = await dispatch(request, call_next)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        safe_log("request", request.state.correlation_id, response.status_code)
        return response

    app.add_middleware(RequestBodyLimit)

    @app.exception_handler(NexusError)
    async def domain_error(request: Request, exc: NexusError):
        return error(request, exc.code, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(request, "validation_failed", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(request, "request_rejected", exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return error(request, "storage_unavailable", 503)

    @app.exception_handler(OSError)
    async def filesystem_error(request: Request, exc: OSError):
        return error(request, "storage_unavailable", 503)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error(request, "internal_error", 500)

    def principal(request: Request) -> Principal:
        return authenticate(db, request.cookies.get(COOKIE_NAME))

    def mutation_principal(
        request: Request, user: Annotated[Principal, Depends(principal)]
    ) -> Principal:
        check_csrf(user, request.headers.get("x-csrf-token"))
        return user

    def command_key(
        value: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    ) -> str:
        return value

    @app.get("/health")
    def health():
        with db.read() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        return {"api": "ok", "database": "ok", "execution": "disabled", "phase": 2}

    @app.post("/auth/pair")
    def pair(body: PairRequest, request: Request, response: Response):
        result = exchange_pairing(db, settings, body.token, request.state.correlation_id)
        response.set_cookie(
            COOKIE_NAME,
            result.session_token,
            max_age=settings.session_seconds,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        return {"schema_version": 1, "csrf_token": result.csrf_token}

    @app.post("/auth/logout")
    def logout(
        body: CommandRequest,
        request: Request,
        response: Response,
        user: Annotated[Principal, Depends(mutation_principal)],
    ):
        revoke_session(db, user, request.state.correlation_id)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
        return {"status": "signed_out"}

    @app.get("/status")
    def status(user: Annotated[Principal, Depends(principal)]):
        return foundation.status()

    @app.post("/fixtures")
    def fixture(
        body: CommandRequest,
        request: Request,
        user: Annotated[Principal, Depends(mutation_principal)],
        key: Annotated[str, Depends(command_key)],
    ):
        return foundation.fixture(user.user_id, key, request.state.correlation_id)

    @app.post("/tasks/{task_id}/transition")
    def transition(
        task_id: str,
        body: TransitionRequest,
        request: Request,
        user: Annotated[Principal, Depends(mutation_principal)],
        key: Annotated[str, Depends(command_key)],
    ):
        try:
            target = TaskState(body.target)
        except ValueError:
            raise NexusError("transition_invalid", status=409) from None
        return foundation.transition(
            user.user_id, key, task_id, body.expected_version, target, request.state.correlation_id
        )

    @app.post("/tasks/{task_id}/enqueue")
    def enqueue(
        task_id: str,
        body: CommandRequest,
        request: Request,
        user: Annotated[Principal, Depends(mutation_principal)],
        key: Annotated[str, Depends(command_key)],
    ):
        return foundation.enqueue(user.user_id, key, task_id, request.state.correlation_id)

    @app.post("/source-sync-requests")
    def request_source_sync(
        body: ManualSyncRequest,
        user: Annotated[Principal, Depends(mutation_principal)],
        key: Annotated[str, Depends(command_key)],
    ):
        return planning.queue_manual_sync(
            user.user_id, body.connection_revision_id, body.stream_key, body.query_hash, key
        )

    @app.get("/source-sync-requests/{request_id}")
    def source_sync_status(request_id: str, user: Annotated[Principal, Depends(principal)]):
        with db.read() as connection:
            row = connection.execute(
                select(s.manual_sync_requests).where(
                    s.manual_sync_requests.c.id == request_id,
                    s.manual_sync_requests.c.actor_id == user.user_id,
                )
            ).first()
        if row is None:
            raise NexusError("sync_request_missing", 404)
        data = dict(row._mapping)
        return {
            "request_id": data["id"],
            "status": data["status"],
            "sync_run_id": data["sync_run_id"],
        }

    @app.get("/planning/days/{local_date}")
    def planning_day(
        local_date: str, profile_revision_id: str, user: Annotated[Principal, Depends(principal)]
    ):
        try:
            parsed_date = date.fromisoformat(local_date)
        except ValueError:
            raise NexusError("date_invalid", 422) from None
        with db.read() as connection:
            row = connection.execute(
                select(s.daily_views).where(
                    s.daily_views.c.profile_revision_id == profile_revision_id,
                    s.daily_views.c.local_date == parsed_date,
                )
            ).first()
        if row is None:
            raise NexusError("planning_day_missing", 404)
        data = dict(row._mapping)
        freshness = {source: bool(value) for source, value in data["freshness"].items()}
        return {
            "local_date": local_date,
            "timezone": data["timezone"],
            "profile_revision_id": profile_revision_id,
            "status": "fresh" if all(freshness.values()) else "stale",
            "freshness": freshness,
            "entries": data["entries"],
            "deadlines_are_separate": True,
            "generated_at": data["generated_at"].isoformat(),
        }

    @app.get("/planning/windows/{start_date}")
    def planning_window(
        start_date: str,
        profile_revision_id: str,
        user: Annotated[Principal, Depends(principal)],
        days: int = 7,
    ):
        try:
            parsed_date = date.fromisoformat(start_date)
        except ValueError:
            raise NexusError("date_invalid", 422) from None
        return PlanningService(db).read_window(profile_revision_id, parsed_date, days)

    return app
