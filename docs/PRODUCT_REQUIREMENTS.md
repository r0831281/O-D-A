# NEXUS product requirements

Status: proposed implementation blueprint. Prepared 2026-10-20. No application functionality exists yet.

## Outcome and users

NEXUS helps a single developer turn scheduled work into reviewed implementation plans and, later, isolated code changes. It reduces organization work while leaving code execution and external changes under human control. The first environment is a local macOS workstation; the default configurable timezone is `Europe/Brussels`. Source integrations and routing are configurable; the initial working profile uses Tempo allocations associated with Jira issues for scheduling, Jira requirements for helpdesk work, and an explicitly linked Odoo task for project-work requirements.

The initial user is the developer/operator. Runtime agents are untrusted executors, not users with approval authority. OpenCode is the first supported coding harness and the default runtime; Codex building NEXUS is a separate role. Additional harness adapters must satisfy the same capability and isolation contracts before their implementation execution is enabled. Multi-user teams, remote public access, and organizational RBAC are later work.

## Milestones and boundaries

| Milestone | Included | Explicit boundary |
| --- | --- | --- |
| M0, Phase 1 | Persistence, state transitions, durable job/audit foundations, fixtures | No connectors, agents, UI, or execution |
| M1, Phases 2–4 | Read-only imports, Connections and Planning Profiles setup, daily/upcoming views, requirements analysis, read-only planning through the default harness, human review/request changes in both modes | Plans can be accepted for planning purposes; code execution remains disabled |
| M2, Phases 5–6 | Bound execution authorization, persistent blockers, sandboxed worktree implementation, independent review, human acceptance | No auto merge/push/deploy; no production access |
| M3, Phases 7/7B/8 | Reconciled usage, honest cost/allowance reporting, explainable scores, scheduling, notifications, cinematic polish | Advanced visuals and scores never gate basic task workflows |

The first usable MVP is M1. A plan's review acceptance is a product decision; it is distinct from M2's execution grant. This avoids treating a first-milestone review button as permission to run future code.

## Functional requirements

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| PR-01 | Resolve scheduled work through a versioned planning profile with separate schedule, work-item, requirements, and repository authorities; initial profile uses Tempo/Jira/Odoo | Replaying fixtures creates no duplicates; allocations resolve to stable Jira identities and correct requirements without title-based joins |
| PR-02 | Fresh daily view without deleting persistent tasks | Switching dates preserves plans, questions, runs, and history |
| PR-03 | Explicit links unify the same work; dependency/related links do not merge tasks | Identical titles stay separate; invalid links enter review |
| PR-04 | Source edits mark dependent plans/approvals stale | Requirement, schedule, assignment, acceptance, repository mapping changes visibly invalidate readiness |
| PR-05 | Requirements agent returns evidence-backed readiness and specific questions | Schema-valid analysis references source snapshot and acceptance criteria |
| PR-06 | Planner inspects pinned source, Odoo version/module evidence, affected paths, risks and tests | Source snapshot is unchanged; uncertainty about installed modules is labeled |
| PR-07 | Both modes support task inspection, review, questions, and permitted launch actions | Shared-state Playwright suite executes each journey in both modes |
| PR-08 | Implementation starts only after bound human authorization | Stale/replayed grants, changed base and changed scope fail closed |
| PR-09 | Human questions survive restart; guidance cannot expand capabilities | Answer/reject/cancel and same-run continuation are durable and audited |
| PR-10 | Isolated implementation and separate review produce diff/test evidence | Host checkout unchanged; human explicitly accepts result |
| PR-11 | External update drafts are previewed, independently approved and reconciled | Payload mutation invalidates approval; uncertain send cannot duplicate blindly |
| PR-12 | Usage distinguishes token, billing, estimate, allowance and budget | Unknown subscription availability never renders a fabricated percentage |
| PR-13 | Versioned efficiency metrics include all retries and quality evidence | Formula can be reproduced; missing baseline/evidence yields no authoritative score |
| PR-14 | Operator sees stale/offline/failed/blocked conditions and controls execution | Safe cancel, checkpoint pause, timeout, retry and restart demonstrations |
| PR-15 | Daily sync works without an interactive harness terminal | OS scheduler enqueues work; persistent worker manages headless runtime |
| PR-16 | Guided Connections and Planning Profiles setup supports read-only tests, discovery, mappings, sample-day preview, version diff, activation and rollback | Every preview item traces schedule → work item → authoritative requirements → repository; invalid or ambiguous routes block activation or the affected item |
| PR-17 | Harness selection is configurable by default, project, and agent role with truthful tested capabilities | Unsupported implementation capabilities keep execution disabled; running sessions retain their frozen adapter/configuration/version |
| PR-18 | AI setup assistance drafts mappings and explains diagnostic results without handling secrets or activating configuration | Human authenticates and reviews the exact version before activation; generated arbitrary code and privileged actions are rejected |

## Journeys

### Morning review

1. OS scheduling requests synchronization; connector pages land durably and daily membership is recomputed.
2. Operator sees today's Brussels date, source freshness and upcoming schedule from the active planning profile. In the initial profile, a Tempo allocation resolves to a Jira issue. Configured Jira project/type/field rules classify it: helpdesk requirements come from Jira; project-work requirements come from an explicitly linked Odoo `project.task`. The UI traces each decision and source identity.
3. Requirements analysis classifies each task as ready, needing clarification, or blocked. Blockers join the attention queue.
4. Read-only planning runs against a pinned repository snapshot. Operator reviews requirements, affected paths, risks, tests, and assumptions; accepts the plan review or requests a new revision.

### Connection and planning-profile setup

1. Operator chooses a supported backend adapter and authenticates through a secure connection flow. Credentials are stored outside prompts, logs, preview URLs, and generated configuration; configuration contains secret references.
2. Read-only connection/discovery tests show account identity, scopes, available projects/types/fields, supported capabilities, and redacted diagnostic errors. A connected account is not yet an active planning profile.
3. Operator maps schedule authority, stable work-item identity, classification rules, requirement-source routes, repository/version bindings, and account identities explicitly. No project/type/field name is assumed from a display title. Tempo/Jira/Odoo account mappings are configured rather than inferred from similar names.
4. A sample-day preview shows inclusion/exclusion reasons, scheduled intervals, classification rule, exact Jira and Odoo identities, authoritative requirement source, repository selection, missing permissions, ambiguities, and expected task changes. A missing or ambiguous Odoo link for Odoo-routed work blocks that item's analysis/planning; it never falls back silently to Jira description.
5. Operator reviews a profile-version diff and explicitly activates it. Activation revalidates source schema and mappings and starts a bounded resynchronization. Prior versions and task history remain available. Rollback activates a prior valid configuration as a new audited version and resynchronizes; it does not erase work or resurrect old approvals.
6. Optional AI assistance proposes schema-valid mappings and explains errors from sanitized discovery evidence. It can draft and ask questions; it cannot authenticate as the user, select accounts silently, activate configuration, execute arbitrary setup code, or grant itself new tools.

Connections and Planning Profiles use shared controls in both dashboard modes. Selecting another account or mapping for an existing supported adapter is configuration, requiring no dashboard code. A new provider/protocol requires an implemented and contract-tested backend adapter; generic setup does not promise compatibility with arbitrary APIs.

### Harness setup and selection

The operator selects a tested harness adapter as the global default, optionally overrides it for a project and role, and inspects capability/test results before use. Resolution is explicit: project-role override, project default, global role default, then global default. A missing or incompatible selection is an actionable configuration error, not a silent switch to another harness. OpenCode is the initial implementation-adapter candidate; its actual installed build and isolation still must pass the compatibility gate before execution is enabled.

Capability status distinguishes supported-and-tested, unsupported, untested, and stale against a recorded adapter/runtime/configuration version. Tests cover session management, execution/abort, questions/checkpoints, telemetry, tool restrictions, and isolation according to role. A harness lacking required safety capabilities cannot run implementation even if it can generate text. Existing runs and approval envelopes retain their selected harness identity/configuration; changing defaults affects only future eligible runs and requires new approval where execution bindings change.

### Controlled implementation

