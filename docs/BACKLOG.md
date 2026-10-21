# Ordered implementation backlog

Updated 2026-10-21: NX-001–NX-006 are **Done** after clean installed-wheel verification, 187 passing tests and the isolated temporary-state demo. See `PHASE1_VERIFICATION.md`. All Phase 2 tickets NX-007, NX-051, NX-008, NX-009, NX-052, NX-010, NX-011 and NX-012 passed fixture-scope acceptance in the hardened container; see `PHASE2_VERIFICATION.md`. Live provider configuration remains unverified. Stable IDs never change when a ticket moves; append new IDs for additional work. Revision 2 adds NX-051–NX-055 without renumbering existing tickets. Do not start Phase 3 work without a separate request.

Priority: P0 = foundation/safety/first usable planning workflow; P1 = controlled implementation or trustworthy telemetry; P2 = analytics/operational polish. P2 does not mean optional where explicitly required by a phase. No effort estimates are asserted before implementation discovery.

## Phase 1 — Core foundation

Status for every ticket in this table: **Done**. NX-001 has a pinned lock, typed
settings, app and CLI; NX-002 a frozen migration; NX-003 state/hash/CAS; NX-004 atomic
commands and local auth; NX-005 a fenced no-op worker; NX-006 tests/demo, logging and
runbook. The installed wheel, migration resources, runtime suite and demo passed in
the hardened disposable container. See `PHASE1_VERIFICATION.md`.

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-001 | P0; none | Bootstrap Python package, app factory, typed settings, private state paths, CLI and reproducible dependency lock. Add README exact commands and ignore runtime/secret/build files. Resolve current dependencies using official docs. | Clean install/import, invalid config safe error, health response; no live network/account prerequisite |
| NX-002 | P0; NX-001 | SQLAlchemy/Alembic database setup and Phase 1 subset migration: local user, project/repository/source identities, task/fingerprint/hold, artifact, jobs/receipts, audit/outbox. Set explicit transaction control, WAL, FKs and busy timeout. | Migrate fresh file DB; FK/unique/check constraints reject malformed data; rollback and supported migration checks |
| NX-003 | P0; NX-002 | Domain state enums/transition guards, typed fingerprints/canonical hash, task projection/version-CAS service. Future implementation edges require unavailable capabilities and have no public activation path. | Table-driven legal/illegal/missing-evidence checks; hash stability and meaningful-change tests; two stale writers conflict |
| NX-004 | P0; NX-003 | Atomic command transaction with principal-scoped idempotency receipt, audit/outbox and safe errors; local pairing/session/Origin/CSRF for any exposed mutation endpoints. | Repeat command returns same entity; same key changed body conflicts; injected failure commits none; unauthorized mutation denied |
| NX-005 | P0; NX-004 | Persistent enqueue/claim/heartbeat/release/finalize with lease epochs and short SQLite claims. Add deterministic fake no-op job handler; no agent/runtime handler. | Two claimers yield one lease; stale epoch cannot finalize; restart can inspect/reconcile expired no-op job; no transaction spans slow work |
| NX-006 | P0; NX-001–005 | Foundation integration fixtures, redacted correlation logs, temporary-state demo and actual run/test/migration documentation. Keep fixture insertion explicit. | Run Phase 1 demo/restart/rollback tests and report evidence; inspect no connector/agent/frontend code introduced |

## Phase 2 — Source synchronization

