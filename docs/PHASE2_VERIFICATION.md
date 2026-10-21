# Phase 2 implementation and verification evidence

Date: 2026-10-21. Status: **accepted for fixture scope; live-provider setup remains unverified**.

Phase 1 remains accepted as recorded in `PHASE1_VERIFICATION.md`. Phase 2 was
implemented in the requested order: NX-007, NX-051, NX-008, NX-009, NX-052, NX-010,
NX-011 and NX-012. The current working tree and all pre-existing files were preserved.
No agent, runtime adapter, frontend, approval capability, worktree, external write,
analytics feature or OS service was added.

## Delivered

- NX-007: versioned source item/page/cursor/snapshot contracts; persistent bounded
  sync runs and restart-safe page resume; deduplication; cursor advancement only after
  full success; classified retry delay and safe failure states.
- NX-051: strict typed connection and planning-profile revisions, environment-only
  credential references, adapter discovery/read tests, profile previews, human local
  activation and rollback events, and binding invalidation/resync markers. CLI supports
  discovery, draft, test, preview, activation, rollback and manual sync.
- NX-008: Jira Cloud enhanced search token pagination, configured fields, ADF text
  normalization, immutable issue identity and read-only transport.
- NX-009: versioned Odoo 17/18 XML-RPC and 19 JSON-2 read adapters with explicit
  project/company domains, fields metadata checks, keyset ordering and safe text.
- NX-052: bounded Tempo v4 plan-search adapter candidate, native date/effort precision,
  allocation ID preservation on reschedule/reassignment, account-versus-assignee
  distinction, multiple allocations per issue and project-only capacity context.
  Live Tempo use stays blocked until an actual product/account probe confirms the
  selected deployment and endpoint semantics.
- NX-010: local ICS import persists occurrence snapshots, handles tested recurrence,
  all-day exclusive end dates, cancellation and DST boundaries. Outlook/Google remain
  optional and were not added without selection/credentials.
- NX-011: explicit local project and repository-binding IDs are required on each
  classification rule and validated against enabled local project/repository rows.
  Jira issue identity is the canonical NEXUS task; the Odoo task is requirements
  provenance, not a second canonical task. Each Tempo allocation and immutable source
  snapshot is associated separately. `planning_task_resolutions` stores profile, Jira,
  requirements, repository mapping, routing trace, blockers and hashes; immutable
  `planning_task_allocations` rows preserve allocation history. `planning-resolve`
  materializes or refreshes the Jira-keyed task. Changed links/snapshots append history;
  a missing or inaccessible Odoo link blocks readiness without Jira fallback or title
  matching. A repaired link resolves its prior readiness hold.
- NX-012: persisted local-date daily projections plus upcoming/carry-over windows,
  separate capacity from appointment time, expose source freshness and provide an
  authenticated read API and fixture CLI projection commands.

## Verification actually run

Builds, tests and demos ran in the documented disposable Docker environment. No
repository tests, builds, imports or demos ran on the host. The image was built with
the pinned Python base and locked wheels; verification ran without network or host
mounts, with a read-only root, non-root user, dropped capabilities, no-new-privileges,
resource limits, and only an ephemeral bounded `/tmp`.

```sh
docker build --pull=false -f verification/Dockerfile -t nexus-phase2-verify .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 512m --cpus 2 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777 nexus-phase2-verify
```

Observed results:

- Container image build succeeded; Docker manifest-list digest:
  `1343661625b5099e5f3e35c369167ddf6a3d850e5a8686005f35bd66a58187ed`.
- Ruff passed; all 27 Python files were already formatted. The package driver built
  two offline wheels reproducibly; wheel SHA-256:
  `ac95c0609328f3ce5338b0f887e276b8c681b1eaa89b061be6f58be5187039d5`.
- Fresh isolated wheel installation reported `installed_import`,
  `packaged_migrations` and `entrypoint` true; no source-tree fallback was used.
- Pytest collected **213 tests: 213 passed, 1 warning in 53.91s**. The warning is
  Starlette's `TestClient`/HTTPX deprecation notice.
- The installed-wheel temporary-state demo passed restart persistence, idempotency
  replay, forbidden-transition and stale-version rejection, integrity/FK check, WAL,
  execution disabled and private temporary-state cleanup.
- `git diff --check` passed after the final documentation updates.

Fixture coverage includes pagination/deduplication, failed-page cursor behavior and
retry resume, allocation rescheduling/reassignment, allocated-user versus Jira-assignee
mismatch, multiple allocations per issue, project-only capacity, repeated connection
draft revisions, helpdesk/project routing, explicit local repository binding checks,
missing/ambiguous/inaccessible/invalid Odoo links and repaired-link hold resolution,
profile activation/rollback/invalidation, source-stale daily projection, ICS
recurrence/all-day/DST/cancellation and safe provider error classification. Canonical
association fixtures prove requirement edits and changed Odoo links retain resolution
history, allocation snapshots remain separately traceable, and same-title Jira issues
remain separate tasks.

Actual private Jira, Tempo, Odoo, Outlook or Google accounts were not accessed.
Live-provider coverage is therefore **none**. Tempo is explicitly not enabled pending
the product/account probe. PostgreSQL portability, a deployed/intermediate database
upgrade, and real-account permission or visibility behavior remain unverified.

## Migration and configuration implications

The NX-011 schema additions are included in migration `0002_source_sync` because this
is still the unshipped Phase 2 development branch and clean migration/install checks
pass. No real or persistent application database was migrated. If an earlier
development build already applied an older form of migration `0002_source_sync`, do
not assume Alembic will alter it: an additive follow-up migration is required before
deployment. Existing profile drafts must be revised to include explicit
`nexus_project_id` and `repository_binding_ids`; no local project or repository mapping
can be backfilled safely from titles, Jira/Odoo identities or the opaque mapping
reference. The `planning-resolve` command must be run after activation and source sync;
it does not infer missing provider snapshots or mappings.

Phase 2 exit criteria passed for fixture scope. No Phase 3 work was started.
