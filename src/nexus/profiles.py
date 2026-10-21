"""Strict planning-profile contracts and deterministic source routing."""

from collections.abc import Callable, Mapping
from enum import StrEnum
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from nexus.domain import NexusError, StrictModel, canonical_hash


class WorkClass(StrEnum):
    HELPDESK = "helpdesk"
    PROJECT = "project"
    JIRA_PROJECT = "jira_project"


class ClassificationRule(StrictModel):
    schema_version: int = 1
    category: WorkClass
    jira_project_ids: tuple[str, ...] = Field(min_length=1)
    issue_types: tuple[str, ...] = ()
    field_id: str | None = None
    field_values: tuple[str, ...] = ()
    acceptance_field_ids: tuple[str, ...] = ()
    requirements_source: str
    odoo_link_field: str | None = None
    repository_mapping_ref: str | None = None

    @model_validator(mode="after")
    def correct_requirements_authority(self):
        if self.category == WorkClass.HELPDESK and self.requirements_source != "jira":
            raise ValueError("helpdesk requirements must come from Jira")
        if self.category == WorkClass.PROJECT and (
            self.requirements_source != "odoo" or not self.odoo_link_field
        ):
            raise ValueError("project requirements require an explicit Odoo link field")
        if self.category == WorkClass.JIRA_PROJECT and self.requirements_source != "jira":
            raise ValueError("Jira project requirements must come from Jira")
        if bool(self.field_values) != bool(self.field_id):
            raise ValueError("classification field and values must be configured together")
        return self


class OdooInstanceRef(StrictModel):
    schema_version: int = 1
    connection_revision_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    database: str = Field(min_length=1)
    company_ids: tuple[int, ...] = ()
    project_ids: tuple[int, ...] = ()

    @model_validator(mode="after")
    def host_is_dns_name(self):
        parsed = urlsplit("https://" + self.host)
        if parsed.hostname != self.host or parsed.path or parsed.port or parsed.username:
            raise ValueError("Odoo host must be a plain configured hostname")
        return self


class PlanningProfileConfig(StrictModel):
    schema_version: int = 1
    slug: str = Field(min_length=1, max_length=128)
    timezone: str = "Europe/Brussels"
    schedule_connection_revision_id: str = Field(min_length=1)
    jira_connection_revision_id: str = Field(min_length=1)
    odoo_connection_revision_ids: tuple[str, ...] = ()
    odoo_instances: tuple[OdooInstanceRef, ...] = ()
    allocated_account_id: str = Field(min_length=1)
    rules: tuple[ClassificationRule, ...] = Field(min_length=1)
    optional_calendar_connection_revision_ids: tuple[str, ...] = ()
    freshness_seconds: int = Field(default=900, ge=60, le=86400)
    horizon_days: int = Field(default=60, ge=1, le=180)

    @model_validator(mode="after")
    def validate_routes(self):
        ZoneInfo(self.timezone)
        for index, rule in enumerate(self.rules):
            for other in self.rules[index + 1:]:
                projects_overlap = bool(set(rule.jira_project_ids) & set(other.jira_project_ids))
                types_overlap = (not rule.issue_types or not other.issue_types
                                 or bool(set(rule.issue_types) & set(other.issue_types)))
                fields_overlap = (
                    (not rule.field_id and not other.field_id)
                    or (rule.field_id == other.field_id and
                        (not rule.field_values or not other.field_values
                         or bool(set(rule.field_values) & set(other.field_values))))
                )
                if projects_overlap and types_overlap and fields_overlap:
                    raise ValueError("overlapping classification rules")
        if len(set(self.odoo_connection_revision_ids)) != len(self.odoo_connection_revision_ids):
            raise ValueError("duplicate Odoo connection revision")
        if {item.connection_revision_id for item in self.odoo_instances} != set(self.odoo_connection_revision_ids):
            raise ValueError("each Odoo revision requires an explicit host/database/company mapping")
        return self

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class LinkStatus(StrEnum):
    RESOLVED = "resolved"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    INACCESSIBLE = "inaccessible"
    INVALID = "invalid"


