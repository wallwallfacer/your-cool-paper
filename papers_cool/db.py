"""SQLite database access layer."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id        TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    authors         TEXT NOT NULL,
    abstract        TEXT NOT NULL,
    primary_subject TEXT NOT NULL,
    subjects        TEXT NOT NULL,
    publish_utc     TEXT NOT NULL,
    pdf_url         TEXT NOT NULL,
    abs_url         TEXT NOT NULL,
    version         INTEGER DEFAULT 1,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subject_pub ON papers(primary_subject, publish_utc DESC);
CREATE INDEX IF NOT EXISTS idx_publish ON papers(publish_utc DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    arxiv_id UNINDEXED,
    title,
    abstract,
    authors,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS ai_summaries (
    arxiv_id   TEXT NOT NULL,
    lang       TEXT NOT NULL,
    model      TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, lang)
);

CREATE TABLE IF NOT EXISTS ai_abstracts (
    arxiv_id   TEXT NOT NULL,
    lang       TEXT NOT NULL,
    model      TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, lang)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    category   TEXT NOT NULL,
    fetch_date TEXT NOT NULL,
    count      INTEGER NOT NULL,
    finished_at TEXT NOT NULL,
    PRIMARY KEY (category, fetch_date)
);
"""


def _db_path() -> Path:
    return get_settings().db_path


def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Ensure schema exists on first connection
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_papers(papers: Iterable[dict]) -> int:
    """Insert/update papers. Returns count actually written."""
    count = 0
    with connect() as conn:
        cur = conn.cursor()
        for p in papers:
            authors_json = json.dumps(p["authors"], ensure_ascii=False)
            subjects_json = json.dumps(p["subjects"], ensure_ascii=False)
            cur.execute(
                """
                INSERT INTO papers
                    (arxiv_id, title, authors, abstract, primary_subject, subjects,
                     publish_utc, pdf_url, abs_url, version, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(arxiv_id) DO UPDATE SET
                    title=excluded.title,
                    authors=excluded.authors,
                    abstract=excluded.abstract,
                    primary_subject=excluded.primary_subject,
                    subjects=excluded.subjects,
                    publish_utc=excluded.publish_utc,
                    pdf_url=excluded.pdf_url,
                    abs_url=excluded.abs_url,
                    version=excluded.version,
                    fetched_at=excluded.fetched_at
                """,
                (
                    p["arxiv_id"],
                    p["title"],
                    authors_json,
                    p["abstract"],
                    p["primary_subject"],
                    subjects_json,
                    p["publish_utc"],
                    p["pdf_url"],
                    p["abs_url"],
                    p.get("version", 1),
                    _now_iso(),
                ),
            )
            cur.execute("DELETE FROM papers_fts WHERE arxiv_id=?", (p["arxiv_id"],))
            cur.execute(
                "INSERT INTO papers_fts(arxiv_id, title, abstract, authors) VALUES (?,?,?,?)",
                (p["arxiv_id"], p["title"], p["abstract"], " ".join(p["authors"])),
            )
            count += 1
        conn.commit()
    return count


def _row_to_paper(row: sqlite3.Row) -> dict:
    return {
        "arxiv_id": row["arxiv_id"],
        "title": row["title"],
        "authors": json.loads(row["authors"]),
        "abstract": row["abstract"],
        "primary_subject": row["primary_subject"],
        "subjects": json.loads(row["subjects"]),
        "publish_utc": row["publish_utc"],
        "pdf_url": row["pdf_url"],
        "abs_url": row["abs_url"],
        "version": row["version"],
        "fetched_at": row["fetched_at"],
    }


