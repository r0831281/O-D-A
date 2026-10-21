"""Versioned provider-neutral source contracts and credential-free adapters."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from nexus.domain import NexusError, StrictModel, canonical_hash


class SourceFailure(NexusError):
    """Safe, bounded connector failure classification; never contains provider body."""

    def __init__(self, code: str, status: int = 503, retry_after: int | None = None):
        self.retry_after = max(0, min(retry_after, 3600)) if retry_after is not None else None
        super().__init__(code, status)


def classify_http_failure(status: int, retry_after: int | None = None) -> SourceFailure:
    if status in {401, 403}:
        return SourceFailure("credentials_or_scope_required", 424)
    if status == 429:
        return SourceFailure("rate_limited", 429, retry_after)
    if status >= 500:
        return SourceFailure("provider_unavailable", 503, retry_after)
    if status >= 400:
        return SourceFailure("provider_rejected_request", 422)
    return SourceFailure("provider_response_invalid", 502)


class ConnectionConfig(StrictModel):
    schema_version: int = 1
    adapter_id: str = Field(min_length=1, max_length=100)
    instance_identity: str = Field(min_length=1, max_length=300)
    base_url: str
    secret_ref: str = Field(min_length=1, max_length=256)

    @field_validator("base_url")
    @classmethod
    def safe_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("connection host must be an HTTPS origin without credentials or path")
        return value.rstrip("/")


class JiraConfig(ConnectionConfig):
    adapter_id: str = "jira-cloud-v1"
    site_url: str
    projects: tuple[str, ...] = ()
    fields: tuple[str, ...] = ("summary", "description", "project", "issuetype", "assignee", "updated", "duedate")
    page_size: int = Field(default=50, ge=1, le=100)

    @field_validator("site_url")
    @classmethod
    def same_configured_origin(cls, value, info):
        base_url = info.data.get("base_url")
        if base_url and value.rstrip("/") != base_url.rstrip("/"):
            raise ValueError("Jira site URL and base URL must identify the same origin")
        return value

    @field_validator("projects")
    @classmethod
    def project_ids_only(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[A-Z0-9_-]{1,64}", project) for project in value):
            raise ValueError("Jira project IDs must be configured canonical keys")
        return value

    @field_validator("fields")
    @classmethod
    def discovered_fields_only(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        base = {"summary", "description", "project", "issuetype", "assignee", "updated", "duedate"}
        if any(field not in base and not re.fullmatch(r"customfield_[0-9]+", field) for field in value):
            raise ValueError("Jira fields must be standard or discovered custom field IDs")
        return value

    @field_validator("site_url")
    @classmethod
    def valid_site(cls, value: str) -> str:
        return ConnectionConfig.safe_https_url(value)


class OdooConfig(ConnectionConfig):
    adapter_id: str
    odoo_major: int = Field(ge=17, le=19)
    database: str = Field(min_length=1, max_length=128)
    login: str = Field(default="", max_length=256)
    company_ids: tuple[int, ...] = ()
    project_ids: tuple[int, ...] = ()
    task_model: str = "project.task"
    readable_fields: tuple[str, ...] = ("id", "name", "description", "project_id", "company_id", "write_date")
    task_domain: tuple[tuple[str, str, object], ...] = ()

    @model_validator(mode="after")
    def adapter_matches_version(self):
        if self.adapter_id != f"odoo-{self.odoo_major}-read-v1":
            raise ValueError("Odoo adapter must match configured major version")
        if self.odoo_major in {17, 18} and not self.login:
            raise ValueError("Odoo RPC login is required")
        return self

    @field_validator("readable_fields")
    @classmethod
    def constrained_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"id", "name", "description", "project_id", "company_id", "write_date", "user_id", "stage_id"}
        if not set(value) <= allowed:
            raise ValueError("unsupported Odoo task field")
        return value


class TempoConfig(ConnectionConfig):
    adapter_id: str = "tempo-cloud-planner-v1"
    product_id: str = Field(min_length=1, max_length=100)
    allocated_account_id: str = Field(min_length=1, max_length=256)
    page_size: int = Field(default=50, ge=1, le=100)
    horizon_days: int = Field(default=60, ge=1, le=180)
    end_date_inclusive: bool | None = None
    from_date: date
    to_date: date

    @field_validator("end_date_inclusive")
    @classmethod
    def explicit_date_semantics(cls, value):
        if value is None:
            raise ValueError("Tempo allocation date-range semantics must be explicitly verified")
        return value

    @field_validator("to_date")
    @classmethod
    def bounded_horizon(cls, value, info):
        start = info.data.get("from_date")
        if start is not None and not 1 <= (value - start).days <= 180:
            raise ValueError("Tempo date window must be bounded to 1..180 days")
        return value


class CalendarConfig(ConnectionConfig):
    adapter_id: str = "ics-local-v1"
    timezone: str = "Europe/Brussels"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


@dataclass(frozen=True)
class SourceItem:
    remote_type: str
    remote_id: str
    display_key: str
    revision: str | None
    modified_at: datetime | None
    normalized: Mapping[str, object]
    raw_hash: str
    origin_uri: str | None = None
    visibility: str = "visible"

    @classmethod
    def build(cls, *, adapter_id: str, remote_type: str, remote_id: str,
              display_key: str, normalized: Mapping[str, object], revision: str | None = None,
              modified_at: datetime | None = None, origin_uri: str | None = None) -> SourceItem:
        raw_hash = canonical_hash(dict(normalized))
        return cls(remote_type, remote_id, display_key, revision, modified_at,
                   dict(normalized), raw_hash, origin_uri)


@dataclass(frozen=True)
class SourcePage:
    key: str
    items: tuple[SourceItem, ...]
    next_cursor: str | None
    complete: bool
    deleted_items: tuple[tuple[str, str], ...] = ()


class ReadTransport(Protocol):
    def request(self, method: str, path: str, *, json_body: dict | None = None) -> tuple[int, Mapping[str, object], int | None]: ...


class SourceAdapter(Protocol):
    adapter_id: str
    build: str

    def discover(self) -> Mapping[str, object]: ...

    def read_test(self) -> Mapping[str, object]: ...

    def fetch_page(self, cursor: str | None) -> SourcePage: ...


def _read(transport: ReadTransport, method: str, path: str, body: dict | None = None) -> Mapping[str, object] | list:
    if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
        raise SourceFailure("operation_not_allowlisted", 403)
    status, payload, retry_after = transport.request(method, path, json_body=body)
    if status < 200 or status >= 300:
        raise classify_http_failure(status, retry_after)
    if not isinstance(payload, (Mapping, list)):
        raise SourceFailure("provider_schema_invalid", 502)
    return payload


def adf_text(node: object) -> str:
    """Extract text only from ADF nodes; never interpret HTML or links as markup."""
    parts: list[str] = []
    if isinstance(node, Mapping):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            parts.append(node["text"])
        for child in node.get("content", ()) if isinstance(node.get("content", ()), list) else ():
            parts.append(adf_text(child))
        if node.get("type") in {"paragraph", "heading", "listItem", "blockquote"}:
            parts.append("\n")
    return "".join(parts).strip()


class JiraCloudAdapter:
    adapter_id = "jira-cloud-v1"
    build = "nexus-jira-cloud-1"

    def __init__(self, config: JiraConfig, transport: ReadTransport):
        self.config, self.transport = config, transport

    def discover(self) -> Mapping[str, object]:
        projects = _read(self.transport, "GET", "/rest/api/3/project/search?maxResults=50")
        fields = _read(self.transport, "GET", "/rest/api/3/field")
        return {"project_count": len(projects.get("values", [])), "field_count": len(fields) if isinstance(fields, list) else 0}

    def read_test(self) -> Mapping[str, object]:
        self.discover()
        return {"identity_verified": True, "read_only": True, "adapter": self.adapter_id}

    def fetch_page(self, cursor: str | None) -> SourcePage:
        body: dict[str, object] = {
            "jql": " ORDER BY updated ASC",
            "fields": list(self.config.fields),
            "maxResults": self.config.page_size,
            "fieldsByKeys": False,
        }
        if self.config.projects:
            body["jql"] = f"project in ({','.join(self.config.projects)}) ORDER BY updated ASC"
        if cursor:
            body["nextPageToken"] = cursor
        result = _read(self.transport, "POST", "/rest/api/3/search/jql", body)
        issues = result.get("issues")
        if not isinstance(issues, list):
            raise SourceFailure("provider_schema_invalid", 502)
        items = []
        for issue in issues:
            if not isinstance(issue, Mapping) or not isinstance(issue.get("fields"), Mapping):
                raise SourceFailure("provider_schema_invalid", 502)
            fields = issue["fields"]
            key, issue_id = issue.get("key"), issue.get("id")
            if not isinstance(key, str) or not isinstance(issue_id, str):
                raise SourceFailure("provider_identity_missing", 502)
            description = fields.get("description")
            normalized = {
                "key": key,
                "title": str(fields.get("summary") or ""),
                "description": adf_text(description) if isinstance(description, Mapping) else str(description or ""),
                "project_id": (fields.get("project") or {}).get("id") if isinstance(fields.get("project"), Mapping) else None,
                "issue_type": (fields.get("issuetype") or {}).get("name") if isinstance(fields.get("issuetype"), Mapping) else None,
                "assignee": (fields.get("assignee") or {}).get("accountId") if isinstance(fields.get("assignee"), Mapping) else None,
                "updated": fields.get("updated"),
                "due_date": fields.get("duedate"),
            }
            items.append(SourceItem.build(adapter_id=self.adapter_id, remote_type="jira.issue", remote_id=issue_id,
                                          display_key=key, normalized=normalized, revision=str(fields.get("updated") or ""),
                                          origin_uri=f"{self.config.site_url}/browse/{key}"))
        next_token = result.get("nextPageToken")
        if next_token is not None and not isinstance(next_token, str):
            raise SourceFailure("provider_schema_invalid", 502)
        complete = result.get("isLast") is True or next_token is None
        return SourcePage(str(cursor or "first"), tuple(items), next_token, complete)


class OdooReadAdapter:
    """Version-gated Odoo task reads; injected transport has no arbitrary method API."""
    build = "nexus-odoo-read-1"

    def __init__(self, config: OdooConfig, transport: ReadTransport):
        self.config, self.transport = config, transport
        self.adapter_id = f"odoo-{config.odoo_major}-read-v1"

    def discover(self) -> Mapping[str, object]:
        if self.config.odoo_major == 19:
            result = _read(self.transport, "POST", "/json/2/project.task/fields_get",
                           {"attributes": ["string", "type", "required"]})
        else:
            # The trusted transport implements XML-RPC authenticate/execute_kw,
            # never a generic caller-supplied model/method proxy.
            result = _read(self.transport, "RPC", "/xmlrpc/2/object/project.task/fields_get",
                           {"attributes": ["string", "type", "required"]})
        available = set(result)
        missing = sorted(set(self.config.readable_fields) - available)
        if missing:
            raise SourceFailure("configured_fields_unavailable", 424)
        return {"model": "project.task", "field_count": len(available), "company_scope": bool(self.config.company_ids)}

    def read_test(self) -> Mapping[str, object]:
        found = self.discover()
        return {**found, "identity_verified": True, "read_only": True}

    def fetch_page(self, cursor: str | None) -> SourcePage:
        offset = int(cursor or 0)
        domain: list[list[object]] = []
        if self.config.project_ids:
            domain.append(["project_id", "in", list(self.config.project_ids)])
        if self.config.company_ids:
            domain.append(["company_id", "in", list(self.config.company_ids)])
        # Cursor is a fixed offset encoded by NEXUS, not an expression or endpoint.
        args = {"domain": domain, "fields": list(self.config.readable_fields), "limit": 100,
                "offset": offset, "order": "write_date,id"}
        path = "/json/2/project.task/search_read" if self.config.odoo_major == 19 else "/xmlrpc/2/object/project.task/search_read"
        records = _read(self.transport, "POST" if self.config.odoo_major == 19 else "RPC", path, args)
        if not isinstance(records, list):
            raise SourceFailure("provider_schema_invalid", 502)
        items = []
        for record in records:
            if not isinstance(record, Mapping) or not isinstance(record.get("id"), int):
                raise SourceFailure("provider_identity_missing", 502)
            normalized = dict(record)
            normalized.pop("__last_update", None)
            items.append(SourceItem.build(adapter_id=self.adapter_id, remote_type="odoo.project_task",
                                          remote_id=str(record["id"]), display_key=str(record.get("name") or record["id"]),
                                          normalized=normalized, revision=str(record.get("write_date") or ""),
                                          origin_uri=f"{self.config.base_url}/web#id={record['id']}&model=project.task"))
        next_offset = offset + len(records) if len(records) == 100 else None
        return SourcePage(str(offset), tuple(items), str(next_offset) if next_offset is not None else None,
                          next_offset is None)


class TempoCloudAdapter:
    """Initial Tempo Cloud Planner candidate; readiness needs an account read-test."""
    adapter_id = "tempo-cloud-planner-v1"
    build = "nexus-tempo-cloud-planner-1-unverified"

    def __init__(self, config: TempoConfig, transport: ReadTransport):
        self.config, self.transport = config, transport

    def discover(self) -> Mapping[str, object]:
        plans = _read(self.transport, "POST", "/4/plans/search", {
            "accountIds": [self.config.allocated_account_id], "from": self.config.from_date.isoformat(),
            "to": self.config.to_date.isoformat(), "limit": 1, "offset": 0,
        })
        return {"product_id": self.config.product_id, "plan_search": isinstance(plans, Mapping),
                "provider_verification": "account_probe_required"}

    def read_test(self) -> Mapping[str, object]:
        found = self.discover()
        account = _read(self.transport, "GET", f"/4/plans/user/{self.config.allocated_account_id}")
        if not isinstance(account, (Mapping, list)):
            raise SourceFailure("provider_schema_invalid", 502)
        return {**found, "account_read": True, "read_only": True}

    def fetch_page(self, cursor: str | None) -> SourcePage:
        offset = int(cursor or 0)
        payload = _read(self.transport, "POST", "/4/plans/search", {
            "accountIds": [self.config.allocated_account_id], "assigneeTypes": ["USER", "GENERIC"],
            "from": self.config.from_date.isoformat(), "to": self.config.to_date.isoformat(),
            "planItemTypes": ["ISSUE", "PROJECT"], "plannedTimeBreakdown": ["DAILY", "PERIOD"],
            "limit": self.config.page_size, "offset": offset,
        })
        values = payload.get("results") if isinstance(payload, Mapping) else None
        metadata = payload.get("metadata") if isinstance(payload, Mapping) and isinstance(payload.get("metadata"), Mapping) else {}
        if not isinstance(values, list) or not isinstance(metadata, Mapping):
            raise SourceFailure("tempo_product_or_schema_unverified", 424)
        items = []
        for value in values:
            if not isinstance(value, Mapping) or value.get("id") is None:
                raise SourceFailure("provider_schema_invalid", 502)
            assignee = value.get("assignee") if isinstance(value.get("assignee"), Mapping) else {}
            item_id = value.get("planItemId")
            item_type = str(value.get("planItemType") or "GENERIC").lower()
            item = {"allocation_id": str(value["id"]), "account_id": str(assignee.get("id") or self.config.allocated_account_id),
                    "resource_type": str(assignee.get("type") or "USER").lower(),
                    "issue_id": str(item_id) if item_type == "issue" and item_id else None,
                    "issue_key": value.get("issueKey"), "project_id": str(item_id) if item_type == "project" and item_id else None,
                    "start_date": value.get("startDate"),
                    "end_date_exclusive": _tempo_exclusive_end(value.get("endDate"), self.config.end_date_inclusive),
                    "effort_seconds": value.get("plannedSeconds"), "seconds_per_day": value.get("plannedSecondsPerDay"),
                    "effort_persistence_type": value.get("effortPersistenceType"),
                    "include_non_working_days": value.get("includeNonWorkingDays"),
                    "status": value.get("status"),
                    "start_time": value.get("startTime"), "updated": value.get("updatedAt")}
            items.append(SourceItem.build(adapter_id=self.adapter_id, remote_type="tempo.allocation", remote_id=str(value["id"]),
                                          display_key=str(issue.get("key") or value["id"]), normalized=item,
                                          revision=str(value.get("updatedAt") or "")))
        next_cursor = offset + len(values) if len(values) >= self.config.page_size else None
        return SourcePage(f"offset:{offset}", tuple(items), str(next_cursor) if next_cursor is not None else None,
                          next_cursor is None)


def _tempo_exclusive_end(value: object, inclusive: bool | None) -> str | None:
    if not isinstance(value, str):
        return None
    end = date.fromisoformat(value)
    return (end + timedelta(days=1) if inclusive else end).isoformat()


def registered_adapters() -> tuple[str, ...]:
    return ("ics-local-v1", "jira-cloud-v1", "odoo-17-read-v1", "odoo-18-read-v1",
            "odoo-19-read-v1", "tempo-cloud-planner-v1")


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return [line for line in lines if line]


def parse_ics(text: str, default_timezone: str = "Europe/Brussels", *, expansion_days: int = 366) -> tuple[dict[str, object], ...]:
    """Parse local ICS content, expand bounded DAILY/WEEKLY recurrence, retain exclusive all-day ends."""
    if len(text.encode()) > 2_000_000 or "BEGIN:VCALENDAR" not in text:
        raise NexusError("calendar_input_invalid", 422)
    ZoneInfo(default_timezone)
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            events.append(current)
            current = None
        elif current is not None and ":" in line:
            name, value = line.split(":", 1)
            key = name.split(";", 1)[0].upper()
            params = name[len(key):]
            current[key + params] = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
    result: list[dict[str, object]] = []
    for event in events:
        uid = event.get("UID")
        start_key = next((key for key in event if key.startswith("DTSTART")), None)
        end_key = next((key for key in event if key.startswith("DTEND")), None)
        if not uid or not start_key or not end_key:
            raise NexusError("calendar_event_incomplete", 422)
        tzid = re.search(r"TZID=([^;:]+)", start_key)
        timezone = ZoneInfo(tzid.group(1) if tzid else default_timezone)
        all_day = "VALUE=DATE" in start_key
        start_value, end_value = event[start_key], event[end_key]
        if all_day:
            start_date, end_date = date.fromisoformat(f"{start_value[:4]}-{start_value[4:6]}-{start_value[6:8]}"), date.fromisoformat(f"{end_value[:4]}-{end_value[4:6]}-{end_value[6:8]}")
            start_local = datetime.combine(start_date, time.min, timezone)
            duration = end_date - start_date
        else:
            start_local = datetime.strptime(start_value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone) if len(start_value) == 15 else datetime.strptime(start_value, "%Y%m%dT%H%M").replace(tzinfo=timezone)
            end_local = datetime.strptime(end_value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone) if len(end_value) == 15 else datetime.strptime(end_value, "%Y%m%dT%H%M").replace(tzinfo=timezone)
            duration = end_local - start_local
        rule = event.get("RRULE", "")
        fields = dict(part.split("=", 1) for part in rule.split(";") if "=" in part)
        frequency = fields.get("FREQ")
        if frequency and frequency not in {"DAILY", "WEEKLY"}:
            raise NexusError("calendar_recurrence_unsupported", 422)
        interval = int(fields.get("INTERVAL", "1"))
        count = min(int(fields.get("COUNT", str(expansion_days))), expansion_days)
        until_raw = fields.get("UNTIL")
        until = datetime.strptime(until_raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone) if until_raw and "T" in until_raw else None
        exceptions = {value for key, value in event.items() if key.startswith("EXDATE")}
        for index in range(count if frequency else 1):
            offset = timedelta(days=index * interval * (7 if frequency == "WEEKLY" else 1))
            occurrence = start_local + offset
            if until and occurrence > until:
                break
            stamp = occurrence.strftime("%Y%m%dT%H%M%S")
            if stamp in exceptions:
                continue
            occurrence_end = occurrence + duration
            entry: dict[str, object] = {"uid": uid, "occurrence_key": stamp, "summary": event.get("SUMMARY", ""),
                                        "timezone": timezone.key, "cancelled": event.get("STATUS") == "CANCELLED"}
            if all_day:
                entry.update(all_day_start=occurrence.date().isoformat(), all_day_end_exclusive=(occurrence.date() + duration).isoformat())
            else:
                entry.update(start_utc=occurrence.astimezone(UTC).isoformat(), end_utc=occurrence_end.astimezone(UTC).isoformat())
            result.append(entry)
    return tuple(result)


def canonical_payload_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
