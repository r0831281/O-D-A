# Architectural decisions and assumptions

Prepared 2026-10-20. `Accepted design` means recommended for implementation, not already built. Revisit decisions with measured evidence and record the replacement, not an unbounded alternatives list.

| ADR | Status | Decision and rationale | Trade-off / revisit trigger |
| --- | --- | --- | --- |
| ADR-001 | Accepted design | Python 3.12+ modular monolith: FastAPI/Pydantic, synchronous SQLAlchemy 2/Alembic, one separate worker process from same package | Sync DB calls run off async request path; short transactions. No distributed broker until queue load demands it |
| ADR-002 | Accepted design | SQLite WAL on local disk; portable types and explicit transactions | One worker, bounded concurrency. PostgreSQL when multi-host operation or sustained lock contention is measured |
| ADR-003 | Revised design v2 | Provider-neutral NEXUS RuntimeAdapter; OpenCode native HTTP is first/default implementation; optional ACP transport requires its own verified adapter | Harness selection is configuration for supported adapters; no universal feature equivalence or live-session switching. Additional production adapters follow need |
| ADR-004 | Accepted design | SvelteKit/TypeScript/Tailwind static client served same origin by FastAPI | No SSR needed for private local tool. Node only build/test time; revisit for authenticated server rendering |
| ADR-005 | Accepted design | HTTP commands plus SSE durable events; snapshot/replay recovery | Bidirectional socket adds complexity without current need; runtime SSE is separately ingested/reconciled |
| ADR-006 | Accepted design | Mission Control and Focus are presentation shells over one domain store/services | More design work than a single shell; identical authorization and critical actions required |
| ADR-007 | Accepted design | Canvas2D aggregated reactor; CSS/DOM for controls and semantic diagrams | Add PixiJS/Three.js only if profiled visual needs justify bundle/GPU costs |
| ADR-008 | Accepted design | OS launchd scheduling, persistent SQL jobs and leases | No scheduler inside HTTP lifespan and no essential FastAPI BackgroundTasks; Linux systemd path later |
| ADR-009 | Accepted design | Read-only planning; sandboxed worktree execution with human-bound grant | Worktree alone is unsafe; implementation disabled without tested sandbox boundary |
| ADR-010 | Accepted design | Immutable evidence/snapshots plus mutable current projections, not full event sourcing | Easier queries/recovery; transitions still emit audit/outbox in same transaction |
| ADR-011 | Accepted design | Explicit equivalence links only; daily view over persistent tasks | Conservative duplicate handling may require human linking |
| ADR-012 | Accepted design | Separate execution and exact-payload external-write grants | More explicit decisions; prevents a plan approval from authorizing remote changes |
| ADR-013 | Accepted design | Costs/allowances retain source semantics, unknowns and versions | Some graphs/scores remain unavailable until reliable evidence exists |
| ADR-014 | Accepted design | Deterministic, versioned efficiency score, conditional on quality and comparable cohorts | No causal model ranking, no score in cold start; weights are hypotheses |
| ADR-015 | Accepted design | Single local operator, authenticated loopback API, same-origin UI | Not a multi-user product; remote server requires TLS/auth/deployment review |
| ADR-016 | Accepted design | Odoo 19 JSON-2; 17/18 RPC by version-specific adapter; no generic arbitrary-method proxy | More fixtures, avoids pretending APIs are uniform |
| ADR-017 | Revised default v2 | Tempo planning allocations → Jira issues; helpdesk requirements from Jira, project requirements from explicitly linked Odoo tasks. Outlook/Google optional alternative/context calendars | Cloud Capacity Planner candidate must match actual product/account; classification/link fields and tenant mappings verified in setup; ICS demo remains available |
| ADR-018 | Accepted design | Active instances do not load repository OpenCode config, plugins, skills or hooks | Trusted NEXUS policy has priority; repository prose is evidence, not execution policy |
| ADR-019 | Accepted design | M1 plan review acceptance is distinct from later implementation authorization | Allows useful first slice without an incomplete launch security flow |
| ADR-020 | Accepted design | State/telemetry instrumentation starts before analytics UI | Avoids losing historical attempts and failures needed for meaningful scores |
| ADR-021 | Accepted design v2 | Typed versioned connections and planning profiles separate schedule, work identity, requirements and repository authorities | Known adapter changes require configuration only; a new API needs a reviewed backend adapter. No arbitrary mapping code |
| ADR-022 | Accepted design v2 | Read-only setup discovery/tests and preview, optional AI draft assistant, explicit human activation/rollback | Manual bootstrap required; no secrets in agent chat, automatic provider settings changes or self-approved activation |
| ADR-023 | Accepted design v2 | Capacity allocations and daily effort are distinct from exact calendar appointments | Never invent clock slots or evenly distribute period effort without provider evidence |

## Defaults to implement as typed configuration

Timezone `Europe/Brussels`; morning 07:30 weekdays; sync every 15 minutes with startup catch-up; one implementation at a time and one concurrent read-only agent (total two); one worker process; bounded connector HTTP concurrency four; grant validity 24 hours; connector freshness at execution at most five minutes followed by a live re-read; job lease 60 seconds/heartbeat 15 seconds; active-time limits requirements/planning/implementation/review five/15/45/15 minutes configurable per role; human-wait expiry seven days. These are product defaults, not provider limits or measured performance claims.

Runtime version is a candidate until the compatibility gate in `OPENCODE_INTEGRATION.md` passes. Do not pin `latest`, infer endpoint names from an unrelated SDK generation, or auto-upgrade runtime/plugins.

## Open decisions that really need the developer

| Decision | Needed by | Default until resolved |
| --- | --- | --- |
| Jira Cloud/Data Center, account and project/field mappings | Phase 2 live connector | Cloud fixtures only |
| Tempo product/deployment, account and planning access | Phase 2 live planning | Tempo schedule authority confirmed; Cloud Planner candidate, account/product probe still needed |
| Jira helpdesk/project classification and Jira→Odoo reference fields | Phase 2 live routing | Typed profile draft; absent/ambiguous link blocks Odoo-routed work |
| Outlook/other calendar connection | Only when selected | Optional context/alternative source; no calendar account required for Tempo workflow |
| Odoo instances, versions, company/project restrictions, subscription/API rights | Phase 2 live connector | No live access; 17/18/19 fixtures |
| Repository paths, allowed Odoo branches/addons, installed-module inventory | Phase 3 live planning | Explicit test repository only; unknown inventory labeled |
| Provider/model policy and permission to transmit client code/tickets | Phase 3 hosted inference | Simulated runtime, no live content transmission |
| Container/VM engine and allowed test environment | Phase 6 | Execution disabled; do not fall back to host execution |
| Remote server identity/access policy | Server migration | Loopback-only single operator |

Do not ask these as prerequisites for creating Phase 1. A later Codex session should request only the configuration its current live integration actually needs.

## Revision 2 change record

Developer clarified on 2026-10-20 that Tempo in Jira supplies planning, helpdesk requirements are Jira tickets and project requirements are Odoo tasks. This replaces the speculative Google-first default and accepts the preceding harness-agnostic/configurable-connections discussion. Existing NX-001–NX-050 IDs are retained; NX-051–NX-055 are inserted by dependency in Phases 2–4. No implementation existed to migrate. See `CONNECTIONS_AND_PROFILES.md` for source authority and activation rules.

## Verified capability versus assumption

### Phase 1 implementation record — 2026-10-21

- ADR-001/002/010/015 implementation is authored in `src/nexus`, pending runtime
  acceptance. SQLAlchemy **Core** is used instead of ORM entities: short connection
  transactions and explicit version predicates avoid an unnecessary repository/ORM
  layer for this slice. This does not change service or future adapter boundaries.
- Phase 1 creates only the documented foundation subset. Source identities are
  adapter/instance/type/remote-ID scoped; connection/profile revisions arrive in
  Phase 2. The sole source is an explicitly inserted simulated fixture identity.
- Runtime/dev versions are pinned in `pyproject.toml` and hash-locked in `uv.lock`;
  selected versions are recorded in `PHASE1_VERIFICATION.md`. Build backend is pinned
  Hatchling 1.27.0. No OpenCode pin or schema exists yet because adapters are excluded.
- Public readiness/planning/approval/execution is disabled. The only Phase 1 task
  mutation records clarification and an orthogonal hold. Pure graph guards describe
  future evidence requirements; there is no public evidence/approval boolean.
- Pairing and session hashes add the minimal authentication tables required before
  exposed mutations. Tokens are printed only by an explicit local `pair` command;
  JSON request limits and Host/Origin/CSRF checks precede domain commands.
- The pinned `verification/Dockerfile` is development tooling, not a NEXUS execution
  adapter or a certified runtime boundary. Phase 1 acceptance passed inside its
  network-disabled, non-root disposable container; no global service was installed.
  The executable temporary filesystem is limited to the container's ephemeral `/tmp`
  because the clean virtual-environment interpreter must execute there.
- SQLite UTC text is implemented; PostgreSQL native timestamp portability remains
  unverified and will need its own adapter/portability checks before migration.
  Fingerprint repository bindings are not verified execution bindings in this slice.
- Migration `0001_foundation` passed fresh and repeated file-backed migration checks
  and is packaged in the installed wheel. No real application state was migrated or
  reset. Later changes require additive versioned migrations.

### Phase 2 implementation record — 2026-10-21

- Migration `0002_source_sync` adds typed connection/profile revisions, read-test and
  activation evidence, source cursors/pages/snapshots, persistent allocation/calendar
  projections, daily views and NX-011 task resolution/allocation history. Phase 2
  behavior and the installed-wheel run are recorded in `PHASE2_VERIFICATION.md`.
- Jira Cloud, Odoo 17/18 RPC, Odoo 19 JSON-2, Tempo Cloud Planner candidate, and local
  ICS adapters share provider-neutral read contracts. Provider credentials remain
  environment secret references. No live account was tested; Tempo remains blocked
  until the actual product/account probe confirms compatibility.
- NX-011 uses the Jira issue as canonical task identity, with Odoo task snapshots as
  project-requirements provenance and Tempo allocation snapshots as separate schedule
  associations. Profile rules explicitly bind a local project and repository-binding
  IDs; the service validates those IDs and does not infer them from titles or source
  IDs. Changed source/profile evidence appends a resolution history row. No live account
  or existing customer database was migrated; an intermediate, already-applied
  development `0002_source_sync` would need an additive migration before deployment,
  and old profile drafts must be updated with explicit local binding IDs.

Official API sources and verification notes are in `ARCHITECTURE.md` and `OPENCODE_INTEGRATION.md`. Public API existence was researched; no private Jira/Odoo/calendar account, installed OpenCode build, real provider billing feed, or sandbox was tested. Odoo installed modules cannot be established from a Git manifest alone. A local scheduler cannot run a powered-off laptop. Subscription allowances are unknown unless officially observed. Planning documents are a design, not a security certification or load-test result.
