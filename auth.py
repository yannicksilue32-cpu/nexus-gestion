"""Authentification Nexus Gestion compatible SQLite et PostgreSQL."""

from __future__ import annotations

from datetime import datetime

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_auth_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_login TEXT
        )
        """
    )

    columns = [row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()]

    if "active" not in columns:
        if "actif" in columns:
            connection.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            connection.execute("UPDATE users SET active = actif")
        else:
            connection.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

    if "created_at" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        connection.execute(
            "UPDATE users SET created_at = COALESCE(created_at, ?)",
            (_now(),),
        )

    if "last_login" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN last_login TEXT")

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)"
    )

    connection.commit()


def get_user_by_username(connection, username):
    return connection.execute(
        "SELECT * FROM users WHERE username = ? LIMIT 1",
        (username,),
    ).fetchone()


def get_user_by_id(connection, user_id):
    if not user_id:
        return None

    return connection.execute(
        "SELECT * FROM users WHERE id = ? LIMIT 1",
        (user_id,),
    ).fetchone()


def count_users(connection):
    row = connection.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def count_admins(connection):
    row = connection.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    if not password_hash:
        return False
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False


def login_user(user):
    session.clear()
    session["user_id"] = int(user["id"])
    session["role"] = user["role"] or "employee"
    session["is_admin"] = (user["role"] == "admin")


def logout_user():
    session.pop("user_id", None)
    session.pop("role", None)
    session.pop("is_admin", None)


def is_logged_in():
    return bool(session.get("user_id"))


def current_user(connection):
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(connection, user_id)


def is_admin():
    return session.get("role") == "admin" or bool(session.get("is_admin"))
