# Phase 1 implementation and verification evidence

Date: 2026-10-21. Status: **Phase 1 accepted; all NX-001–NX-006 exit criteria pass**.
The latest session section records installed-wheel, test and demo evidence. Earlier
blockers below are preserved as historical observations and are superseded there.

## Historical repository inspection

- Initial files were `AGENTS.md` plus the planning documents in `docs/`.
- `/Users/jonas/Desktop/AGENTS.md` and repository instructions were read, along with
  all seven requested planning documents, before editing.
- `git status --short` returned `fatal: not a git repository`. No repository was
  initialized, no refs were changed, and no push/merge/publish was attempted.
- Unrelated blueprint files and instructions were preserved. Only implementation
  status/context was added to relevant planning documents.

## Authored scope

NX-001–NX-006 have code and test coverage prepared. The exact Phase 1 subset is in
`src/nexus/schema.py` and frozen migration `0001_foundation`. Public operations are
local pairing/revocation, synthetic fixtures, no-op enqueue, clarification hold,
status and health. CLI adds migration, one-job worker, integrity inspection and an
explicit temporary-state demonstration. No future authorization capability exists.

## Checks actually performed

| Check | Observed result |
| --- | --- |
| Python discovery | Installed CPython 3.12.11 found at the explicit pyenv version path; generic `python3.12` shim was not selected |
| Official documentation | Context7 resolve→query for official SQLAlchemy 2.0 SQLite transactions, FastAPI lifespan/request handling and Alembic shared-connection migrations |
| Dependency resolution | uv 0.11.26 resolved 31 packages including the project; all direct runtime/dev dependencies pinned |
| Download integrity | 30 selected dependency wheels matched SHA-256 in their exact-version PyPI JSON records |
| Portable lock | Local wheel resolution enriched with official registry URLs and hashes; no temporary wheelhouse references remain |
| `uv lock --check --offline --python <explicit-3.12.11>` | Passed: resolved 31 packages |
| `uv sync --frozen --no-install-project --no-build --dry-run --python <explicit-3.12.11>` | Passed planning stage: would create environment and install 28 applicable third-party packages on this Mac |
| `uv export --frozen --no-emit-project --format requirements-txt` | Passed parsing/export with hashes |
| Ruff 0.17.1 lint and format check over `src tests` | Passed; 20 Python files formatted |
| CPython 3.12.11 static AST/TOML parsing | Passed for all 20 Python files, `pyproject.toml` and `uv.lock`; no repository imports or execution |
| `sh -n verification/run.sh` | Passed shell syntax check; script not executed |
| Independent read-only review | Corrected lease time calculation to occur after lock acquisition; matched service/schema fields and inspected tests |

The host shell could not resolve PyPI DNS. Official package metadata/wheels were
downloaded through the available network-capable tool, then resolved offline with
uv; each selected artifact hash was checked before producing the portable lock.
Only the Ruff third-party wheel was installed in a temporary tool environment.
No repository package build backend or test code was executed on the host.

## Blocked or unverified

No `docker`, `podman`, `colima`, OrbStack or corresponding Docker socket was available.
The native Node runtime also identified itself as Darwin, so it is not an independent
Linux sandbox. `sandbox-exec` on the host was not substituted for the required
disposable test environment. No engine/global service was installed.

The following have **not run**: clean full dependency installation/import; package
build/install; actual SQLite migrations/constraints; pytest collection/execution;
real concurrency and restart checks; API startup/authentication checks; temporary
private-state demonstration; Docker image build and its isolation behavior.
The prepared tests and demo cannot be counted as verification evidence until run.

`AGENTS.md` says “Do not run repository-provided hooks, plugins, install scripts, or
tests on the host.” `docs/SECURITY.md` requires tests/builds to use a separate
disposable sandbox without credentials or host mounts. Phase 1 itself requires no
container **for the application**; the verification environment is a separate
development prerequisite under those active instructions. This is an environmental
blocker, not a developer-approved reduction in acceptance scope.

