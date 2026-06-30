"""
db.py
─────────────────────────────────────────────────────────────────────────────
Persistence layer for the AI-Powered Chatbot for Medical Diagnosis.

Connects to a PostgreSQL database (designed for the free Neon Postgres tier)
and provides two things:

    1. Case Memory  — every diagnosis generated (online AI or built-in
       engine) is fingerprinted and stored. If a visitor later presents the
       same case again, the saved response is returned instantly instead of
       calling the online AI engine again.

    2. Usage Tracking — counts how many times the online AI engine has been
       called today, which app.py uses to proactively switch to the
       built-in engine once a configured daily ceiling is reached
       (protecting the free-tier AI quota).

The entire module is fault-tolerant by design: if DATABASE_URL is missing,
or the database cannot be reached for any reason, every function degrades
gracefully (caching and usage-tracking are simply skipped) instead of
crashing the application. The chatbot must keep working with or without
the database.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import hashlib
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_pool = None
_db_available = False


def _build_dsn(url: str) -> str:
    if "sslmode=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def _init_pool():
    global _pool, _db_available
    if not DATABASE_URL:
        logger.warning(
            "DATABASE_URL is not set. Case memory and usage tracking are disabled; "
            "the chatbot will continue to function without persistence."
        )
        return
    try:
        import psycopg2
        from psycopg2 import pool as pg_pool

        _pool = pg_pool.SimpleConnectionPool(1, 5, dsn=_build_dsn(DATABASE_URL))
        _db_available = True
        _bootstrap_schema()
        logger.info("Connected to PostgreSQL database successfully.")
    except Exception as exc:
        _pool = None
        _db_available = False
        logger.error("Database connection failed; continuing without persistence: %s", exc)


class _Cursor:
    """Context manager that borrows/returns a pooled connection and commits or
    rolls back automatically."""

    def __init__(self):
        self.conn = None

    def __enter__(self):
        self.conn = _pool.getconn()
        return self.conn.cursor()

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            _pool.putconn(self.conn)


def _bootstrap_schema():
    ddl = """
    CREATE TABLE IF NOT EXISTS diagnosis_cases (
        id              SERIAL PRIMARY KEY,
        case_hash       VARCHAR(64) UNIQUE NOT NULL,
        symptom_text    TEXT NOT NULL,
        response_text   TEXT NOT NULL,
        urgency_tier    VARCHAR(20),
        source          VARCHAR(20) NOT NULL,
        hit_count       INTEGER NOT NULL DEFAULT 1,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_served_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS engine_usage_log (
        usage_date          DATE PRIMARY KEY,
        ai_call_count        INTEGER NOT NULL DEFAULT 0,
        engine_call_count    INTEGER NOT NULL DEFAULT 0,
        cache_hit_count      INTEGER NOT NULL DEFAULT 0
    );
    """
    with _Cursor() as cur:
        cur.execute(ddl)


_init_pool()


# ──────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────
def is_available() -> bool:
    return _db_available


def normalize_case_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def hash_case(text: str) -> str:
    return hashlib.sha256(normalize_case_text(text).encode("utf-8")).hexdigest()


def get_cached_case(case_hash: str):
    """Return (response_text, urgency_tier, source) if this exact case has
    been seen before, else None. Also records a cache-hit in usage stats."""
    if not _db_available:
        return None
    try:
        with _Cursor() as cur:
            cur.execute(
                "SELECT response_text, urgency_tier, source FROM diagnosis_cases WHERE case_hash = %s",
                (case_hash,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE diagnosis_cases SET hit_count = hit_count + 1, last_served_at = NOW() "
                    "WHERE case_hash = %s",
                    (case_hash,),
                )
                _bump_usage(cur, cache=True)
            return row
    except Exception as exc:
        logger.error("Case-memory lookup failed (continuing without cache): %s", exc)
        return None


def save_case(case_hash: str, symptom_text: str, response_text: str, urgency_tier: str, source: str):
    """Persist a generated diagnosis so identical future cases can be served
    instantly. source is one of 'ai' | 'engine'."""
    if not _db_available:
        return
    try:
        with _Cursor() as cur:
            cur.execute(
                """
                INSERT INTO diagnosis_cases (case_hash, symptom_text, response_text, urgency_tier, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (case_hash) DO UPDATE SET
                    response_text  = EXCLUDED.response_text,
                    urgency_tier   = EXCLUDED.urgency_tier,
                    source         = EXCLUDED.source,
                    hit_count      = diagnosis_cases.hit_count + 1,
                    last_served_at = NOW()
                """,
                (case_hash, (symptom_text or "")[:4000], response_text, urgency_tier, source),
            )
            _bump_usage(cur, ai=(source == "ai"), engine=(source == "engine"))
    except Exception as exc:
        logger.error("Saving case to database failed (response was still returned to the user): %s", exc)


def _bump_usage(cur, ai=False, engine=False, cache=False):
    cur.execute(
        """
        INSERT INTO engine_usage_log (usage_date, ai_call_count, engine_call_count, cache_hit_count)
        VALUES (CURRENT_DATE, %s, %s, %s)
        ON CONFLICT (usage_date) DO UPDATE SET
            ai_call_count     = engine_usage_log.ai_call_count + EXCLUDED.ai_call_count,
            engine_call_count = engine_usage_log.engine_call_count + EXCLUDED.engine_call_count,
            cache_hit_count   = engine_usage_log.cache_hit_count + EXCLUDED.cache_hit_count
        """,
        (1 if ai else 0, 1 if engine else 0, 1 if cache else 0),
    )


def get_today_ai_count() -> int:
    """How many times the online AI engine has already been used today."""
    if not _db_available:
        return 0
    try:
        with _Cursor() as cur:
            cur.execute(
                "SELECT ai_call_count FROM engine_usage_log WHERE usage_date = CURRENT_DATE"
            )
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as exc:
        logger.error("Usage lookup failed (assuming 0): %s", exc)
        return 0


def get_status_snapshot() -> dict:
    """Used by /api/status for a small transparency panel."""
    if not _db_available:
        return {"connected": False, "ai_calls_today": 0, "engine_calls_today": 0, "cache_hits_today": 0, "total_cases": 0}
    try:
        with _Cursor() as cur:
            cur.execute(
                "SELECT ai_call_count, engine_call_count, cache_hit_count FROM engine_usage_log "
                "WHERE usage_date = CURRENT_DATE"
            )
            row = cur.fetchone() or (0, 0, 0)
            cur.execute("SELECT COUNT(*) FROM diagnosis_cases")
            total = cur.fetchone()[0]
            return {
                "connected": True,
                "ai_calls_today": row[0],
                "engine_calls_today": row[1],
                "cache_hits_today": row[2],
                "total_cases": total,
            }
    except Exception as exc:
        logger.error("Status snapshot failed: %s", exc)
        return {"connected": False, "ai_calls_today": 0, "engine_calls_today": 0, "cache_hits_today": 0, "total_cases": 0}
