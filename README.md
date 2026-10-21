# NEXUS — Phase 2 source synchronization

Phase 1 passed its exit criteria. Phase 2 adds typed source connections, planning
profiles, read-only synchronization, canonical task resolution, ICS import and
daily/window projections. The complete fixture-scope Phase 2 exit passed in the hardened container;
see [Phase 1 evidence](docs/PHASE1_VERIFICATION.md) and
[Phase 2 evidence](docs/PHASE2_VERIFICATION.md). No Phase 3 work is included.

This is one Python package with synchronous SQLAlchemy Core, one SQLite database and
an explicitly invoked no-op worker. It has read-only source adapters but no runtime adapters, AI agents,
frontend, execution grants, external writes, automatic scheduling or OS services.
OpenCode is the intended first future adapter; no core module imports or invokes it.

## Prerequisites and dependency installation

Use Python 3.12+ (development target **3.12.11**) and **uv 0.11.26**. The runtime and
development dependency graph is pinned and hash-locked in `uv.lock`. Supported state
storage is a local POSIX filesystem on macOS/Linux, not a network share. Python 3.13/3.14,
Windows and PostgreSQL have not been verified.

The following installs only locked third-party wheels. It does not execute a repository
build backend, hooks, plugins or tests. Run from the repository root:

```sh
cd /Users/jonas/Desktop/NEXUS
uv --version
uv sync --frozen --no-install-project --no-build --python 3.12.11
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
.venv/bin/python -c 'import nexus; print(nexus.__version__)'
```

Use `.venv/bin/python -m nexus.cli` for all commands below. `pyproject.toml` also
declares a `nexus` console entrypoint covered by the prepared isolated package probe. The
packaged Alembic migration lives inside `src/nexus/migrations`; there is no ambient
Alembic DSN or automatic startup migration.

## Migrate, bootstrap and serve

Choose a new private state directory outside the checkout. The CLI creates the final
directory as `0700` and the database as `0600`. Existing unsafe permissions, symlink
ancestors and multiply linked database files are rejected, not silently repaired.
Resolve `/tmp` or `/var` aliases before passing macOS temporary paths.

```sh
export NEXUS_STATE_DIR="$HOME/.local/share/nexus"
.venv/bin/python -m nexus.cli migrate
.venv/bin/python -m nexus.cli pair
.venv/bin/python -m nexus.cli serve
```

`pair` prints a one-time, five-minute pairing capability to the local terminal. Treat
that explicit output as a secret; do not paste it into a ticket, URL or command history.
Issuing another capability invalidates the unused previous one. Startup creates no
fixtures. `serve` requires the packaged migration head and binds only the configured
loopback origin, default `http://127.0.0.1:8765`.

Typed environment settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXUS_STATE_DIR` | `~/.local/share/nexus` | Absolute private state directory |
| `NEXUS_ORIGIN` | `http://127.0.0.1:8765` | Exact loopback HTTP origin, including port |
| `NEXUS_TIMEZONE` | `Europe/Brussels` | Valid IANA timezone; no scheduling yet |
| `NEXUS_BUSY_TIMEOUT_MS` | `5000` | SQLite lock wait, 1–30000 ms |
| `NEXUS_PAIRING_SECONDS` | `300` | One-time capability lifetime, 1–600 seconds |
| `NEXUS_SESSION_SECONDS` | `43200` | Session lifetime, 1–86400 seconds |
| `NEXUS_LEASE_SECONDS` | `60` | Fixture lease lifetime, 1–600 seconds |

Configuration does not contain connector credentials. Contracts reject unknown fields
and unsupported schema versions. Version 1 canonical hashes normalize Unicode to NFC,
sort object keys, use integer values and reject floats and duplicate normalized keys.
Source identity includes adapter, instance, remote type and immutable remote ID.
No repository commit has been verified or authorized by the fixture manifest.

## Phase 2 source setup and planning

