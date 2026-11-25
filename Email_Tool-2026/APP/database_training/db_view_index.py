import csv
import json
import logging
import pickle
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


_INDEX_LOCK = threading.RLock()
_PICKLE_READ_LOCK = threading.Lock()
_COUNT_CACHE_LOCK = threading.Lock()
_COUNT_CACHE = {}
_HISTORY_LOCK = threading.RLock()
_HISTORY_FIELDS = ("timestamp", "database", "count", "source_signature", "event", "source")
_LOGGER = logging.getLogger(__name__)
_MAX_PAGE_SIZE = 100


def _format_pattern(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(_format_pattern(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _source_signature(source_path):
    stat = source_path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _normalized_company_count(source_data):
    return len({company for raw_company in source_data if (company := str(raw_company).strip())})


def _load_source_data(source_path):
    with _PICKLE_READ_LOCK:
        with source_path.open("rb") as pickle_file:
            source_data = pickle.load(pickle_file)
        if not isinstance(source_data, dict):
            raise ValueError("Database pickle must contain a company-to-pattern dictionary")

        signature = _source_signature(source_path)
        cache_key = str(source_path.resolve())
        with _COUNT_CACHE_LOCK:
            _COUNT_CACHE[cache_key] = (signature, _normalized_company_count(source_data))
        return source_data, signature


def get_database_count(pickle_path):
    source_path = Path(pickle_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database pickle not found: {source_path}")

    cache_key = str(source_path.resolve())
    signature = _source_signature(source_path)
    with _COUNT_CACHE_LOCK:
        cached_count = _COUNT_CACHE.get(cache_key)
        if cached_count is not None and cached_count[0] == signature:
            return cached_count[1]

    with _PICKLE_READ_LOCK:
        signature = _source_signature(source_path)
        with _COUNT_CACHE_LOCK:
            cached_count = _COUNT_CACHE.get(cache_key)
            if cached_count is not None and cached_count[0] == signature:
                return cached_count[1]

        with source_path.open("rb") as pickle_file:
            source_data = pickle.load(pickle_file)
        if not isinstance(source_data, dict):
            raise ValueError("Database pickle must contain a company-to-pattern dictionary")

        signature = _source_signature(source_path)
        count = _normalized_company_count(source_data)
        with _COUNT_CACHE_LOCK:
            _COUNT_CACHE[cache_key] = (signature, count)
        return count


def _history_path(source_path):
    return source_path.parent / "database_count_history.csv"


def _read_history(source_path):
    history_path = _history_path(source_path)
    if not history_path.exists():
        return []
    with history_path.open("r", encoding="utf-8", newline="") as history_file:
        return [
            row for row in csv.DictReader(history_file)
            if row.get("database") == source_path.name
        ]


def record_database_snapshot(pickle_path, event="database update", source=""):
    source_path = Path(pickle_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database pickle not found: {source_path}")

    count = get_database_count(source_path)
    signature = _source_signature(source_path)
    history_path = _history_path(source_path)

    with _HISTORY_LOCK:
        records = _read_history(source_path)
        if records and records[-1].get("source_signature") == signature:
            return records[-1]

        row = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database": source_path.name,
            "count": count,
            "source_signature": signature,
            "event": str(event or "database update")[:100],
            "source": str(source or "")[:255],
        }
        history_path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = not history_path.exists() or history_path.stat().st_size == 0
        try:
            with history_path.open("a", encoding="utf-8", newline="") as history_file:
                writer = csv.DictWriter(history_file, fieldnames=_HISTORY_FIELDS)
                if needs_header:
                    writer.writeheader()
                writer.writerow(row)
        except OSError:
            _LOGGER.exception("Could not append database count history to %s", history_path)
            return None
        return row


def ensure_database_history_baseline(pickle_path):
    source_path = Path(pickle_path)
    with _HISTORY_LOCK:
        records = _read_history(source_path)
        if not records:
            return record_database_snapshot(source_path, event="baseline")
    return record_database_snapshot(source_path, event="detected database change")


def get_database_history(pickle_path, limit=12):
    source_path = Path(pickle_path)
    current_count = get_database_count(source_path)
    ensure_database_history_baseline(source_path)
    with _HISTORY_LOCK:
        records = _read_history(source_path)

    latest = records[-1] if records else None
    previous = records[-2] if len(records) > 1 else None
    previous_count = int(previous["count"]) if previous else None
    return {
        "database": source_path.name,
        "current_count": current_count,
        "previous_count": previous_count,
        "change": current_count - previous_count if previous_count is not None else None,
        "last_updated": latest["timestamp"] if latest else "",
        "records": [
            {**row, "count": int(row["count"])}
            for row in reversed(records[-max(1, min(int(limit), 50)):])
        ],
    }


def get_database_page(pickle_path, page=1, page_size=100, search=""):
    source_path = Path(pickle_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database pickle not found: {source_path}")

    try:
        page = max(1, int(page))
        page_size = min(_MAX_PAGE_SIZE, max(1, int(page_size)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Page and page size must be integers") from exc

    search = str(search or "").strip()[:200]
    index_path = source_path.with_name(f"{source_path.stem}.viewer.sqlite3")
    signature = _source_signature(source_path)

    with _INDEX_LOCK, sqlite3.connect(index_path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE IF NOT EXISTS company_patterns "
            "(company TEXT PRIMARY KEY, email_pattern TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

        cached_signature = connection.execute(
            "SELECT value FROM metadata WHERE key = 'source_signature'"
        ).fetchone()
        if cached_signature is None or cached_signature[0] != signature:
            source_data, signature = _load_source_data(source_path)
            connection.execute("DROP INDEX IF EXISTS idx_company_patterns_name")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM company_patterns")
            connection.execute("DELETE FROM metadata WHERE key = 'source_signature'")
            connection.executemany(
                "INSERT OR REPLACE INTO company_patterns(company, email_pattern) VALUES (?, ?)",
                (
                    (company, _format_pattern(pattern))
                    for raw_company, pattern in source_data.items()
                    if (company := str(raw_company).strip())
                ),
            )
            connection.commit()
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_patterns_name "
                "ON company_patterns(company COLLATE NOCASE)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('source_signature', ?)",
                (signature,),
            )
            connection.commit()
        else:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_patterns_name "
                "ON company_patterns(company COLLATE NOCASE)"
            )

        where_clause = ""
        query_params = []
        if search:
            escaped_search = (
                search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where_clause = "WHERE company LIKE ? ESCAPE '\\'"
            query_params.append(f"{escaped_search}%")

        total = connection.execute(
            f"SELECT COUNT(*) FROM company_patterns {where_clause}",
            query_params,
        ).fetchone()[0]
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        rows = connection.execute(
            "SELECT company, email_pattern FROM company_patterns "
            f"{where_clause} ORDER BY company COLLATE NOCASE, company LIMIT ? OFFSET ?",
            [*query_params, page_size, offset],
        ).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }