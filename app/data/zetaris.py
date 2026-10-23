"""Zetaris data adapter: the four sources through one Unified Semantic Layer, over REST.

The default data path (architecture §3). Agents keep writing `<source>.<table>`; the adapter maps each
reference to its USL table (`orders.orders` -> `lightning.metastore.explain_why.olist_usl.orders`, see
`app/data/usl.py`) and sends the statement, whole, to `POST <ZETARIS_URL>/sql-editor/sqls/run`.

- Same contract as `LocalDataLayer`: the same read-only guard (`check_read_only`), row limit, query
  ids (`q001`, …) and JSONL query log; a query never raises.
- REST returns every value as a string (decimals with 18 places, sometimes `0E-18`), so values are
  converted from the USL column types; computed columns are inferred column by column.
- Auth: `Authorization: Bearer <ZETARIS_API_KEY>`; if no key is set, or the key is refused (401/403),
  a session token from `GET /auth/login` (Basic `ZETARIS_USERNAME` / `ZETARIS_PASSWORD`). Every call
  sends `X-Org-ID` and a fresh `X-Request-ID` and has a timeout. Credentials are only ever placed in
  request headers; error texts are scrubbed of them before they reach a result or a log.
- Fallback (architecture §4): a connection error, timeout or 5xx is retried once; if the retry fails
  too, the same statement runs on the local DuckDB adapter and the result and the log line say
  `adapter: "local (fallback from zetaris)"`. A 4xx (Zetaris rejected the SQL) is not an outage: it is
  returned as a `failed` error so the Investigator can repair the statement.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings, resolve_path
from app.data.layer import (
    ColumnInfo,
    DataLayer,
    QueryError,
    QueryLog,
    QueryOutcome,
    QueryResult,
    SourceInfo,
    TableInfo,
    elapsed_ms,
)
from app.data.local import GuardError, LocalDataLayer, check_read_only
from app.data.usl import SOURCES, TABLES, UslTable, tables_of

FALLBACK_ADAPTER = "local (fallback from zetaris)"
RUN_SQL_PATH = "/sql-editor/sqls/run"
LOGIN_PATH = "/auth/login"
MAX_ERROR_CHARS = 500
CONNECT_TIMEOUT_SECONDS = 10.0


class ZetarisUnavailable(Exception):
    """Zetaris could not answer: connection error, timeout or HTTP 5xx. Triggers retry and fallback."""

    def __init__(self, message: str, *, timeout: bool = False) -> None:
        super().__init__(message)
        self.timeout = timeout


class ZetarisRequestError(Exception):
    """Zetaris answered with a 4xx: the statement or the request was rejected."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class ZetarisAuthError(ZetarisRequestError):
    """Zetaris refused the credentials (401/403) and no login fallback worked."""


@dataclass(frozen=True)
class RestResult:
    """One `sqls/run` response: column names, declared types if the server sent them, string rows."""

    headers: list[str]
    header_types: list[str | None]
    data: list[list[Any]]
    total: int | None
    body: dict[str, Any]


Recorder = Callable[[str, int, dict[str, Any]], None]


