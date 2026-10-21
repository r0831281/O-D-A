"""Pure state and canonical input contracts; no runtime-specific identifiers."""

import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NexusError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def integer_schema_version(cls, value):
        if isinstance(value, dict) and "schema_version" in value:
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError("unsupported schema version")
        return value


class TaskState(StrEnum):
    IMPORTED = "imported"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_PLANNING = "ready_for_planning"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    APPROVED = "approved"
    IMPLEMENTING = "implementing"
    IMPLEMENTATION_REVIEW = "implementation_review"
    COMPLETED = "completed"


class RunState(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    WAITING = "waiting"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNCERTAIN = "uncertain"


class Evidence(StrEnum):
    """Required *server facts*, never request fields or authorization substitutes."""

    CLARIFICATION = "clarification_recorded"
    ANALYSIS = "validated_analysis"
    CONDITIONS = "resolved_conditions"
    CLAIM = "planning_claim"
    PLAN = "validated_plan"
    CHANGES = "human_changes_requested"
    GRANT = "bound_execution_grant"
    START = "consumed_grant_and_preflight"
    STALE = "expired_or_changed_binding"
    CANDIDATE = "immutable_candidate_and_evidence"
    ACCEPTANCE = "human_candidate_acceptance"
    REOPEN = "explicit_reopen"


EDGES: dict[tuple[TaskState, TaskState], frozenset[Evidence]] = {
    (TaskState.IMPORTED, TaskState.NEEDS_CLARIFICATION): frozenset({Evidence.CLARIFICATION}),
    (TaskState.IMPORTED, TaskState.READY_FOR_PLANNING): frozenset({Evidence.ANALYSIS}),
    (TaskState.NEEDS_CLARIFICATION, TaskState.READY_FOR_PLANNING): frozenset(
        {Evidence.ANALYSIS, Evidence.CONDITIONS}
    ),
    (TaskState.READY_FOR_PLANNING, TaskState.PLANNING): frozenset({Evidence.CLAIM}),
    (TaskState.PLANNING, TaskState.PLAN_REVIEW): frozenset({Evidence.PLAN}),
    (TaskState.PLANNING, TaskState.NEEDS_CLARIFICATION): frozenset({Evidence.CLARIFICATION}),
    (TaskState.PLAN_REVIEW, TaskState.READY_FOR_PLANNING): frozenset({Evidence.CHANGES}),
    (TaskState.PLAN_REVIEW, TaskState.APPROVED): frozenset({Evidence.GRANT}),
    (TaskState.APPROVED, TaskState.IMPLEMENTING): frozenset({Evidence.START}),
    (TaskState.APPROVED, TaskState.PLAN_REVIEW): frozenset({Evidence.STALE}),
    (TaskState.IMPLEMENTING, TaskState.IMPLEMENTATION_REVIEW): frozenset({Evidence.CANDIDATE}),
    (TaskState.IMPLEMENTATION_REVIEW, TaskState.COMPLETED): frozenset({Evidence.ACCEPTANCE}),
    (TaskState.IMPLEMENTATION_REVIEW, TaskState.PLAN_REVIEW): frozenset({Evidence.CHANGES}),
    (TaskState.COMPLETED, TaskState.IMPORTED): frozenset({Evidence.REOPEN}),
}


def guard_transition(
    current: TaskState,
    target: TaskState,
    facts: frozenset[Evidence] = frozenset(),
    *,
    has_hold: bool = False,
) -> None:
    required = EDGES.get((current, target))
    if required is None:
        raise NexusError("forbidden_transition")
    if not required <= facts:
        raise NexusError("missing_evidence")
    if has_hold and target in {
        TaskState.READY_FOR_PLANNING,
        TaskState.PLANNING,
        TaskState.APPROVED,
        TaskState.IMPLEMENTING,
        TaskState.COMPLETED,
    }:
        raise NexusError("task_on_hold")


def _canonical(value):
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        result = {}
        for key, item in value.items():
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                raise ValueError("duplicate normalized canonical key")
            result[normalized] = _canonical(item)
        return result
    raise ValueError("canonical values must use strings, integers, booleans and null")


def canonical_hash(value) -> str:
    envelope = {"algorithm": "nexus-canonical-v1", "value": _canonical(value)}
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SourceIdentity(StrictModel):
    schema_version: Literal[1] = 1
    adapter_id: str = Field(min_length=1, max_length=100)
    instance_identity: str = Field(min_length=1, max_length=200)
    remote_type: str = Field(min_length=1, max_length=100)
    remote_id: str = Field(min_length=1, max_length=200)


class FingerprintManifest(StrictModel):
    schema_version: Literal[1] = 1
    source: SourceIdentity
    requirements_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    repository_commits: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        data = self.model_dump(mode="json")
        data["repository_commits"] = sorted(data["repository_commits"])
        return canonical_hash(data)