Status: **Done for fixture scope; live provider setup remains unverified.** Evidence is recorded in `PHASE2_VERIFICATION.md`.

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-007 | P0; NX-006 | Add connector snapshot/cursor/page/error contracts, source config/secret references, source schema and manual sync jobs/doctor. Implement bounded page persistence and retry classes. | Failed page does not advance cursor; repeated pages deduplicate; 401/429/timeout fixtures classify correctly. **Done** |
| NX-051 | P0; NX-007 | Typed connection/profile revision schemas, adapter discovery/test contracts, explicit authority/classification/link resolvers, CLI draft/test/preview/activate/rollback and private secret references. Human activates local config; test reads only. | Representative fixture preview traces; invalid/ambiguous mappings block; failed test leaves active profile intact; manual bootstrap works without AI. **Done** |
| NX-008 | P0; NX-007 | Jira Cloud read-only adapter: enhanced JQL pagination, account/project/field discovery, ADF safe normalization and exact issue reconciliation. | Token pagination and ADF normalization fixtures. Live Jira, field-discovery drift and provider visibility behavior remain unverified. **Done for fixture scope** |
| NX-009 | P0; NX-007 | Odoo read-only version adapters: RPC 17/18 and JSON-2 19, fields_get validation, configured task planned/acceptance fields, project/company scoping and write_date reconciliation. | Version contract fixtures, explicit company/project scope and stable cursor. Live rights and deployment behavior remain unverified. **Done for fixture scope** |
| NX-052 | P0; NX-008, NX-051 | Tempo allocation adapter for verified deployment/product; initial Cloud candidate uses official v4 planning reads. Resolve numeric Jira issue IDs for allocated account; persist date/effort precision and native daily breakdown; reconcile moves/reallocation/removal. | Fixture paging/reschedule/reassignment, assignee mismatch and project-only capacity pass. Live adapter remains blocked pending product/account probe. **Done for fixture scope** |
| NX-010 | P0; NX-051 | Provider-neutral calendar/context contract plus local ICS demo import, occurrence identity, cancellations and timezone rules. Outlook/Google live adapters are optional follow-up work when selected, using verified provider sync semantics. | ICS recurring/all-day/DST/cancellation fixtures pass; Outlook/Google were not selected. **Done** |
| NX-011 | P0; NX-008–010, NX-051–052 | Profile-driven canonical associations: Tempo schedule→Jira issue, Jira helpdesk requirements, explicit Jira→Odoo project-task requirements and repository mapping. Preserve resolution/source/allocation evidence history and profile/source hashes. | Explicit local project/repository-binding IDs validated; Jira-keyed canonical task, Odoo requirements provenance, allocation snapshot associations, changed-link history, same-title separation and missing-link hold/recovery pass. **Done for fixture scope** |
| NX-012 | P0; NX-011 | Daily/upcoming/carry-over projections, deterministic priority, freshness health, safe query/manual-sync API and CLI fixture demo. | Daily/window fixture projection, separate capacity/clock semantics, stale state and authenticated read/manual-sync surfaces pass. **Done for implemented projection scope** |

## Phase 3 — Read-only OpenCode agents

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-053 | P0; NX-012 | Minimal RuntimeAdapter contract/registry, versioned connection and role/project selection, capability test reports and generic runtime session identity. Fake alternate harness exercises unchanged domain API; no second live adapter required. | OpenCode details stay within first adapter; unsupported telemetry remains unknown; unverified cancel/isolation blocks implementation; selection change cannot mutate approved/live run |
| NX-013 | P0; NX-053 | Pin/probe official OpenCode runtime and extension dependencies. Capture OpenAPI schema/digest, auth/session/prompt/event/message/abort/structured-output/tool/accounting compatibility manifest. | Real disposable runtime probe passes; mismatched schema disables starts; no generation-mixed endpoints |
| NX-014 | P0; NX-013 | Read-only runtime supervisor, sanitized config/home/source export, private network/provider policy, broker read/search/report tooling. Disable arbitrary shell/write/delegation/native question paths. | Malicious repository plugin/AGENTS/config/symlink/write fixtures fail safely; host/source hashes unchanged; secrets unavailable |
| NX-015 | P0; NX-014 | Run/segment/session/dispatch-intent persistence, bounded Python HTTP/SSE adapter, reconciliation/abort/checkpoint lifecycle and first accounting receipts/time intervals. | Lost prompt response becomes uncertain; disconnect/restart recovers one report/accounting identity; actual descendant stop proved |
| NX-016 | P0; NX-015 | Requirements role, strict schema/evidence validation, extracted/proposed criteria distinction, readiness/conflict/risk/questions and one bounded report repair. | Clear/incomplete/conflicting/unsupported instruction fixtures; invalid/oversized report rejected; no invented acceptance approval |
| NX-017 | P0; NX-016 | Odoo-aware planner with exact repository manifests, safe static inspection, affected paths/methods/tests/risks/assumptions and immutable plan revisions. | Version/dependency/report/security/controller fixture coverage; unknown installed modules labeled; plan/source/base hashes reproducible |
| NX-018 | P0; NX-017 | Minimal persistent planning questions/conditions, CLI answer/reject/resume, analysis/plan CLI/API projections and full M1 backend scenario. | Crash while question open; duplicate answer causes one continuation; source edit supersedes plan; source remains unchanged |
| NX-054 | P0; NX-018, NX-051 | Optional setup-assistant role over trusted connection discovery/test/draft services; explain mapping and failed tests, propose typed profile revisions, no activation/credential/external-write authority. | Helpdesk/Odoo routing proposals match evidence; injected provider instructions cannot broaden tools; no secret in prompt; human/manual authentication+activation remain available |