## Completion gate and next work

All NX-001–NX-006 remain **verification blocked**, not Done. Use the exact isolated
commands in `README.md`; inspect and fix every failure, rerun the relevant tests,
demonstrate the slice and append actual output summaries here. Prove a clean import
and packaged migration resource availability, and report wheel-build coverage
separately if attempted. Update ticket status only after runtime proof exists.

Phase 2 has not begun. After Phase 1 passes, the next dependency order is NX-007,
NX-051, NX-008, NX-009, NX-052, NX-010, NX-011, NX-012. The next session must initially
finish Phase 1 only; do not treat this note as authorization to implement Phase 2.

## Reinspection and bounded corrections — 2026-10-21

This section records a later session. Earlier inspection/results above are historical;
they must not be mistaken for the current Git baseline or runtime acceptance.

### Current access and Git baseline

Workspace access now works. These commands executed successfully from the requested
checkout before edits:

```sh
ls -ld /Users/jonas/Desktop/NEXUS
git status --short --branch
git rev-parse --short HEAD
```

The checkout is now a Git repository on `main...origin/main`, HEAD `f2a3d1b`.
Initial tracked modifications were README plus ARCHITECTURE, BACKLOG,
CONNECTIONS_AND_PROFILES, DATA_MODEL, DECISIONS and IMPLEMENTATION_PLAN. Initial
untracked paths were `.dockerignore`, `.gitignore`, `.python-version`, this report,
`pyproject.toml`, `src/`, `tests/`, `uv.lock` and `verification/`. All existing work was
preserved; no Git refs/index were changed and no commit/push/merge was attempted.
Parent/repository AGENTS and every requested document were read. Bounded independent
read-only reviews covered persistence/worker and API/auth/config/demo paths before
the reviewers made the explicitly scoped changes below.

The previous exec-server failure is not the current blocker. The shell and file
inspection tools executed normally in this checkout in this session.

### Disposable verification environment discovery

Actual read-only discovery included:

```sh
for name in docker podman colima orb nerdctl limactl container; do
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
  else
    print -r -- "not on PATH: $name"
  fi
done
for p in /Applications/Docker.app /Applications/OrbStack.app \
  /usr/local/bin/docker /opt/homebrew/bin/docker /Users/jonas/.docker/bin/docker \
  /var/run/docker.sock /Users/jonas/.docker/run/docker.sock \
  /Users/jonas/.colima/default/docker.sock /Users/jonas/.orbstack/run/docker.sock; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    /bin/ls -ld "$p"
  else
    print -r -- "not present: $p"
  fi
done
for name in DOCKER_HOST DOCKER_CONTEXT CONTAINER_HOST; do
  if (( ${+parameters[$name]} )); then
    print -r -- "$name is set (value withheld)"
  else
    print -r -- "$name is unset"
  fi
done
uname -s
```

Results: none of those commands, application paths or sockets was available;
all three endpoint/context environment variables were unset. Host is `Darwin`.
README and `verification/` configure only the Docker-compatible pinned runner;
no alternate verification environment was found. These observations establish no
configured permitted runner was located, not that every possible VM or remote
environment has been exhaustively ruled out. The README Docker build/run commands
were not executed because the required executable/endpoint was unavailable.
No engine/service was installed or started, no host test/build/import of repository
code occurred, and no alternative execution boundary was substituted.

### Corrections made, still awaiting runtime verification

- `src/nexus/cli.py`: the explicit demo previously accepted any exit-code-2 error
  as the intended invalid-transition/stale-version rejection. It now checks
  `forbidden_transition` and `stale_version` exactly, validates the worker's completed
  job identity, the persisted task/job identity/state/version, nonempty matching
  audit/outbox signatures, integrity/FK/WAL results and disabled execution. Successful
  output includes `temporary_state_removed: true` only after leaving the temporary
  directory context and checking removal. No private path is printed.
