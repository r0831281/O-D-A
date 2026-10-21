"""File-backed local authentication and HTTP mutation boundary tests."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from nexus import auth
from nexus.api import COOKIE_NAME, create_app
from nexus.config import Settings
from nexus.domain import NexusError
from nexus.schema import audit_events, pairing_tokens, sessions, users, utcnow
from nexus.storage import Database, migrate


@pytest.fixture
def local_api(tmp_path):
    settings = Settings(state_dir=tmp_path.resolve() / "state")
    db = Database(settings)
    migrate(db)
    token = auth.issue_pairing(db, settings)
    app = create_app(settings)
    with TestClient(app, base_url=settings.origin) as client:
        yield client, db, settings, token
    db.engine.dispose()


def pair(client, settings, token):
    response = client.post("/auth/pair", json={"token": token}, headers={"Origin": settings.origin})
    assert response.status_code == 200
    return response, {
        "Origin": settings.origin,
        "X-CSRF-Token": response.json()["csrf_token"],
        "Idempotency-Key": "http-fixture",
    }


def test_health_is_minimal_and_startup_does_not_seed_tasks(local_api):
    client, db, settings, token = local_api
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"api": "ok", "database": "ok", "execution": "disabled", "phase": 1}
    assert client.get("/status").status_code == 401
    pair(client, settings, token)
    assert client.get("/status").json()["tasks"] == []
    assert client.get("/openapi.json").status_code == 404


def test_startup_requires_migration_without_creating_demo_data(tmp_path):
    settings = Settings(state_dir=tmp_path.resolve() / "unmigrated")
    app = create_app(settings)
    with pytest.raises(RuntimeError, match="database_migration_required"):
        with TestClient(app, base_url=settings.origin):
            pass


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null", "http://127.0.0.1:8765/"])
def test_pairing_requires_exact_origin(local_api, origin):
    client, db, settings, token = local_api
    headers = {} if origin is None else {"Origin": origin}
    response = client.post("/auth/pair", json={"token": token}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_invalid"
    # A rejected cross-origin request cannot consume the one-time capability.
    pair(client, settings, token)


def test_host_rebinding_and_json_boundary(local_api):
    client, db, settings, token = local_api
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 403
    response = client.post(
        "/auth/pair",
        content=token,
        headers={"Origin": settings.origin, "Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    response = client.post(
        "/auth/pair",
        content="{}",
        headers={
            "Origin": settings.origin,
            "Content-Type": "application/json",
            "Content-Length": "20000",
        },
    )
    assert response.status_code == 413
    response = client.post(
        "/auth/pair",
        content="x" * 20_000,
        headers={
            "Origin": settings.origin,
            "Content-Type": "application/json",
            "Content-Length": "1",
        },
    )
    # The ASGI test transport rejects invalid HTTP framing before the app sees it.
    assert response.status_code == 400


def test_received_body_limit_rejects_oversized_chunk():
    from starlette.exceptions import HTTPException

    from nexus.api import BODY_LIMIT, RequestBodyLimit

    responses = []

    async def endpoint(scope, receive, send):
        try:
            await receive()
        except HTTPException as exc:
            await send({"type": "http.response.start", "status": exc.status_code, "headers": []})
            await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"x" * (BODY_LIMIT + 1), "more_body": False}

    async def send(message):
        responses.append(message)

    app = RequestBodyLimit(endpoint)
    asyncio.run(app({"type": "http", "method": "POST"}, receive, send))
    assert responses[0]["status"] == 413


def test_one_time_pairing_private_cookie_and_hashed_storage(local_api):
    client, db, settings, token = local_api
    response, headers = pair(client, settings, token)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # Fixed HTTP loopback deployment only.
    session_token = client.cookies[COOKIE_NAME]
    assert (
        client.post(
            "/auth/pair", json={"token": token}, headers={"Origin": settings.origin}
        ).status_code
        == 401
    )
    with db.read() as connection:
        assert connection.execute(select(pairing_tokens)).first() is None
        persisted = connection.execute(select(sessions)).mappings().one()
        audit = [dict(row) for row in connection.execute(select(audit_events)).mappings()]
    assert persisted["token_hash"] == auth._digest(session_token)
    assert persisted["csrf_hash"] == auth._digest(headers["X-CSRF-Token"])
    serialized = str(persisted) + str(audit)
    assert token not in serialized
    assert session_token not in serialized
    assert headers["X-CSRF-Token"] not in serialized


def test_pairing_rotation_and_expiry(local_api, monkeypatch):
    client, db, settings, first = local_api
    current = auth.issue_pairing(db, settings)
    assert (
        client.post(
            "/auth/pair", json={"token": first}, headers={"Origin": settings.origin}
        ).status_code
        == 401
    )
    future = utcnow() + timedelta(seconds=settings.pairing_seconds + 1)
    monkeypatch.setattr(auth, "utcnow", lambda: future)
    assert (
        client.post(
            "/auth/pair", json={"token": current}, headers={"Origin": settings.origin}
        ).status_code
        == 401
    )


def test_session_expiry_and_operator_deactivation(local_api, monkeypatch):
    client, db, settings, token = local_api
    pair(client, settings, token)
    assert client.get("/status").status_code == 200
    now = utcnow()
    monkeypatch.setattr(
        auth, "utcnow", lambda: now + timedelta(seconds=settings.session_seconds + 1)
    )
    assert client.get("/status").status_code == 401
    monkeypatch.setattr(auth, "utcnow", lambda: now)
    with db.write() as connection:
        connection.execute(update(users).values(active=False))
    assert client.get("/status").status_code == 401


@pytest.mark.parametrize(
    "path,body",
    [
        ("/fixtures", {}),
        ("/tasks/example/enqueue", {}),
        ("/tasks/example/transition", {"expected_version": 1, "target": "needs_clarification"}),
        ("/auth/logout", {}),
    ],
)
def test_all_mutations_require_authentication_and_csrf(local_api, path, body):
    client, db, settings, token = local_api
    headers = {"Origin": settings.origin, "Idempotency-Key": "test"}
    assert client.post(path, json=body, headers=headers).status_code == 401
    pair(client, settings, token)
    assert client.post(path, json=body, headers=headers).status_code == 403
    headers["X-CSRF-Token"] = "wrong"
    assert client.post(path, json=body, headers=headers).status_code == 403


def test_http_commands_and_forbidden_execution_surface(local_api):
    client, db, settings, token = local_api
    _, headers = pair(client, settings, token)
    response = client.post("/fixtures", json={}, headers=headers)
    assert response.status_code == 200
    task = response.json()
    assert client.post("/fixtures", json={}, headers=headers).json() == task
    headers["Idempotency-Key"] = "enqueue"
    queued = client.post(f"/tasks/{task['task_id']}/enqueue", json={}, headers=headers)
    assert queued.status_code == 200
    assert queued.json()["state"] == "queued"
    headers["Idempotency-Key"] = "clarify"
    changed = client.post(
        f"/tasks/{task['task_id']}/transition",
        json={"expected_version": task["version"], "target": "needs_clarification"},
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == task["version"] + 1
    headers["Idempotency-Key"] = "stale"
    assert (
        client.post(
            f"/tasks/{task['task_id']}/transition",
            json={"expected_version": task["version"], "target": "needs_clarification"},
            headers=headers,
        ).status_code
        == 409
    )
    headers["Idempotency-Key"] = "future"
    assert (
        client.post(
            f"/tasks/{task['task_id']}/transition",
            json={"expected_version": changed.json()["version"], "target": "approved"},
            headers=headers,
        ).status_code
        == 409
    )
    assert client.post("/approvals", json={"approved": True}, headers=headers).status_code == 404


@pytest.mark.parametrize(
    "body", [{"approved": True}, {"schema_version": 2}, {"schema_version": True}]
)
def test_unknown_fields_and_unsupported_versions_are_rejected(local_api, body):
    client, db, settings, token = local_api
    _, headers = pair(client, settings, token)
    response = client.post("/fixtures", json=body, headers=headers)
    assert response.status_code == 422
    assert "approved" not in response.text
    assert client.get("/status").json()["tasks"] == []


def test_logout_revokes_persisted_session(local_api):
    client, db, settings, token = local_api
    _, headers = pair(client, settings, token)
    saved_cookie = client.cookies[COOKIE_NAME]
    assert client.post("/auth/logout", json={}, headers=headers).status_code == 200
    assert (
        client.get("/status", headers={"Cookie": f"{COOKIE_NAME}={saved_cookie}"}).status_code
        == 401
    )
    with db.read() as connection:
        assert connection.execute(select(sessions)).first() is None


def test_pairing_race_consumes_exactly_once(local_api):
    client, db, settings, token = local_api

    def exchange():
        try:
            return auth.exchange_pairing(db, settings, token).user_id
        except NexusError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange(), range(2)))
    assert results.count("pairing_invalid") == 1
    with db.read() as connection:
        assert len(connection.execute(select(sessions)).all()) == 1


def test_pairing_failure_rolls_back_consumption_and_session(local_api, monkeypatch):
    client, db, settings, token = local_api
    original = auth.record_event

    def fail(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(auth, "record_event", fail)
    with pytest.raises(RuntimeError, match="injected"):
        auth.exchange_pairing(db, settings, token)
    with db.read() as connection:
        assert connection.execute(select(pairing_tokens)).first() is not None
        assert connection.execute(select(sessions)).first() is None
    monkeypatch.setattr(auth, "record_event", original)
    auth.exchange_pairing(db, settings, token)


def test_errors_and_request_logs_do_not_echo_secrets(local_api, monkeypatch):
    client, db, settings, token = local_api
    _, headers = pair(client, settings, token)
    events = []
    monkeypatch.setattr("nexus.api.safe_log", lambda *args: events.append(args))
    response = client.post(
        "/fixtures?password=secret-query", json={"password": "secret-body"}, headers=headers
    )
    assert response.status_code == 422
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]
    assert "secret" not in response.text + json.dumps(events)

    def storage_failure(*args):
        raise OperationalError(
            "secret-statement", {"password": "secret-db"}, RuntimeError("secret")
        )

    monkeypatch.setattr(client.app.state.foundation, "fixture", storage_failure)
    response = client.post("/fixtures", json={}, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "secret" not in response.text + json.dumps(events)

    def unexpected_failure(*args):
        raise RuntimeError("secret-unexpected")

    monkeypatch.setattr(client.app.state.foundation, "fixture", unexpected_failure)
    response = client.post("/fixtures", json={}, headers=headers)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text + json.dumps(events)
