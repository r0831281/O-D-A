# Per-task AI efficiency scoring

Status: proposed deterministic specification `nexus-efficiency-v1`; implement in Phase 7B. The weights and thresholds are product hypotheses requiring calibration, not scientific measurements of model intelligence. Collect the required events from the first agent run. [Telemetry](TELEMETRY.md) defines accounting semantics; [Agent contracts](AGENT_CONTRACTS.md) defines execution evidence.

## Runtime/profile attribution (revision 2)

Record runtime adapter/build/transport and agent/tool-policy revision alongside provider/model; model and harness are distinct comparison dimensions. A harness change may change tool/recovery/retry behavior and is a confounder, not evidence of model improvement. Profile/resolution revisions bind episode inputs so a change from Jira to linked Odoo requirements cannot silently reuse the prior score evidence. Setup-assistant overhead is reported separately and never creates a fictitious completed development task. Tempo planned effort remains a scheduling input, not measured agent active time or a free substitute for the time baseline. Existing formulas/quality gates remain unchanged.

## 1. Unit of evaluation and completion gate

An efficiency score evaluates one task outcome episode. Create the episode at a stable source-requirements fingerprint before requirements analysis so early planning costs have an owner. Its plan/base/scope bindings are initially provisional, then frozen to the initial accepted execution plan revision, base commit and approved scope before the first implementation; the reviewed resulting diff completes its outcome evidence. Retries against the same outcome are part of that episode. A materially changed ticket starts a successor episode; it does not erase consumption from the parent task. Show the whole-task total beside episode scores. Do not average episode scores into an authoritative task score when scope changed. The UI displays the latest completed episode's score with its episode label and all-task cost/history.

A final efficiency score requires a human-accepted outcome, all mandatory acceptance criteria to have independent evidence, required verification checks to have passed on the reviewed diff, and blocking review findings to be resolved. The application may let a human accept a task with a specific audited verification waiver, as defined in [Agent contracts](AGENT_CONTRACTS.md); that task remains accepted but cannot receive a final efficiency score under this configuration. A waiver never becomes passing evidence. An agent's `succeeded` run is not a completed task. A planning-only task can have planning metrics but is excluded from implementation-score comparisons. No score may reward an untested implementation merely because it was cheap.

| State | Presentation |
| --- | --- |
| Incomplete, failed, cancelled, or awaiting human acceptance | Raw/component metrics with `provisional`; no overall score |
| Completed but missing required evidence, cost/time coverage, or comparable baseline | `Insufficient data`; explain each missing input |
| Completed with adequate evidence and baseline | Overall 0–100 score, breakdown, confidence, calculation version |
| Later known regression invalidates acceptance | Append invalidation event; previous score remains historical and is labelled superseded; no current final score until reviewed resolution |

No missing-weight redistribution. Unknown is not zero and not an average. Synthetic/simulated outcomes never enter baselines or production comparisons.

## 2. Evidence inventory

Persist stable criterion IDs and required test IDs in the approved plan. The test runner, diff collector, reviewer and human decision service supply evidence; the implementing agent cannot award itself passes. Test results include command-policy ID, commit/diff hash, environment/image digest, test selection, exit code, artifact hash, collected/passed/failed/skipped counts and timestamps. Reusing an old green result against a new diff is invalid. Test count alone is not quality evidence.

The first submitted implementation candidate is an immutable diff captured when the agent first claims readiness for review. Record its acceptance checks and tests before fixes. Auto-repair inside an unsubmitted agent run is visible in tool/run history and resource cost, but is not falsely called a new human review cycle. Capture retries/failed runs, distinct reviewer rejection cycles, and unanticipated scope corrections with non-overlapping cause IDs. Store plan revisions, impacted files, anticipated risks, missed clarifications, active-time intervals, human interventions, usage coverage and valuation provenance.

Human review confirms test adequacy and marks each required test `passed`, `failed`, or `waived_with_reason`. A waiver is not a pass. A legitimately testless task requires a pre-approved verification strategy with manual evidence; it is compared only with the corresponding verification-policy cohort. Deleting required tests/criteria during implementation requires scope reapproval and a successor evidence specification, not a better score.

## 3. Complexity classification

Freeze a complexity assessment before the first implementation run. Planning computes a proposal; a human can revise it with a reason. The assessment links its exact plan/source revision and is independent of which model will execute it.

Score each axis 0, 1, or 2 using these anchors:

| Axis | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Files/modules | At most 2 files in 1 module | 3–8 files or 2 modules | More than 8 files or at least 3 modules |
| Dependencies | Self-contained | 1–2 existing integration boundaries | At least 3 boundaries or a new external integration |
| Technical uncertainty | Existing local pattern | Partial precedent or one unresolved technical question | New behavior or several unresolved technical questions |
| Migration risk | No persisted-data/compatibility impact | Backward-compatible schema/config change | Data transformation, version migration, or compatibility break |
| Verification complexity | Isolated test/inspection | Multiple interacting behaviors | Cross-system, concurrency, or migration verification |
| Implementation scope | One bounded behavior | Several connected behaviors | Cross-cutting workflow or subsystem change |

Sum 0–12: `C1=0–2`, `C2=3–5`, `C3=6–8`, `C4=9–10`, `C5=11–12`. The thresholds are initial operational definitions. Examples: an existing Odoo report label might be C1; a multi-module stock unit conversion with migration and security implications might be C4. Classify from evidence rather than using these examples as defaults.

Store axis scores, supporting paths/references, assessor, reason, and assessment version. Complexity changes discovered after execution append a revision; retain the pre-run classification and flag that episode for a human cohort decision. Do not silently upgrade complexity after an expensive failure. Display scores under both classifications only as an explicit sensitivity analysis. Complexity is a cohort adjustment, not free points added to quality.

## 4. Comparable baselines

Use previously completed, human-accepted episodes under a compatible verification policy. Cohort dimensions are task type, complexity class, ecosystem and major version (for example Odoo 19), and verification policy. Do not condition the reference baseline on the evaluated model; comparisons need the same reference. Record environment class and concurrency to identify time confounding. Exclude the episode being scored and future outcomes from its reference snapshot.

Require at least 20 eligible episodes from at least 5 distinct task lineages, with no lineage contributing more than 20% of reference weight. Use the median of per-episode cost and effective-time measures. Exact cohort first; a deterministic approved fallback may pool adjacent ecosystem minor versions, but never pool incompatible verification policies or complexity classes to manufacture sample size. Record fallback level. If thresholds are unmet, report component observations and `Insufficient data`; do not invent a universal baseline. A user-entered target can support a clearly labelled target comparison, not a final peer score.

Each immutable `efficiency_baselines` revision records cohort predicates, episode IDs, exclusions, data cutoff, normalized accounting basis, tariff snapshot if applicable, medians, sample count, dispersion (IQR), and canonical dataset/method hash. Freeze the baseline at first implementation admission for reproducible scoring, or explicitly mark `no baseline at start`; a later baseline may create a retrospective score revision with that label. Never mutate history when new tasks complete.

Cost comparison uses either complete actual attributable billed cost for every member, or complete API-equivalent estimates using one common reference tariff snapshot. Do not mix subscription actual cost zero with API invoices. In the default early product, use API-equivalent cost for comparison and show actual billing separately. Tokens remain visible independently because tokenizers and reasoning accounting differ across models.

## 5. Deterministic component formulas

All scores are clipped to [0,100]. Compute with Decimal, retain full intermediate precision, and display one decimal with round-half-even. Null required inputs produce null component/overall results. The final score is:

\[
S = 0.30C + 0.25Q + 0.20R + 0.15T + 0.10P.
\]

Weights belong to an immutable scoring configuration that sums to 1. Config changes create a new version. The component names below remain explicit in the UI.

### Cost efficiency C

Let `cost` include all requirements, planning, implementation, review and corrective runs in the episode, including failed attempts and visible provider retries. Let `B_cost` be the cohort median under the same valuation basis. Then:

\[
C=100\min(1, B_{cost}/cost).
\]

This saturates at the baseline: spending less cannot outweigh bad quality. Require `B_cost > 0`. When `cost=0` is verified with complete accounting under the same valuation basis and `B_cost > 0`, define `C=100` without division. A missing price cannot produce a zero. A zero/nonpositive baseline makes C unavailable because this ratio has no informative reference; do not use an arbitrary epsilon. Show planning/implementation/review cost splits and failed-run spend as diagnostics; do not subtract them from the total.

### First-pass quality Q

Let `A1` be the fraction of approved acceptance criteria met on the first submitted candidate; `V1` the fraction of required verification checks passing on that candidate; `J1=1` if the separate reviewer found no blocking defect on the first candidate, otherwise 0. Criterion/check weights default equal, or are frozen in the approved plan. Then:

\[
Q=100(0.60A1+0.25V1+0.15J1).
\]

All final criteria/checks still must pass the completion gate; Q preserves the first-pass evidence after corrections. Reviewer findings have documented severity and human confirmation. Nonblocking style suggestions do not set `J1=0`. A verification waiver remains in the denominator without a pass; a no-test cohort uses its pre-approved manual checks. Missing initial evidence gives unknown Q, not inferred perfection from a final green run.