- `tests/test_cli.py`: successful-demo assertions include exact rejection and cleanup
  evidence. Three fault-injection cases replace invalid/stale rejection evidence with
  an unrelated storage error or replace doctor integrity with corruption; each must
  reject the demonstration and remove temporary state. These cases are authored,
  not passing runtime results.
- `tests/test_foundation.py`: atomic rollback coverage now also injects failure just
  before and just after the receipt INSERT. Existing row-count and task-state
  assertions check mutation/receipt/audit/outbox rollback together, including an
  already inserted receipt. Event listeners are removed in `finally`.
- `README.md`: explicitly distinguishes source-tree runner coverage from installed
  package/resource coverage. No dependency, public command schema, persisted schema
  or migration was changed. Existing databases require no migration for these edits;
  additive versioned migrations remain required for future accepted schema changes.

Static reviews found no confirmed persistence/worker defect or authentication bypass;
that is not a runtime correctness or security certification. Official SQLAlchemy 2.0
documentation was checked via Context7 resolve then query for the cursor event
signatures used by the added rollback injection:
https://docs.sqlalchemy.org/en/20/core/events.html.

### Current static checks actually run

All commands below ran from `/Users/jonas/Desktop/NEXUS`. The explicit existing
temporary tool/cache paths avoid the unavailable generic Ruff shim and the default
uv cache's protected path. These are third-party static tools, not host repository
test execution.

| Actual command | Result |
| --- | --- |
| `uv --version` | uv 0.11.26 |
| `ruff --version` | Failed: pyenv shim has no selected Ruff; not a repository/test failure |
| `uv tool run --offline --from ruff==0.17.1 ruff --version` | Failed before running Ruff: default cache `/Users/jonas/.cache/uv/sdists-v9/.git` is not writable under active permissions |
| `uv lock --check --offline --python /Users/jonas/.pyenv/versions/3.12.11/bin/python` | Same default-cache permission failure |
| `/tmp/nexus-tools/bin/ruff --version` | Ruff 0.17.1 |
| `/tmp/nexus-tools/bin/ruff check --no-cache src tests` | Passed: all checks passed |
| `/tmp/nexus-tools/bin/ruff format --check --no-cache src tests` | Passed: 20 files already formatted |
| `UV_CACHE_DIR=/tmp/nexus-uv-cache uv lock --check --offline --python /Users/jonas/.pyenv/versions/3.12.11/bin/python` | Passed: resolved 31 packages |
| `UV_CACHE_DIR=/tmp/nexus-uv-cache uv sync --frozen --no-install-project --no-build --dry-run --offline --python /Users/jonas/.pyenv/versions/3.12.11/bin/python` | Passed planning only: would create `.venv`, download/install 28 dependencies; no installation performed |
| `/bin/sh -n verification/run.sh` | Passed syntax check only |
| `git diff --check` | Passed for tracked changes; Git emitted existing LF-to-CRLF conversion warnings. Untracked implementation files are not covered by this Git check. |

Static Python/TOML parsing also passed with this exact command, without repository
imports, bytecode generation or execution of parsed files:

```sh
/Users/jonas/.pyenv/versions/3.12.11/bin/python -I -S -B - <<'PY'
import ast
from pathlib import Path
import tomllib
files = sorted(Path('src').rglob('*.py')) + sorted(Path('tests').rglob('*.py'))
for path in files:
    ast.parse(path.read_text(), filename=str(path))
for name in ('pyproject.toml', 'uv.lock'):
    with Path(name).open('rb') as stream:
        tomllib.load(stream)
print(f'Static parse passed: {len(files)} Python files and 2 TOML files; no repository imports or execution')
PY
```

Observed: 20 Python files and two TOML files parsed successfully.

### Exit criteria: no runtime acceptance yet

