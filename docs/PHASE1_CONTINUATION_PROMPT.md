# Phase 1 continuation prompt

> Resolved on 2026-10-21. Phase 1 acceptance passed; this file preserves the prompt
> used for that work. Its reported blockers below are historical. See the final
> `Runtime acceptance` section in `PHASE1_VERIFICATION.md` for current evidence.
> No Phase 2 implementation was started.

```text
Finish Phase 1 of NEXUS only in /Users/jonas/Desktop/NEXUS.

Inspect current files and Git status before editing. Preserve every existing change.
Follow active session instructions and applicable parent/repository AGENTS.md.

Read README.md and docs/PHASE1_VERIFICATION.md, IMPLEMENTATION_PLAN.md, BACKLOG.md,
DECISIONS.md, ARCHITECTURE.md, DATA_MODEL.md, SECURITY.md and
CONNECTIONS_AND_PROFILES.md. Read the complete current verification runner too.
Use the latest evidence section rather than treating earlier blockers as current.

Reported baseline to reverify:
- Git was main...origin/main, HEAD f2a3d1b, with preexisting tracked modifications
  and untracked implementation/tests/verification files. Do not reset or discard.
- NX-001–NX-006 remain Verification blocked; no runtime acceptance is established.
- Earlier demo checks and receipt-insertion rollback tests were strengthened.
- The latest session prepared an isolated installed-wheel verification path;
  inspect the current files and evidence to determine its actual execution status.
- Docker CLI 29.9.2 and Docker Desktop were found. The desktop-linux context names
  unix:///Users/jonas/.docker/run/docker.sock. The socket exists and belongs to
  jonas, matching runner uid 501, but Docker commands returned permission denied.
  This is a tool-to-engine access blocker, not evidence Docker is absent.
- The exact README docker build command was attempted and exited 1 with the same
  socket permission denial before building. No container run/test/demo followed.
- The execution transport disconnected/closed transiently but recovered. Recheck
  current access; do not treat a historical transport failure as the remaining cause.
- No Docker socket permissions, execution policies, services or transports were
  changed. No alternate tool was used to bypass the denied connection.
- Static lint/format, syntax parsing and lock checks are not runtime acceptance.

Locate an already permitted disposable verification environment. Use README.md's
pinned Dockerfile and hardened container commands. Do not run repository tests,
builds, install scripts or verification probes on the host, install global
services, weaken security instructions, change socket permissions or substitute
an unauthorized transport/tool to bypass denied access. If access is still denied,
record the exact error and distinguish it from an absent environment.

When the permitted boundary is available, build the verification image and run its
complete default command. Ensure the project build executes offline/non-root in
the disposable container, installs a wheel in a clean environment and imports it
without a source-tree PYTHONPATH fallback. Verify packaged migrations and the
installed console entrypoint. Inspect/fix failures, then rerun relevant checks.
Use current official framework documentation through Context7 when changes require it.

Verify and record actual evidence for:
1. Clean dependency installation/import, wheel installation and packaged resources.
2. Fresh/repeated file SQLite migrations, constraints, WAL, foreign keys, explicit
   transactions and UTC timestamps.
3. Allowed/forbidden transitions, missing evidence, holds and stale versions.
4. Concurrent idempotency replay, changed-body conflicts and atomic rollback of
   mutation/receipt/audit/outbox, including after receipt insertion.
5. Concurrent claims; heartbeat/start/release/finalization fencing; expiry;
   restart recovery; and no transaction during slow work.
6. Authentication, pairing replay/expiry, Host, Origin, CSRF, strict schemas and
   secret-safe errors/logging.
7. Locked/full SQLite failure handling and private state-path protections.
8. Explicit CLI demonstration in automatically removed temporary private state:
   restart persistence, idempotency replay, no-op completion, exact invalid/stale
   rejection, integrity and cleanup evidence. Run false-evidence regressions too.

Record exact commands, exit/results and gaps in docs/PHASE1_VERIFICATION.md.
Advance backlog acceptance only when proof exists. Document material deviations
and migration implications. Keep the domain provider-neutral. Never add client
approval booleans or permissive authorization placeholders.

Exclude later phases: live connectors, runtime adapters, AI agents, frontend,
implementation worktrees, external writes, analytics and OS services. Stop after
Phase 1. Report changes, actual verification/demo results, limitations, whether
every exit criterion passes, and a complete next-session prompt. If incomplete,
provide a complete Phase 1 continuation prompt with the current exact blocker.

Only if every Phase 1 exit criterion passes, provide a ready-to-copy prompt for
Phase 2 only, derived from the latest documents, with scope, dependencies,
acceptance tests and exclusions. Use this order:
NX-007, NX-051, NX-008, NX-009, NX-052, NX-010, NX-011, NX-012.

Preserve in that prompt:
- Tempo allocations linked to Jira issues supply planning.
- Jira tickets supply helpdesk requirements.
- Explicitly linked Odoo tasks supply project requirements.
- Connections, routing and planning profiles are configurable and testable.
- Missing/ambiguous Odoo links block readiness.
- Outlook/Google calendars are optional.
- Date/effort allocations never become invented clock appointments.
- Phase 2 stops at its boundary and supplies the subsequent phase prompt.
```