After migrating, the operator CLI supports `source-discovery`, `connection-draft`,
`connection-test`, `profile-draft`, `profile-preview`, `profile-activate`,
`profile-rollback`, `source-sync`, `source-sync-request`, `planning-resolve`,
`planning-day`, `planning-window` and `calendar-import`. Drafts are strict versioned JSON files.
Credential fields are rejected; provider credentials are resolved from explicitly
named `NEXUS_SECRET_*` environment variables at read time and are never stored in the
database or sent to agents. Odoo connection and profile scopes require explicit
company/project IDs. Each planning classification rule names a local NEXUS project
and explicit repository-binding IDs; the IDs must point to enabled repositories linked
to that project. The Jira issue is the canonical task identity. For project work, the
explicitly linked Odoo task snapshot is requirements provenance; each Tempo allocation
and snapshot is stored as a separate planning association. Tempo live use remains
blocked until the selected Tempo product and account are verified. No provider was
live-tested in Phase 2.

`connection-test` performs allowlisted read checks only. `profile-preview` accepts
fixture cases and records a redacted preview. Activation requires a complete preview
and fresh connection-read tests, and records the local operator. Rollback creates a
new activation event and requires resynchronization. `planning-day` and
`planning-window` accept fixture JSON with `freshness`, `allocations` and `schedules`
arrays and mark their output simulated. Date/effort capacity remains separate from
clock appointments. `planning-resolve PROFILE_REVISION_ID JIRA_EXTERNAL_ITEM_ID`
materializes current source evidence into a Jira-keyed canonical task and immutable
resolution history; missing or inaccessible Odoo requirements keep that task blocked.
`calendar-import` parses a local ICS file, persists recurrence
occurrences and reconciles only the complete file supplied by that command.

The authenticated local API also exposes `POST /source-sync-requests`,
`GET /source-sync-requests/{request_id}`, `GET /planning/days/{local_date}` and
`GET /planning/windows/{start_date}`. These local reads/queues do not write to external
providers. Canonical resolution uses explicit NX-011 local project/repository
bindings and the `planning-resolve` operator command.

## HTTP contract

| Route | Authentication / behavior |
| --- | --- |
| `GET /health` | Public minimal API/DB reachability; execution explicitly disabled |
| `POST /auth/pair` | One-time capability → HttpOnly, SameSite=Strict session cookie and CSRF token |
| `POST /auth/logout` | Session and CSRF; durable revocation |
| `GET /status` | Session; safe task/job/audit/outbox projections |
| `POST /fixtures` | Session, CSRF and `Idempotency-Key`; explicit simulated task |
| `POST /tasks/{id}/enqueue` | Same protections; only `fixture_noop` |
| `POST /tasks/{id}/transition` | Same protections; `expected_version` and `target` |

All requests require the exact configured Host. Every mutation requires the exact
Origin, JSON Content-Type and Content-Length, with a 16 KiB received-body limit.
Authenticated mutations also require `X-CSRF-Token`. Pairing uses the one-time
capability to bootstrap CSRF protection. There is no CORS, bearer token in a URL,
localStorage credential, arbitrary shell route or generic authorization endpoint.

Pair body: `{"schema_version":1,"token":"<capability>"}`. The returned CSRF token
belongs to that cookie session. Fixture/enqueue/logout bodies are `{"schema_version":1}`.
Transition body: `{"schema_version":1,"expected_version":1,"target":"needs_clarification"}`.
Version defaults to 1 when omitted; `true`, strings, unsupported versions and unknown
fields such as `approved` are rejected. The only public lifecycle change in Phase 1
is `imported → needs_clarification`, which records an operator hold. Future graph
edges exist as pure domain rules but cannot be activated by any public service.

Command replay is scoped to the operator and exact operation/body: the same key
returns the original result; changed content returns `409 idempotency_conflict`.
Stale versions and forbidden transitions return `409`. Safe error envelopes contain
only a fixed code and server-generated correlation ID. Request bodies, headers,
paths, queries, SQL parameters and exception text are excluded from structured logs.
Do not enable Uvicorn access logging or exception-debug middleware.

## Explicit fixture and worker commands