1. Operator reviews a concrete execution envelope: plan revision/hash, ticket snapshot fingerprint, repository/base commits, allowed paths/tools/tests/network, run budget and expiry.
2. A fresh source/base check precedes an atomic single-use grant consumption and job creation. Concurrent clicks cannot start two runs.
3. Worker starts the isolated runtime. Tool events and observations stream into both dashboards. Missing evidence or unexpected scope leads to a durable question and stopped runtime.
4. Guidance resumes the same authorized run only if its original envelope still matches. Scope/source/base changes require revision and new authorization.
5. Tests and independent reviewer report against the actual patch. Operator accepts or requests changes. Completion does not merge or close remote tickets automatically.

### Writeback and analytics

1. NEXUS prepares a field-level Jira/Odoo draft from reviewed outcomes. Operator sees target account/record, before/after, payload, freshness, and side effects.
2. A distinct write approval permits only that immutable draft. Result is reconciled before marking sent.
3. Operator examines measured usage and score evidence; can compare sufficiently similar completed tasks without mistaking estimated API cost for subscription billing.

## Scheduling and conflict rules

- The active profile explicitly selects schedule authority. Tempo/Jira allocations are the initial authority. Outlook is optional supplementary context or an explicitly selected alternative calendar authority, not a required account or the current schedule source. Other calendar/task-field sources require a supported adapter and explicit profile configuration; no implicit fallback when the selected authority fails. A due date appears as a deadline, not an invented appointment. Unscheduled assigned tasks are a separate backlog.
- Membership includes any schedule interval overlapping the local day's half-open interval. All-day dates stay dates; recurring occurrences retain original start identity. Carry-over appears as a labeled section and does not silently reschedule a ticket.
- A configured route selects the authoritative requirement source independently of scheduling and work-item identity. Jira helpdesk work reads Jira requirements; Odoo-routed project work reads the explicit linked Odoo task. Secondary descriptions remain visible as context with provenance. Missing/ambiguous routing, unknown classification, conflicting instructions, or repository mappings block the affected task until resolved. Never silently pick the longest or newest description or substitute Jira content for unresolved Odoo requirements.
- Connection/profile revisions, classified route, authoritative source revisions, explicit links, and repository mappings are part of the task's resolved provenance and relevant fingerprint. Activation/rollback preserves canonical tasks and histories while invalidating affected plans/readiness/unused approvals and stopping affected execution through the existing safety policy.
- Explicit equivalent-work links require matching project/repository context and evidence. Generic Jira `relates to` is not equivalence. Merge/unmerge is an audited human operation.
- Deterministic priority: blocked/attention status first in its own queue, then manual priority, schedule start, mapped source priority, stable task ID. Do not let an LLM overwrite operator priorities.

## Nonfunctional requirements

- Local-first means state and artifacts remain local and the UI works with cached data offline. Hosted model calls still transmit selected task/code content; project/provider policy must allow this.
- No Redis, broker, vector database, microservices, GPU requirement, or public webhook endpoint for M1.
- Durable transitions are atomic; integration delivery is at least once, not an exactly-once promise. Recovery must not duplicate execution or external writes.
- Dashboard performance/accessibility budgets are specified in `DASHBOARD_DESIGN.md`; both modes are release-blocking functional targets.
- Every significant action records actor, causation, before/after or immutable reference, result, timestamp, and correlation ID. Sensitive payload retention is bounded.

## Product success and measurement

Collect from Phase 1: import-to-review lead time, source freshness, tasks with complete requirements, reviewed plans, question wait time, active execution time, attempts, accepted outcomes and usage completeness. Initial success is a repeatable morning workflow and reproducible recovery, not a target efficiency score. Establish numeric improvement targets after observing real use; do not invent a time-saved claim.

## Decisions requiring developer input

These do not block Phase 1: actual Tempo product/deployment/API entitlement and Jira account identity; Jira Cloud versus Data Center; project/type/field classification rules and explicit Odoo-link fields; Odoo databases/project/company IDs and API entitlement; repository/version mapping; approved model providers and data policy; OS/container engine availability; any optional Outlook account and whether it is context or an alternative authority. The initial source-routing intent is established above; exact account IDs/fields and supported API variants still require read-only discovery and human setup. Secure live connections, profile activation, additional harness compatibility, and M2 execution remain blocked until their relevant evidence is supplied. Defaults and alternatives are in `DECISIONS.md`.