class ZetarisClient:
    """Minimal REST client for `POST /sql-editor/sqls/run`, one statement per request."""

    def __init__(
        self,
        base_url: str,
        *,
        org_id: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        recorder: Recorder | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("ZETARIS_URL is empty")
        if not org_id:
            raise ValueError("ZETARIS_ORG_ID is empty")
        if not api_key and not (username and password):
            raise ValueError("set ZETARIS_API_KEY, or ZETARIS_USERNAME and ZETARIS_PASSWORD for login")
        self.base_url = base_url.rstrip("/")
        self.org_id = str(org_id)
        self.timeout = float(timeout)
        self.recorder = recorder
        self._api_key = api_key
        self._username = username
        self._password = password
        self._session_token = ""
        self._key_refused = False
        self._http = httpx.Client(transport=transport, follow_redirects=False)

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> ZetarisClient:
        """Client configured from `ZETARIS_*` settings; raises `ValueError` if they are incomplete."""
        return cls(
            settings.zetaris_url,
            org_id=settings.zetaris_org_id,
            api_key=settings.zetaris_api_key,
            username=settings.zetaris_username,
            password=settings.zetaris_password,
            timeout=float(settings.query_timeout_seconds),
            **kwargs,
        )

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()

    def redact(self, text: str) -> str:
        """Replace every credential this client holds with `***`."""
        for secret in (self._api_key, self._session_token, self._password):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _timeout(self, seconds: float | None) -> httpx.Timeout:
        total = self.timeout if seconds is None else float(seconds)
        return httpx.Timeout(total, connect=min(CONNECT_TIMEOUT_SECONDS, total))

    def _send(self, method: str, path: str, *, timeout: float | None, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, self.base_url + path, timeout=self._timeout(timeout), **kwargs)
        except httpx.TimeoutException as exc:
            raise ZetarisUnavailable(f"timeout after {self._timeout(timeout).read:g} s ({type(exc).__name__})",
                                     timeout=True) from None
        except httpx.TransportError as exc:
            raise ZetarisUnavailable(f"connection error ({type(exc).__name__})") from None
        if response.status_code >= 500:
            raise ZetarisUnavailable(f"HTTP {response.status_code}: {self._error_text(response)}")
        return response

    def _login(self, timeout: float | None) -> str:
        if not (self._username and self._password):
            raise ZetarisAuthError("Zetaris refused the API key and no login is configured", 401)
        response = self._send("GET", LOGIN_PATH, timeout=timeout, auth=(self._username, self._password),
                              headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise ZetarisAuthError(f"Zetaris login failed: HTTP {response.status_code}", response.status_code)
        try:
            token = response.json()["idToken"]
        except (ValueError, KeyError, TypeError):
            raise ZetarisAuthError("Zetaris login returned no idToken", response.status_code) from None
        self._session_token = str(token)
        return self._session_token

    def _post_sql(self, token: str, sql: str, limit: int, timeout: float | None) -> httpx.Response:
        return self._send(
            "POST",
            RUN_SQL_PATH,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Org-ID": self.org_id,
                "X-Request-ID": str(uuid.uuid4()),
                "Accept": "application/json",
            },
            json={"queryId": str(uuid.uuid4()), "sql": sql, "limit": int(limit), "source": "SqlEditor"},
        )

    def run_sql(self, sql: str, *, limit: int, timeout: float | None = None) -> RestResult:
        """Send one whole statement; return its rows or raise `ZetarisUnavailable` / `ZetarisRequestError`."""
        use_key = bool(self._api_key) and not self._key_refused
        token = self._api_key if use_key else (self._session_token or self._login(timeout))
        response = self._post_sql(token, sql, limit, timeout)
        if response.status_code in (401, 403) and (self._username and self._password):
            # The key was refused (from now on the session token is used) or the token expired:
            # log in once and send again.
            self._key_refused = self._key_refused or use_key
            response = self._post_sql(self._login(timeout), sql, limit, timeout)
        if response.status_code in (401, 403):
            raise ZetarisAuthError(f"Zetaris refused the credentials: HTTP {response.status_code}",
                                   response.status_code)
        if response.status_code >= 400:
            raise ZetarisRequestError(self._error_text(response), response.status_code)
        try:
            body = response.json()
            result = parse_rest_body(body)
        except (ValueError, KeyError, TypeError) as exc:
            raise ZetarisRequestError(f"unexpected response shape: {type(exc).__name__}", response.status_code) from None
        if self.recorder is not None:
            self.recorder(sql, int(limit), body)
        return result

    def _error_text(self, response: httpx.Response) -> str:
        """The useful part of a Zetaris error: `msg`/`message`, else the text after `Exception: `."""
        text = response.text or ""
        try:
            body = response.json()
            if isinstance(body, dict):
                text = str(body.get("msg") or body.get("message") or body.get("error") or text)
        except ValueError:
            pass
        if "Exception: " in text:
            text = text.split("Exception: ", 1)[1]
        text = text.strip().splitlines()[0] if text.strip() else f"HTTP {response.status_code}"
        return self.redact(text)[:MAX_ERROR_CHARS]


def parse_rest_body(body: dict[str, Any]) -> RestResult:
    """Parse `{"headers": [...], "data": [[...]], "total": n}`; a header may be a name or an object."""
    headers: list[str] = []
    types: list[str | None] = []
    for header in body["headers"]:
        if isinstance(header, dict):
            headers.append(str(header.get("name") or header.get("label") or header.get("columnName")))
            declared = header.get("type") or header.get("dataType") or header.get("columnType")
            types.append(str(declared) if declared else None)
        else:
            headers.append(str(header))
            types.append(None)
    data = [list(row) for row in body.get("data") or []]
    total = body.get("total")
    return RestResult(headers=headers, header_types=types, data=data,
                      total=int(total) if total is not None else None, body=body)


# --- SQL: <source>.<table> -> USL tables ------------------------------------------------------------

_QUALIFIED_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b")
_UNQUALIFIED_RE = re.compile(r"\b(FROM|JOIN)(\s+)([A-Za-z_]\w*)\b(?!\s*[.(])", re.IGNORECASE)


def _segments(sql: str) -> list[tuple[bool, str]]:
    """Split SQL into (is_code, text): string literals, quoted identifiers and comments are not code."""
    out: list[tuple[bool, str]] = []
    i, n, start = 0, len(sql), 0
    while i < n:
        ch = sql[i]
        end = -1
        if sql.startswith("--", i):
            nl = sql.find("\n", i)
            end = n if nl == -1 else nl
        elif sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            end = n if close == -1 else close + 2
        elif ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            end = min(j + 1, n)
        if end == -1:
            i += 1
            continue
        if start < i:
            out.append((True, sql[start:i]))
        out.append((False, sql[i:end]))
        i = start = end
    if start < n:
        out.append((True, sql[start:]))
    return out


def to_usl_sql(sql: str, source: str | None = None) -> tuple[str, list[str]]:
    """Rewrite table references to USL names; return the statement and the USL tables it reads.

    `<source>.<table>` is rewritten anywhere in code (not in literals or comments). With a source scope,
    an unqualified table of that source right after FROM or JOIN is rewritten too, as the local
    adapter resolves it through its search path.
    """
    used: list[str] = []

    def use(table: UslTable) -> str:
        if table.fqn not in used:
            used.append(table.fqn)
        return table.fqn

    def qualified(match: re.Match[str]) -> str:
        table = TABLES.get(match.group(2))
        if match.group(1) in SOURCES and table is not None and table.source == match.group(1):
            return use(table)
        return match.group(0)

    scoped = {t.name: t for t in tables_of(source)} if source else {}

    def unqualified(match: re.Match[str]) -> str:
        table = scoped.get(match.group(3))
        return f"{match.group(1)}{match.group(2)}{use(table)}" if table else match.group(0)

    parts = []
    for is_code, text in _segments(sql):
        if is_code:
            text = _QUALIFIED_RE.sub(qualified, text)
            if scoped:
                text = _UNQUALIFIED_RE.sub(unqualified, text)
        parts.append(text)
    return "".join(parts), used


# --- types: REST strings -> Python values ---------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$")


def type_family(declared: str | None) -> str | None:
    """Map a USL or Spark type name to int | float | decimal | date | timestamp | bool | str."""
    if not declared:
        return None
    name = declared.strip().lower()
    base = name.split("(", 1)[0].strip()
    if base in ("int", "integer", "bigint", "smallint", "tinyint", "long", "short", "byte"):
        return "int"
    if base in ("double", "float", "real"):
        return "float"
    if base in ("decimal", "numeric", "dec"):
        return "decimal"
    if base == "date":
        return "date"
    if base.startswith("timestamp"):
        return "timestamp"
    if base in ("boolean", "bool"):
        return "bool"
    if base in ("varchar", "char", "string", "text"):
        return "str"
    return None


def convert_value(value: Any, family: str | None) -> Any:
    """Convert one REST value to the Python value the local adapter returns for that type.

    int -> int; decimal and double -> float (the local adapter returns floats for both); date ->
    `YYYY-MM-DD`; timestamp -> ISO 8601 (`2017-11-24T10:00:00`); boolean -> bool; null -> None.
    A value that does not parse is returned unchanged rather than raising.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if family in (None, "str"):
        return value
    text = value.strip()
    if text.lower() in ("null", ""):
        return None
    try:
        if family == "int":
            number = Decimal(text)
            return int(number) if number == number.to_integral_value() else float(number)
        if family in ("float", "decimal"):
            return float(Decimal(text))
        if family == "date":
            return date.fromisoformat(text[:10]).isoformat()
        if family == "timestamp":
            return datetime.fromisoformat(text.replace(" ", "T", 1)).isoformat()
        if family == "bool":
            return {"true": True, "false": False, "t": True, "f": False, "1": True, "0": False}[text.lower()]
    except (InvalidOperation, ValueError, KeyError):
        return value
    return value


def infer_family(values: list[Any]) -> str:
    """Type family of a computed column from all of its values (int, then float, then timestamp)."""
    texts = [v.strip() for v in values if isinstance(v, str) and v.strip().lower() not in ("null", "")]
    if not texts or any(not isinstance(v, str) for v in values if v is not None):
        return "str"
    if all(_INT_RE.match(t) for t in texts):
        return "int"
    if all(_NUM_RE.match(t) for t in texts):
        return "float"
    if all(_TS_RE.match(t) for t in texts):
        return "timestamp"
    return "str"


def column_families(rest: RestResult, usl_tables: list[str]) -> list[str]:
    """Type family per column: the server's type, else the USL column type, else inferred."""
    tables = [TABLES[fqn.rsplit(".", 1)[1]] for fqn in usl_tables if fqn.rsplit(".", 1)[1] in TABLES]
    families = []
    for index, (name, declared) in enumerate(zip(rest.headers, rest.header_types, strict=True)):
        family = type_family(declared)
        if family is None:
            short = name.rsplit(".", 1)[-1]
            matches = {type_family(c.type) for t in tables if (c := t.column(short)) is not None}
            if len(matches) == 1:
                family = matches.pop()
        if family is None:
            family = infer_family([row[index] if index < len(row) else None for row in rest.data])
        families.append(family)
    return families


def convert_rows(rest: RestResult, usl_tables: list[str]) -> list[dict[str, Any]]:
    """REST rows as dicts of converted values, keyed by column name."""
    families = column_families(rest, usl_tables)
    return [
        {name: convert_value(row[i] if i < len(row) else None, families[i]) for i, name in enumerate(rest.headers)}
        for row in rest.data
    ]


# --- the adapter ----------------------------------------------------------------------------------


class ZetarisDataLayer(DataLayer):
    """`DataLayer` over the Zetaris USL `lightning.metastore.explain_why.olist_usl`, with local fallback."""

    adapter_name = "zetaris"

    def __init__(
        self,
        *,
        run_id: str = "adhoc",
        log_dir: Path | str | None = None,
        max_rows: int | None = None,
        timeout_seconds: float | None = None,
        settings: Settings | None = None,
        client: ZetarisClient | None = None,
        local_factory: Callable[[], LocalDataLayer] | None = None,
        fallback: bool = True,
        retry_delay_seconds: float | None = None,
    ) -> None:
        settings = settings or get_settings()
        if settings.sample_mode:
            raise ValueError("sample mode uses the local adapter; ZetarisDataLayer is for live runs only")
        self.max_rows = max_rows if max_rows is not None else settings.max_query_rows
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else float(settings.query_timeout_seconds)
        )
        self.retry_delay = (
            retry_delay_seconds if retry_delay_seconds is not None else settings.zetaris_retry_delay_seconds
        )
        log_path = Path(log_dir) if log_dir else resolve_path(settings.log_dir)
        self.log = QueryLog(log_path, run_id)
        self.client = client or ZetarisClient.from_settings(settings)
        self.fallback = fallback
        self._local_factory = local_factory or (
            lambda: LocalDataLayer(run_id=run_id, log_dir=log_path, settings=settings)
        )
        self._local: LocalDataLayer | None = None
        self._described: dict[str, SourceInfo] = {}
        self._counter = 0
        self._counter_lock = threading.Lock()

    def close(self) -> None:
        """Close the REST client and the fallback database if it was opened."""
        self.client.close()
        if self._local is not None:
            self._local.close()

    def _local_layer(self) -> LocalDataLayer:
        if self._local is None:
            self._local = self._local_factory()
        return self._local

    def _next_query_id(self) -> str:
        with self._counter_lock:
            self._counter += 1
            return f"q{self._counter:03d}"

    def _run_with_retry(self, sql: str, limit: int, timeout: float) -> RestResult:
        """One call, and one retry after a connection error, timeout or 5xx; re-raises the second failure."""
        try:
            return self.client.run_sql(sql, limit=limit, timeout=timeout)
        except ZetarisUnavailable:
            if self.retry_delay:
                time.sleep(self.retry_delay)
        return self.client.run_sql(sql, limit=limit, timeout=timeout)

    def list_sources(self) -> list[str]:
        """The four source systems; every one is part of the one USL."""
        return list(SOURCES)

    def describe(self, source: str) -> SourceInfo:
        """USL tables of one source with their declared column types and row counts through Zetaris.

        Row counts come from one `COUNT(*) … UNION ALL …` query per source. If Zetaris is unavailable
        after one retry, the local adapter's description is returned instead (when fallback is on).
        """
        if source not in SOURCES:
            raise KeyError(f"unknown source {source!r}; available: {', '.join(SOURCES)}")
        if source in self._described:
            return self._described[source]
        tables = tables_of(source)
        sql = "\nUNION ALL\n".join(
            f"SELECT '{t.name}' AS table_name, COUNT(*) AS row_count FROM {t.fqn}" for t in tables
        )
        try:
            rest = self._run_with_retry(sql, len(tables) + 1, self.timeout_seconds)
        except ZetarisUnavailable:
            if not self.fallback:
                raise
            return self._local_layer().describe(source)
        except ZetarisRequestError as exc:
            raise RuntimeError(f"Zetaris could not describe source {source!r}: {exc}") from None
        counts = {row["table_name"]: int(row["row_count"]) for row in convert_rows(rest, [])}
        info = SourceInfo(
            name=source,
            tables=[
                TableInfo(
                    name=t.name,
                    row_count=counts.get(t.name, 0),
                    columns=[ColumnInfo(name=c.name, type=c.type) for c in t.columns],
                )
                for t in tables
            ],
        )
        self._described[source] = info
        return info

    def query(
        self,
        source: str | None,
        sql: str,
        limit: int | None = None,
        timeout: float | None = None,
    ) -> QueryOutcome:
        """Run one read-only statement through the USL; see `DataLayer.query`. Every call is logged."""
        query_id = self._next_query_id()
        limit = self.max_rows if limit is None else max(1, min(int(limit), self.max_rows))
        timeout = self.timeout_seconds if timeout is None else float(timeout)
        started = time.perf_counter()
        extra: dict[str, Any] = {"usl_tables": []}

        def finish(outcome: QueryOutcome) -> QueryOutcome:
            self.log.write(outcome, extra)
            return outcome

        def error(code: str, message: str, adapter: str = self.adapter_name) -> QueryOutcome:
            return finish(QueryError(query_id=query_id, source=source, sql=sql, adapter=adapter, code=code,
                                     message=message, duration_ms=elapsed_ms(started)))

        if source is not None and source not in SOURCES:
            return error("unknown_source", f"unknown source {source!r}; available: {', '.join(SOURCES)}")
        try:
            body = check_read_only(sql)
        except GuardError as exc:
            return error("rejected", str(exc))
        usl_sql, usl_tables = to_usl_sql(body, source)
        extra.update(usl_tables=usl_tables, zetaris_sql=usl_sql)

        try:
            rest = self._run_with_retry(usl_sql, limit + 1, timeout)
        except ZetarisRequestError as exc:
            return error("failed", f"Zetaris: {exc}")
        except ZetarisUnavailable as exc:
            reason = f"Zetaris unavailable after one retry: {exc}"
            if not self.fallback:
                return error("timeout" if exc.timeout else "failed", reason)
            extra["fallback_reason"] = reason
            try:
                outcome = self._local_layer().execute(source, sql, limit, timeout)
            except Exception as local_exc:  # noqa: BLE001 - a query never raises
                return error("failed", f"{reason}; local fallback failed: {type(local_exc).__name__}: {local_exc}",
                             FALLBACK_ADAPTER)
            return finish(replace(outcome, query_id=query_id, adapter=FALLBACK_ADAPTER,
                                  duration_ms=elapsed_ms(started)))

        rows = convert_rows(rest, usl_tables)
        truncated = len(rows) > limit
        rows = rows[:limit]
        return finish(QueryResult(
            query_id=query_id,
            source=source,
            sql=sql,
            adapter=self.adapter_name,
            columns=list(rest.headers),
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=elapsed_ms(started),
        ))