class RouteResult(StrictModel):
    schema_version: int = 1
    status: str
    category: str | None = None
    jira_issue_id: str
    requirements_source: str | None = None
    requirements_identity: str | None = None
    requirements: Mapping[str, object] | None = None
    repository_mapping_ref: str | None = None
    allocated_account_id: str | None = None
    jira_assignee_id: str | None = None
    mismatch: bool = False
    blockers: tuple[str, ...] = ()
    trace: tuple[Mapping[str, object], ...] = ()


def _field_value(issue: Mapping[str, object], field_id: str) -> object:
    fields = issue.get("fields", {})
    if not isinstance(fields, Mapping):
        return None
    return fields.get(field_id)


def _explicit_odoo_identity(value: object, allowed_hosts: set[str]) -> tuple[str, int] | None:
    if isinstance(value, Mapping):
        model, record_id, host, database = value.get("model"), value.get("id"), value.get("host"), value.get("database")
        if model == "project.task" and isinstance(record_id, int) and record_id > 0 and isinstance(host, str) and isinstance(database, str):
            parsed = urlsplit(host)
            if parsed.scheme == "https" and parsed.hostname in allowed_hosts and parsed.path in {"", "/"}:
                return f"{parsed.hostname}/{database}", record_id
        return None
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts or parsed.username:
            return None
        query = parse_qs(parsed.query)
        match = re.search(r"(?:[?&#]|^)id=(\d+)", parsed.query)
        model = re.search(r"(?:[?&#]|^)model=([^&#]+)", parsed.query)
        database = (query.get("db") or [None])[0]
        if match and model and model.group(1) == "project.task" and database:
            return f"{parsed.hostname}/{database}", int(match.group(1))
    return None


