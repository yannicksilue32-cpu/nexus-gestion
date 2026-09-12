"""Authentification Nexus Gestion - gestion multi-utilisateurs."""

from __future__ import annotations

from datetime import datetime

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# NORMALISATION
# ============================================================

def normalize_username(username):
    """Normalise le nom d'utilisateur pour éviter les doublons."""
    if username is None:
        return ""

    return str(username).strip().lower()


# ============================================================
# TABLE USERS
# ============================================================

def create_auth_tables(connection):
    """
    Crée et migre la table users.

    Compatible avec la structure SQLite actuelle de Nexus Gestion.
    """

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

    # --------------------------------------------------------
    # Migration SQLite
    # --------------------------------------------------------

    try:
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        ]
    except Exception:
        columns = []

    if columns:

        if "active" not in columns:
            if "actif" in columns:
                connection.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN active INTEGER NOT NULL DEFAULT 1
                    """
                )

                connection.execute(
                    """
                    UPDATE users
                    SET active = actif
                    """
                )
            else:
                connection.execute(
                    """
                    ALTER TABLE users
                    ADD COLUMN active INTEGER NOT NULL DEFAULT 1
                    """
                )

        if "created_at" not in columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN created_at TEXT
                """
            )

            connection.execute(
                """
                UPDATE users
                SET created_at = ?
                WHERE created_at IS NULL
                """,
                (_now(),),
            )

        if "last_login" not in columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN last_login TEXT
                """
            )

        if "role" not in columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN role TEXT NOT NULL DEFAULT 'employee'
                """
            )

        if "full_name" not in columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN full_name TEXT NOT NULL DEFAULT 'Utilisateur'
                """
            )

    # --------------------------------------------------------
    # Index
    # --------------------------------------------------------

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_username
        ON users(username)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_role
        ON users(role)
        """
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_active
        ON users(active)
        """
    )

    connection.commit()


# ============================================================
# RECHERCHE UTILISATEUR
# ============================================================

def get_user_by_username(connection, username):
    username = normalize_username(username)

    if not username:
        return None

    return connection.execute(
        """
        SELECT *
        FROM users
        WHERE LOWER(username) = ?
        LIMIT 1
        """,
        (username,),
    ).fetchone()


def get_user_by_id(connection, user_id):
    if not user_id:
        return None

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    return connection.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


# ============================================================
# STATISTIQUES
# ============================================================

def count_users(connection):
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM users
        """
    ).fetchone()

    return int(row[0] or 0) if row else 0


def count_admins(connection):
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE role = 'admin'
        AND active = 1
        """
    ).fetchone()

    return int(row[0] or 0) if row else 0


# ============================================================
# MOTS DE PASSE
# ============================================================

def hash_password(password):
    if password is None:
        password = ""

    return generate_password_hash(str(password))


def verify_password(password, password_hash):
    if not password_hash:
        return False

    try:
        return check_password_hash(
            password_hash,
            password or "",
        )
    except (TypeError, ValueError):
        return False


# ============================================================
# SESSION UTILISATEUR
# ============================================================

def login_user(user):
    """
    Connecte exactement l'utilisateur fourni.

    Chaque compte possède son propre user_id.
    """

    session.clear()

    session["user_id"] = int(user["id"])

    role = user["role"] or "employee"

    if role not in ("admin", "employee"):
        role = "employee"

    session["role"] = role
    session["is_admin"] = role == "admin"


def logout_user():
    session.clear()


def is_logged_in():
    return bool(session.get("user_id"))


def current_user(connection):
    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(connection, user_id)


def is_admin():
    return (
        session.get("role") == "admin"
        or bool(session.get("is_admin"))
    )