| Required verification | Current evidence / remaining gap |
| --- | --- |
| Clean dependency installation/import and packaged migration resources | Lock and dry-run pass only. No actual clean install/import. Current Dockerfile uses `--no-install-project` and `PYTHONPATH=/app/src`; even a passing existing runner would not prove installed-wheel resources or console entrypoint. Add/run an isolated wheel build/install/resource/migration probe without source-path fallback before claiming package coverage. |
| Fresh/repeated file SQLite migration, constraints, WAL/FKs, transactions, UTC | Tests inspected; none run. |
| Allowed/forbidden/missing-evidence/holds/stale transitions | Tests inspected; none run. |
| Concurrent idempotency, changed-body conflict, atomic rollback | Tests inspected; receipt-insertion rollback tests strengthened; none run. |
| Concurrent claims, all lease fences/expiry/restart, no transaction during slow work | Tests and implementation inspected; none run. |
| Authentication, pairing replay/expiry, Host/Origin/CSRF, strict schemas, secret safety | Tests and implementation inspected; none run. |
| Locked/full SQLite and private state-path protections | Tests and implementation inspected; none run. |
| Explicit temporary-private-state CLI demo and restart/replay/no-op/rejections | Demo validation strengthened; demo and new fault-injection tests not run. |

Every NX-001–NX-006 acceptance status remains **Verification blocked**. Phase 1 is
incomplete and no Phase 2 work was started. Next session must locate the permitted
environment, close the package-verification runner gap, run the complete suite/demo
under the README boundary, fix runtime failures and record actual results before
advancing any ticket or providing a Phase 2 implementation handoff.

## Docker access discovery and execution transport loss — 2026-10-21

Current checkout inspection initially succeeded: `/Users/jonas/Desktop/NEXUS`,
`main...origin/main`, HEAD `f2a3d1b`, with the same existing tracked modifications
and untracked foundation files. Parent/repository instructions and phase documents
were consulted before changes. All prior work was preserved.

Docker is now installed. This supersedes earlier reports that no engine tooling
was present, but it does not establish a usable verification environment:

| Actual command / observation | Result |
| --- | --- |
| `command -v docker` | `/opt/homebrew/bin/docker` |
| `docker version` (initial) | Client 29.9.2, darwin/arm64; default context could not find `/var/run/docker.sock` |
| `docker context ls` | Docker Desktop context `desktop-linux` appeared, using `unix:///Users/jonas/.docker/run/docker.sock` |
| `docker version` (after Desktop context appeared) | Client details only; permission denied connecting to that socket |
| `docker info --format '{{.OSType}} {{.OperatingSystem}} {{.ServerVersion}}'` | Permission denied connecting to that socket; no server details obtained |
| `docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}'` | Same permission denied |
| `id` and `ls -lde /Users/jonas/.docker /Users/jonas/.docker/run /Users/jonas/.docker/run/docker.sock` | Runner uid 501 (`jonas`); socket and ancestors owned by jonas, mode 0755; ordinary owner permissions do not explain the denied connection |
| `docker --context desktop-linux version` | Same permission denied |
| `/tmp/nexus-tools/bin/ruff check --no-cache src tests` | Passed before transport loss |
| `/tmp/nexus-tools/bin/ruff format --check --no-cache src tests` | Passed before transport loss: 20 files already formatted |
| `UV_CACHE_DIR=/tmp/nexus-uv-cache uv lock --check --offline --python /Users/jonas/.pyenv/versions/3.12.11/bin/python` | Passed before transport loss: resolved 31 packages |
| `git diff --check` | Passed before transport loss; existing LF-to-CRLF conversion warnings |

The socket denial is consistent with the active tool access boundary; its exact
enforcement component was not established. No socket permissions, Docker daemon
configuration, execution policy, service or transport was changed. No alternate
tool was used to bypass the denial. Docker Desktop's installation/socket presence
is not a passing engine, image or container-isolation probe.

Later, an inspection command failed before execution with:

```text
Failed to create unified exec process: exec-server transport disconnected
```

Read-only recovery checks used `/bin/pwd` with explicit `/bin/zsh`, `login=false`,
`workdir=/tmp`, and `git status --short --branch` from the project. Both failed:

```text
exec-server transport disconnected; failed to resume exec-server session:
recovery timed out after 25s
```