def get_paper(arxiv_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        return _row_to_paper(row) if row else None


def list_papers_by_categories(
    categories: list[str],
    date: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """List papers whose primary_subject is in categories.

    If `date` (YYYY-MM-DD) is given, restrict to that publish date.
    Otherwise return the most recent publish date that has data for these categories.
    """
    if not categories:
        return []
    placeholders = ",".join("?" for _ in categories)
    with connect() as conn:
        if date is None:
            row = conn.execute(
                f"""
                SELECT substr(publish_utc, 1, 10) AS d
                FROM papers
                WHERE primary_subject IN ({placeholders})
                ORDER BY publish_utc DESC LIMIT 1
                """,
                categories,
            ).fetchone()
            if not row:
                return []
            date = row["d"]
        rows = conn.execute(
            f"""
            SELECT * FROM papers
            WHERE primary_subject IN ({placeholders})
              AND substr(publish_utc, 1, 10) = ?
            ORDER BY publish_utc DESC, arxiv_id ASC
            LIMIT ?
            """,
            (*categories, date, limit),
        ).fetchall()
        # Dedup just in case
        seen: set[str] = set()
        result: list[dict] = []
        for r in rows:
            if r["arxiv_id"] in seen:
                continue
            seen.add(r["arxiv_id"])
            result.append(_row_to_paper(r))
        return result


def latest_publish_date(categories: list[str]) -> str | None:
    if not categories:
        return None
    placeholders = ",".join("?" for _ in categories)
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT substr(publish_utc, 1, 10) AS d
            FROM papers
            WHERE primary_subject IN ({placeholders})
            ORDER BY publish_utc DESC LIMIT 1
            """,
            categories,
        ).fetchone()
        return row["d"] if row else None


def available_dates(categories: list[str], limit: int = 60) -> list[str]:
    if not categories:
        return []
    placeholders = ",".join("?" for _ in categories)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT substr(publish_utc, 1, 10) AS d
            FROM papers
            WHERE primary_subject IN ({placeholders})
            ORDER BY d DESC LIMIT ?
            """,
            (*categories, limit),
        ).fetchall()
        return [r["d"] for r in rows]


def search_papers(query: str, limit: int = 100) -> list[dict]:
    """Full-text search across title/abstract/authors."""
    if not query.strip():
        return []
    safe = _fts_escape(query)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.* FROM papers p
            JOIN papers_fts f ON f.arxiv_id = p.arxiv_id
            WHERE papers_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe, limit),
        ).fetchall()
        return [_row_to_paper(r) for r in rows]


def _fts_escape(q: str) -> str:
    # Wrap each whitespace-separated token in double quotes for safe MATCH usage.
    tokens = [t for t in q.split() if t]
    if not tokens:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def get_summary(arxiv_id: str, lang: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM ai_summaries WHERE arxiv_id=? AND lang=?",
            (arxiv_id, lang),
        ).fetchone()
        if not row:
            return None
        return {
            "arxiv_id": row["arxiv_id"],
            "lang": row["lang"],
            "model": row["model"],
            "content": row["content"],
            "created_at": row["created_at"],
        }


def save_summary(arxiv_id: str, lang: str, model: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_summaries(arxiv_id, lang, model, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id, lang) DO UPDATE SET
                model=excluded.model,
                content=excluded.content,
                created_at=excluded.created_at
            """,
            (arxiv_id, lang, model, content, _now_iso()),
        )


def delete_summary(arxiv_id: str, lang: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM ai_summaries WHERE arxiv_id=? AND lang=?",
            (arxiv_id, lang),
        )


def get_abstract_translation(arxiv_id: str, lang: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT content FROM ai_abstracts WHERE arxiv_id=? AND lang=?",
            (arxiv_id, lang),
        ).fetchone()
        return row["content"] if row else None


def save_abstract_translation(arxiv_id: str, lang: str, model: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_abstracts(arxiv_id, lang, model, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id, lang) DO UPDATE SET
                model=excluded.model,
                content=excluded.content,
                created_at=excluded.created_at
            """,
            (arxiv_id, lang, model, content, _now_iso()),
        )


def record_fetch(category: str, fetch_date: str, count: int) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO fetch_log(category, fetch_date, count, finished_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(category, fetch_date) DO UPDATE SET
                count=excluded.count, finished_at=excluded.finished_at
            """,
            (category, fetch_date, count, _now_iso()),
        )


def has_fetch(category: str, fetch_date: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM fetch_log WHERE category=? AND fetch_date=?",
            (category, fetch_date),
        ).fetchone()
        return row is not None