def resolve_route(
    profile: PlanningProfileConfig,
    jira_issue: Mapping[str, object],
    *,
    allocated_account_id: str,
    fetch_odoo: Callable[[str, int], tuple[LinkStatus, Mapping[str, object] | None]] | None = None,
) -> RouteResult:
    """Resolve only configured exact metadata/IDs; no title match or fallback."""
    issue_id = str(jira_issue.get("id") or "")
    fields = jira_issue.get("fields") if isinstance(jira_issue.get("fields"), Mapping) else {}
    project = str((fields.get("project") or {}).get("id") or "") if isinstance(fields.get("project"), Mapping) else ""
    issue_type = str((fields.get("issuetype") or {}).get("name") or "") if isinstance(fields.get("issuetype"), Mapping) else ""
    matches = []
    for rule in profile.rules:
        if project not in rule.jira_project_ids:
            continue
        if rule.issue_types and issue_type not in rule.issue_types:
            continue
        if rule.field_id and _field_value(jira_issue, rule.field_id) not in rule.field_values:
            continue
        matches.append(rule)
    if len(matches) != 1:
        reason = "classification_unmatched" if not matches else "classification_ambiguous"
        return RouteResult(status="blocked", jira_issue_id=issue_id, blockers=(reason,),
                           allocated_account_id=allocated_account_id,
                           jira_assignee_id=_assignee(fields), mismatch=_assignee(fields) not in {None, allocated_account_id},
                           trace=({"step": "classification", "status": reason},))
    rule = matches[0]
    trace: list[Mapping[str, object]] = [
        {"step": "tempo_allocation", "account_id": allocated_account_id},
        {"step": "jira_issue", "issue_id": issue_id, "project_id": project, "issue_type": issue_type},
        {"step": "classification", "category": rule.category.value},
    ]
    assignee = _assignee(fields)
    mismatch = assignee not in {None, allocated_account_id}
    if rule.requirements_source == "jira":
        trace.append({"step": "requirements", "source": "jira", "identity": issue_id})
        return RouteResult(status="ready", category=rule.category.value, jira_issue_id=issue_id,
                           requirements_source="jira", requirements_identity=issue_id,
                           requirements={"description": fields.get("description"),
                                         "acceptance": {field: fields.get(field) for field in rule.acceptance_field_ids}},
                           repository_mapping_ref=rule.repository_mapping_ref,
                           allocated_account_id=allocated_account_id, jira_assignee_id=assignee,
                           mismatch=mismatch, trace=tuple(trace))
    if not rule.odoo_link_field:
        raise NexusError("invalid_profile_route", 422)
    identities = _explicit_odoo_identity(_field_value(jira_issue, rule.odoo_link_field),
                                         {item.host for item in profile.odoo_instances})
    if identities is None:
        link_value = _field_value(jira_issue, rule.odoo_link_field)
        status, reason = (LinkStatus.MISSING, "odoo_link_missing") if link_value is None or link_value == "" else (LinkStatus.INVALID, "odoo_link_invalid")
        trace.append({"step": "odoo_link", "status": status.value})
        return RouteResult(status="blocked", category=rule.category.value, jira_issue_id=issue_id,
                           requirements_source="odoo", blockers=(reason,), allocated_account_id=allocated_account_id,
                           jira_assignee_id=assignee, mismatch=mismatch, trace=tuple(trace))
    odoo_instance = next((item for item in profile.odoo_instances
                          if f"{item.host}/{item.database}" == identities[0]), None)
    if odoo_instance is None:
        return RouteResult(status="blocked", category=rule.category.value, jira_issue_id=issue_id,
                           requirements_source="odoo", blockers=("odoo_instance_or_database_mismatch",),
                           allocated_account_id=allocated_account_id, jira_assignee_id=assignee,
                           mismatch=mismatch, trace=tuple(trace))
    if fetch_odoo is None:
        return RouteResult(status="blocked", category=rule.category.value, jira_issue_id=issue_id,
                           requirements_source="odoo", blockers=("odoo_fetch_not_configured",),
                           allocated_account_id=allocated_account_id, jira_assignee_id=assignee,
                           mismatch=mismatch, trace=tuple(trace))
    status, task = fetch_odoo(*identities)
    trace.append({"step": "odoo_task", "instance": identities[0], "record_id": identities[1], "status": status.value})
    if status != LinkStatus.RESOLVED or task is None:
        reason = {LinkStatus.AMBIGUOUS: "odoo_link_ambiguous", LinkStatus.INACCESSIBLE: "odoo_task_inaccessible",
                  LinkStatus.MISSING: "odoo_task_missing", LinkStatus.INVALID: "odoo_link_invalid"}.get(status, "odoo_link_unresolved")
        return RouteResult(status="blocked", category=rule.category.value, jira_issue_id=issue_id,
                           requirements_source="odoo", requirements_identity=f"{identities[0]}:project.task:{identities[1]}",
                           blockers=(reason,), allocated_account_id=allocated_account_id,
                           jira_assignee_id=assignee, mismatch=mismatch, trace=tuple(trace))
    trace.append({"step": "requirements", "source": "odoo", "identity": f"{identities[0]}:project.task:{identities[1]}"})
    return RouteResult(status="ready", category=rule.category.value, jira_issue_id=issue_id,
                       requirements_source="odoo", requirements_identity=f"{identities[0]}:project.task:{identities[1]}",
                       requirements=dict(task), repository_mapping_ref=rule.repository_mapping_ref,
                       allocated_account_id=allocated_account_id, jira_assignee_id=assignee,
                       mismatch=mismatch, trace=tuple(trace))


def _assignee(fields: Mapping[str, object]) -> str | None:
    assignee = fields.get("assignee")
    return str(assignee["accountId"]) if isinstance(assignee, Mapping) and assignee.get("accountId") else None