This latest failure is unavailable execution tooling, independent of the preceding
Docker-socket denial. No runtime test, import, package build/install, migration,
container build/run or CLI demonstration succeeded or was claimed. No global
service was installed or host execution fallback used. Every Phase 1 runtime gate
and NX-001–NX-006 acceptance remains blocked. Phase 2 has not begun.

An independent read-only review confirmed schema/frozen-migration parity and found
no concrete new application defect. It did not execute repository code. Official
Docker documentation was consulted through Context7 resolve then query for the
documented container isolation flags. Runner preparation, if present in the current
files, is authored work until a permitted build and container run establishes proof.
The complete next-session scope is in `PHASE1_CONTINUATION_PROMPT.md`.

### Final runner correction and current blocker

The transport recovered, briefly closed again during an attempted documentation
update (`apply_patch` reported `exec-server transport closed` before reading README),
then recovered again. Subsequent inspection and edits succeeded. No pending mutation
was left behind. Docker socket access remained denied after recovery; it is the
current blocker, not an absent executable or an unrecovered working-directory error.

The packaging delegate made no file edits: a read-only external-metadata request
stalled and was stopped. The primary agent completed the bounded runner correction:

- `verification/Dockerfile`: preserves the pinned Python image digest. Exports
  hash-locked requirements without the project, installs third-party wheels and
  hash-pinned build tools before copying source, and removes source `PYTHONPATH`.
  These image-local third-party installations are not host/global-service installs.
- `verification/build-requirements.txt`: pins Hatchling 1.27.0, packaging 26.3,
  pathspec 1.1.1, pluggy 1.7.0 and trove-classifiers 2026.9.21.13 with SHA-256 values
  calculated from the existing local wheelhouse. The earlier report records artifact
  integrity work; this session confirmed the five local bytes/hashes and wheel
  dependency metadata, not a new live registry/download result. Image installation
  must still match the hashes against registry wheels when actually executed.
- `verification/verify_package.py`: requires non-root Linux, builds the wheel twice
  offline under the hardened runtime boundary using fixed `SOURCE_DATE_EPOCH`,
  compares hashes and installs the wheel in a fresh temporary venv. That venv uses
  the image's immutable third-party site packages; the base image never installs
  NEXUS. A separate `-I` interpreter rejects NEXUS modules outside the fresh venv,
  checks packaged migration resources, migrates twice and invokes the installed
  `nexus` entrypoint for integrity/FK/WAL inspection. Pytest and the explicit demo
  then run from the installed package without a source-tree fallback. Child commands
  have finite timeouts, and temporary build/install/state directories are removed.
- `verification/run.sh` and `.dockerignore`: include the package probe and pinned
  build requirements; lint covers verification Python too. README's selected
  demo/tests commands now go through the same installed-wheel preparation.
- README and backlog context distinguish inaccessible Docker from absent Docker.
  Backlog acceptance statuses were not advanced. The continuation prompt is saved
  separately for the next session.

No application domain, dependency lock, database schema or migration changed in this
session. No application-state migration/reset is required. This is a development
verification change; it does not add or certify a future NEXUS runtime adapter.
An independent static review found no source fallback or concrete runner defect
after an import-order correction. None of these authored checks has executed.

The exact README build command was attempted after the runner edit:

```sh
docker build --pull=false -f verification/Dockerfile -t nexus-phase1-verify .
```

It exited 1 before building, with:

```text
ERROR: permission denied while trying to connect to the docker API at unix:///Users/jonas/.docker/run/docker.sock
```

No container run was attempted after that failed prerequisite. The clean dependency
installation, reproducible package build/install/probe, runtime tests, migrations,
concurrency/failure scenarios and explicit CLI demonstration therefore all remain
unverified. Existing README runtime hardening flags were preserved; their actual
effect on this engine is also unverified.

Final static checks, after runner changes:

| Actual command | Result |
| --- | --- |
| `/tmp/nexus-tools/bin/ruff check --no-cache src tests verification` | Passed after correcting one I001 import-order finding in the new script |
| `/tmp/nexus-tools/bin/ruff format --check --no-cache src tests verification` | Passed: 21 files already formatted |
| `/bin/sh -n verification/run.sh` | Passed syntax only |
| `git diff --check` | Passed for tracked changes; existing LF-to-CRLF warnings |

The static parser command from the previous section was extended to include
`sorted(Path('verification').rglob('*.py'))`: 21 Python files and two TOML files
parsed successfully. A standard-library-only reader matched all five requirements
SHA-256 values against the existing wheel ZIP bytes. No repository module was
imported or executed. Current uv CLI help and official uv documentation were checked
for offline wheel build, no-build-isolation and local-wheel installation flags.

Exact final parse/hash command (reads source and wheel bytes only):

```sh
/Users/jonas/.pyenv/versions/3.12.11/bin/python -I -S -B - <<'PY'
import ast
from pathlib import Path
import tomllib
import re
import hashlib
files = sorted(Path('src').rglob('*.py')) + sorted(Path('tests').rglob('*.py')) + sorted(Path('verification').rglob('*.py'))
for path in files:
    ast.parse(path.read_text(), filename=str(path))
for name in ('pyproject.toml', 'uv.lock'):
    with Path(name).open('rb') as stream:
        tomllib.load(stream)
requirements = Path('verification/build-requirements.txt').read_text()
matched = re.findall(r'([\w-]+)==([^\s]+)\s*\\\s*--hash=sha256:([0-9a-f]{64})', requirements)
assert len(matched) == 5
for name, version, expected in matched:
    wheel = Path('/tmp/nexus-wheelhouse') / f'{name.replace("-", "_")}-{version}-py3-none-any.whl'
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == expected, name
print(f'Static parse passed: {len(files)} Python files, 2 TOML files; 5 build-tool wheel hashes matched; no repository imports/execution')
PY
```

All eight requested runtime verification categories remain blocked. Every Phase 1
exit criterion has **not** been established as passing; NX-001–NX-006 stay
**Verification blocked** at the time of that earlier section; the latest evidence
below supersedes it.

## Runtime acceptance — 2026-10-21

Docker Desktop access was initially denied by the sandbox. The requested explicit
Docker approval was granted; `docker info` then succeeded (Server 29.9.1, Docker
Desktop on Linux/arm64, 12 CPUs, 7.748 GiB). No socket permissions, daemon settings,
services or transports were changed. The repository image is development verification
tooling only.

### Runner correction

The first hardened run built both wheels but `uv` could not inspect the new venv
interpreter in `/tmp`. A same-container diagnostic showed the interpreter had mode
0755 while `os.access(..., X_OK)` was false on the tmpfs. Docker's current CLI docs
allow tmpfs mount options to be specified explicitly, including `exec`. README's
three run commands now use `--tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777`.
This grants execution only on the ephemeral, size-limited container tmpfs; the root
filesystem stays read-only, the process remains non-root, capabilities stay dropped,
and the container has no network or host mounts.

The first full suite run then exposed a test-transport mismatch: an HTTPX/Starlette
request declaring a one-byte body while sending 20,000 bytes was rejected as malformed
HTTP with 400 before the application could inspect its body. The test now records that
transport behavior and separately invokes the app's actual receive-byte limiter with
an oversized ASGI chunk, asserting 413. This distinguishes bad HTTP framing from the
application's received-body limit; no application defect was observed.

### Exact commands and results

| Command | Exit/result |
| --- | --- |
| `docker info` (ordinary sandbox call) | Exit 1: permission denied connecting to `/Users/jonas/.docker/run/docker.sock` |
| `docker info` (approval-gated call) | Exit 0; Docker Desktop engine reachable |
| `docker build --pull=false -f verification/Dockerfile -t nexus-phase1-verify .` | Exit 0; pinned Python 3.12.11 image; locked third-party dependencies installed; project source copied after dependency installation; final image manifest `sha256:1b38a0d027508efe8ed71ece31fe4bc5d7f99122ce3f3b58e133de53aaa2c8fe` |
| `docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m --cpus 2 --tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777 nexus-phase1-verify` | Exit 0; full default command, detailed below |

