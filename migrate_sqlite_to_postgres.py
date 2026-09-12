"""Migre les données de Nexus Gestion de SQLite vers PostgreSQL.

Usage local :
    set DATABASE_URL=postgresql://...
    python migrate_sqlite_to_postgres.py

La base SQLite originale n'est jamais modifiée.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import psycopg


BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "database.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


SCHEMA = {
    "products": """
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            purchase_price REAL DEFAULT 0,
            selling_price REAL DEFAULT 0,
            quantity INTEGER DEFAULT 0,
            stock_alert INTEGER DEFAULT 5
        )
    """,
    "sales": """
        CREATE TABLE IF NOT EXISTS sales (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            date TEXT,
            purchase_price_at_sale REAL DEFAULT NULL
        )
    """,
    "purchases": """
        CREATE TABLE IF NOT EXISTS purchases (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            date TEXT
        )
    """,
    "expenses": """
        CREATE TABLE IF NOT EXISTS expenses (
            id BIGSERIAL PRIMARY KEY,
            description TEXT,
            amount REAL DEFAULT 0,
            category TEXT,
            date TEXT
        )
    """,
    "customers": """
        CREATE TABLE IF NOT EXISTS customers (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            created_at TEXT
        )
    """,
    "invoices": """
        CREATE TABLE IF NOT EXISTS invoices (
            id BIGSERIAL PRIMARY KEY,
            invoice_number TEXT UNIQUE,
            customer_id BIGINT,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'Impayée',
            date TEXT
        )
    """,
    "invoice_items": """
        CREATE TABLE IF NOT EXISTS invoice_items (
            id BIGSERIAL PRIMARY KEY,
            invoice_id BIGINT,
            product_id BIGINT,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            subtotal REAL DEFAULT 0
        )
    """,
    "inventory_movements": """
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            reference_id BIGINT,
            date TEXT,
            reason TEXT,
            created_by BIGINT
        )
    """,
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_login TEXT
        )
    """,
    "app_settings": """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY,
            company_name TEXT DEFAULT 'Nexus Gestion',
            company_phone TEXT DEFAULT '',
            company_email TEXT DEFAULT '',
            company_address TEXT DEFAULT '',
            currency TEXT DEFAULT 'FCFA',
            updated_at TEXT
        )
    """,
}


COLUMNS = {
    "products": ["id", "name", "category", "purchase_price", "selling_price", "quantity", "stock_alert"],
    "sales": ["id", "product_id", "quantity", "price", "date", "purchase_price_at_sale"],
    "purchases": ["id", "product_id", "quantity", "price", "date"],
    "expenses": ["id", "description", "amount", "category", "date"],
    "customers": ["id", "name", "phone", "email", "address", "created_at"],
    "invoices": ["id", "invoice_number", "customer_id", "total", "status", "date"],
    "invoice_items": ["id", "invoice_id", "product_id", "quantity", "price", "subtotal"],
    "inventory_movements": ["id", "product_id", "movement_type", "quantity", "reference_id", "date", "reason", "created_by"],
    "users": ["id", "username", "password_hash", "full_name", "role", "active", "created_at", "last_login"],
    "app_settings": ["id", "company_name", "company_phone", "company_email", "company_address", "currency", "updated_at"],
}


def sqlite_columns(connection, table):
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def migrate():
    if not DATABASE_URL:
        raise RuntimeError("Définissez DATABASE_URL avant de lancer la migration.")

    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"Base SQLite introuvable : {SQLITE_PATH}")

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    try:
        with psycopg.connect(DATABASE_URL) as pg_conn:
            with pg_conn.cursor() as cur:
                for sql in SCHEMA.values():
                    cur.execute(sql)

                for table in COLUMNS:
                    source_columns = sqlite_columns(sqlite_conn, table)
                    target_columns = [c for c in COLUMNS[table] if c in source_columns]
                    if not target_columns:
                        continue

                    rows = sqlite_conn.execute(
                        f"SELECT {', '.join(target_columns)} FROM {table}"
                    ).fetchall()

                    if not rows:
                        continue

                    placeholders = ", ".join(["%s"] * len(target_columns))
                    sql = (
                        f"INSERT INTO {table} ({', '.join(target_columns)}) "
                        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                    )

                    cur.executemany(
                        sql,
                        [tuple(row[col] for col in target_columns) for row in rows],
                    )

                for table in COLUMNS:
                    if "id" not in COLUMNS[table] or table == "app_settings":
                        continue

                    cur.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                        "COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM " + table,
                        (table,),
                    )

            pg_conn.commit()

    finally:
        sqlite_conn.close()

    print("Migration SQLite → PostgreSQL terminée.")
    print(f"Source conservée : {SQLITE_PATH}")


if __name__ == "__main__":
    migrate()
