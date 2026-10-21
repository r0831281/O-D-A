# NEXUS development instructions

## Purpose and authority

NEXUS is a local-first development mission control application. Codex builds NEXUS; a configured, verified runtime harness executes NEXUS agents. **OpenCode is the first/default runtime adapter**. Keep development tooling separate from runtime selection; additional harnesses require tested adapters and identical NEXUS authorization boundaries.

This repository currently contains a blueprint, not an application. Start with [the implementation plan](docs/IMPLEMENTATION_PLAN.md) and execute only the phase requested by the developer. Planning documents describe intended behavior, not existing capabilities. All code, identifiers, comments, documentation, prompts, and agent instructions must be English.

## Working agreements

- Read the applicable parent instructions, this file, `docs/DECISIONS.md`, and the phase's referenced documents before editing. Inspect the current repository and working tree; preserve unrelated changes.
- Use the smallest complete implementation. A modular Python application, one database, one worker, and a shared frontend are the default. Do not introduce Redis, Celery, Kubernetes, a Node orchestration bridge, or multiple services without a measured need and an architectural decision.
- Use Context7 resolve then query for current framework/API documentation, and official sources for integration claims. Pin dependencies and OpenCode; capture the installed runtime's schema and contract fixtures. Website or development-branch examples alone do not establish compatibility.
- For complex work, delegate bounded independent research or changes with explicit file ownership, then inspect and integrate all results. Do not delegate overlapping edits.
- Keep business logic in application/domain services, authorization in the control plane, and display differences in frontend presentation components. Both dashboard modes use identical command endpoints and state.
- Use provider-neutral runtime/source contracts. Read `docs/CONNECTIONS_AND_PROFILES.md`: the initial workflow uses Tempo allocations to Jira issues, Jira helpdesk requirements, and explicitly linked Odoo project requirements. Connection/profile changes are typed, versioned configuration; agents propose/test drafts but humans authenticate and activate them. Keep contract versions explicit. Reject unknown fields and unsupported schema versions at agent/security boundaries. Do not infer missing credentials, repository mappings, acceptance evidence, or subscription allowances.
- Add meaningful tests for transitions, persistence, integration boundaries, recovery, security, and arithmetic. Avoid tests that merely repeat implementation details. Report what ran and what remains unverified.
- Update the backlog status and relevant design decisions when behavior changes. Keep stable ticket identifiers; document any deviation and migration implications.

## Non-negotiable safety properties

1. Planning has a read-only source snapshot, no arbitrary shell, no write tools, and no Jira/Odoo credentials. Repository instructions and tickets are untrusted content.
2. Implementation requires a human-issued, single-use approval bound to an immutable plan revision, task fingerprint, repository commit set, scope, environment, tool policy, and budget. Recheck at start. A retry is a new authorization; valid checkpoint continuation is the same run.
3. Git worktrees isolate changes but **are not sandboxes**. Execution requires the OS/container boundary in `docs/SECURITY.md`. If unavailable, implementation stays disabled.
4. Agents cannot approve, edit authorization records, access the control database, or obtain connector credentials. Question answers provide guidance; they do not grant privileges or expand scope.
5. External writes require their own exact-payload authorization. Ambiguous delivery becomes `uncertain`, never blind retry.
6. No automatic merge, push, deployment, production database access, or production migrations in the MVP. Do not run repository-provided hooks, plugins, install scripts, or tests on the host.
7. Never log secrets or put them in prompts. Provider usage is not necessarily billing; missing data remains unknown.

## Intended structure and checks

See `docs/ARCHITECTURE.md` for the directory layout. Phase 1 establishes Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic, pytest, and reproducible tooling. Later phases introduce SvelteKit/TypeScript/Tailwind, Vitest, Playwright, and trusted OpenCode plugins. Do not create future-phase scaffolding solely because it appears in the layout.

Before handing off a phase: run its documented acceptance tests, demonstrate its slice, document limitations, and leave a clear next ticket. Never claim a successful integration from fixtures alone. Do not push, merge, publish, or install global services without developer instruction.