## Phase 4 — Shared dashboard and first usable MVP

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-019 | P0; NX-018 | SvelteKit static client/TypeScript/Tailwind design tokens, accessible semantic primitives, typed API/auth command client and AppShell-scoped store. | Static build same origin; no singleton SSR data leak; safe errors/401; Vitest selectors and component semantics |
| NX-020 | P0; NX-019 | DB snapshot/high-water and authenticated replayable SSE endpoint plus one browser reducer/reconnect client; bounded event/log buffers. | Event during snapshot/toggle applied once; duplicate/out-of-order versions ignored; expired cursor resync and offline banner |
| NX-055 | P0; NX-020, NX-054 | Shared Connections, Planning Profiles and Runtime Settings UI: guided auth, capability tests, sample-day source trace, profile diff/impact preview, activate/rollback, stale/error states in both modes. | No dashboard edits switching installed adapters; bad/missing links visible; human activation version-checked; running sessions frozen; no duplicate history/memberships on rollback |
| NX-021 | P0; NX-055 | Focus layout: today/upcoming, calendar day/week/timeline, attention list, task plan/criteria/source/session detail, search/filters/keyboard. | Keyboard morning journey, empty/loading/stale/error states, provenance and smaller-screen controls |
| NX-022 | P0; NX-021 | Mission Control layout over same components/store: overview cards, meaningful agent network/status and lightweight activity reactor placeholder. Add no-reload toggle, URL context and persisted preferences. | Same task/filter/live state preserved across repeated toggles; critical actions identical; Focus/hidden tab stops rendering |
| NX-023 | P0; NX-022 | Plan accept/request-changes review service and UI, version conflicts/history, question forms and read-only run details. Do not create execution grants. | Both modes review same revision; stale request conflicts; changed plan request queues replan; launch visibly unavailable |
| NX-024 | P0; NX-019–023 | M1 journey suite, fixture-backed real-time demo, responsive/manual keyboard/screen-reader checks and measured baseline performance. | All Phase 4 parity tests; reduced motion and 360px width; first usable import→analysis→plan→human review demo |

## Phase 5 — Authorization and persistent decisions

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-025 | P1; NX-024 | Immutable execution envelope/grant/revocation/consumption migrations and user-only approval service. Bind all repositories, policy/image/runtime adapter/build/capability hashes, planning profile/routing/config revisions, limits and expiry. | Approval mutation/reuse/expiry/stale-config/source/base rejected; CAS races create one run/job; agent cannot issue grant |
| NX-026 | P1; NX-025 | Preflight freshness/source/base checks, durable launch intent, capability epochs, repository admission lock and budget reservation foundations using fake executor only. | Unreachable upstream prevents launch; changed base/source between approval/start denied; late fenced result rejected |
| NX-027 | P1; NX-026 | Full human question categories/answer revisions/conditions/expiry, checkpoint stop and same-run continuation; explicit scope expansion and expired-grant renewal. | Kill at question/answer/stop/continuation boundaries; no active provider while waiting; duplicate/late answer safe; no scope escalation |
| NX-028 | P1; NX-027 | Both-mode approval/attention/history UI and run pause/cancel/resume/retry controls with honest availability and stop acknowledgment. | Identical authorization backend in both modes; retry fresh grant; pause is checkpoint stop; stop failure quarantines |
| NX-029 | P1; NX-028 | External draft revisions and separate exact-payload approval/preview, target freshness and immutable send-intent schema. Keep actual sending disabled. | Code grant cannot send; draft edit invalidates write grant; payload/target changes require new review; fake-only delivery |

