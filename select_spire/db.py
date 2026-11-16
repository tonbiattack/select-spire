"""Read-only, budgeted execution of generated SQLite SELECT statements."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time


@dataclass
class Query:
    sql: str
    params: tuple = ()


@dataclass
class QueryResult:
    row_count: int
    columns: tuple[str, ...]
    elapsed_ms: float
    over_budget: bool = False
    error: str | None = None


# Only these SQLite authorizer actions are needed for ordinary SELECTs,
# including subqueries, joins, aggregate functions, and recursive CTEs.
_READ_ACTIONS = frozenset(
    (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
     sqlite3.SQLITE_RECURSIVE)
)
_SELECT_PREFIX = re.compile(r"\s*SELECT\b", re.IGNORECASE | re.ASCII)


def _authorize(action: int, arg1: str | None, arg2: str | None,
               database: str | None, source: str | None) -> int:
    # load_extension can load native code and is not a read operation.
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY


def execute_select(
    path: str | Path,
    query: Query,
    timeout_ms: int = 100,
    max_rows: int = 100,
) -> QueryResult:
    """Run one SELECT and return its bounded row count and column names.

    Counts are capped at max_rows; over_budget signals either an extra row or
    expiry. On an error, row_count is the number already fetched, if any.
    The timeout is cooperative: SQLite's progress handler cannot preempt a
    blocking filesystem call or a long-running native SQLite function.
    """
    start = time.monotonic()
    deadline = start + timeout_ms / 1000
    row_count = 0
    columns: tuple[str, ...] = ()
    connection: sqlite3.Connection | None = None

    def result(over_budget: bool = False, error: str | None = None) -> QueryResult:
        return QueryResult(row_count, columns, (time.monotonic() - start) * 1000,
                           over_budget, error)

    if timeout_ms <= 0:
        return result(True, "Query timed out")
    if max_rows < 0:
        return result(error="max_rows must be non-negative")
    if not _SELECT_PREFIX.match(query.sql):
        return result(error="Only statements beginning with SELECT are allowed")

    try:
        # as_uri percent-encodes special characters so a path cannot inject URI
        # options. resolve() also makes relative paths acceptable to as_uri().
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0)
        connection.execute("PRAGMA query_only=ON")
        connection.set_authorizer(_authorize)
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        if time.monotonic() >= deadline:
            return result(True, "Query timed out")

        # sqlite3.execute rejects multiple statements; the authorizer rejects
        # modifying actions even if they are hidden within an apparent SELECT.
        cursor = connection.execute(query.sql, query.params)
        columns = tuple(column[0] for column in (cursor.description or ()))
        while True:
            if time.monotonic() >= deadline:
                return result(True, "Query timed out")
            row = cursor.fetchone()
            if time.monotonic() >= deadline:
                return result(True, "Query timed out")
            if row is None:
                return result()
            if row_count == max_rows:
                return result(True)
            row_count += 1
    except sqlite3.Error as exc:
        if time.monotonic() >= deadline:
            return result(True, "Query timed out")
        return result(error=str(exc))
    except (OSError, ValueError) as exc:
        return result(error=str(exc))
    finally:
        if connection is not None:
            connection.close()