After migration and local pairing bootstrap, use a **disposable** state directory:

```sh
.venv/bin/python -m nexus.cli fixture --key example-task
# Use task_id printed by the previous command:
.venv/bin/python -m nexus.cli enqueue TASK_ID --key example-job
.venv/bin/python -m nexus.cli worker-once
.venv/bin/python -m nexus.cli status
.venv/bin/python -m nexus.cli doctor
.venv/bin/python -m nexus.cli transition TASK_ID needs_clarification --expected-version 1 --key clarify
```

Repeating `fixture --key example-task` returns the same task. Repeating a transition
under a new key with the old version rejects it. `doctor` runs SQLite integrity/FK
checks and reports WAL mode; it grants no execution permission. `worker-once` claims
at most one job, executes the deterministic no-op and exits. No long-running service
or timer is installed. Expired no-op claims are reclaimable with a higher epoch;
exhausted jobs become failed. Heartbeat/start/release/finalize require current owner,
epoch and unexpired lease, checked after acquiring the write lock.

SQLite uses `foreign_keys=ON`, WAL, `synchronous=FULL`, explicit `BEGIN` reads,
`BEGIN IMMEDIATE` writes and bounded lock waits. Commands commit their mutations,
receipts, audit and outbox together. Work happens after releasing the transaction.
Audit/outbox and fingerprint evidence are insert-only through application services;
they are not tamper-proof against an administrator with database access.

## Tests and temporary demonstration — isolated runner only

`AGENTS.md` prohibits repository tests/install scripts on the host. Use a configured
Docker-compatible Linux VM/container engine. The engine is **development verification
tooling**, not a future NEXUS runtime adapter or an installed OS service. Docker
Docker Desktop is used only as the local verification engine; it is not installed or
configured by NEXUS.

Review the small build context allowlist and pinned image before building. Build
network access is for pinned third-party wheels at PyPI; no repository build backend
runs during the image build. Source/tests are copied afterward. The project wheel
build, package probes, tests and demonstration run as
a non-root user, without network or host mounts, with a read-only root and temporary
writable, executable storage for the installed virtual-environment interpreter:

```sh
docker build --pull=false -f verification/Dockerfile -t nexus-phase2-verify .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777 nexus-phase2-verify
```

The default command runs Ruff, then `verification/verify_package.py`. The driver
builds the project wheel twice offline using pinned Hatchling/build dependencies and
a fixed `SOURCE_DATE_EPOCH`, compares SHA-256, and installs into a fresh temporary venv.
That venv reuses only the image's immutable, hash-locked third-party dependencies.
There is no NEXUS installed in the base image and no source-tree `PYTHONPATH`.
A separate isolated interpreter checks installed module provenance, packaged Alembic
resources, repeat migration and the installed `nexus` console entrypoint. It then
runs pytest and the explicit demo from the installed wheel. All temporary build,
installation and state directories are removed on success or failure.

To select only the demo or tests after the same package probe, use the same boundary:

```sh
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777 nexus-phase2-verify \
  python -I /app/verification/verify_package.py --demo-only
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777 nexus-phase2-verify \
  python -I /app/verification/verify_package.py --tests-only
```

The demo creates and automatically removes its own resolved, private temporary
directory. It migrates, bootstraps a local operator without printing the capability,
creates/replays a task, enqueues and completes a no-op job, rejects an illegal edge,
records clarification, rejects a stale writer and inspects persisted state from new
Python processes. Output labels simulation and includes audit/outbox and integrity
results. It never selects the normal state directory. There is no live integration.

The suite covers file-backed migrations and constraints, transactional DDL, UTC
round trips, state/evidence/hold guards, idempotency/CAS races, partial event rollback,
SQLite busy/full failure, worker races/expiry/epoch fencing, restart persistence,
slow work releasing DB transactions, private paths and HTTP authentication/Origin/CSRF.
These are the implemented test contents. Their current execution results and the
verified container settings are recorded in [the Phase 1 evidence report](docs/PHASE1_VERIFICATION.md).