## Phase 6 — Sandboxed code changes and review

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-030 | P1; NX-029 | Worktree creation/archive/quarantine and platform sandbox boundary. Hide common Git metadata, sanitize source export, enforce non-root/mount/network/resource/credential controls and real-stop escalation. | Dirty host untouched; malicious script/config cannot escape/read secrets; descendants terminated; unavailable sandbox disables launch |
| NX-031 | P1; NX-030 | Broker patch application and read views with scoped normalized paths/no-follow descriptors, expected blobs, atomic writes and final diff/tree-scope verification. | Traversal/symlink/hardlink/delete/rename/mode/binary/oversize fixtures; out-of-scope edits blocked before change |
| NX-032 | P1; NX-031 | Isolated verification profiles, pinned dependency/test images, disposable Odoo DBs, no-secret/no-network test containers and trusted structured test receipts. | False agent pass rejected; timeout/kill/counters/report hashes; repo tests cannot access host/provider/connector secrets |
| NX-033 | P1; NX-032 | Approved implementation role and segment/checkpoint recovery, exact envelope tool admission, candidate/diff snapshots, episode/complexity/first-pass/time/corrective facts. | Successful fixture patch plus blocker continuation; retry requires grant; source change stops; unknown restart does not duplicate run |
| NX-034 | P1; NX-033 | Separate frozen-candidate reviewer, evidence-linked findings, human acceptance/change request/regression records and criteria/check coverage. | New patch invalidates review/test; required evidence/independent review before acceptance; waivers visible and not passes |
| NX-035 | P1; NX-030–034 | M2 full workflow, emergency stop and backup/restore rehearsal; completed outcome/log/diff UI in both modes. Gate multi-repo execution until all bindings/admission/partial failure behavior tested. | Reviewed local patch usable; no host checkout/ref/remotes change, no push/merge/deploy; restore invalidates capabilities |

## Phase 7 — Trustworthy telemetry

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-036 | P1; NX-035 | Immutable accounting observations, deduplicated current charge-unit ledger, runtime/provider semantic adapters and reconciliation/backfill. | Duplicate/cumulative/out-of-order/corrected/partial/failed-run golden fixtures; no category double count; unknown total preserved |
| NX-037 | P1; NX-036 | Versioned pricing/valuation, fixed micros/currency, API-equivalent versus reported versus actual billing, bill allocation and coverage detail. | Shared tariff recalculation preserves history; missing price not zero; mixed currency separate; unmatched bill not copied to every task |
| NX-038 | P1; NX-037 | Official allowance observations/expiry/unknown UI, configured soft/hard budgets and atomic reservations/settlement. No unsupported subscription scraper. | No invented percentage; stale allowance labeled; competing jobs cannot oversubscribe known admission budget; delayed cost limitation visible |
| NX-039 | P1; NX-038 | Session/task/model/provider/phase usage queries, coalesced bucket rates, simulation isolation and Focus charts/tables. | Replayed totals match ledger, partial coverage visible, sim data excluded from spend/baselines and clearly labeled |
| NX-040 | P1; NX-039 | Canvas2D Usage Observatory, bounded aggregate particles/session cues, capped update/render rate, quality tiers and reduced-motion fallback. | Same numeric data as Focus, unknown stream not fake throughput, background zero animation, performance-budget browser tests |

