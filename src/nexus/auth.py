"""Single-operator local pairing and hashed, expiring sessions."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, insert, select

from nexus.config import Settings
from nexus.domain import NexusError
from nexus.schema import pairing_tokens, sessions, users, utcnow
from nexus.services import record_event
from nexus.storage import Database


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: str
    token_hash: str
    csrf_hash: str


@dataclass(frozen=True)
class PairingResult:
    session_token: str
    csrf_token: str
    user_id: str


def issue_pairing(db: Database, settings: Settings) -> str:
    """Return a one-time capability to an explicit local CLI caller only."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with db.write() as connection:
        operator = (
            connection.execute(select(users).where(users.c.identity == "local-operator"))
            .mappings()
            .one_or_none()
        )
        if operator is None:
            user_id = str(uuid4())
            connection.execute(
                insert(users).values(
                    id=user_id,
                    identity="local-operator",
                    display_name="Local operator",
                    active=True,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
        else:
            if not operator["active"]:
                raise NexusError("operator_inactive", status=403)
            user_id = operator["id"]
        # Rotation invalidates every unused bootstrap capability.
        connection.execute(delete(pairing_tokens))
        connection.execute(
            insert(pairing_tokens).values(
                token_hash=_digest(token),
                user_id=user_id,
                expires_at=now + timedelta(seconds=settings.pairing_seconds),
            )
        )
        record_event(
            connection,
            "auth.pairing_issued",
            user_id,
            1,
            user_id,
            str(uuid4()),
            {},
        )
    return token


def exchange_pairing(
    db: Database, settings: Settings, token: str, correlation_id: str | None = None
) -> PairingResult:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    with db.write() as connection:
        now = utcnow()
        pairing = (
            connection.execute(
                select(pairing_tokens.c.user_id, pairing_tokens.c.expires_at)
                .join(users, users.c.id == pairing_tokens.c.user_id)
                .where(pairing_tokens.c.token_hash == _digest(token), users.c.active.is_(True))
            )
            .mappings()
            .one_or_none()
        )
        if pairing is None or pairing["expires_at"] <= now:
            raise NexusError("pairing_invalid", status=401)
        connection.execute(
            delete(pairing_tokens).where(pairing_tokens.c.token_hash == _digest(token))
        )
        connection.execute(
            insert(sessions).values(
                token_hash=_digest(session_token),
                csrf_hash=_digest(csrf_token),
                user_id=pairing["user_id"],
                expires_at=now + timedelta(seconds=settings.session_seconds),
            )
        )
        record_event(
            connection,
            "auth.session_created",
            pairing["user_id"],
            1,
            pairing["user_id"],
            correlation_id or str(uuid4()),
            {},
        )
    return PairingResult(session_token, csrf_token, pairing["user_id"])


def authenticate(db: Database, token: str | None) -> Principal:
    if token is None or not 32 <= len(token) <= 128:
        raise NexusError("authentication_required", status=401)
    with db.read() as connection:
        session = (
            connection.execute(
                select(sessions)
                .join(users, users.c.id == sessions.c.user_id)
                .where(sessions.c.token_hash == _digest(token), users.c.active.is_(True))
            )
            .mappings()
            .one_or_none()
        )
    if session is None or session["expires_at"] <= utcnow():
        raise NexusError("authentication_required", status=401)
    return Principal(session["user_id"], session["token_hash"], session["csrf_hash"])


def check_csrf(principal: Principal, token: str | None) -> None:
    if token is None or not secrets.compare_digest(principal.csrf_hash, _digest(token)):
        raise NexusError("csrf_invalid", status=403)


def revoke_session(db: Database, principal: Principal, correlation_id: str) -> None:
    with db.write() as connection:
        connection.execute(delete(sessions).where(sessions.c.token_hash == principal.token_hash))
        record_event(
            connection,
            "auth.session_revoked",
            principal.user_id,
            1,
            principal.user_id,
            correlation_id,
            {},
        )