The container's default command passed Ruff (`All checks passed!`, 21 Python files
already formatted), built the project wheel twice offline, and got the same SHA-256
for both copies: `e1d5cb343a7a3445fed43663292f971717ff2d2c09c01905ba025367b0b88548`.
It installed `nexus-control==0.1.0` into a fresh temporary venv, then ran the
separate isolated interpreter probe: `installed_import`, `packaged_migrations` and
`entrypoint` were all true. Module provenance came from the fresh venv, not the
source tree. The packaged Alembic environment and `0001_foundation` migration were
present; fresh and repeated file migrations succeeded; the installed `nexus doctor`
entrypoint reported integrity `ok`, zero FK errors, WAL and execution `disabled`.

The full test suite collected **187 tests** and passed: `187 passed, 1 warning in
46.81s`. The one warning is Starlette's deprecation notice for FastAPI's
`TestClient` dependency on HTTPX; it did not affect execution. Coverage included:

| Acceptance area | Runtime evidence |
| --- | --- |
| Clean dependency install/import, reproducible wheel and packaged resources | Image's hash-locked third-party install; two identical offline wheel builds; fresh-venv provenance; Alembic resources and installed console script |
| Fresh/repeated file migrations, schema constraints, WAL/FKs, transactions and UTC | `tests/test_foundation.py`, including failed-migration rollback and UTC round trips; installed probe migrated twice |
| Allowed/forbidden transitions, required evidence, holds and stale versions | `tests/test_foundation.py` transition/evidence/hold/CAS cases; explicit demo rejected forbidden transition and stale version |
| Concurrent idempotency, body conflicts and atomic mutation/receipt/audit/outbox rollback | `tests/test_foundation.py`, including concurrent same-key commands and injected rollback stages through receipt insertion |
| Concurrent claims, lease fencing/heartbeat/expiry/restart and short transactions | `tests/test_worker.py`, including two claimers, owner/epoch fencing, restart recovery and blocked slow work without an open DB transaction |
| Pairing/session replay and expiry; Host/Origin/CSRF; strict schemas; safe errors/logs | `tests/test_api.py`; secret-redaction and pairing race/rollback cases |
| Locked/full database and private state paths | `tests/test_foundation.py` busy/full rollback; `tests/test_configuration.py` private-mode, symlink/hardlink and invalid configuration checks |
| CLI demonstration, restart/replay/no-op/rejections/integrity/cleanup and false evidence | Installed-wheel `nexus demo` returned `simulated=true`, `restarted_processes=true`, `idempotency_replay=true`, `invalid_transition=forbidden_transition`, `stale_version=stale_version`, doctor integrity `ok`, and `temporary_state_removed=true`; `tests/test_cli.py` false-evidence fault regressions all passed |

The verification driver removes temporary wheel, venv, database and state directories
on success or failure. The demo output showed seven matching audit/outbox entries and
no cleanup residue. No credentials, host mounts, external connections or real source
systems were involved. The complete current behavior is a Phase 1 fixture foundation,
not a live integration or a certification of Docker as NEXUS's future runtime sandbox.

### Phase decision

All NX-001–NX-006 acceptance criteria passed; the Phase 1 backlog status is **Done**.
No Phase 2 implementation has begun. The next work, only when separately requested,
is Phase 2 in this exact order: NX-007, NX-051, NX-008, NX-009, NX-052, NX-010,
NX-011, NX-012. Phase 1 makes no live Jira, Odoo, Tempo, calendar, OpenCode or AI calls.

## Superseding phase status — 2026-10-21

The Phase 1 results above remain historical evidence for that phase. Phase 2 work
has since passed its fixture-scope exit gate; current implementation and verification
status are in `PHASE2_VERIFICATION.md`. Phase 3 has not started.