### Rework avoidance R

Let `n` be the number of distinct corrective cycles: failed implementation attempts, reviewer-requested rework, or missed-scope correction cycles. One cause producing both a failed run and reviewer rejection counts once, using its cause ID. Technical provider outages are labelled separately and excluded from `n`, although consumed resources stay in cost/time. Let `rho` be consumed cost attributable to corrective runs divided by total episode cost, bounded [0,1]. When both are verified zero use `rho=0`. Then:

\[
R = \frac{100}{1+0.25n+0.50\rho}.
\]

This initial penalty requires calibration. Retries, scope corrections and review cycles are visible individually; a human can correct cause attribution with an audited revision. Genuine external scope changes create a successor episode and are not mislabelled model rework. The task-level report still includes their resources.

### Time efficiency T

Let `active` be the union of active task execution intervals (not summed parallel agent durations), `human` the explicitly measured active human intervention/review minutes, and `effective=active+human`. Let `B_time` be the comparable cohort median of that same measure. Then:

\[
T=100\min(1,B_{time}/effective).
\]

Require `B_time > 0` and `effective > 0`; otherwise T is unavailable. A reported zero active duration is insufficient timing evidence for a real implementation, not a perfect time score. Do not use an arbitrary epsilon or award points for missing intervals.

Provider backoff, queue delay, human waiting and machine downtime are reported separately. They do not reward or punish the model through T; time-to-acceptable-outcome including all waits is another displayed metric. If active human timing is unavailable, the operator may explicitly select a separate versioned `agent-active-only` cohort/configuration for every member, prominently stating that human time is excluded. It is not an automatic fallback for the default formula. Never substitute zero human minutes into a cohort that measured them. Human intervention counts are visible even in that restricted cohort. Also show agent-seconds so parallelism cannot hide increased compute expenditure.

### Planning accuracy P

Freeze the affected-file predictions and major-risk/clarification list in the approved plan before implementation. Let `F` be file-set F1 between predicted and actually relevant touched source files; generated/build artifacts and mechanical formatting-only changes are excluded by an audited rule. `F=2pr/(p+r)`, where precision and recall have their standard set meanings. Both empty sets yield 1 only for an approved no-code outcome; otherwise absent evidence is unknown.

Let `K` be the fraction of human-confirmed major realized risks anticipated by the plan; if no major risk occurred, `K=1` after review confirms that fact. Let `M` be the count of necessary clarifications missed before implementation and discovered later, excluding genuine source changes. Then:

\[
P=100(0.50F+0.30K+0.20/(1+M)).
\]

Predicting every repository file damages precision. Risks need specific failure conditions and evidence; a generic list of everything that might go wrong is not credited. Planned-versus-actual steps, scope deltas and assumptions remain visible alongside the score. A missed question is adjudicated by the reviewer/human, not by the agent being scored.

## 6. Worked example

Illustrative values below are invented to demonstrate the formula; they are not historical NEXUS results or model benchmarks. A completed C3 Odoo task uses a valid cohort of 24 prior episodes and a shared reference tariff.

| Input | Value |
| --- | --- |
| API-equivalent cost / cohort median | 8.00 / 6.00 USD |
| First-candidate criteria and verification passes | `A1=1.00`, `V1=1.00` |
| First review | One blocking finding, `J1=0` |
| Distinct corrective cycles / corrective cost fraction | `n=1`, `rho=0.20` |
| Effective active time / cohort median | 50 / 40 minutes |
| Planned files / actual files | `{a,b,c,d}` / `{a,b,c,e}` |
| Anticipated major realized risks / missed clarifications | All / 0 |

The final candidate is independently reviewed and accepted with all required checks passing. Cost component is 75.0; first-pass quality is 85.0; rework avoidance is `100/1.35=74.074…`; time is 80.0. File precision and recall are both 0.75, so planning accuracy is `100(0.375+0.30+0.20)=87.5`.

\[
S=0.30(75)+0.25(85)+0.20(74.074\ldots)+0.15(80)+0.10(87.5)=79.3148\ldots
\]

Display **79.3 / 100**, configuration `nexus-efficiency-v1`, reference cohort ID/cutoff, valuation basis and confidence. If the first-candidate verification record is absent, display `Insufficient data` rather than reweighting the remaining components. If a regression later invalidates the accepted result, preserve this historical calculation and mark it superseded.

## 7. Confidence and transparency

Confidence describes evidence completeness/comparability, not statistical certainty that a model caused the outcome. Persist:

- `evidence_coverage`: fraction of required named evidence groups present; all gate groups must be complete for a final score.
- `usage_coverage`: complete, partial, or unknown; source limitations and reconciliation status.
- `baseline_n`, lineage count, cohort fallback, IQR and age.
- `attribution_quality`: exact, allocated, mixed-model, or unknown.
- `review_independence`: separate session, separate model when configured, human acceptance, and known reviewer correlation.

Deterministic labels: `high` requires all gates, exact attribution, an exact cohort with at least 50 episodes/10 lineages, and no unresolved semantic flags; `moderate` requires all gates and at least the 20-episode/5-lineage minimum; otherwise `insufficient`. These are product labels, not confidence intervals. Where valid, analytics may bootstrap cohort medians to show dispersion, with method/version and no claims about causality.

Every task page exposes raw tokens/categories, costs and coverage, duration breakdown, run/cycle counts, plan revisions, acceptance/test/review artifacts, complexity assessment, baseline peers, formula inputs and score revision history. Users can open the calculation evidence, not just a colored gauge.

## 8. Analytics and calibration

Aggregate by exact model/variant, agent-definition revision, task type, complexity, project/Odoo major version, strategy and phase. Display sample size, completed/failed/cancelled counts, telemetry coverage, first-pass success rate, corrective spend, median score/IQR, and cost per accepted task. Cost per accepted task uses all consumed cost in the cohort, including failed/cancelled work, divided by accepted tasks; zero accepted tasks yields undefined, not zero. Show failure rates so ranking only survivors cannot make an unreliable model appear excellent.

Mixed-model tasks are a `mixed` strategy cohort. Per-message cost can be allocated exactly, but quality is an episode outcome and cannot be assigned causally to whichever model generated the most tokens. Do not duplicate one success into several model success counts. Compare within complexity/verification cohorts or standardize to an explicit common task mix; never rank by an unadjusted global average. Calendar periods and incomplete outcomes must use the same cutoff and maturation policy.

Calibration procedure:

1. Collect outcomes without forcing a score during the cold start. Manually inspect at least 20 eligible episodes per candidate cohort.
2. Review whether component scores correspond to human judgments of useful, correct work. Check whether missing tests, scope splitting, expensive planning, or aggressive retries produce misleading rankings.
3. Evaluate proposed weights/penalties on a frozen historical dataset, including failed tasks and complexity revisions. Publish sensitivity results for the initial 30/25/20/15/10 hypothesis and alternatives.
4. Approve a versioned methodology; keep historical scores unchanged and permit an explicitly labelled recalculation view.
5. Reassess monthly or after a meaningful policy/provider/runtime change. Detect drift; retire incompatible baselines rather than blending different test standards.

No employee performance ranking, automated model replacement, or quota enforcement is driven by the score in the MVP. The score supports human comparison and investigation.

## 9. Persistence and tests

`complexity_assessments` stores immutable axis/reason revisions and their pre-run status. `efficiency_baselines` stores immutable cohort/evidence snapshots. `efficiency_scores` stores `(episode_id, scoring_config_hash, baseline_id, evidence_hash)` as a unique calculation, component inputs/values, weights, confidence, status, source cost valuation and supersedes links. Scoring configuration is versioned immutable data. Review/test/outcome events remain independently auditable; the score is a rebuildable projection with a stored reproducibility artifact. See [data model](DATA_MODEL.md) for relationships.

Required tests:

- Golden worked example equals 79.3 after final rounding; identical evidence/config produces the same hash and score on SQLite/PostgreSQL.
- Bounds, monotonic penalties and Decimal arithmetic; every missing required input prevents an overall score; zero denominator cases follow explicit rules.
- Skipped tests, invalid diff hashes, waived mandatory criteria/verification, absent initial-candidate evidence, agent-only completion and unresolved blocking reviews cannot receive a final score. A human-accepted task with an audited waiver stays accepted while its score is unavailable.
- A retry's resources count once; a failure/review rejection sharing one cause ID creates one corrective cycle; genuine scope changes preserve task consumption.
- Baseline excludes current/future/simulated episodes, enforces lineage caps and sample gates, and remains stable after later data arrives.
- User complexity changes, price corrections and regressions create traceable new revisions without replacing prior evidence.
- Paused/waiting intervals and overlapping agents do not inflate union active minutes; missing human timing cannot masquerade as zero.
- Mixed-model attribution and failed-task costs cannot be silently dropped from aggregates. Both dashboard modes expose identical calculations and provenance.

Demonstration: ingest one accepted first-pass episode, one corrected episode, one incomplete episode, and one simulated episode; seed a clearly labelled fixture baseline; inspect score components and missing-data states; then invalidate an acceptance with a regression and verify that the historical score remains available but is no longer current.