## Phase 7B — Explainable efficiency

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-041 | P2; NX-040 | Complexity/config/baseline/score schema, immutable pre-run axes/human revisions, eligible episode cohorts and frozen lineage-weighted cutoff snapshots. | No self/future data; cold-start unavailable; 20 episodes/five lineages/20% cap; changed complexity auditable |
| NX-042 | P2; NX-041 | Decimal scoring engine, deterministic evidence hashes, quality gates, supersession/regression and full calculation artifact. | Worked example 79.3; missing inputs/waived tests/unreviewed outcome cannot create final score; penalties/bounds/zero cases |
| NX-043 | P2; NX-042 | Per-task score breakdown/evidence/history, whole-task cost across episodes, confidence/coverage and similar-task reference in both modes. | No authoritative score for incomplete/insufficient data; identical mode values; human can reproduce every input |
| NX-044 | P2; NX-043 | Aggregated model/agent/project/task-type/strategy comparisons and calibration export; failure denominators, mixed-model category, cohort/maturity/sample controls. | No duplicated successes, no survivor-only cost denominator; common task mix and sensitivity labels; simulation excluded |

## Phase 8 — Operations and polish

| ID | Priority; dependencies | Engineering ticket and output | Acceptance proof |
| --- | --- | --- | --- |
| NX-045 | P2; NX-044 | launchd API/worker/enqueue templates, typed Brussels schedule slots, startup/wake catch-up, periodic/nightly reconciliation and no interactive runtime dependency. | DST repeated/skipped time, duplicate tick and sleep catch-up fixtures enqueue once; no automatic service install |
| NX-046 | P2; NX-045 | Persistent in-app notifications plus opt-in local OS adapter, quiet hours, delivery dedup and safe deep links; operational health/freshness. | Duplicate event one notification, blocked source/worker visible, sensitive payload redacted; external messaging not enabled implicitly |
| NX-047 | P1; NX-046 | Uncertain-job/delivery recovery UI/CLI doctor, owned-sandbox reconciliation and fencing/timeout/quarantine runbooks. | Kill at dispatch/stop/lease boundaries; no duplicate implementation/write; lock release requires confirmed stop |
| NX-048 | P1; NX-047 | Backup/restore/retention/GC tooling, encrypted-storage guidance, Linux systemd guide and PostgreSQL migration checklist/portability test target. | Restore separate DB+blobs with hashes/FKs/sequence; purge preserves active evidence; no silent DSN rollback after new writes |
| NX-049 | P1; NX-048 | Enable separately authorized safe external writeback on sandbox accounts only: append-only approved operation markers, target checks and uncertain delivery reconciliation. Keep field writes copy-only without verified atomic CAS. | Mutated draft/target blocked; ambiguous send not retried; one remote operation after reconciliation; approval/audit exact payload |
| NX-050 | P2; NX-049 | Final dual-mode cinematic transitions, responsive polish, accessibility/performance profiling, full regression demo and operational handoff. | Shared-action parity, reduced motion, hidden/Focus render suspension, bounded logs/particles, manual keyboard and failure-recovery demo |

## Deferred work / exclusions

No automatic push/merge/deploy, production SQL access, unrestricted terminal, silent plugin installation, multi-tenant cloud service, unsupported subscription scraping, causal model leaderboards, vector retrieval platform, Redis/Celery cluster, or mandatory WebSocket/3D engine. Outlook/Google calendars and Tempo/Jira Data Center adapters follow confirmed actual need and separate verified contracts. OpenCode is the first/default harness; additional harness adapters follow verified capability requirements. A generic plugin marketplace is excluded. Webhooks follow a reachable authenticated deployment. These are not uncompleted MVP tickets.

## Completion record template

When implementing a ticket append its status, commit/worktree reference if available, actual commands/tests run, evidence artifact or concise result, known limitations and approved deviations. Never mark fixture-only integration as live verified. Preserve this planning baseline and stable IDs; do not delete failed attempts from the outcome/usage history to make a phase look complete.
