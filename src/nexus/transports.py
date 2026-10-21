"""Constrained HTTPS transports. Credentials are read at process start, never persisted."""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
import xmlrpc.client
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from nexus.sources import ReadTransport, SourceFailure


def resolve_secret(reference: str) -> str:
    match = re.fullmatch(r"env:(NEXUS_SECRET_[A-Z0-9_]{1,64})", reference)
    if not match:
        raise SourceFailure("secret_reference_invalid", 422)
    value = os.environ.get(match.group(1))
    if not value:
        raise SourceFailure("credentials_not_available", 424)
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


class HttpsJsonTransport(ReadTransport):
    """Fixed-host JSON client with explicit GET/POST operation allowlists."""

    def __init__(
        self,
        base_url: str,
        credential: str,
        *,
        adapter: str,
        timeout: float = 10,
        database: str | None = None,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("HTTPS provider origin required")
        self.base_url, self.host, self.adapter, self.timeout = (
            base_url.rstrip("/"),
            parsed.hostname,
            adapter,
            timeout,
        )
        self.credential = credential
        self.database = database
        self._opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def _allowed(self, method: str, path: str) -> bool:
        if self.adapter == "jira":
            return (method, path.split("?", 1)[0]) in {
                ("GET", "/rest/api/3/project/search"),
                ("GET", "/rest/api/3/field"),
                ("POST", "/rest/api/3/search/jql"),
            }
        if self.adapter == "tempo":
            return (method, path) == ("POST", "/4/plans/search")
        if self.adapter == "odoo19":
            return method == "POST" and path in {
                "/json/2/project.task/fields_get",
                "/json/2/project.task/search_read",
            }
        return False

    def request(self, method: str, path: str, *, json_body: dict | None = None):
        if not self._allowed(method, path):
            raise SourceFailure("operation_not_allowlisted", 403)
        headers = {"Accept": "application/json", "User-Agent": "NEXUS-read-only/1"}
        if self.adapter == "jira":
            try:
                email, token = self.credential.split(":", 1)
            except ValueError as exc:
                raise SourceFailure("credentials_not_available", 424) from exc
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{email}:{token}".encode()
            ).decode("ascii")
        else:
            headers["Authorization"] = f"Bearer {self.credential}"
        if self.adapter == "odoo19" and self.database:
            headers["X-Odoo-Database"] = self.database
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(json_body).encode() if json_body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise SourceFailure("provider_response_too_large", 502)
                try:
                    payload = json.loads(raw) if raw else {}
                except (ValueError, UnicodeDecodeError) as exc:
                    raise SourceFailure("provider_schema_invalid", 502) from exc
                if not isinstance(payload, (Mapping, list)):
                    raise SourceFailure("provider_schema_invalid", 502)
                return response.status, payload, None
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After")
            try:
                retry_seconds = int(retry) if retry else None
            except ValueError:
                try:
                    retry_time = parsedate_to_datetime(retry) if retry else None
                    retry_seconds = (
                        max(0, int(retry_time.timestamp() - time.time())) if retry_time else None
                    )
                except (TypeError, ValueError, OverflowError):
                    retry_seconds = None
            return exc.code, {}, retry_seconds
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceFailure("provider_timeout_or_network_error", 503) from exc


class OdooRpcTransport(ReadTransport):
    """17/18 RPC facade exposing fields_get/search_read only for project.task."""

    def __init__(self, base_url: str, database: str, login: str, api_key: str, timeout: float = 10):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("HTTPS Odoo origin required")
        self.base_url, self.database, self.login, self.api_key, self.timeout = (
            base_url.rstrip("/"),
            database,
            login,
            api_key,
            timeout,
        )

    def _proxy(self, path: str):
        transport = _BoundedXmlRpcTransport(self.timeout)
        return xmlrpc.client.ServerProxy(
            self.base_url + path, transport=transport, allow_none=False, use_builtin_types=True
        )

    def request(self, method: str, path: str, *, json_body: dict | None = None):
        if method != "RPC" or path not in {
            "/xmlrpc/2/object/project.task/fields_get",
            "/xmlrpc/2/object/project.task/search_read",
        }:
            raise SourceFailure("operation_not_allowlisted", 403)
        try:
            common = self._proxy("/xmlrpc/2/common")
            uid = common.authenticate(self.database, self.login, self.api_key, {})
            if not isinstance(uid, int) or uid <= 0:
                return 401, {}, None
            proxy = self._proxy("/xmlrpc/2/object")
            method_name = path.rsplit("/", 1)[1]
            args = json_body or {}
            if method_name == "fields_get":
                result = proxy.execute_kw(
                    self.database,
                    uid,
                    self.api_key,
                    "project.task",
                    "fields_get",
                    [],
                    {"attributes": args.get("attributes", [])},
                )
            else:
                result = proxy.execute_kw(
                    self.database,
                    uid,
                    self.api_key,
                    "project.task",
                    "search_read",
                    [args.get("domain", [])],
                    {
                        "fields": args.get("fields", []),
                        "limit": args.get("limit", 100),
                        "offset": args.get("offset", 0),
                        "order": "write_date,id",
                    },
                )
            if not isinstance(result, (Mapping, list)):
                raise SourceFailure("provider_schema_invalid", 502)
            return 200, result, None
        except xmlrpc.client.Fault as exc:
            message = str(exc).lower()
            status = 403 if "access" in message or "permission" in message else 422
            return status, {}, None
        except (xmlrpc.client.ProtocolError, OSError, TimeoutError) as exc:
            raise SourceFailure("provider_timeout_or_network_error", 503) from exc


class _BoundedXmlRpcTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__(context=ssl.create_default_context())
        self.timeout = timeout

    def make_connection(self, host):
        host_with_port, _, _ = self.get_host_info(host)
        return http.client.HTTPSConnection(
            host_with_port, timeout=self.timeout, context=ssl.create_default_context()
        )


def json_transport_for(config: Mapping[str, object], secret_ref: str):
    credential = resolve_secret(secret_ref)
    adapter_id = str(config.get("adapter_id"))
    transport = {
        "jira-cloud-v1": "jira",
        "tempo-cloud-planner-v1": "tempo",
        "odoo-19-read-v1": "odoo19",
    }.get(adapter_id)
    if transport is None:
        raise SourceFailure("transport_adapter_unavailable", 424)
        return HttpsJsonTransport(
            str(config["base_url"]),
            credential,
            adapter=transport,
            database=str(config["database"]) if config.get("database") else None,
        )
