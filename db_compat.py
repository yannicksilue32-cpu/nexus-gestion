"""Nexus Gestion - couche de compatibilité SQLite / PostgreSQL.

Localement, Nexus Gestion continue d'utiliser database.db.
Lorsque DATABASE_URL est défini (Render/production), l'application utilise PostgreSQL.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
import os

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USING_POSTGRES = bool(DATABASE_URL)

try:
    import psycopg
    from psycopg import Error as PsycopgError
    from psycopg import IntegrityError as PsycopgIntegrityError
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    class _PsycopgUnavailableError(Exception):
        pass
    PsycopgError = _PsycopgUnavailableError
    PsycopgIntegrityError = _PsycopgUnavailableError
    dict_row = None

DB_ERROR = (sqlite3.Error, PsycopgError)
DB_INTEGRITY_ERROR = (sqlite3.IntegrityError, PsycopgIntegrityError)


class CompatRow(dict):
    """Ligne PostgreSQL compatible avec sqlite3.Row : row['name'] et row[0]."""

    def __getitem__(self, key: Any):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CompatCursor:
    def __init__(self, raw_cursor=None, manual_rows=None):
        self._raw = raw_cursor
        self._manual_rows = manual_rows
        self._insert_table = None
        self.description = getattr(raw_cursor, "description", None)

    def execute(self, query, params=()):
        if self._manual_rows is not None:
            self._manual_rows = None

        self._insert_table = _extract_insert_table(query)
        self._raw.execute(_translate_sql(query), params or ())
        self.description = self._raw.description
        return self

    def executemany(self, query, seq_of_params):
        self._insert_table = _extract_insert_table(query)
        self._raw.executemany(_translate_sql(query), seq_of_params)
        self.description = self._raw.description
        return self

    def fetchone(self):
        if self._manual_rows is not None:
            if not self._manual_rows:
                return None
            return self._manual_rows.pop(0)
        row = self._raw.fetchone()
        return _wrap_row(row)

    def fetchall(self):
        if self._manual_rows is not None:
            rows = self._manual_rows
            self._manual_rows = []
            return rows
        return [_wrap_row(row) for row in self._raw.fetchall()]

    @property
    def lastrowid(self):
        if not self._insert_table:
            return None
        try:
            self._raw.execute(
                "SELECT currval(pg_get_serial_sequence(%s, 'id'))",
                (self._insert_table,),
            )
            row = self._raw.fetchone()
            return next(iter(row.values())) if row else None
        except Exception:
            return None

    @property
    def rowcount(self):
        if self._manual_rows is not None:
            return len(self._manual_rows)
        return self._raw.rowcount

    def close(self):
        if self._raw is not None:
            return self._raw.close()

    def __iter__(self):
        return iter(self.fetchall())


def _wrap_row(row):
    if row is None:
        return None
    if isinstance(row, CompatRow):
        return row
    if isinstance(row, dict):
        return CompatRow(row)
    return row


def _extract_insert_table(query: str | None):
    if not query:
        return None
    match = re.search(r"\bINSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+([A-Za-z_][\w]*)", query, re.I)
    return match.group(1) if match else None


def _table_info_rows(connection, table_name: str):
    """Émule PRAGMA table_info pour PostgreSQL."""
    rows = connection._raw_conn.execute(
        """
        SELECT
            ordinal_position - 1 AS cid,
            column_name AS name,
            CASE
                WHEN data_type = 'integer' THEN 'INTEGER'
                WHEN data_type = 'bigint' THEN 'BIGINT'
                WHEN data_type = 'real' THEN 'REAL'
                WHEN data_type = 'double precision' THEN 'REAL'
                WHEN data_type = 'boolean' THEN 'INTEGER'
                ELSE UPPER(data_type)
            END AS type,
            CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
            column_default AS dflt_value,
            CASE WHEN EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                  AND ccu.column_name = columns.column_name
            ) THEN 1 ELSE 0 END AS pk
        FROM information_schema.columns columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name, table_name),
    ).fetchall()

    return [
        (
            row["cid"],
            row["name"],
            row["type"],
            row["notnull"],
            row["dflt_value"],
            row["pk"],
        )
        for row in rows
    ]


def _translate_sql(query: str) -> str:
    sql = str(query)

    # SQLite-only pragma handled separately by CompatConnection.execute().
    # SQL placeholders: sqlite ? -> psycopg %s.
    sql = sql.replace("?", "%s")

    # SQLite AUTOINCREMENT -> PostgreSQL sequence-backed primary key.
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        sql,
        flags=re.I,
    )

    # SQLite case-insensitive collation is not a PostgreSQL collation keyword.
    sql = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.I)

    # SQLite INSERT OR IGNORE -> PostgreSQL ON CONFLICT DO NOTHING.
    insert_ignore = bool(
        re.search(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.I)
    )
    if insert_ignore:
        sql = re.sub(
            r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            sql,
            count=1,
            flags=re.I,
        )
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    # SQLite date/time functions used by the existing application.
    sql = re.sub(
        r"\bdate\(\s*'now'\s*,\s*'localtime'\s*\)",
        "CURRENT_DATE",
        sql,
        flags=re.I,
    )

    sql = re.sub(
        r"\bdate\(\s*(%s)\s*\)",
        r"CAST(\1 AS DATE)",
        sql,
        flags=re.I,
    )

    sql = re.sub(
        r"\bdate\(\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)\s*\)",
        r"CAST(\1 AS DATE)",
        sql,
        flags=re.I,
    )

    sql = re.sub(
        r"\bstrftime\(\s*'%Y-%m'\s*,\s*'now'\s*,\s*'localtime'\s*\)",
        "TO_CHAR(CURRENT_DATE, 'YYYY-MM')",
        sql,
        flags=re.I,
    )

    sql = re.sub(
        r"\bstrftime\(\s*'%Y-%m'\s*,\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)\s*\)",
        r"TO_CHAR(CAST(\1 AS DATE), 'YYYY-MM')",
        sql,
        flags=re.I,
    )

    return sql


class CompatConnection:
    """Expose une API proche d'une connexion sqlite3 pour l'app actuelle."""

    def __init__(self, raw_connection):
        self._raw_conn = raw_connection

    def execute(self, query, params=()):
        normalized = str(query).strip()

        if re.fullmatch(r"PRAGMA\s+foreign_keys\s*=\s*ON", normalized, flags=re.I):
            return CompatCursor(_NoOpCursor())

        match = re.fullmatch(
            r"PRAGMA\s+table_info\(\s*([A-Za-z_][\w]*)\s*\)",
            normalized,
            flags=re.I,
        )
        if match and USING_POSTGRES:
            return CompatCursor(manual_rows=_table_info_rows(self, match.group(1)))

        raw = self._raw_conn.execute(_translate_sql(query), params or ())
        return CompatCursor(raw)

    def cursor(self):
        return CompatCursor(self._raw_conn.cursor())

    def commit(self):
        return self._raw_conn.commit()

    def rollback(self):
        return self._raw_conn.rollback()

    def close(self):
        return self._raw_conn.close()

    def __getattr__(self, name):
        return getattr(self._raw_conn, name)


class _NoOpCursor:
    description = []
    rowcount = 0

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


def get_db_connection():
    if not USING_POSTGRES:
        connection = sqlite3.connect(
            str(DATABASE),
            timeout=20,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL est défini mais psycopg n'est pas installé. "
            "Installez psycopg[binary]."
        )

    raw = psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )
    raw.execute("SET TIME ZONE 'UTC'")
    return CompatConnection(raw)
