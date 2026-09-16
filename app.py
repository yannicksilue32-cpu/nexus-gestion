
# ============================================================
# NEXUS GESTION
# APP.PY FINAL - VERSION ROBUSTE + NEXUS INTELLIGENCE
# + NEXUS NOTATION
# ============================================================

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import os
import csv
import io

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PACKAGES_DIR = BASE_DIR / "packages"

if PACKAGES_DIR.exists():
    sys.path.insert(0, str(PACKAGES_DIR))

from flask import (
    Flask,
    render_template,
    render_template_string,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session,
)

from db_compat import (
    DATABASE,
    DATABASE_URL,
    USING_POSTGRES,
    DB_ERROR,
    DB_INTEGRITY_ERROR,
    get_db_connection,
)

from nexus_prix import (
    calculate_nexus_price,
    build_nexus_price_recommendation,
)

from nexus_simulateur import (
    simulate_business,
    build_business_report,
)

from auth import (
    create_auth_tables,
    get_user_by_username,
    get_user_by_id,
    count_users,
    count_admins,
    hash_password,
    verify_password,
    login_user,
    logout_user,
    current_user,
    is_logged_in,
    is_admin,
    normalize_username,
)

# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

app.secret_key = os.environ.get(
    "NEXUS_SECRET_KEY",
    "nexus-gestion-secret-2026"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("NEXUS_SECURE_COOKIES", "").lower()
    in ("1", "true", "yes", "on")
)

# ============================================================
# DATABASE
# ============================================================

get_db = get_db_connection


def scalar(connection, query, params=(), default=0):
    row = connection.execute(query, params).fetchone()

    if row is None or row[0] is None:
        return default

    return row[0]


def one(connection, query, params=()):
    return connection.execute(query, params).fetchone()


def many(connection, query, params=()):
    return connection.execute(query, params).fetchall()


# ============================================================
# SAFE CONVERSIONS
# ============================================================

def safe_float(value, default=0.0):
    if value is None:
        return default

    try:
        if isinstance(value, str):
            value = value.strip().replace(" ", "")

            if not value:
                return default

            value = value.replace(",", ".")

        return float(value)

    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    if value is None:
        return default

    try:
        if isinstance(value, str):
            value = value.strip().replace(" ", "")

            if not value:
                return default

            value = value.replace(",", ".")

        return int(float(value))

    except (TypeError, ValueError):
        return default


def safe_text(value, default=""):
    if value is None:
        return default

    return str(value).strip()


def money_number(value):
    return round(safe_float(value), 2)


def money(value):
    number = safe_float(value)
    return f"{number:,.0f}".replace(",", " ")


@app.template_filter("money")
def money_filter(value):
    return money(value)


def today():
    return datetime.now().strftime("%Y-%m-%d")


def now_datetime():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def days_ago(days):
    return (
        datetime.now().date() - timedelta(days=days)
    ).strftime("%Y-%m-%d")


# ============================================================
# GLOBALS
# ============================================================

@app.context_processor
def inject_globals():
    connection = get_db_connection()

    try:
        user = current_user(connection)

    finally:
        connection.close()

    return {
        "current_date": today(),
        "current_datetime": now_datetime(),
        "current_user": user,
        "current_user_is_admin": is_admin(),
        "is_logged_in": is_logged_in(),
    }


# ============================================================
# TEMPLATE HELPERS
# ============================================================

def template_exists(name):
    return (
        BASE_DIR / "templates" / name
    ).exists()


def choose_template(*names):
    for name in names:
        if template_exists(name):
            return name

    return names[0]


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_database():

    connection = get_db_connection()
    cursor = connection.cursor()

    # --------------------------------------------------------
    # PRODUCTS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            purchase_price REAL DEFAULT 0,
            selling_price REAL DEFAULT 0,
            quantity INTEGER DEFAULT 0,
            stock_alert INTEGER DEFAULT 5
        )
    """)

    # --------------------------------------------------------
    # SALES
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            date TEXT,
            purchase_price_at_sale REAL DEFAULT NULL
        )
    """)

    sales_columns = [
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(sales)"
        ).fetchall()
    ]

    if "purchase_price_at_sale" not in sales_columns:

        cursor.execute("""
            ALTER TABLE sales
            ADD COLUMN purchase_price_at_sale REAL DEFAULT NULL
        """)

        cursor.execute("""
            UPDATE sales
            SET purchase_price_at_sale = (
                SELECT CAST(p.purchase_price AS REAL)
                FROM products p
                WHERE p.id = sales.product_id
            )
            WHERE purchase_price_at_sale IS NULL
        """)

    # --------------------------------------------------------
    # PURCHASES
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # EXPENSES
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            amount REAL DEFAULT 0,
            category TEXT,
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # CUSTOMERS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            created_at TEXT
        )
    """)

    # --------------------------------------------------------
    # INVOICES
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            customer_id INTEGER,
            total REAL DEFAULT 0,
            status TEXT DEFAULT 'Impayée',
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # INVOICE ITEMS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER,
            product_id INTEGER,
            quantity INTEGER DEFAULT 1,
            price REAL DEFAULT 0,
            subtotal REAL DEFAULT 0
        )
    """)

    # --------------------------------------------------------
    # INVENTORY MOVEMENTS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            reference_id INTEGER,
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cursor.execute("""
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
    """)

    # --------------------------------------------------------
    # NEXUS NOTATION
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # --------------------------------------------------------
    # INDEXES
    # --------------------------------------------------------

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_username "
        "ON users(username)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_role "
        "ON users(role)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sales_product "
        "ON sales(product_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sales_date "
        "ON sales(date)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchases_product "
        "ON purchases(product_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchases_date "
        "ON purchases(date)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice "
        "ON invoice_items(invoice_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_product "
        "ON invoice_items(product_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_product "
        "ON inventory_movements(product_id)"
    )

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_user "
        "ON ratings(user_id)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ratings_rating "
        "ON ratings(rating)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ratings_created_at "
        "ON ratings(created_at)"
    )

    connection.commit()
    connection.close()


init_database()


# ============================================================
# V1 PRO - MIGRATIONS
# ============================================================

def ensure_pro_schema():

    connection = get_db_connection()

    try:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                company_name TEXT DEFAULT 'Nexus Gestion',
                company_phone TEXT DEFAULT '',
                company_email TEXT DEFAULT '',
                company_address TEXT DEFAULT '',
                currency TEXT DEFAULT 'FCFA',
                updated_at TEXT
            )
        """)

        connection.execute("""
            INSERT OR IGNORE INTO app_settings
            (id, company_name, currency, updated_at)
            VALUES (1, 'Nexus Gestion', 'FCFA', ?)
        """, (now_datetime(),))

        movement_columns = [
            r[1]
            for r in connection.execute(
                "PRAGMA table_info(inventory_movements)"
            ).fetchall()
        ]

        if "reason" not in movement_columns:
            connection.execute(
                "ALTER TABLE inventory_movements ADD COLUMN reason TEXT"
            )

        if "created_by" not in movement_columns:
            connection.execute(
                "ALTER TABLE inventory_movements ADD COLUMN created_by INTEGER"
            )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_movements_date "
            "ON inventory_movements(date)"
        )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_movements_type "
            "ON inventory_movements(movement_type)"
        )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_invoices_status "
            "ON invoices(status)"
        )

        connection.commit()

    finally:
        connection.close()


def admin_required():

    if not is_admin():

        flash(
            "Accès réservé aux administrateurs.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    return None


def csv_response(filename, headers, rows):

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow(headers)

    for row in rows:
        writer.writerow(row)

    response = app.response_class(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8"
    )

    response.headers[
        "Content-Disposition"
    ] = f'attachment; filename="{filename}"'

    return response


ensure_pro_schema()


# ============================================================
# AUTH TABLE MIGRATION
# ============================================================

_connection = get_db_connection()

try:
    create_auth_tables(_connection)

finally:
    _connection.close()


# ============================================================
# STOCK AUDIT
# ============================================================

def log_inventory_movement(
    connection,
    product_id,
    movement_type,
    quantity,
    reference_id=None,
):

    connection.execute(
        """
        INSERT INTO inventory_movements
        (product_id, movement_type, quantity, reference_id, date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            safe_int(product_id),
            safe_text(movement_type),
            safe_int(quantity),
            safe_int(reference_id, 0)
            if reference_id
            else None,
            now_datetime(),
        ),
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
def dashboard():

    connection = get_db_connection()

    try:

        revenue = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM sales
                """
            )
        )

        purchases = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM purchases
                """
            )
        )

        expenses = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(amount AS REAL)),
                    0
                )
                FROM expenses
                """
            )
        )

        cogs = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(s.quantity AS REAL) *
                    CAST(
                        COALESCE(
                            s.purchase_price_at_sale,
                            p.purchase_price,
                            0
                        ) AS REAL
                    )
                ), 0)
                FROM sales s
                LEFT JOIN products p
                    ON p.id = s.product_id
                """
            )
        )

        gross_profit = revenue - cogs

        profit = gross_profit - expenses

        margin = (
            profit / revenue * 100
            if revenue > 0
            else 0.0
        )

        ca_jour = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM sales
                WHERE date(date) =
                    date('now', 'localtime')
                """
            )
        )

        ca_mois = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM sales
                WHERE strftime('%Y-%m', date) =
                    strftime('%Y-%m', 'now', 'localtime')
                """
            )
        )

        depenses_jour = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(amount AS REAL)), 0
                )
                FROM expenses
                WHERE date(date) =
                    date('now', 'localtime')
                """
            )
        )

        depenses_mois = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(amount AS REAL)), 0
                )
                FROM expenses
                WHERE strftime('%Y-%m', date) =
                    strftime('%Y-%m', 'now', 'localtime')
                """
            )
        )

        cogs_mois = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(s.quantity AS REAL) *
                    CAST(
                        COALESCE(
                            s.purchase_price_at_sale,
                            p.purchase_price,
                            0
                        ) AS REAL
                    )
                ), 0)
                FROM sales s
                LEFT JOIN products p
                    ON p.id = s.product_id
                WHERE strftime('%Y-%m', s.date) =
                    strftime('%Y-%m', 'now', 'localtime')
                """
            )
        )

        benefice_mois = (
            ca_mois -
            cogs_mois -
            depenses_mois
        )

        nombre_produits = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM products"
            )
        )

        nombre_clients = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM customers"
            )
        )

        nombre_ventes = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM sales"
            )
        )

        nombre_factures = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM invoices"
            )
        )

        stock_total = safe_int(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(quantity AS INTEGER)),
                    0
                )
                FROM products
                """
            )
        )

        stock_faible = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM products
                WHERE CAST(quantity AS INTEGER)
                    <= CAST(stock_alert AS INTEGER)
                """
            )
        )

        produit_populaire = one(
            connection,
            """
            SELECT
                p.name,
                COALESCE(
                    SUM(CAST(s.quantity AS INTEGER)),
                    0
                ) AS total_quantity

            FROM products p

            LEFT JOIN sales s
                ON s.product_id = p.id

            GROUP BY p.id

            ORDER BY total_quantity DESC

            LIMIT 1
            """
        )

        produits_stock_faible = many(
            connection,
            """
            SELECT *
            FROM products
            WHERE CAST(quantity AS INTEGER)
                <= CAST(stock_alert AS INTEGER)
            ORDER BY CAST(quantity AS INTEGER) ASC
            LIMIT 5
            """
        )

        ventes_recentes = many(
            connection,
            """
            SELECT
                p.name AS product_name,
                s.quantity,
                s.price,
                s.date

            FROM sales s

            LEFT JOIN products p
                ON p.id = s.product_id

            ORDER BY s.id DESC

            LIMIT 5
            """
        )

        analyse = (
            "Votre activité est bénéficiaire ce mois-ci."
            if benefice_mois > 0

            else
            "Attention : votre activité est actuellement "
            "déficitaire ce mois-ci."
            if benefice_mois < 0

            else
            "Votre activité est actuellement à l'équilibre."
        )

        template = choose_template(
            "dashboard.html",
            "index.html"
        )

        return render_template(
            template,
            chiffre_affaires=money_number(revenue),
            ca_jour=money_number(ca_jour),
            ca_mois=money_number(ca_mois),
            total_depenses=money_number(expenses),
            depenses_jour=money_number(depenses_jour),
            depenses_mois=money_number(depenses_mois),
            cout_ventes=money_number(cogs),
            benefice=money_number(profit),
            benefice_mois=money_number(benefice_mois),
            nombre_produits=nombre_produits,
            nombre_clients=nombre_clients,
            stock_total=stock_total,
            stock_faible=stock_faible,
            nombre_ventes=nombre_ventes,
            nombre_factures=nombre_factures,
            produit_populaire=produit_populaire,
            produits_stock_faible=produits_stock_faible,
            ventes_recentes=ventes_recentes,
            analyse=analyse,
            revenue=money(revenue),
            purchases=money(purchases),
            expenses=money(expenses),
            profit=money(profit),
            margin=round(margin, 2),
            products_count=nombre_produits,
            customers_count=nombre_clients,
            sales_count=nombre_ventes,
            invoices_count=nombre_factures,
        )

    finally:
        connection.close()


@app.route("/dashboard")
def dashboard_alias():
    return redirect(url_for("dashboard"))


# ============================================================
# PRODUITS
# ============================================================

@app.route("/products")
def products():

    connection = get_db_connection()

    try:

        product_list = many(
            connection,
            "SELECT * FROM products ORDER BY id DESC"
        )

        return render_template(
            "products.html",
            products=product_list
        )

    finally:
        connection.close()


@app.route("/products/add", methods=["POST"])
def add_product():

    name = safe_text(
        request.form.get("name")
    )

    category = safe_text(
        request.form.get("category")
    )

    purchase_price = max(
        0,
        safe_float(
            request.form.get("purchase_price")
        )
    )

    selling_price = max(
        0,
        safe_float(
            request.form.get("selling_price")
        )
    )

    quantity = max(
        0,
        safe_int(
            request.form.get("quantity")
        )
    )

    stock_alert = max(
        0,
        safe_int(
            request.form.get("stock_alert"),
            5
        )
    )

    if not name:

        flash(
            "Le nom du produit est obligatoire.",
            "error"
        )

        return redirect(url_for("products"))

    connection = get_db_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO products
            (
                name,
                category,
                purchase_price,
                selling_price,
                quantity,
                stock_alert
            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                category,
                purchase_price,
                selling_price,
                quantity,
                stock_alert
            )
        )

        product_id = cursor.lastrowid

        if quantity > 0:

            log_inventory_movement(
                connection,
                product_id,
                "initial",
                quantity
            )

        connection.commit()

        flash(
            "Produit ajouté avec succès.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(url_for("products"))


@app.route(
    "/products/edit/<int:id>",
    methods=["GET", "POST"]
)
def edit_product(id):

    connection = get_db_connection()

    try:

        product = one(
            connection,
            "SELECT * FROM products WHERE id = ?",
            (id,)
        )

        if not product:
            return "Produit introuvable", 404

        if request.method == "POST":

            name = safe_text(
                request.form.get("name")
            )

            category = safe_text(
                request.form.get("category")
            )

            purchase_price = max(
                0,
                safe_float(
                    request.form.get("purchase_price")
                )
            )

            selling_price = max(
                0,
                safe_float(
                    request.form.get("selling_price")
                )
            )

            new_quantity = max(
                0,
                safe_int(
                    request.form.get("quantity")
                )
            )

            stock_alert = max(
                0,
                safe_int(
                    request.form.get("stock_alert"),
                    5
                )
            )

            if not name:

                flash(
                    "Le nom du produit est obligatoire.",
                    "error"
                )

                return redirect(
                    url_for(
                        "edit_product",
                        id=id
                    )
                )

            old_quantity = safe_int(
                product["quantity"]
            )

            connection.execute(
                """
                UPDATE products
                SET
                    name = ?,
                    category = ?,
                    purchase_price = ?,
                    selling_price = ?,
                    quantity = ?,
                    stock_alert = ?

                WHERE id = ?
                """,
                (
                    name,
                    category,
                    purchase_price,
                    selling_price,
                    new_quantity,
                    stock_alert,
                    id
                )
            )

            delta = (
                new_quantity -
                old_quantity
            )

            if delta != 0:

                log_inventory_movement(
                    connection,
                    id,
                    "adjustment",
                    delta
                )

            connection.commit()

            flash(
                "Produit modifié.",
                "success"
            )

            return redirect(
                url_for("products")
            )

        template = choose_template(
            "product_edit.html",
            "edit_product.html"
        )

        return render_template(
            template,
            product=product
        )

    finally:
        connection.close()


@app.route(
    "/products/delete/<int:id>",
    methods=["GET", "POST"]
)
def delete_product(id):

    connection = get_db_connection()

    try:

        product = one(
            connection,
            "SELECT * FROM products WHERE id = ?",
            (id,)
        )

        if not product:

            flash(
                "Produit introuvable.",
                "error"
            )

            return redirect(
                url_for("products")
            )

        history = (
            safe_int(
                scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM sales
                    WHERE product_id = ?
                    """,
                    (id,)
                )
            )
            +
            safe_int(
                scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM invoice_items
                    WHERE product_id = ?
                    """,
                    (id,)
                )
            )
        )

        if history > 0:

            flash(
                "Ce produit possède un historique de "
                "ventes ou de factures. "
                "Il est conservé pour préserver les données.",
                "warning"
            )

            return redirect(
                url_for("products")
            )

        connection.execute(
            "DELETE FROM products WHERE id = ?",
            (id,)
        )

        connection.commit()

        flash(
            "Produit supprimé.",
            "success"
        )

        return redirect(
            url_for("products")
        )

    finally:
        connection.close()


# ============================================================
# VENTES
# ============================================================

@app.route("/sales")
def sales():

    connection = get_db_connection()

    try:

        sales_list = many(
            connection,
            """
            SELECT
                s.id,
                s.product_id,
                s.quantity,
                s.price,
                s.date,
                p.name AS product_name

            FROM sales s

            LEFT JOIN products p
                ON p.id = s.product_id

            ORDER BY s.id DESC
            """
        )

        product_list = many(
            connection,
            "SELECT * FROM products ORDER BY name"
        )

        return render_template(
            "sales.html",
            sales=sales_list,
            products=product_list
        )

    finally:
        connection.close()


@app.route(
    "/sales/add",
    methods=["POST"]
)
def add_sale():

    product_id = safe_int(
        request.form.get("product_id")
    )

    quantity = safe_int(
        request.form.get("quantity")
    )

    if product_id <= 0 or quantity <= 0:

        flash(
            "Produit ou quantité invalide.",
            "error"
        )

        return redirect(
            url_for("sales")
        )

    connection = get_db_connection()

    try:

        product = one(
            connection,
            "SELECT * FROM products WHERE id = ?",
            (product_id,)
        )

        if not product:

            flash(
                "Produit introuvable.",
                "error"
            )

            return redirect(
                url_for("sales")
            )

        stock = safe_int(
            product["quantity"]
        )

        if stock < quantity:

            flash(
                f"Stock insuffisant : {stock} disponible(s).",
                "error"
            )

            return redirect(
                url_for("sales")
            )

        price = max(
            0,
            safe_float(
                request.form.get("price"),
                safe_float(
                    product["selling_price"]
                )
            )
        )

        purchase_price = safe_float(
            product["purchase_price"]
        )

        cursor = connection.execute(
            """
            INSERT INTO sales
            (
                product_id,
                quantity,
                price,
                date,
                purchase_price_at_sale
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product_id,
                quantity,
                price,
                today(),
                purchase_price
            )
        )

        connection.execute(
            """
            UPDATE products
            SET quantity =
                CAST(quantity AS INTEGER) - ?
            WHERE id = ?
            """,
            (
                quantity,
                product_id
            )
        )

        log_inventory_movement(
            connection,
            product_id,
            "sale",
            -quantity,
            cursor.lastrowid
        )

        connection.commit()

        flash(
            "Vente enregistrée avec succès.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur pendant la vente : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("sales")
    )


# ============================================================
# ACHATS
# ============================================================

@app.route("/purchases")
def purchases():

    connection = get_db_connection()

    try:

        purchase_list = many(
            connection,
            """
            SELECT
                pu.id,
                pu.product_id,
                pu.quantity,
                pu.price,
                pu.date,
                p.name AS product_name

            FROM purchases pu

            LEFT JOIN products p
                ON p.id = pu.product_id

            ORDER BY pu.id DESC
            """
        )

        product_list = many(
            connection,
            "SELECT * FROM products ORDER BY name"
        )

        return render_template(
            "purchases.html",
            purchases=purchase_list,
            products=product_list
        )

    finally:
        connection.close()


@app.route(
    "/purchases/add",
    methods=["POST"]
)
def add_purchase():

    product_id = safe_int(
        request.form.get("product_id")
    )

    quantity = safe_int(
        request.form.get("quantity")
    )

    price = max(
        0,
        safe_float(
            request.form.get("price")
        )
    )

    if product_id <= 0 or quantity <= 0:

        flash(
            "Produit ou quantité invalide.",
            "error"
        )

        return redirect(
            url_for("purchases")
        )

    connection = get_db_connection()

    try:

        product = one(
            connection,
            "SELECT id FROM products WHERE id = ?",
            (product_id,)
        )

        if not product:

            flash(
                "Produit introuvable.",
                "error"
            )

            return redirect(
                url_for("purchases")
            )

        cursor = connection.execute(
            """
            INSERT INTO purchases
            (
                product_id,
                quantity,
                price,
                date
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                product_id,
                quantity,
                price,
                today()
            )
        )

        connection.execute(
            """
            UPDATE products
            SET quantity =
                CAST(quantity AS INTEGER) + ?
            WHERE id = ?
            """,
            (
                quantity,
                product_id
            )
        )

        log_inventory_movement(
            connection,
            product_id,
            "purchase",
            quantity,
            cursor.lastrowid
        )

        connection.commit()

        flash(
            "Achat enregistré avec succès.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur pendant l'achat : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("purchases")
    )


# ============================================================
# DEPENSES
# ============================================================

@app.route("/expenses")
def expenses():

    connection = get_db_connection()

    try:

        expense_list = many(
            connection,
            """
            SELECT *
            FROM expenses
            ORDER BY id DESC
            """
        )

        return render_template(
            "expenses.html",
            expenses=expense_list
        )

    finally:
        connection.close()


@app.route(
    "/expenses/add",
    methods=["POST"]
)
def add_expense():

    description = safe_text(
        request.form.get("description")
    )

    category = safe_text(
        request.form.get("category")
    )

    amount = safe_float(
        request.form.get("amount")
    )

    if amount <= 0:

        flash(
            "Le montant doit être supérieur à zéro.",
            "error"
        )

        return redirect(
            url_for("expenses")
        )

    connection = get_db_connection()

    try:

        connection.execute(
            """
            INSERT INTO expenses
            (
                description,
                amount,
                category,
                date
            )

            VALUES (?, ?, ?, ?)
            """,
            (
                description,
                amount,
                category,
                today()
            )
        )

        connection.commit()

        flash(
            "Dépense enregistrée.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("expenses")
    )


# ============================================================
# CLIENTS
# ============================================================

@app.route("/customers")
def customers():

    connection = get_db_connection()

    try:

        search = safe_text(
            request.args.get("search")
        )

        if search:

            customer_list = many(
                connection,
                """
                SELECT *
                FROM customers

                WHERE
                    name LIKE ?
                    OR phone LIKE ?
                    OR email LIKE ?

                ORDER BY id DESC
                """,
                (
                    f"%{search}%",
                    f"%{search}%",
                    f"%{search}%"
                )
            )

        else:

            customer_list = many(
                connection,
                """
                SELECT *
                FROM customers
                ORDER BY id DESC
                """
            )

        return render_template(
            "customers.html",
            customers=customer_list,
            search=search
        )

    finally:
        connection.close()


@app.route(
    "/customers/add",
    methods=["POST"]
)
def add_customer():

    name = safe_text(
        request.form.get("name")
    )

    phone = safe_text(
        request.form.get("phone")
    )

    email = safe_text(
        request.form.get("email")
    )

    address = safe_text(
        request.form.get("address")
    )

    if not name:

        flash(
            "Le nom du client est obligatoire.",
            "error"
        )

        return redirect(
            url_for("customers")
        )

    connection = get_db_connection()

    try:

        connection.execute(
            """
            INSERT INTO customers
            (
                name,
                phone,
                email,
                address,
                created_at
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                phone,
                email,
                address,
                now_datetime()
            )
        )

        connection.commit()

        flash(
            "Client ajouté avec succès.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("customers")
    )


@app.route(
    "/customers/edit/<int:id>",
    methods=["GET", "POST"]
)
def edit_customer(id):

    connection = get_db_connection()

    try:

        customer = one(
            connection,
            "SELECT * FROM customers WHERE id = ?",
            (id,)
        )

        if not customer:
            return "Client introuvable", 404

        if request.method == "POST":

            name = safe_text(
                request.form.get("name")
            )

            phone = safe_text(
                request.form.get("phone")
            )

            email = safe_text(
                request.form.get("email")
            )

            address = safe_text(
                request.form.get("address")
            )

            if not name:

                flash(
                    "Le nom est obligatoire.",
                    "error"
                )

                return redirect(
                    url_for(
                        "edit_customer",
                        id=id
                    )
                )

            connection.execute(
                """
                UPDATE customers

                SET
                    name = ?,
                    phone = ?,
                    email = ?,
                    address = ?

                WHERE id = ?
                """,
                (
                    name,
                    phone,
                    email,
                    address,
                    id
                )
            )

            connection.commit()

            flash(
                "Client modifié.",
                "success"
            )

            return redirect(
                url_for("customers")
            )

        template = choose_template(
            "customer_edit.html",
            "edit_customer.html"
        )

        return render_template(
            template,
            customer=customer
        )

    finally:
        connection.close()


@app.route(
    "/customers/delete/<int:id>",
    methods=["GET", "POST"]
)
def delete_customer(id):

    connection = get_db_connection()

    try:

        invoice_count = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM invoices
                WHERE customer_id = ?
                """,
                (id,)
            )
        )

        if invoice_count > 0:

            flash(
                "Ce client possède un historique de "
                "facturation et est conservé.",
                "warning"
            )

            return redirect(
                url_for("customers")
            )

        connection.execute(
            "DELETE FROM customers WHERE id = ?",
            (id,)
        )

        connection.commit()

        flash(
            "Client supprimé.",
            "success"
        )

        return redirect(
            url_for("customers")
        )

    finally:
        connection.close()


# ============================================================
# FACTURATION
# ============================================================

def generate_invoice_number(connection):

    year = datetime.now().year

    prefix = f"FAC-{year}-"

    last = one(
        connection,
        """
        SELECT invoice_number
        FROM invoices
        WHERE invoice_number LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (prefix + "%",)
    )

    number = 1

    if last and last["invoice_number"]:

        try:

            number = (
                int(
                    str(
                        last["invoice_number"]
                    ).split("-")[-1]
                )
                + 1
            )

        except (ValueError, IndexError):

            number = safe_int(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(MAX(id), 0)
                    FROM invoices
                    """
                )
            ) + 1

    candidate = f"{prefix}{number:05d}"

    while one(
        connection,
        """
        SELECT id
        FROM invoices
        WHERE invoice_number = ?
        """,
        (candidate,)
    ):

        number += 1

        candidate = f"{prefix}{number:05d}"

    return candidate


@app.route("/invoices")
def invoices():

    connection = get_db_connection()

    try:

        invoice_list = many(
            connection,
            """
            SELECT
                i.*,
                c.name AS customer_name

            FROM invoices i

            LEFT JOIN customers c
                ON c.id = i.customer_id

            ORDER BY i.id DESC
            """
        )

        customer_list = many(
            connection,
            """
            SELECT *
            FROM customers
            ORDER BY name
            """
        )

        product_list = many(
            connection,
            """
            SELECT *
            FROM products
            ORDER BY name
            """
        )

        return render_template(
            "invoices.html",
            invoices=invoice_list,
            customers=customer_list,
            products=product_list
        )

    finally:
        connection.close()


def process_invoice_creation():

    customer_id = safe_int(
        request.form.get("customer_id")
    )

    product_ids = request.form.getlist(
        "product_id"
    )

    quantities = request.form.getlist(
        "quantity"
    )

    prices = request.form.getlist(
        "price"
    )

    if not product_ids:

        raw_product = request.form.get(
            "product_id"
        )

        if raw_product:

            product_ids = [
                raw_product
            ]

            quantities = [
                request.form.get(
                    "quantity",
                    "1"
                )
            ]

            prices = [
                request.form.get(
                    "price",
                    ""
                )
            ]

    if not product_ids:

        flash(
            "Aucun produit sélectionné.",
            "error"
        )

        return redirect(
            url_for("invoices")
        )

    if len(quantities) != len(product_ids):

        flash(
            "Les données de la facture sont invalides.",
            "error"
        )

        return redirect(
            url_for("invoices")
        )

    connection = get_db_connection()

    try:

        if customer_id > 0:

            customer = one(
                connection,
                """
                SELECT id
                FROM customers
                WHERE id = ?
                """,
                (customer_id,)
            )

            if not customer:

                flash(
                    "Client introuvable.",
                    "error"
                )

                return redirect(
                    url_for("invoices")
                )

        requested = {}
        supplied_prices = {}

        for index, raw_product_id in enumerate(
            product_ids
        ):

            product_id = safe_int(
                raw_product_id
            )

            quantity = safe_int(
                quantities[index]
            )

            if product_id <= 0 or quantity <= 0:

                flash(
                    "Produit ou quantité invalide.",
                    "error"
                )

                return redirect(
                    url_for("invoices")
                )

            requested[product_id] = (
                requested.get(
                    product_id,
                    0
                )
                + quantity
            )

            if index < len(prices):

                override = safe_float(
                    prices[index],
                    -1
                )

                if override >= 0:
                    supplied_prices[
                        product_id
                    ] = override

        invoice_items = []
        total = 0.0

        for product_id, quantity in requested.items():

            product = one(
                connection,
                """
                SELECT *
                FROM products
                WHERE id = ?
                """,
                (product_id,)
            )

            if not product:

                flash(
                    "Un des produits n'existe plus.",
                    "error"
                )

                return redirect(
                    url_for("invoices")
                )

            stock = safe_int(
                product["quantity"]
            )

            if stock < quantity:

                flash(
                    f"Stock insuffisant pour "
                    f"{product['name']}. "
                    f"Disponible : {stock}.",
                    "error"
                )

                return redirect(
                    url_for("invoices")
                )

            price = supplied_prices.get(
                product_id,
                safe_float(
                    product["selling_price"]
                )
            )

            price = max(0, price)

            subtotal = (
                price * quantity
            )

            total += subtotal

            invoice_items.append({
                "product_id": product_id,
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal,
            })

        invoice_number = (
            generate_invoice_number(
                connection
            )
        )

        invoice_date = today()

        cursor = connection.execute(
            """
            INSERT INTO invoices
            (
                invoice_number,
                customer_id,
                total,
                status,
                date
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                invoice_number,
                customer_id
                if customer_id > 0
                else None,
                total,
                "Impayée",
                invoice_date
            )
        )

        invoice_id = cursor.lastrowid

        for item in invoice_items:

            product_id = item["product_id"]
            quantity = item["quantity"]
            price = item["price"]
            subtotal = item["subtotal"]

            connection.execute(
                """
                INSERT INTO invoice_items
                (
                    invoice_id,
                    product_id,
                    quantity,
                    price,
                    subtotal
                )

                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    product_id,
                    quantity,
                    price,
                    subtotal
                )
            )

            product_row = one(
                connection,
                """
                SELECT purchase_price
                FROM products
                WHERE id = ?
                """,
                (product_id,)
            )

            purchase_price = (
                safe_float(
                    product_row["purchase_price"]
                )
                if product_row
                else 0.0
            )

            sale_cursor = connection.execute(
                """
                INSERT INTO sales
                (
                    product_id,
                    quantity,
                    price,
                    date,
                    purchase_price_at_sale
                )

                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    quantity,
                    price,
                    invoice_date,
                    purchase_price
                )
            )

            connection.execute(
                """
                UPDATE products
                SET quantity =
                    CAST(quantity AS INTEGER) - ?
                WHERE id = ?
                """,
                (
                    quantity,
                    product_id
                )
            )

            log_inventory_movement(
                connection,
                product_id,
                "invoice_sale",
                -quantity,
                invoice_id
            )

        connection.commit()

        flash(
            f"Facture {invoice_number} créée avec succès.",
            "success"
        )

        return redirect(
            url_for(
                "invoice_detail",
                invoice_id=invoice_id
            )
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur lors de la création de la facture : {error}",
            "error"
        )

        return redirect(
            url_for("invoices")
        )

    finally:
        connection.close()


@app.route(
    "/invoices/add",
    methods=["POST"]
)
def add_invoice():
    return process_invoice_creation()


@app.route(
    "/invoices/create",
    methods=["POST"]
)
def create_invoice():
    return process_invoice_creation()


def show_invoice(
    invoice_id,
    print_mode=False
):

    connection = get_db_connection()

    try:

        invoice = one(
            connection,
            """
            SELECT
                i.id,
                i.invoice_number,
                i.customer_id,
                i.total,
                i.status,
                i.date,
                c.name AS customer_name,
                c.phone AS customer_phone,
                c.email AS customer_email,
                c.address AS customer_address

            FROM invoices i

            LEFT JOIN customers c
                ON c.id = i.customer_id

            WHERE i.id = ?
            """,
            (invoice_id,)
        )

        if not invoice:
            return "Facture introuvable", 404

        items = many(
            connection,
            """
            SELECT
                ii.id,
                ii.invoice_id,
                ii.product_id,
                ii.quantity,
                ii.price,
                ii.subtotal,
                p.name AS product_name

            FROM invoice_items ii

            LEFT JOIN products p
                ON p.id = ii.product_id

            WHERE ii.invoice_id = ?

            ORDER BY ii.id
            """,
            (invoice_id,)
        )

        template = choose_template(
            "invoice.html",
            "invoice_detail.html"
        )

        return render_template(
            template,
            invoice=invoice,
            items=items,
            print_mode=print_mode
        )

    finally:
        connection.close()


@app.route(
    "/invoice/<int:invoice_id>"
)
def invoice_detail(invoice_id):
    return show_invoice(invoice_id)


@app.route(
    "/invoices/<int:invoice_id>"
)
def invoice_detail_old(invoice_id):
    return show_invoice(invoice_id)


@app.route(
    "/invoice/<int:invoice_id>/print"
)
def invoice_print(invoice_id):
    return show_invoice(
        invoice_id,
        print_mode=True
    )


@app.route(
    "/invoice/<int:invoice_id>/paid",
    methods=["GET", "POST"]
)
def mark_invoice_paid(invoice_id):

    connection = get_db_connection()

    try:

        invoice = one(
            connection,
            """
            SELECT *
            FROM invoices
            WHERE id = ?
            """,
            (invoice_id,)
        )

        if not invoice:

            flash(
                "Facture introuvable.",
                "error"
            )

            return redirect(
                url_for("invoices")
            )

        connection.execute(
            """
            UPDATE invoices
            SET status = 'Payée'
            WHERE id = ?
            """,
            (invoice_id,)
        )

        connection.commit()

        flash(
            "Facture marquée comme payée.",
            "success"
        )

        return redirect(
            url_for(
                "invoice_detail",
                invoice_id=invoice_id
            )
        )

    finally:
        connection.close()


@app.route(
    "/invoices/<int:invoice_id>/paid",
    methods=["GET", "POST"]
)
def mark_invoice_paid_alias(invoice_id):
    return mark_invoice_paid(invoice_id)


# ============================================================
# NEXUS INTELLIGENCE
# ============================================================

def intelligence_analysis():

    connection = get_db_connection()

    try:

        revenue = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM sales
                """
            )
        )

        purchases = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)
                FROM purchases
                """
            )
        )

        expenses = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(amount AS REAL)),
                    0
                )
                FROM expenses
                """
            )
        )

        cogs = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(s.quantity AS REAL) *
                    CAST(
                        COALESCE(
                            s.purchase_price_at_sale,
                            p.purchase_price,
                            0
                        ) AS REAL
                    )
                ), 0)

                FROM sales s

                LEFT JOIN products p
                    ON p.id = s.product_id
                """
            )
        )

        gross_profit = (
            revenue - cogs
        )

        net_profit = (
            gross_profit - expenses
        )

        gross_margin = (
            gross_profit /
            revenue *
            100
            if revenue > 0
            else 0.0
        )

        margin = (
            net_profit /
            revenue *
            100
            if revenue > 0
            else 0.0
        )

        stock_quantity = safe_int(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(quantity AS INTEGER)),
                    0
                )
                FROM products
                """
            )
        )

        stock_value = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        CAST(quantity AS REAL) *
                        CAST(purchase_price AS REAL)
                    ),
                    0
                )
                FROM products
                """
            )
        )

        stock_selling_value = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        CAST(quantity AS REAL) *
                        CAST(selling_price AS REAL)
                    ),
                    0
                )
                FROM products
                """
            )
        )

        low_stock = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM products
                WHERE
                    CAST(quantity AS INTEGER) > 0
                    AND
                    CAST(quantity AS INTEGER)
                    <= CAST(stock_alert AS INTEGER)
                """
            )
        )

        out_of_stock = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM products
                WHERE CAST(quantity AS INTEGER) <= 0
                """
            )
        )

        products_count = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM products"
            )
        )

        sales_count = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM sales"
            )
        )

        units_sold = safe_int(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(quantity AS INTEGER)),
                    0
                )
                FROM sales
                """
            )
        )

        average_sale = (
            revenue / sales_count
            if sales_count > 0
            else 0.0
        )

        purchase_count = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM purchases"
            )
        )

        units_purchased = safe_int(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(quantity AS INTEGER)),
                    0
                )
                FROM purchases
                """
            )
        )

        average_purchase = (
            purchases / purchase_count
            if purchase_count > 0
            else 0.0
        )

        customers_count = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM customers"
            )
        )

        invoices_count = safe_int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM invoices"
            )
        )

        paid_invoices = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM invoices
                WHERE status = 'Payée'
                """
            )
        )

        unpaid_invoices = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM invoices
                WHERE status != 'Payée'
                   OR status IS NULL
                """
            )
        )

        invoice_total = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(total AS REAL)),
                    0
                )
                FROM invoices
                """
            )
        )

        paid_amount = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(total AS REAL)),
                    0
                )
                FROM invoices
                WHERE status = 'Payée'
                """
            )
        )

        unpaid_amount = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(total AS REAL)),
                    0
                )
                FROM invoices
                WHERE status != 'Payée'
                   OR status IS NULL
                """
            )
        )

        current_start = days_ago(30)
        previous_start = days_ago(60)

        current_revenue = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)

                FROM sales

                WHERE date(date) >= date(?)
                """,
                (current_start,)
            )
        )

        previous_revenue = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)

                FROM sales

                WHERE
                    date(date) >= date(?)
                    AND
                    date(date) < date(?)
                """,
                (
                    previous_start,
                    current_start
                )
            )
        )

        if previous_revenue > 0:

            revenue_growth = (
                (
                    current_revenue -
                    previous_revenue
                )
                /
                previous_revenue
            ) * 100

        else:
            revenue_growth = 0.0

        revenue_7_days = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)

                FROM sales

                WHERE date(date) >= date(?)
                """,
                (days_ago(7),)
            )
        )

        expenses_30_days = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(CAST(amount AS REAL)),
                    0
                )

                FROM expenses

                WHERE date(date) >= date(?)
                """,
                (current_start,)
            )
        )

        purchases_30_days = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(SUM(
                    CAST(quantity AS REAL) *
                    CAST(price AS REAL)
                ), 0)

                FROM purchases

                WHERE date(date) >= date(?)
                """,
                (current_start,)
            )
        )

        expense_categories = many(
            connection,
            """
            SELECT
                COALESCE(
                    category,
                    'Non classée'
                ) AS category,
                COALESCE(
                    SUM(
                        CAST(amount AS REAL)
                    ),
                    0
                ) AS total

            FROM expenses

            GROUP BY category

            ORDER BY total DESC
            """
        )

        top_rows = many(
            connection,
            """
            SELECT
                p.id,
                p.name,

                COALESCE(
                    SUM(
                        CAST(s.quantity AS INTEGER)
                    ),
                    0
                ) AS quantity_sold,

                COALESCE(
                    SUM(
                        CAST(s.quantity AS REAL) *
                        CAST(s.price AS REAL)
                    ),
                    0
                ) AS revenue

            FROM products p

            LEFT JOIN sales s
                ON s.product_id = p.id

            GROUP BY p.id

            ORDER BY revenue DESC

            LIMIT 10
            """
        )

        top_products = [
            {
                "id": safe_int(row["id"]),
                "name": safe_text(row["name"]),
                "quantity_sold": safe_int(
                    row["quantity_sold"]
                ),
                "revenue": safe_float(
                    row["revenue"]
                ),
            }

            for row in top_rows
        ]

        product_rows = many(
            connection,
            "SELECT * FROM products ORDER BY name"
        )

        product_analysis = []

        for product in product_rows:

            product_id = safe_int(
                product["id"]
            )

            stock = safe_int(
                product["quantity"]
            )

            stock_alert = safe_int(
                product["stock_alert"],
                5
            )

            purchase_price = safe_float(
                product["purchase_price"]
            )

            selling_price = safe_float(
                product["selling_price"]
            )

            quantity_sold = safe_int(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS INTEGER)
                        ),
                        0
                    )

                    FROM sales

                    WHERE product_id = ?
                    """,
                    (product_id,)
                )
            )

            recent_sales = safe_int(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS INTEGER)
                        ),
                        0
                    )

                    FROM sales

                    WHERE
                        product_id = ?
                        AND date(date) >= date(?)
                    """,
                    (
                        product_id,
                        current_start
                    )
                )
            )

            recent_7_sales = safe_int(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS INTEGER)
                        ),
                        0
                    )

                    FROM sales

                    WHERE
                        product_id = ?
                        AND date(date) >= date(?)
                    """,
                    (
                        product_id,
                        days_ago(7)
                    )
                )
            )

            previous_30_sales = safe_int(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS INTEGER)
                        ),
                        0
                    )

                    FROM sales

                    WHERE
                        product_id = ?
                        AND date(date) >= date(?)
                        AND date(date) < date(?)
                    """,
                    (
                        product_id,
                        previous_start,
                        current_start
                    )
                )
            )

            product_revenue = safe_float(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS REAL) *
                            CAST(price AS REAL)
                        ),
                        0
                    )

                    FROM sales

                    WHERE product_id = ?
                    """,
                    (product_id,)
                )
            )

            unit_profit = (
                selling_price -
                purchase_price
            )

            total_profit = (
                quantity_sold *
                unit_profit
            )

            margin_percent = (
                unit_profit /
                selling_price *
                100
                if selling_price > 0
                else 0.0
            )

            daily_sales = (
                recent_sales / 30.0
            )

            daily_sales_7 = (
                recent_7_sales / 7.0
            )

            previous_daily_sales = (
                previous_30_sales / 30.0
            )

            if daily_sales and daily_sales_7:

                demand_daily = (
                    daily_sales * 0.4
                    +
                    daily_sales_7 * 0.6
                )

            else:

                demand_daily = (
                    daily_sales
                    or daily_sales_7
                )

            demand_trend = (
                (
                    demand_daily /
                    previous_daily_sales
                )
                - 1.0
                if previous_daily_sales > 0
                else (
                    0.0
                    if demand_daily == 0
                    else 1.0
                )
            )

            trend_capped = max(
                -0.50,
                min(
                    0.50,
                    demand_trend
                )
            )

            forecast_7 = max(
                0.0,
                demand_daily *
                (
                    1 +
                    trend_capped * 0.35
                )
                * 7
            )

            forecast_14 = max(
                0.0,
                demand_daily *
                (
                    1 +
                    trend_capped * 0.50
                )
                * 14
            )

            forecast_30 = max(
                0.0,
                demand_daily *
                (
                    1 +
                    trend_capped * 0.65
                )
                * 30
            )

            stock_days = (
                stock / demand_daily
                if demand_daily > 0
                else None
            )

            target_stock = int(
                round(
                    forecast_14 * 1.20
                )
            )

            reorder_quantity = max(
                0,
                target_stock - stock
            )

            reorder_value = (
                reorder_quantity *
                purchase_price
            )

            capital_immobilized = (
                stock *
                purchase_price
            )

            potential_30_revenue = max(
                0.0,
                forecast_30 *
                selling_price
            )

            potential_30_profit = max(
                0.0,
                forecast_30 *
                unit_profit
            )

            if selling_price < purchase_price:
                status = "Prix déficitaire"

            elif stock <= 0:
                status = "Rupture"

            elif stock <= stock_alert:
                status = "Stock faible"

            elif (
                stock_days is not None
                and stock_days <= 7
            ):
                status = "Risque de rupture"

            elif quantity_sold == 0:
                status = "Aucune vente"

            elif margin_percent < 10:
                status = "Marge faible"

            else:
                status = "Normal"

            if selling_price < purchase_price:

                intelligence_level = "Risque élevé"

            elif (
                stock <= 0
                and demand_daily > 0
            ):

                intelligence_level = "Urgence"

            elif (
                demand_trend >= 0.20
                and demand_daily > 0
            ):

                intelligence_level = (
                    "Produit stratégique"
                )

            elif (
                stock_days is not None
                and stock_days <= 14
            ):

                intelligence_level = (
                    "À réapprovisionner"
                )

            elif (
                stock > 0
                and quantity_sold == 0
            ):

                intelligence_level = (
                    "Capital immobilisé"
                )

            elif (
                margin_percent >= 25
                and demand_daily > 0
            ):

                intelligence_level = (
                    "Très rentable"
                )

            elif demand_daily > 0:

                intelligence_level = (
                    "À surveiller"
                )

            else:

                intelligence_level = (
                    "Sans données"
                )

            item = {

                "id": product_id,

                "name": safe_text(
                    product["name"]
                ),

                "category": safe_text(
                    product["category"]
                ),

                "stock": stock,

                "quantity": stock,

                "stock_alert": stock_alert,

                "purchase_price":
                    purchase_price,

                "selling_price":
                    selling_price,

                "quantity_sold":
                    quantity_sold,

                "sold_quantity":
                    quantity_sold,

                "recent_sales":
                    recent_sales,

                "revenue":
                    product_revenue,

                "unit_profit":
                    unit_profit,

                "total_profit":
                    total_profit,

                "profit":
                    total_profit,

                "margin_percent":
                    margin_percent,

                "margin":
                    margin_percent,

                "daily_sales":
                    daily_sales,

                "daily_sales_7":
                    daily_sales_7,

                "demand_daily":
                    demand_daily,

                "demand_trend":
                    demand_trend,

                "demand_trend_percent":
                    demand_trend * 100,

                "forecast_7_days":
                    round(forecast_7, 2),

                "forecast_14_days":
                    round(forecast_14, 2),

                "forecast_30_days":
                    round(forecast_30, 2),

                "stock_days":
                    stock_days,

                "days_remaining":
                    stock_days,

                "target_stock":
                    target_stock,

                "reorder_quantity":
                    reorder_quantity,

                "reorder_value":
                    round(
                        reorder_value,
                        2
                    ),

                "capital_immobilized":
                    round(
                        capital_immobilized,
                        2
                    ),

                "potential_30_revenue":
                    round(
                        potential_30_revenue,
                        2
                    ),

                "potential_30_profit":
                    round(
                        potential_30_profit,
                        2
                    ),

                "intelligence_level":
                    intelligence_level,

                "status":
                    status,
            }

            product_analysis.append(item)

        profitable_products = sorted(
            product_analysis,
            key=lambda p:
                safe_float(
                    p.get(
                        "total_profit",
                        0
                    )
                ),
            reverse=True
        )[:10]

        slow_products = sorted(
            product_analysis,
            key=lambda p:
                safe_int(
                    p.get(
                        "quantity_sold",
                        0
                    )
                )
        )[:10]

        product_risk = sorted(
            [
                p
                for p in product_analysis
                if p.get(
                    "intelligence_level"
                )
                in (
                    "Urgence",
                    "Risque élevé",
                    "À réapprovisionner"
                )
            ],
            key=lambda p: (
                safe_float(
                    p.get(
                        "reorder_value"
                    )
                ),
                safe_float(
                    p.get(
                        "demand_daily"
                    )
                )
            ),
            reverse=True
        )[:10]

        product_opportunities = sorted(
            product_analysis,
            key=lambda p:
                safe_float(
                    p.get(
                        "potential_30_profit"
                    )
                ),
            reverse=True
        )[:10]

        capital_locked_products = sorted(
            product_analysis,
            key=lambda p:
                safe_float(
                    p.get(
                        "capital_immobilized"
                    )
                ),
            reverse=True
        )[:10]

        total_reorder_value = sum(
            safe_float(
                p.get(
                    "reorder_value"
                )
            )
            for p in product_analysis
        )

        total_capital_immobilized = sum(
            safe_float(
                p.get(
                    "capital_immobilized"
                )
            )
            for p in product_analysis
        )

        potential_30_revenue = sum(
            safe_float(
                p.get(
                    "potential_30_revenue"
                )
            )
            for p in product_analysis
        )

        potential_30_profit = sum(
            safe_float(
                p.get(
                    "potential_30_profit"
                )
            )
            for p in product_analysis
        )

        top_customers = many(
            connection,
            """
            SELECT
                c.id,
                c.name,

                COUNT(i.id)
                    AS invoice_count,

                COALESCE(
                    SUM(
                        CAST(i.total AS REAL)
                    ),
                    0
                )
                    AS total_billed,

                COALESCE(
                    SUM(
                        CASE
                            WHEN i.status = 'Payée'
                            THEN CAST(i.total AS REAL)
                            ELSE 0
                        END
                    ),
                    0
                )
                    AS total_paid,

                COALESCE(
                    SUM(
                        CASE
                            WHEN
                                i.status != 'Payée'
                                OR i.status IS NULL
                            THEN CAST(i.total AS REAL)
                            ELSE 0
                        END
                    ),
                    0
                )
                    AS total_unpaid

            FROM customers c

            LEFT JOIN invoices i
                ON i.customer_id = c.id

            GROUP BY c.id

            ORDER BY total_billed DESC

            LIMIT 10
            """
        )

        daily_sales = []

        for offset in range(
            29,
            -1,
            -1
        ):

            day = (
                datetime.now().date()
                -
                timedelta(days=offset)
            ).strftime(
                "%Y-%m-%d"
            )

            day_revenue = safe_float(
                scalar(
                    connection,
                    """
                    SELECT COALESCE(
                        SUM(
                            CAST(quantity AS REAL) *
                            CAST(price AS REAL)
                        ),
                        0
                    )

                    FROM sales

                    WHERE date(date) = date(?)
                    """,
                    (day,)
                )
            )

            daily_sales.append({
                "date": day,
                "revenue": day_revenue,
            })

        return {

            "revenue":
                revenue,

            "purchases":
                purchases,

            "expenses":
                expenses,

            "cogs":
                cogs,

            "gross_profit":
                gross_profit,

            "net_profit":
                net_profit,

            "gross_margin":
                gross_margin,

            "margin":
                margin,

            "stock_quantity":
                stock_quantity,

            "stock_value":
                stock_value,

            "stock_selling_value":
                stock_selling_value,

            "low_stock":
                low_stock,

            "out_of_stock":
                out_of_stock,

            "products_count":
                products_count,

            "sales_count":
                sales_count,

            "units_sold":
                units_sold,

            "average_sale":
                average_sale,

            "purchase_count":
                purchase_count,

            "units_purchased":
                units_purchased,

            "average_purchase":
                average_purchase,

            "customers_count":
                customers_count,

            "invoices_count":
                invoices_count,

            "paid_invoices":
                paid_invoices,

            "unpaid_invoices":
                unpaid_invoices,

            "invoice_total":
                invoice_total,

            "paid_amount":
                paid_amount,

            "unpaid_amount":
                unpaid_amount,

            "current_revenue":
                current_revenue,

            "previous_revenue":
                previous_revenue,

            "revenue_growth":
                revenue_growth,

            "revenue_7_days":
                revenue_7_days,

            "revenue_30_days":
                current_revenue,

            "expenses_30_days":
                expenses_30_days,

            "purchases_30_days":
                purchases_30_days,

            "expense_categories":
                expense_categories,

            "top_products":
                top_products,

            "profitable_products":
                profitable_products,

            "slow_products":
                slow_products,

            "product_analysis":
                product_analysis,

            "product_risk":
                product_risk,

            "product_opportunities":
                product_opportunities,

            "capital_locked_products":
                capital_locked_products,

            "total_reorder_value":
                total_reorder_value,

            "total_capital_immobilized":
                total_capital_immobilized,

            "potential_30_revenue":
                potential_30_revenue,

            "potential_30_profit":
                potential_30_profit,

            "top_customers":
                top_customers,

            "daily_sales":
                daily_sales,
        }

    finally:
        connection.close()


# ============================================================
# ALERTES
# ============================================================

def generate_intelligence_alerts(analysis):

    alerts = []

    revenue = safe_float(
        analysis.get("revenue")
    )

    profit = safe_float(
        analysis.get("net_profit")
    )

    margin = safe_float(
        analysis.get("margin")
    )

    growth = safe_float(
        analysis.get("revenue_growth")
    )

    low_stock = safe_int(
        analysis.get("low_stock")
    )

    out_of_stock = safe_int(
        analysis.get("out_of_stock")
    )

    unpaid_amount = safe_float(
        analysis.get("unpaid_amount")
    )

    products = analysis.get(
        "product_analysis",
        []
    )

    if profit < 0:

        alerts.append({
            "type": "danger",
            "title": "Entreprise déficitaire",
            "message":
                "Le résultat net est négatif de "
                f"{money(abs(profit))} FCFA.",
        })

    elif profit > 0:

        alerts.append({
            "type": "success",
            "title": "Rentabilité positive",
            "message":
                "Le bénéfice net actuel est de "
                f"{money(profit)} FCFA.",
        })

    else:

        alerts.append({
            "type": "warning",
            "title": "Équilibre financier",
            "message":
                "L'activité est actuellement "
                "proche de l'équilibre.",
        })

    if revenue > 0:

        if margin < 10:

            alerts.append({
                "type": "warning",
                "title": "Marge faible",
                "message":
                    f"La marge nette est de {margin:.1f} %.",
            })

        elif margin >= 20:

            alerts.append({
                "type": "success",
                "title": "Bonne marge",
                "message":
                    f"La marge nette atteint {margin:.1f} %.",
            })

    if growth <= -20:

        alerts.append({
            "type": "danger",
            "title": "Forte baisse du CA",
            "message":
                f"Le chiffre d'affaires recule de "
                f"{abs(growth):.1f} %.",
        })

    elif growth <= -10:

        alerts.append({
            "type": "warning",
            "title": "Ralentissement des ventes",
            "message":
                f"Le chiffre d'affaires recule de "
                f"{abs(growth):.1f} %.",
        })

    elif growth >= 10:

        alerts.append({
            "type": "success",
            "title": "Croissance des ventes",
            "message":
                f"Le chiffre d'affaires progresse de "
                f"{growth:.1f} %.",
        })

    if out_of_stock > 0:

        alerts.append({
            "type": "danger",
            "title": "Ruptures de stock",
            "message":
                f"{out_of_stock} produit(s) sont en rupture.",
        })

    if low_stock > 0:

        alerts.append({
            "type": "warning",
            "title": "Stock faible",
            "message":
                f"{low_stock} produit(s) sont sous "
                "leur seuil d'alerte.",
        })

    pricing_issues = [
        p
        for p in products
        if safe_float(
            p.get("selling_price")
        )
        <
        safe_float(
            p.get("purchase_price")
        )
    ]

    if pricing_issues:

        alerts.append({
            "type": "danger",
            "title": "Prix déficitaires",
            "message":
                f"{len(pricing_issues)} produit(s) "
                "sont vendus sous leur coût d'achat.",
        })

    if unpaid_amount > 0:

        alerts.append({
            "type": "warning",
            "title": "Créances clients",
            "message":
                f"{safe_int(analysis.get('unpaid_invoices'))} "
                f"facture(s) représentent "
                f"{money(unpaid_amount)} FCFA à recouvrer.",
        })

    purchases = safe_float(
        analysis.get("purchases")
    )

    if revenue > 0 and purchases > revenue:

        alerts.append({
            "type": "warning",
            "title": "Achats élevés",
            "message":
                "Les achats cumulés dépassent "
                "le chiffre d'affaires cumulé. "
                "Surveillez la trésorerie et "
                "la rotation du stock.",
        })

    return alerts


# ============================================================
# RECOMMANDATIONS
# ============================================================

def generate_recommendations(analysis):

    recommendations = []

    revenue = safe_float(
        analysis.get("revenue")
    )

    profit = safe_float(
        analysis.get("net_profit")
    )

    margin = safe_float(
        analysis.get("margin")
    )

    expenses = safe_float(
        analysis.get("expenses")
    )

    growth = safe_float(
        analysis.get("revenue_growth")
    )

    unpaid_amount = safe_float(
        analysis.get("unpaid_amount")
    )

    stock_value = safe_float(
        analysis.get("stock_value")
    )

    products = analysis.get(
        "product_analysis",
        []
    )

    def add(
        priority,
        category,
        title,
        reason,
        action,
        impact_amount=0,
        impact_label=""
    ):

        amount = max(
            0.0,
            safe_float(impact_amount)
        )

        impact_score = (
            min(
                100,
                int(
                    round(
                        amount /
                        max(revenue, 1) *
                        100
                    )
                )
            )
            if amount
            else 0
        )

        decision_score = (
            max(
                0,
                100 - priority * 15
            )
            +
            impact_score
        )

        recommendations.append({

            "priority":
                priority,

            "type":
                category.lower(),

            "category":
                category,

            "title":
                title,

            "reason":
                reason,

            "action":
                action,

            "impact":
                impact_label
                or
                (
                    f"{money(amount)} FCFA"
                    if amount
                    else "À surveiller"
                ),

            "impact_amount":
                round(
                    amount,
                    2
                ),

            "impact_score":
                impact_score,

            "decision_score":
                decision_score,

            "message":
                f"{reason} Action : {action}",
        })

    for p in [
        x
        for x in products
        if safe_float(
            x.get("selling_price")
        )
        <
        safe_float(
            x.get("purchase_price")
        )
    ][:3]:

        loss = (
            safe_float(
                p.get("purchase_price")
            )
            -
            safe_float(
                p.get("selling_price")
            )
        )

        add(
            1,
            "Rentabilité",
            f"Prix de vente déficitaire — {p['name']}",
            f"Chaque unité vendue génère environ "
            f"{money(loss)} FCFA de perte brute.",
            "Corriger le prix ou négocier "
            "le coût d'achat.",
            loss *
            safe_int(
                p.get("recent_sales")
            ),
            "Critique"
        )

    for p in [
        x
        for x in products
        if safe_int(
            x.get("stock")
        ) <= 0
        and safe_int(
            x.get("recent_sales")
        ) > 0
    ][:3]:

        add(
            1,
            "Stock",
            f"Réapprovisionnement urgent — {p['name']}",
            f"{safe_int(p.get('recent_sales'))} "
            "unité(s) ont été vendues sur 30 jours "
            "alors que le stock est nul.",
            f"Réapprovisionner {p['name']} rapidement.",
            0,
            "Critique"
        )

    for p in [
        x
        for x in products
        if x.get("stock_days") is not None
        and safe_float(
            x.get("stock_days")
        ) <= 14
        and safe_int(
            x.get("recent_sales")
        ) > 0
    ][:5]:

        daily = safe_float(
            p.get("daily_sales")
        )

        target = max(
            0,
            int(
                round(
                    daily * 14
                )
            )
        )

        need = max(
            0,
            target -
            safe_int(
                p.get("stock")
            )
        )

        if need > 0:

            add(
                2,
                "Stock",
                f"Prévoir le réassort — {p['name']}",
                f"La couverture actuelle est "
                f"d'environ "
                f"{safe_float(p.get('stock_days')):.1f} jours.",
                f"Prévoir environ {need} unité(s) "
                "pour viser 14 jours de couverture.",
                need *
                safe_float(
                    p.get("purchase_price")
                ),
                "Élevé"
            )

    for p in [
        x
        for x in products
        if
        0 <= safe_float(
            x.get("margin_percent")
        ) < 10
        and safe_int(
            x.get("quantity_sold")
        ) > 0
    ][:3]:

        add(
            2,
            "Rentabilité",
            f"Marge faible — {p['name']}",
            f"La marge unitaire est de "
            f"{safe_float(p.get('margin_percent')):.1f} %.",
            "Revoir le prix, le coût d'achat "
            "ou le positionnement.",
            abs(
                safe_float(
                    p.get("total_profit")
                )
            ),
            "Important"
        )

    dormant = [
        x
        for x in products
        if safe_int(
            x.get("stock")
        ) > 0
        and safe_int(
            x.get("quantity_sold")
        ) == 0
    ]

    for p in dormant[:3]:

        capital = (
            safe_int(
                p.get("stock")
            )
            *
            safe_float(
                p.get("purchase_price")
            )
        )

        add(
            2,
            "Stock",
            f"Capital immobilisé — {p['name']}",
            f"Le produit dispose de "
            f"{safe_int(p.get('stock'))} unité(s) "
            "sans vente enregistrée.",
            "Éviter un nouveau réassort "
            "et envisager une stratégie d'écoulement.",
            capital,
            "Important"
        )

    if profit < 0:

        add(
            1,
            "Finance",
            "Restaurer la rentabilité",
            f"Le résultat net est déficitaire "
            f"de {money(abs(profit))} FCFA.",
            "Réduire les charges prioritaires "
            "et corriger les produits peu rentables.",
            abs(profit),
            "Critique"
        )

    if revenue > 0:

        expense_ratio = (
            expenses /
            revenue *
            100
        )

        if expense_ratio >= 40:

            add(
                1,
                "Finance",
                "Dépenses excessives",
                f"Les dépenses représentent "
                f"{expense_ratio:.1f} % du CA.",
                "Réduire ou renégocier "
                "les charges non essentielles.",
                expenses,
                "Très élevé"
            )

        elif expense_ratio >= 25:

            add(
                3,
                "Finance",
                "Surveiller les dépenses",
                f"Les dépenses représentent "
                f"{expense_ratio:.1f} % du CA.",
                "Suivre les principales "
                "catégories de charges.",
                expenses,
                "Moyen"
            )

    if growth <= -20:

        add(
            1,
            "Ventes",
            "Forte baisse du chiffre d'affaires",
            f"Le CA recule de {abs(growth):.1f} %.",
            "Identifier les produits responsables "
            "de la baisse.",
            abs(
                revenue *
                growth /
                100
            ),
            "Très élevé"
        )

    elif growth <= -10:

        add(
            2,
            "Ventes",
            "Ralentissement commercial",
            f"Le CA recule de {abs(growth):.1f} %.",
            "Analyser les produits en baisse "
            "et surveiller leur évolution.",
            abs(
                revenue *
                growth /
                100
            ),
            "Élevé"
        )

    elif growth >= 20:

        add(
            2,
            "Opportunité",
            "Forte croissance commerciale",
            f"Le CA progresse de {growth:.1f} %.",
            "Renforcer les produits à forte demande "
            "avec prudence.",
            revenue *
            growth /
            100,
            "Important"
        )

    if unpaid_amount > 0:

        add(
            1
            if revenue
            and unpaid_amount / revenue >= .2
            else 2,

            "Trésorerie",

            "Recouvrement des créances",

            f"{money(unpaid_amount)} FCFA "
            "restent à recouvrer.",

            "Prioriser les factures impayées "
            "les plus élevées.",

            unpaid_amount,

            "Élevé"
        )

    if (
        revenue > 0
        and stock_value / revenue >= 1
    ):

        add(
            2,
            "Stock",
            "Stock très important",
            f"La valeur d'achat du stock atteint "
            f"environ "
            f"{stock_value / revenue * 100:.0f} % "
            "du CA cumulé.",
            "Limiter les achats des produits "
            "à faible rotation.",
            stock_value,
            "Important"
        )

    for p in products:

        reorder = safe_int(
            p.get("reorder_quantity")
        )

        reorder_value = safe_float(
            p.get("reorder_value")
        )

        stock_days = p.get(
            "stock_days"
        )

        if (
            reorder > 0
            and reorder_value > 0
            and safe_float(
                p.get("demand_daily")
            ) > 0
        ):

            priority = (
                1
                if
                stock_days is not None
                and safe_float(
                    stock_days
                ) <= 7
                else 2
            )

            add(
                priority,
                "Intelligence produit",
                f"Commander {reorder} unité(s) — {p['name']}",
                f"La demande prévue est d'environ "
                f"{safe_float(p.get('forecast_14_days')):.0f} "
                "unité(s) sur 14 jours et le stock cible "
                f"est de {safe_int(p.get('target_stock'))}.",
                f"Prévoir un achat d'environ "
                f"{reorder} unité(s), soit "
                f"{money(reorder_value)} FCFA.",
                reorder_value,
                "Prévision"
            )

        if (
            safe_float(
                p.get("demand_trend")
            ) >= 0.20
            and
            safe_float(
                p.get("forecast_30_days")
            ) > 0
        ):

            add(
                2,
                "Opportunité",
                f"Demande en forte progression — {p['name']}",
                f"La demande estimée progresse "
                f"d'environ "
                f"{safe_float(p.get('demand_trend')) * 100:.0f} %.",
                "Surveiller les ventes "
                "et sécuriser le stock "
                "avant une rupture.",
                safe_float(
                    p.get(
                        "potential_30_profit"
                    )
                ),
                "Opportunité"
            )

    if not recommendations:

        add(
            4,
            "Général",
            "Situation stable",
            "Aucune anomalie importante détectée.",
            "Continuer à suivre ventes, marges, "
            "dépenses, créances et stocks.",
            0,
            "Normal"
        )

    unique = {}

    for r in recommendations:

        if (
            r["title"] not in unique
            or
            r["decision_score"]
            >
            unique[
                r["title"]
            ]["decision_score"]
        ):

            unique[
                r["title"]
            ] = r

    recommendations = sorted(
        unique.values(),
        key=lambda r: (
            r["decision_score"],
            r["impact_amount"]
        ),
        reverse=True
    )

    return recommendations[:10]


# ============================================================
# STOCK
# ============================================================

@app.route("/stock")
def stock():

    connection = get_db_connection()

    try:

        search = safe_text(
            request.args.get("search")
        )

        state = safe_text(
            request.args.get("state")
        )

        movement = safe_text(
            request.args.get("movement")
        )

        product_id = safe_int(
            request.args.get("product_id")
        )

        where = []
        params = []

        if search:

            where.append(
                "(p.name LIKE ? OR p.category LIKE ?)"
            )

            params += [
                f"%{search}%",
                f"%{search}%"
            ]

        if state == "rupture":

            where.append(
                "CAST(p.quantity AS INTEGER) <= 0"
            )

        elif state == "faible":

            where.append(
                """
                CAST(p.quantity AS INTEGER) > 0
                AND CAST(p.quantity AS INTEGER)
                    <= CAST(p.stock_alert AS INTEGER)
                """
            )

        elif state == "normal":

            where.append(
                """
                CAST(p.quantity AS INTEGER)
                    > CAST(p.stock_alert AS INTEGER)
                """
            )

        query = """
            SELECT
                p.*,
                (p.quantity * p.purchase_price)
                    AS purchase_value,
                (p.quantity * p.selling_price)
                    AS selling_value

            FROM products p
        """

        if where:
            query += (
                " WHERE " +
                " AND ".join(where)
            )

        query += """
            ORDER BY
                p.quantity ASC,
                p.name COLLATE NOCASE
        """

        products_list = many(
            connection,
            query,
            tuple(params)
        )

        movement_where = []
        movement_params = []

        if product_id > 0:

            movement_where.append(
                "m.product_id = ?"
            )

            movement_params.append(
                product_id
            )

        if movement in (
            "entry",
            "exit",
            "sale",
            "purchase",
            "invoice_sale",
            "adjustment",
            "initial"
        ):

            movement_where.append(
                "m.movement_type = ?"
            )

            movement_params.append(
                movement
            )

        movement_query = """
            SELECT
                m.*,
                p.name AS product_name

            FROM inventory_movements m

            LEFT JOIN products p
                ON p.id = m.product_id
        """

        if movement_where:

            movement_query += (
                " WHERE " +
                " AND ".join(
                    movement_where
                )
            )

        movement_query += """
            ORDER BY m.id DESC
            LIMIT 100
        """

        movements = many(
            connection,
            movement_query,
            tuple(movement_params)
        )

        total_quantity = safe_int(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(quantity),
                    0
                )
                FROM products
                """
            )
        )

        purchase_value = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        purchase_price
                    ),
                    0
                )
                FROM products
                """
            )
        )

        selling_value = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        selling_price
                    ),
                    0
                )
                FROM products
                """
            )
        )

        low_stock = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM products
                WHERE quantity > 0
                  AND quantity <= stock_alert
                """
            )
        )

        out_of_stock = safe_int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM products
                WHERE quantity <= 0
                """
            )
        )

        potential_margin = (
            selling_value -
            purchase_value
        )

        product_list = many(
            connection,
            """
            SELECT
                id,
                name,
                quantity
            FROM products
            ORDER BY name COLLATE NOCASE
            """
        )

        return render_template(
            "stock_pro.html",
            products=products_list,
            products_list=product_list,
            movements=movements,
            total_quantity=total_quantity,
            purchase_value=purchase_value,
            selling_value=selling_value,
            potential_margin=potential_margin,
            low_stock=low_stock,
            out_of_stock=out_of_stock,
            search=search,
            state=state,
            movement=movement,
            product_id=product_id
        )

    finally:
        connection.close()


@app.route(
    "/stock/movement",
    methods=["POST"]
)
def stock_movement():

    product_id = safe_int(
        request.form.get("product_id")
    )

    movement_type = safe_text(
        request.form.get(
            "movement_type"
        )
    ).lower()

    quantity = safe_int(
        request.form.get("quantity")
    )

    reason = safe_text(
        request.form.get("reason"),
        "Mouvement manuel"
    )

    if (
        product_id <= 0
        or quantity <= 0
        or movement_type not in (
            "entry",
            "exit"
        )
    ):

        flash(
            "Mouvement de stock invalide.",
            "error"
        )

        return redirect(
            url_for("stock")
        )

    connection = get_db_connection()

    try:

        product = one(
            connection,
            "SELECT * FROM products WHERE id=?",
            (product_id,)
        )

        if not product:

            flash(
                "Produit introuvable.",
                "error"
            )

            return redirect(
                url_for("stock")
            )

        current = safe_int(
            product["quantity"]
        )

        delta = (
            quantity
            if movement_type == "entry"
            else -quantity
        )

        if current + delta < 0:

            flash(
                f"Stock insuffisant : "
                f"{current} disponible(s).",
                "error"
            )

            return redirect(
                url_for("stock")
            )

        connection.execute(
            """
            UPDATE products
            SET quantity = ?
            WHERE id = ?
            """,
            (
                current + delta,
                product_id
            )
        )

        connection.execute(
            """
            INSERT INTO inventory_movements
            (
                product_id,
                movement_type,
                quantity,
                reference_id,
                date,
                reason,
                created_by
            )

            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                movement_type,
                delta,
                None,
                now_datetime(),
                reason,
                session.get("user_id")
            )
        )

        connection.commit()

        flash(
            "Mouvement de stock enregistré.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("stock")
    )


@app.route("/api/stock/movements")
def api_stock_movements():

    connection = get_db_connection()

    try:

        rows = many(
            connection,
            """
            SELECT
                m.*,
                p.name AS product_name

            FROM inventory_movements m

            LEFT JOIN products p
                ON p.id = m.product_id

            ORDER BY m.id DESC

            LIMIT 200
            """
        )

        return jsonify({
            "success": True,
            "movements": [
                dict(row)
                for row in rows
            ]
        })

    finally:
        connection.close()


# ============================================================
# CRUD / HISTORIQUE
# ============================================================

@app.route(
    "/sales/delete/<int:id>",
    methods=["POST"]
)
def delete_sale(id):

    connection = get_db_connection()

    try:

        sale = one(
            connection,
            "SELECT * FROM sales WHERE id=?",
            (id,)
        )

        if not sale:

            flash(
                "Vente introuvable.",
                "error"
            )

            return redirect(
                url_for("sales")
            )

        product_id = safe_int(
            sale["product_id"]
        )

        qty = safe_int(
            sale["quantity"]
        )

        connection.execute(
            "DELETE FROM sales WHERE id=?",
            (id,)
        )

        if product_id:

            connection.execute(
                """
                UPDATE products
                SET quantity = quantity + ?
                WHERE id = ?
                """,
                (
                    qty,
                    product_id
                )
            )

            connection.execute(
                """
                INSERT INTO inventory_movements
                (
                    product_id,
                    movement_type,
                    quantity,
                    reference_id,
                    date,
                    reason,
                    created_by
                )

                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    "sale_reversal",
                    qty,
                    id,
                    now_datetime(),
                    "Annulation de vente",
                    session.get("user_id")
                )
            )

        connection.commit()

        flash(
            "Vente supprimée et stock restauré.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("sales")
    )


@app.route(
    "/purchases/delete/<int:id>",
    methods=["POST"]
)
def delete_purchase(id):

    connection = get_db_connection()

    try:

        purchase = one(
            connection,
            "SELECT * FROM purchases WHERE id=?",
            (id,)
        )

        if not purchase:

            flash(
                "Achat introuvable.",
                "error"
            )

            return redirect(
                url_for("purchases")
            )

        product_id = safe_int(
            purchase["product_id"]
        )

        qty = safe_int(
            purchase["quantity"]
        )

        product = one(
            connection,
            "SELECT quantity FROM products WHERE id=?",
            (product_id,)
        )

        if (
            product
            and
            safe_int(
                product["quantity"]
            ) < qty
        ):

            flash(
                "Suppression impossible : le stock actuel "
                "ne permet pas d'annuler cet achat.",
                "error"
            )

            return redirect(
                url_for("purchases")
            )

        connection.execute(
            "DELETE FROM purchases WHERE id=?",
            (id,)
        )

        connection.execute(
            """
            UPDATE products
            SET quantity = quantity - ?
            WHERE id = ?
            """,
            (
                qty,
                product_id
            )
        )

        connection.execute(
            """
            INSERT INTO inventory_movements
            (
                product_id,
                movement_type,
                quantity,
                reference_id,
                date,
                reason,
                created_by
            )

            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                "purchase_reversal",
                -qty,
                id,
                now_datetime(),
                "Annulation d'achat",
                session.get("user_id")
            )
        )

        connection.commit()

        flash(
            "Achat supprimé et stock ajusté.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("purchases")
    )


@app.route(
    "/expenses/delete/<int:id>",
    methods=["POST"]
)
def delete_expense(id):

    connection = get_db_connection()

    try:

        if not one(
            connection,
            "SELECT id FROM expenses WHERE id=?",
            (id,)
        ):

            flash(
                "Dépense introuvable.",
                "error"
            )

        else:

            connection.execute(
                "DELETE FROM expenses WHERE id=?",
                (id,)
            )

            connection.commit()

            flash(
                "Dépense supprimée.",
                "success"
            )

    finally:
        connection.close()

    return redirect(
        url_for("expenses")
    )


# ============================================================
# RAPPORTS / EXPORTS
# ============================================================

@app.route("/reports")
def reports():

    connection = get_db_connection()

    try:

        start = safe_text(
            request.args.get("start")
        )

        end = safe_text(
            request.args.get("end")
        )

        if not start:
            start = days_ago(30)

        if not end:
            end = today()

        revenue = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(quantity * price),
                    0
                )
                FROM sales
                WHERE date(date)
                    BETWEEN date(?) AND date(?)
                """,
                (start, end)
            )
        )

        cogs = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        COALESCE(
                            purchase_price_at_sale,
                            0
                        )
                    ),
                    0
                )
                FROM sales
                WHERE date(date)
                    BETWEEN date(?) AND date(?)
                """,
                (start, end)
            )
        )

        expenses = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(amount),
                    0
                )
                FROM expenses
                WHERE date(date)
                    BETWEEN date(?) AND date(?)
                """,
                (start, end)
            )
        )

        purchases = safe_float(
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(quantity * price),
                    0
                )
                FROM purchases
                WHERE date(date)
                    BETWEEN date(?) AND date(?)
                """,
                (start, end)
            )
        )

        return render_template(
            "reports.html",
            start=start,
            end=end,
            revenue=revenue,
            cogs=cogs,
            expenses=expenses,
            purchases=purchases,
            gross_profit=revenue - cogs,
            net_profit=revenue - cogs - expenses
        )

    finally:
        connection.close()


@app.route(
    "/export/<resource>.csv"
)
def export_csv(resource):

    connection = get_db_connection()

    try:

        if resource == "products":

            rows = many(
                connection,
                """
                SELECT
                    id,
                    name,
                    category,
                    purchase_price,
                    selling_price,
                    quantity,
                    stock_alert
                FROM products
                ORDER BY name
                """
            )

            return csv_response(
                "nexus_produits.csv",
                [
                    "ID",
                    "Nom",
                    "Catégorie",
                    "Prix achat",
                    "Prix vente",
                    "Stock",
                    "Seuil"
                ],
                rows
            )

        if resource == "sales":

            rows = many(
                connection,
                """
                SELECT
                    s.id,
                    p.name,
                    s.quantity,
                    s.price,
                    s.date
                FROM sales s
                LEFT JOIN products p
                    ON p.id = s.product_id
                ORDER BY s.id DESC
                """
            )

            return csv_response(
                "nexus_ventes.csv",
                [
                    "ID",
                    "Produit",
                    "Quantité",
                    "Prix",
                    "Date"
                ],
                rows
            )

        if resource == "purchases":

            rows = many(
                connection,
                """
                SELECT
                    pu.id,
                    p.name,
                    pu.quantity,
                    pu.price,
                    pu.date
                FROM purchases pu
                LEFT JOIN products p
                    ON p.id = pu.product_id
                ORDER BY pu.id DESC
                """
            )

            return csv_response(
                "nexus_achats.csv",
                [
                    "ID",
                    "Produit",
                    "Quantité",
                    "Prix",
                    "Date"
                ],
                rows
            )

        if resource == "expenses":

            rows = many(
                connection,
                """
                SELECT
                    id,
                    description,
                    category,
                    amount,
                    date
                FROM expenses
                ORDER BY id DESC
                """
            )

            return csv_response(
                "nexus_depenses.csv",
                [
                    "ID",
                    "Description",
                    "Catégorie",
                    "Montant",
                    "Date"
                ],
                rows
            )

        if resource == "customers":

            rows = many(
                connection,
                """
                SELECT
                    id,
                    name,
                    phone,
                    email,
                    address,
                    created_at
                FROM customers
                ORDER BY name
                """
            )

            return csv_response(
                "nexus_clients.csv",
                [
                    "ID",
                    "Nom",
                    "Téléphone",
                    "Email",
                    "Adresse",
                    "Créé le"
                ],
                rows
            )

        if resource == "invoices":

            rows = many(
                connection,
                """
                SELECT
                    invoice_number,
                    total,
                    status,
                    date
                FROM invoices
                ORDER BY id DESC
                """
            )

            return csv_response(
                "nexus_factures.csv",
                [
                    "Numéro",
                    "Total",
                    "Statut",
                    "Date"
                ],
                rows
            )

        return "Export inconnu", 404

    finally:
        connection.close()


# ============================================================
# PROFIL / PARAMETRES
# ============================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
def profile():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    try:

        user = get_user_by_id(
            connection,
            user_id
        )

        if request.method == "POST":

            full_name = safe_text(
                request.form.get("full_name")
            )

            old_password = request.form.get(
                "old_password",
                ""
            )

            new_password = request.form.get(
                "new_password",
                ""
            )

            confirm = request.form.get(
                "confirm_password",
                ""
            )

            if not full_name:

                flash(
                    "Le nom complet est obligatoire.",
                    "error"
                )

            elif (
                new_password
                and
                (
                    len(new_password) < 8
                    or
                    new_password != confirm
                    or
                    not verify_password(
                        old_password,
                        user["password_hash"]
                    )
                )
            ):

                flash(
                    "Pour changer le mot de passe, "
                    "vérifiez l'ancien mot de passe "
                    "et utilisez deux nouveaux mots "
                    "de passe identiques d'au moins "
                    "8 caractères.",
                    "error"
                )

            else:

                if new_password:

                    connection.execute(
                        """
                        UPDATE users
                        SET
                            full_name=?,
                            password_hash=?
                        WHERE id=?
                        """,
                        (
                            full_name,
                            hash_password(
                                new_password
                            ),
                            user_id
                        )
                    )

                else:

                    connection.execute(
                        """
                        UPDATE users
                        SET full_name=?
                        WHERE id=?
                        """,
                        (
                            full_name,
                            user_id
                        )
                    )

                connection.commit()

                flash(
                    "Profil mis à jour.",
                    "success"
                )

            return redirect(
                url_for("profile")
            )

        return render_template(
            "profile.html",
            user=user
        )

    finally:
        connection.close()


@app.route(
    "/settings",
    methods=["GET", "POST"]
)
def settings():

    denied = admin_required()

    if denied:
        return denied

    connection = get_db_connection()

    try:

        if request.method == "POST":

            data = (
                safe_text(
                    request.form.get(
                        "company_name"
                    )
                )
                or
                "Nexus Gestion",

                safe_text(
                    request.form.get(
                        "company_phone"
                    )
                ),

                safe_text(
                    request.form.get(
                        "company_email"
                    )
                ),

                safe_text(
                    request.form.get(
                        "company_address"
                    )
                ),

                safe_text(
                    request.form.get(
                        "currency"
                    )
                )
                or "FCFA",

                now_datetime()
            )

            connection.execute(
                """
                UPDATE app_settings

                SET
                    company_name=?,
                    company_phone=?,
                    company_email=?,
                    company_address=?,
                    currency=?,
                    updated_at=?

                WHERE id=1
                """,
                data
            )

            connection.commit()

            flash(
                "Paramètres enregistrés.",
                "success"
            )

            return redirect(
                url_for("settings")
            )

        config = one(
            connection,
            """
            SELECT *
            FROM app_settings
            WHERE id=1
            """
        )

        return render_template(
            "settings.html",
            settings=config
        )

    finally:
        connection.close()


@app.route(
    "/api/reports/summary"
)
def api_reports_summary():

    analysis = intelligence_analysis()

    return jsonify({
        "success": True,
        "revenue":
            analysis["revenue"],
        "gross_profit":
            analysis["gross_profit"],
        "net_profit":
            analysis["net_profit"],
        "margin":
            analysis["margin"],
        "stock_value":
            analysis["stock_value"],
        "unpaid_amount":
            analysis["unpaid_amount"],
    })


# ============================================================
# SCORE DE SANTE
# ============================================================

def calculate_health_score(analysis):

    revenue = safe_float(
        analysis.get("revenue")
    )

    profit = safe_float(
        analysis.get("net_profit")
    )

    margin = safe_float(
        analysis.get("margin")
    )

    growth = safe_float(
        analysis.get("revenue_growth")
    )

    ruptures = safe_int(
        analysis.get("out_of_stock")
    )

    low_stock = safe_int(
        analysis.get("low_stock")
    )

    unpaid = safe_float(
        analysis.get("unpaid_amount")
    )

    score = 50

    factors = []

    if profit > 0:

        score += 15

        factors.append(
            "rentabilité positive"
        )

    elif profit < 0:

        score -= 20

        factors.append(
            "résultat déficitaire"
        )

    if margin >= 25:

        score += 15

        factors.append(
            "marge forte"
        )

    elif margin >= 20:

        score += 12

    elif margin >= 10:

        score += 7

    elif revenue > 0:

        score -= 7

        factors.append(
            "marge faible"
        )

    if growth >= 20:

        score += 10

        factors.append(
            "forte croissance"
        )

    elif growth >= 10:

        score += 7

    elif growth <= -20:

        score -= 15

        factors.append(
            "forte baisse du CA"
        )

    elif growth <= -10:

        score -= 10

    if ruptures:

        score -= min(
            15,
            ruptures * 3
        )

        factors.append(
            f"{ruptures} rupture(s)"
        )

    if low_stock:

        score -= min(
            8,
            low_stock
        )

        factors.append(
            f"{low_stock} stock(s) faible(s)"
        )

    if unpaid > 0:

        score -= 5

        factors.append(
            "créances à recouvrer"
        )

    score = max(
        0,
        min(
            100,
            int(round(score))
        )
    )

    status = (
        "Excellente"
        if score >= 80

        else
        "Bonne"
        if score >= 65

        else
        "Moyenne"
        if score >= 50

        else
        "Fragile"
        if score >= 30

        else
        "Critique"
    )

    return {
        "score": score,
        "status": status,
        "factors": factors
    }


# ============================================================
# DIAGNOSTIC
# ============================================================

def generate_diagnostic(
    analysis,
    health
):

    score = safe_int(
        health.get("score")
    )

    revenue = safe_float(
        analysis.get("revenue")
    )

    profit = safe_float(
        analysis.get("net_profit")
    )

    margin = safe_float(
        analysis.get("margin")
    )

    growth = safe_float(
        analysis.get("revenue_growth")
    )

    ruptures = safe_int(
        analysis.get("out_of_stock")
    )

    low_stock = safe_int(
        analysis.get("low_stock")
    )

    unpaid = safe_float(
        analysis.get("unpaid_amount")
    )

    text = (
        "La situation globale de votre entreprise "
        "est très bonne."
        if score >= 80

        else
        "La situation globale de votre entreprise "
        "est plutôt saine."
        if score >= 65

        else
        "La situation globale est moyenne et nécessite "
        "une surveillance régulière."
        if score >= 50

        else
        "La situation de l'entreprise est fragile "
        "et plusieurs actions correctives "
        "sont nécessaires."
        if score >= 30

        else
        "La situation économique de l'entreprise "
        "est préoccupante et demande des actions "
        "prioritaires."
    )

    if revenue <= 0:

        text += (
            " Aucun chiffre d'affaires n'est encore disponible."
        )

    elif profit < 0:

        text += (
            f" Le résultat net est déficitaire de "
            f"{money(abs(profit))} FCFA."
        )

    else:

        text += (
            f" Le bénéfice net est actuellement de "
            f"{money(profit)} FCFA."
        )

    if revenue > 0:

        text += (
            f" La marge nette est de {margin:.1f} %."
        )

    if growth >= 10:

        text += (
            f" Le chiffre d'affaires progresse de "
            f"{growth:.1f} %."
        )

    elif growth <= -10:

        text += (
            f" Le chiffre d'affaires recule de "
            f"{abs(growth):.1f} %."
        )

    if ruptures > 0:

        text += (
            f" {ruptures} produit(s) sont en rupture."
        )

    elif low_stock > 0:

        text += (
            f" {low_stock} produit(s) ont un stock faible."
        )

    if unpaid > 0:

        text += (
            f" {money(unpaid)} FCFA restent à recouvrer."
        )

    return text


# ============================================================
# PREVISIONS
# ============================================================

def generate_forecast(analysis):

    revenue_30 = safe_float(
        analysis.get(
            "revenue_30_days"
        )
    )

    revenue_7 = safe_float(
        analysis.get(
            "revenue_7_days"
        )
    )

    average_30 = (
        revenue_30 / 30
        if revenue_30 > 0
        else 0.0
    )

    average_7 = (
        revenue_7 / 7
        if revenue_7 > 0
        else 0.0
    )

    base = (
        average_7 * 0.6
        +
        average_30 * 0.4
        if average_7 > 0
        else average_30
    )

    trend = (
        average_7 / average_30
        if
        average_30 > 0
        and average_7 > 0
        else 1.0
    )

    trend = max(
        0.70,
        min(
            1.30,
            trend
        )
    )

    estimated_daily = (
        base * trend
    )

    daily = [
        safe_float(
            x.get("revenue")
        )
        for x in analysis.get(
            "daily_sales",
            []
        )
    ]

    mean = (
        sum(daily) /
        len(daily)
        if daily
        else 0.0
    )

    volatility = (
        (
            (
                sum(
                    (
                        x - mean
                    ) ** 2
                    for x in daily
                )
                /
                len(daily)
            ) ** 0.5
        )
        /
        mean
        * 100
        if
        daily
        and
        mean > 0
        else 0.0
    )

    confidence = (
        "Élevée"
        if
        len(daily) >= 25
        and volatility < 50

        else
        "Moyenne"
        if len(daily) >= 14

        else
        "Faible"
    )

    return {

        "daily_average":
            estimated_daily,

        "daily_average_30":
            average_30,

        "daily_average_7":
            average_7,

        "next_7_days":
            estimated_daily * 7,

        "next_30_days":
            estimated_daily * 30,

        "trend_factor":
            trend,

        "trend_percent":
            (trend - 1) * 100,

        "volatility_percent":
            volatility,

        "confidence":
            confidence,

        "observed_days":
            len(daily),
    }


# ============================================================
# INTELLIGENCE ROUTE
# ============================================================

@app.route("/intelligence")
def intelligence():

    analysis = intelligence_analysis()

    health = calculate_health_score(
        analysis
    )

    alerts = generate_intelligence_alerts(
        analysis
    )

    recommendations = generate_recommendations(
        analysis
    )

    diagnostic = generate_diagnostic(
        analysis,
        health
    )

    forecast = generate_forecast(
        analysis
    )

    product_analysis = analysis[
        "product_analysis"
    ]

    risk_products = [
        p
        for p in product_analysis
        if p["status"]
        in (
            "Rupture",
            "Stock faible",
            "Risque de rupture",
            "Prix déficitaire",
            "Marge faible"
        )
    ]

    top_products = sorted(
        product_analysis,
        key=lambda p:
            safe_float(
                p.get("revenue")
            ),
        reverse=True
    )[:10]

    profitable_products = sorted(
        product_analysis,
        key=lambda p:
            safe_float(
                p.get("total_profit")
            ),
        reverse=True
    )[:10]

    slow_products = sorted(
        product_analysis,
        key=lambda p:
            safe_int(
                p.get("quantity_sold")
            )
    )[:10]

    return render_template(
        "intelligence.html",

        analysis=analysis,

        alerts=alerts,

        recommendations=recommendations,

        health=health,

        score=health["score"],

        health_status=health["status"],

        diagnostic=diagnostic,

        forecast=forecast,

        product_analysis=product_analysis,

        risk_products=risk_products,

        top_products=top_products,

        profitable_products=profitable_products,

        slow_products=slow_products,
    )


# ============================================================
# API INTELLIGENCE
# ============================================================

@app.route("/api/intelligence")
def api_intelligence():

    analysis = intelligence_analysis()

    health = calculate_health_score(
        analysis
    )

    return jsonify({

        "application":
            "Nexus Gestion",

        "health":
            health,

        "diagnostic":
            generate_diagnostic(
                analysis,
                health
            ),

        "alerts":
            generate_intelligence_alerts(
                analysis
            ),

        "recommendations":
            generate_recommendations(
                analysis
            ),

        "forecast":
            generate_forecast(
                analysis
            ),

        "analysis":
            analysis,
    })


@app.route("/api/dashboard")
def api_dashboard():

    analysis = intelligence_analysis()

    health = calculate_health_score(
        analysis
    )

    return jsonify({

        "revenue":
            analysis["revenue"],

        "expenses":
            analysis["expenses"],

        "profit":
            analysis["net_profit"],

        "margin":
            analysis["margin"],

        "stock_value":
            analysis["stock_value"],

        "customers":
            analysis["customers_count"],

        "sales":
            analysis["sales_count"],

        "invoices":
            analysis["invoices_count"],

        "health_score":
            health["score"],
    })


@app.route("/api/stock")
def api_stock():

    analysis = intelligence_analysis()

    return jsonify({

        "total_quantity":
            analysis["stock_quantity"],

        "purchase_value":
            analysis["stock_value"],

        "selling_value":
            analysis["stock_selling_value"],

        "low_stock":
            analysis["low_stock"],

        "out_of_stock":
            analysis["out_of_stock"],

        "products":
            analysis["product_analysis"],
    })


@app.route(
    "/api/intelligence/products/predictions"
)
def api_intelligence_product_predictions():

    analysis = intelligence_analysis()

    return jsonify({

        "success": True,

        "products":
            analysis["product_analysis"],

        "risk_products":
            analysis["product_risk"],

        "opportunities":
            analysis["product_opportunities"],

        "capital_locked":
            analysis["capital_locked_products"],

        "total_reorder_value":
            analysis["total_reorder_value"],

        "total_capital_immobilized":
            analysis[
                "total_capital_immobilized"
            ],

        "potential_30_revenue":
            analysis["potential_30_revenue"],

        "potential_30_profit":
            analysis["potential_30_profit"],
    })


# ============================================================
# NEXUS PRIX
# ============================================================

@app.route(
    "/prix",
    methods=["GET", "POST"]
)
def nexus_prix_alias():
    return nexus_prix()


@app.route(
    "/nexus-prix",
    methods=["GET", "POST"]
)
def nexus_prix():

    form = {

        "purchase_price": "",

        "target_margin": "30",

        "fixed_cost": "",

        "variable_cost_percent": "",

        "current_price": "",

        "market_price": "",

        "quantity": "1",
    }

    result = None

    if request.method == "POST":

        for key in form:

            form[key] = request.form.get(
                key,
                form[key]
            )

        try:

            result = calculate_nexus_price(
                purchase_price=
                    form["purchase_price"],

                target_margin=
                    form["target_margin"],

                fixed_cost=
                    form["fixed_cost"],

                variable_cost_percent=
                    form[
                        "variable_cost_percent"
                    ],

                current_price=
                    form["current_price"],

                market_price=
                    form["market_price"],

                quantity=
                    form["quantity"],
            )

            result[
                "recommendation"
            ] = build_nexus_price_recommendation(
                result
            )

        except ValueError as error:

            flash(
                str(error),
                "error"
            )

    return render_template(
        "nexus_prix.html",
        form=form,
        result=result,
    )


@app.route(
    "/api/nexus-prix",
    methods=["POST"]
)
def api_nexus_prix():

    data = (
        request.get_json(
            silent=True
        )
        or
        request.form
    )

    try:

        result = calculate_nexus_price(

            purchase_price=
                data.get(
                    "purchase_price",
                    0
                ),

            target_margin=
                data.get(
                    "target_margin",
                    30
                ),

            fixed_cost=
                data.get(
                    "fixed_cost",
                    0
                ),

            variable_cost_percent=
                data.get(
                    "variable_cost_percent",
                    0
                ),

            current_price=
                data.get(
                    "current_price",
                    0
                ),

            market_price=
                data.get(
                    "market_price",
                    0
                ),

            quantity=
                data.get(
                    "quantity",
                    1
                ),
        )

        result[
            "recommendation"
        ] = build_nexus_price_recommendation(
            result
        )

        return jsonify({
            "success": True,
            **result
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400


# ============================================================
# NEXUS SIMULATEUR BUSINESS
# ============================================================

@app.route(
    "/nexus-simulateur",
    methods=["GET", "POST"]
)
def nexus_simulateur():

    form_data = {

        "capital": "500000",

        "selling_price": "5000",

        "purchase_cost": "2500",

        "monthly_sales": "100",

        "fixed_costs": "50000",

        "variable_cost_percent": "5",

        "employees": "0",

        "salary_per_employee": "0",

        "growth_rate": "0",

        "duration_months": "12",
    }

    result = None

    if request.method == "POST":

        for key in form_data:

            form_data[key] = request.form.get(
                key,
                form_data[key]
            )

        result = simulate_business(

            capital=form_data[
                "capital"
            ],

            selling_price=form_data[
                "selling_price"
            ],

            purchase_cost=form_data[
                "purchase_cost"
            ],

            monthly_sales=form_data[
                "monthly_sales"
            ],

            fixed_costs=form_data[
                "fixed_costs"
            ],

            variable_cost_percent=
                form_data[
                    "variable_cost_percent"
                ],

            employees=form_data[
                "employees"
            ],

            salary_per_employee=
                form_data[
                    "salary_per_employee"
                ],

            growth_rate=form_data[
                "growth_rate"
            ],

            duration_months=form_data[
                "duration_months"
            ],
        )

        if result.get("success"):

            result[
                "business_report"
            ] = build_business_report(
                result
            )

    return render_template(
        "nexus_simulateur.html",
        result=result,
        form_data=form_data,
    )


@app.route("/nexus-business")
def nexus_business_alias():
    return redirect(
        url_for("nexus_simulateur")
    )


@app.route(
    "/api/nexus-simulateur",
    methods=["POST"]
)
def api_nexus_simulateur():

    data = (
        request.get_json(
            silent=True
        )
        or
        request.form
    )

    result = simulate_business(

        capital=data.get(
            "capital",
            0
        ),

        selling_price=data.get(
            "selling_price",
            0
        ),

        purchase_cost=data.get(
            "purchase_cost",
            0
        ),

        monthly_sales=data.get(
            "monthly_sales",
            0
        ),

        fixed_costs=data.get(
            "fixed_costs",
            0
        ),

        variable_cost_percent=
            data.get(
                "variable_cost_percent",
                0
            ),

        employees=data.get(
            "employees",
            0
        ),

        salary_per_employee=
            data.get(
                "salary_per_employee",
                0
            ),

        growth_rate=data.get(
            "growth_rate",
            0
        ),

        duration_months=data.get(
            "duration_months",
            12
        ),
    )

    if not result.get("success"):

        return jsonify(
            result
        ), 400

    result[
        "business_report"
    ] = build_business_report(
        result
    )

    return jsonify(result)


# ============================================================
# ============================================================
# NEXUS NOTATION
# ============================================================
# ============================================================

def get_rating_statistics(connection):

    total = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            """
        )
    )

    average = safe_float(
        scalar(
            connection,
            """
            SELECT COALESCE(
                AVG(
                    CAST(rating AS REAL)
                ),
                0
            )

            FROM ratings
            """
        )
    )

    rating_5 = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            WHERE rating = 5
            """
        )
    )

    rating_4 = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            WHERE rating = 4
            """
        )
    )

    rating_3 = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            WHERE rating = 3
            """
        )
    )

    rating_2 = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            WHERE rating = 2
            """
        )
    )

    rating_1 = safe_int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM ratings
            WHERE rating = 1
            """
        )
    )

    return {

        "total":
            total,

        "average":
            round(
                average,
                1
            ),

        "rating_5":
            rating_5,

        "rating_4":
            rating_4,

        "rating_3":
            rating_3,

        "rating_2":
            rating_2,

        "rating_1":
            rating_1,
    }


@app.route(
    "/notation",
    methods=["GET", "POST"]
)
def notation():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return redirect(
            url_for(
                "login",
                next=url_for("notation")
            )
        )

    connection = get_db_connection()

    try:

        existing_rating = one(
            connection,
            """
            SELECT *
            FROM ratings
            WHERE user_id = ?
            """,
            (user_id,)
        )

        if request.method == "POST":

            rating = safe_int(
                request.form.get(
                    "rating"
                )
            )

            comment = safe_text(
                request.form.get(
                    "comment"
                )
            )

            if rating < 1 or rating > 5:

                flash(
                    "Veuillez sélectionner "
                    "une note entre 1 et 5 étoiles.",
                    "error"
                )

                return redirect(
                    url_for("notation")
                )

            now = now_datetime()

            if existing_rating:

                connection.execute(
                    """
                    UPDATE ratings

                    SET
                        rating = ?,
                        comment = ?,
                        updated_at = ?

                    WHERE user_id = ?
                    """,
                    (
                        rating,
                        comment,
                        now,
                        user_id
                    )
                )

                message = (
                    "Votre avis a été mis à jour "
                    "avec succès."
                )

            else:

                connection.execute(
                    """
                    INSERT INTO ratings
                    (
                        user_id,
                        rating,
                        comment,
                        created_at,
                        updated_at
                    )

                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        rating,
                        comment,
                        now,
                        now
                    )
                )

                message = (
                    "Merci pour votre évaluation "
                    "de Nexus Gestion !"
                )

            connection.commit()

            flash(
                message,
                "success"
            )

            return redirect(
                url_for("notation")
            )

        statistics = get_rating_statistics(
            connection
        )

        recent_reviews = many(
            connection,
            """
            SELECT
                r.id,
                r.rating,
                r.comment,
                r.created_at,
                r.updated_at,
                u.full_name

            FROM ratings r

            LEFT JOIN users u
                ON u.id = r.user_id

            WHERE
                r.comment IS NOT NULL
                AND TRIM(r.comment) != ''

            ORDER BY r.id DESC

            LIMIT 20
            """
        )

        return render_template(
            "notation.html",
            rating=existing_rating,
            statistics=statistics,
            recent_reviews=recent_reviews
        )

    finally:
        connection.close()


@app.route(
    "/notation/delete",
    methods=["POST"]
)
def delete_my_rating():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return redirect(
            url_for("login")
        )

    connection = get_db_connection()

    try:

        connection.execute(
            """
            DELETE FROM ratings
            WHERE user_id = ?
            """,
            (user_id,)
        )

        connection.commit()

        flash(
            "Votre évaluation a été supprimée.",
            "success"
        )

    finally:
        connection.close()

    return redirect(
        url_for("notation")
    )


@app.route(
    "/notation/admin"
)
def notation_admin():

    denied = admin_required()

    if denied:
        return denied

    connection = get_db_connection()

    try:

        statistics = get_rating_statistics(
            connection
        )

        reviews = many(
            connection,
            """
            SELECT
                r.id,
                r.rating,
                r.comment,
                r.created_at,
                r.updated_at,
                u.username,
                u.full_name

            FROM ratings r

            LEFT JOIN users u
                ON u.id = r.user_id

            ORDER BY r.id DESC
            """
        )

        return render_template(
            "notation_admin.html",
            statistics=statistics,
            reviews=reviews
        )

    finally:
        connection.close()


@app.route(
    "/notation/admin/delete/<int:rating_id>",
    methods=["POST"]
)
def admin_delete_rating(
    rating_id
):

    denied = admin_required()

    if denied:
        return denied

    connection = get_db_connection()

    try:

        rating_row = one(
            connection,
            """
            SELECT id
            FROM ratings
            WHERE id = ?
            """,
            (rating_id,)
        )

        if not rating_row:

            flash(
                "Avis introuvable.",
                "error"
            )

            return redirect(
                url_for("notation_admin")
            )

        connection.execute(
            """
            DELETE FROM ratings
            WHERE id = ?
            """,
            (rating_id,)
        )

        connection.commit()

        flash(
            "Avis supprimé.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur lors de la suppression : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("notation_admin")
    )


@app.route(
    "/api/notation"
)
def api_notation():

    connection = get_db_connection()

    try:

        statistics = get_rating_statistics(
            connection
        )

        return jsonify({

            "success":
                True,

            "application":
                "Nexus Gestion",

            "statistics":
                statistics,
        })

    finally:
        connection.close()


@app.route(
    "/api/notation/reviews"
)
def api_notation_reviews():

    connection = get_db_connection()

    try:

        reviews = many(
            connection,
            """
            SELECT
                r.rating,
                r.comment,
                r.created_at,
                u.full_name

            FROM ratings r

            LEFT JOIN users u
                ON u.id = r.user_id

            WHERE
                r.comment IS NOT NULL
                AND TRIM(r.comment) != ''

            ORDER BY r.id DESC

            LIMIT 20
            """
        )

        return jsonify({

            "success":
                True,

            "reviews": [

                {
                    "rating":
                        safe_int(
                            row["rating"]
                        ),

                    "comment":
                        safe_text(
                            row["comment"]
                        ),

                    "date":
                        safe_text(
                            row["created_at"]
                        ),

                    "user":
                        safe_text(
                            row["full_name"],
                            "Utilisateur"
                        ),
                }

                for row in reviews
            ]
        })

    finally:
        connection.close()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health_check():

    connection = get_db_connection()

    try:

        return jsonify({

            "status":
                "OK",

            "application":
                "Nexus Gestion",

            "database":
                "OK",

            "products":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM products"
                    )
                ),

            "sales":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM sales"
                    )
                ),

            "purchases":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM purchases"
                    )
                ),

            "customers":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM customers"
                    )
                ),

            "invoices":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM invoices"
                    )
                ),

            "ratings":
                safe_int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM ratings"
                    )
                ),
        })

    finally:
        connection.close()


# ============================================================
# AUTHENTIFICATION
# ============================================================

PUBLIC_ENDPOINTS = {

    "login",

    "logout",

    "register",

    "setup_admin",

    "health_check",

    "static",

    "page_not_found",

}


@app.before_request
def authentication_guard():

    endpoint = request.endpoint

    if (
        endpoint in PUBLIC_ENDPOINTS
        or
        endpoint is None
    ):

        return None

    connection = get_db_connection()

    try:

        total_users = count_users(
            connection
        )

        user = current_user(
            connection
        )

    finally:
        connection.close()

    if total_users == 0:

        return redirect(
            url_for("setup_admin")
        )

    if user is None:

        return redirect(
            url_for(
                "login",
                next=request.path
            )
        )

    if not bool(
        user["active"]
    ):

        logout_user()

        flash(
            "Votre compte a été désactivé."
        )

        return redirect(
            url_for("login")
        )

    return None


@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if is_logged_in():

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        username = normalize_username(
            request.form.get(
                "username",
                ""
            )
        )

        password = request.form.get(
            "password",
            ""
        )

        next_page = (
            request.form.get("next")
            or
            request.args.get("next")
        )

        if not username or not password:

            flash(
                "Veuillez remplir tous les champs."
            )

            return redirect(
                url_for(
                    "login",
                    next=next_page or ""
                )
            )

        connection = get_db_connection()

        try:

            user = get_user_by_username(
                connection,
                username
            )

            if (
                user is None
                or
                not verify_password(
                    password,
                    user["password_hash"]
                )
            ):

                flash(
                    "Nom d'utilisateur "
                    "ou mot de passe incorrect."
                )

                return redirect(
                    url_for(
                        "login",
                        next=next_page or ""
                    )
                )

            if not bool(
                user["active"]
            ):

                flash(
                    "Ce compte a été désactivé."
                )

                return redirect(
                    url_for(
                        "login",
                        next=next_page or ""
                    )
                )

            connection.execute(
                """
                UPDATE users
                SET last_login = ?
                WHERE id = ?
                """,
                (
                    now_datetime(),
                    user["id"]
                )
            )

            connection.commit()

        finally:
            connection.close()

        login_user(user)

        if (
            next_page
            and
            next_page.startswith("/")
            and
            not next_page.startswith("//")
        ):

            return redirect(
                next_page
            )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )


@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if is_logged_in():

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        full_name = (
            request.form.get(
                "full_name",
                ""
            ).strip()
        )

        username = (
            request.form.get(
                "username",
                ""
            ).strip().lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        password_confirm = (
            request.form.get(
                "password_confirm",
                ""
            )
        )

        if not full_name:

            flash(
                "Le nom complet est obligatoire.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if len(username) < 3:

            flash(
                "Le nom d'utilisateur doit "
                "contenir au moins 3 caractères.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if len(password) < 8:

            flash(
                "Le mot de passe doit "
                "contenir au moins 8 caractères.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if password != password_confirm:

            flash(
                "Les mots de passe ne correspondent pas.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        connection = get_db_connection()

        try:

            if get_user_by_username(
                connection,
                username
            ):

                flash(
                    "Ce nom d'utilisateur existe déjà.",
                    "error"
                )

                return redirect(
                    url_for("register")
                )

            connection.execute(
                """
                INSERT INTO users
                (
                    username,
                    password_hash,
                    full_name,
                    role,
                    active,
                    created_at
                )

                VALUES (?, ?, ?, 'employee', 1, ?)
                """,
                (
                    username,
                    hash_password(password),
                    full_name,
                    now_datetime()
                )
            )

            connection.commit()

        except DB_INTEGRITY_ERROR:

            connection.rollback()

            flash(
                "Ce nom d'utilisateur existe déjà.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        except DB_ERROR as error:

            connection.rollback()

            flash(
                f"Impossible de créer le compte : {error}",
                "error"
            )

            return redirect(
                url_for("register")
            )

        finally:
            connection.close()

        flash(
            "Compte créé avec succès. "
            "Vous pouvez maintenant vous connecter.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


@app.route("/logout")
def logout():

    logout_user()

    flash(
        "Vous avez été déconnecté."
    )

    return redirect(
        url_for("login")
    )


@app.route(
    "/setup-admin",
    methods=["GET", "POST"]
)
def setup_admin():

    connection = get_db_connection()

    try:

        total_users = count_users(
            connection
        )

    finally:
        connection.close()

    if total_users > 0:

        return redirect(
            url_for(
                "dashboard"
                if is_logged_in()
                else "login"
            )
        )

    if request.method == "POST":

        full_name = (
            request.form.get(
                "full_name",
                ""
            ).strip()
        )

        username = normalize_username(
            request.form.get(
                "username",
                ""
            )
        )

        password = request.form.get(
            "password",
            ""
        )

        password_confirm = (
            request.form.get(
                "password_confirm",
                ""
            )
        )

        if not full_name:

            flash(
                "Le nom complet est obligatoire."
            )

            return redirect(
                url_for("setup_admin")
            )

        if len(username) < 3:

            flash(
                "Le nom d'utilisateur doit "
                "contenir au moins 3 caractères."
            )

            return redirect(
                url_for("setup_admin")
            )

        if len(password) < 8:

            flash(
                "Le mot de passe doit "
                "contenir au moins 8 caractères."
            )

            return redirect(
                url_for("setup_admin")
            )

        if password != password_confirm:

            flash(
                "Les mots de passe ne correspondent pas."
            )

            return redirect(
                url_for("setup_admin")
            )

        connection = get_db_connection()

        try:

            if count_users(
                connection
            ) > 0:

                return redirect(
                    url_for("login")
                )

            connection.execute(
                """
                INSERT INTO users
                (
                    username,
                    password_hash,
                    full_name,
                    role,
                    active,
                    created_at
                )

                VALUES (?, ?, ?, 'admin', 1, ?)
                """,
                (
                    username,
                    hash_password(password),
                    full_name,
                    now_datetime()
                )
            )

            connection.commit()

        except DB_INTEGRITY_ERROR:

            connection.rollback()

            flash(
                "Ce nom d'utilisateur existe déjà."
            )

            return redirect(
                url_for("setup_admin")
            )

        finally:
            connection.close()

        flash(
            "Administrateur créé avec succès. "
            "Connectez-vous."
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "setup_admin.html"
    )


@app.route("/users")
def users():

    denied = admin_required()

    if denied:
        return denied

    connection = get_db_connection()

    try:

        users_list = connection.execute(
            """
            SELECT
                id,
                username,
                full_name,
                role,
                active,
                created_at,
                last_login

            FROM users

            ORDER BY
                CASE
                    WHEN role = 'admin'
                    THEN 0
                    ELSE 1
                END,

                full_name COLLATE NOCASE,

                username COLLATE NOCASE
            """
        ).fetchall()

    finally:
        connection.close()

    return render_template(
        "users.html",
        users=users_list
    )


@app.route(
    "/users/create",
    methods=["GET", "POST"]
)
def create_user():

    denied = admin_required()

    if denied:
        return denied

    if request.method == "POST":

        full_name = safe_text(
            request.form.get(
                "full_name"
            )
        )

        username = normalize_username(
            request.form.get(
                "username",
                ""
            )
        )

        password = request.form.get(
            "password",
            ""
        )

        password_confirm = request.form.get(
            "password_confirm",
            ""
        )

        role = safe_text(
            request.form.get(
                "role",
                "employee"
            )
        ).lower()

        if not full_name:

            flash(
                "Le nom complet est obligatoire.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        if (
            len(username) < 3
            or
            len(username) > 50
        ):

            flash(
                "Le nom d'utilisateur doit "
                "contenir entre 3 et 50 caractères.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        if not username.replace(
            "_",
            ""
        ).replace(
            "-",
            ""
        ).isalnum():

            flash(
                "Le nom d'utilisateur ne peut "
                "contenir que des lettres, chiffres, "
                "_ ou -.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        if len(password) < 8:

            flash(
                "Le mot de passe doit contenir "
                "au moins 8 caractères.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        if password != password_confirm:

            flash(
                "Les mots de passe ne correspondent pas.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        if role not in (
            "admin",
            "employee"
        ):

            role = "employee"

        connection = get_db_connection()

        try:

            if get_user_by_username(
                connection,
                username
            ):

                flash(
                    "Ce nom d'utilisateur existe déjà.",
                    "error"
                )

                return redirect(
                    url_for("create_user")
                )

            connection.execute(
                """
                INSERT INTO users
                (
                    username,
                    password_hash,
                    full_name,
                    role,
                    active,
                    created_at
                )

                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    username,
                    hash_password(password),
                    full_name,
                    role,
                    now_datetime()
                )
            )

            connection.commit()

        except DB_INTEGRITY_ERROR:

            connection.rollback()

            flash(
                "Ce nom d'utilisateur existe déjà.",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        except DB_ERROR as error:

            connection.rollback()

            flash(
                f"Erreur lors de la création du compte : {error}",
                "error"
            )

            return redirect(
                url_for("create_user")
            )

        finally:
            connection.close()

        flash(
            f"Le compte « {full_name} » a été créé avec succès.",
            "success"
        )

        return redirect(
            url_for("users")
        )

    return render_template(
        "create_user.html"
    )


@app.route(
    "/users/<int:user_id>/toggle",
    methods=["POST"]
)
def toggle_user(user_id):

    denied = admin_required()

    if denied:
        return denied

    if session.get(
        "user_id"
    ) == user_id:

        flash(
            "Vous ne pouvez pas désactiver "
            "votre propre compte.",
            "error"
        )

        return redirect(
            url_for("users")
        )

    connection = get_db_connection()

    try:

        user = get_user_by_id(
            connection,
            user_id
        )

        if user is None:

            flash(
                "Utilisateur introuvable.",
                "error"
            )

            return redirect(
                url_for("users")
            )

        if (
            user["role"] == "admin"
            and bool(user["active"])
            and count_admins(
                connection
            ) <= 1
        ):

            flash(
                "Impossible de désactiver "
                "le dernier administrateur actif.",
                "error"
            )

            return redirect(
                url_for("users")
            )

        new_status = (
            0
            if bool(
                user["active"]
            )
            else 1
        )

        connection.execute(
            """
            UPDATE users
            SET active = ?
            WHERE id = ?
            """,
            (
                new_status,
                user_id
            )
        )

        connection.commit()

        flash(
            f"Le compte « {user['full_name']} » "
            f"est maintenant "
            f"{'actif' if new_status else 'désactivé'}.",
            "success"
        )

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur : {error}",
            "error"
        )

    finally:
        connection.close()

    return redirect(
        url_for("users")
    )


@app.route(
    "/users/<int:user_id>/delete",
    methods=["POST"]
)
def delete_user(user_id):

    denied = admin_required()

    if denied:
        return denied

    if session.get(
        "user_id"
    ) == user_id:

        flash(
            "Vous ne pouvez pas supprimer "
            "votre propre compte.",
            "error"
        )

        return redirect(
            url_for("users")
        )

    connection = get_db_connection()

    try:

        user = get_user_by_id(
            connection,
            user_id
        )

        if user is None:

            flash(
                "Utilisateur introuvable.",
                "error"
            )

            return redirect(
                url_for("users")
            )

        if (
            user["role"] == "admin"
            and bool(user["active"])
            and count_admins(
                connection
            ) <= 1
        ):

            flash(
                "Impossible de supprimer "
                "le dernier administrateur actif.",
                "error"
            )

            return redirect(
                url_for("users")
            )

        connection.execute(
            """
            DELETE FROM users
            WHERE id = ?
            """,
            (user_id,)
        )

        connection.commit()

    except DB_ERROR as error:

        connection.rollback()

        flash(
            f"Erreur lors de la suppression : {error}",
            "error"
        )

    finally:
        connection.close()

    flash(
        "Utilisateur supprimé.",
        "success"
    )

    return redirect(
        url_for("users")
    )


# ============================================================
# ERROR HANDLER
# ============================================================


# ============================================================
# NEXUS GRAPHIQUE
# ============================================================

def _graph_parse_date(value):
    """Transforme une valeur date SQL en date Python."""
    if value is None:
        return None

    if hasattr(value, "date"):
        try:
            return value.date() if hasattr(value, "date") else value
        except Exception:
            pass

    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    )

    for fmt in formats:
        try:
            return datetime.strptime(text[:26], fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _graph_month_key(value):
    parsed = _graph_parse_date(value)
    return parsed.strftime("%Y-%m") if parsed else None


def _graph_last_months(count=12):
    """Retourne les N derniers mois calendaires, du plus ancien au plus récent."""
    today_date = datetime.now().date()
    year = today_date.year
    month = today_date.month

    result = []

    for offset in range(count - 1, -1, -1):
        y = year
        m = month - offset

        while m <= 0:
            y -= 1
            m += 12

        result.append(f"{y:04d}-{m:02d}")

    return result


def _graph_month_label(month_key):
    labels = {
        "01": "Jan",
        "02": "Fév",
        "03": "Mar",
        "04": "Avr",
        "05": "Mai",
        "06": "Juin",
        "07": "Juil",
        "08": "Août",
        "09": "Sep",
        "10": "Oct",
        "11": "Nov",
        "12": "Déc",
    }
    month = month_key[5:7]
    return f"{labels.get(month, month)} {month_key[:4]}"


def _graph_aggregate(data, months, amount_builder):
    totals = {month: 0.0 for month in months}

    for row in data:
        month = _graph_month_key(row["date"])
        if month in totals:
            totals[month] += safe_float(amount_builder(row))

    return [round(totals[month], 2) for month in months]


GRAPH_NEXUS_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexus Graphique - Nexus Gestion</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #f5f7fb;
            --card: #ffffff;
            --text: #172033;
            --muted: #667085;
            --border: #e5e7eb;
            --primary: #2563eb;
            --primary-soft: #eff6ff;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: Inter, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
        }
        .topbar {
            background: #0f172a;
            color: white;
            padding: 18px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        .brand { font-weight: 800; font-size: 21px; }
        .subtitle { opacity: .72; font-size: 13px; margin-top: 3px; }
        .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
        .toolbar {
            display: flex;
            justify-content: space-between;
            gap: 14px;
            align-items: center;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }
        .periods { display: flex; gap: 8px; flex-wrap: wrap; }
        .periods a, .back {
            text-decoration: none;
            border: 1px solid var(--border);
            background: white;
            color: var(--text);
            padding: 9px 14px;
            border-radius: 9px;
            font-weight: 700;
            font-size: 14px;
        }
        .periods a.active { background: var(--primary); color: white; border-color: var(--primary); }
        .back { background: #0f172a; color: white; border-color: #0f172a; }
        .grid-kpi {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 18px;
        }
        .kpi {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 17px;
            box-shadow: 0 2px 10px rgba(15,23,42,.04);
        }
        .kpi-label { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
        .kpi-value { font-size: 25px; font-weight: 800; }
        .chart-grid {
            display: grid;
            grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
            gap: 18px;
            margin-bottom: 18px;
        }
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 18px;
            box-shadow: 0 2px 10px rgba(15,23,42,.04);
        }
        .card h2 { margin: 0 0 5px; font-size: 18px; }
        .card p { margin: 0 0 14px; color: var(--muted); font-size: 13px; }
        .chart-wrap { position: relative; height: 380px; }
        .mini-wrap { position: relative; height: 300px; }
        .metrics {
            display: grid;
            grid-template-columns: repeat(3, minmax(0,1fr));
            gap: 12px;
        }
        .metric {
            background: #f8fafc;
            border: 1px solid var(--border);
            padding: 13px;
            border-radius: 10px;
        }
        .metric span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
        .metric strong { font-size: 16px; }
        .error {
            background: #fff7ed;
            color: #9a3412;
            border: 1px solid #fed7aa;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 18px;
        }
        @media (max-width: 1050px) {
            .grid-kpi { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .chart-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 650px) {
            .container { padding: 14px; }
            .grid-kpi, .metrics { grid-template-columns: 1fr; }
            .chart-wrap { height: 300px; }
        }
    </style>
</head>
<body>
<header class="topbar">
    <div>
        <div class="brand">NEXUS GESTION — NEXUS GRAPHIQUE</div>
        <div class="subtitle">Analyse visuelle des ventes, coûts, achats, dépenses et bénéfices</div>
    </div>
    <a class="back" href="{{ url_for('dashboard') }}">← Tableau de bord</a>
</header>

<main class="container">
    {% if graphique_error %}
        <div class="error">Erreur de génération du graphique : {{ graphique_error }}</div>
    {% endif %}

    <div class="toolbar">
        <div>
            <strong>Période analysée : {{ months_count }} mois</strong>
        </div>
        <div class="periods">
            <a href="{{ url_for('nexus_graphique', periode=6) }}" class="{% if months_count == 6 %}active{% endif %}">6 mois</a>
            <a href="{{ url_for('nexus_graphique', periode=12) }}" class="{% if months_count == 12 %}active{% endif %}">12 mois</a>
            <a href="{{ url_for('nexus_graphique', periode=24) }}" class="{% if months_count == 24 %}active{% endif %}">24 mois</a>
        </div>
    </div>

    <section class="grid-kpi">
        <div class="kpi"><div class="kpi-label">Chiffre d'affaires</div><div class="kpi-value">{{ total_revenue|money }} FCFA</div></div>
        <div class="kpi"><div class="kpi-label">Coût des marchandises vendues</div><div class="kpi-value">{{ total_cogs|money }} FCFA</div></div>
        <div class="kpi"><div class="kpi-label">Dépenses</div><div class="kpi-value">{{ total_expenses|money }} FCFA</div></div>
        <div class="kpi"><div class="kpi-label">Bénéfice net</div><div class="kpi-value">{{ total_net_profit|money }} FCFA</div></div>
    </section>

    <section class="chart-grid">
        <div class="card">
            <h2>Évolution financière</h2>
            <p>Comparaison mensuelle du chiffre d'affaires, des coûts, des dépenses et du bénéfice net.</p>
            <div class="chart-wrap"><canvas id="financialChart"></canvas></div>
        </div>
        <div class="card">
            <h2>Répartition des flux</h2>
            <p>Total cumulé sur la période sélectionnée.</p>
            <div class="mini-wrap"><canvas id="flowChart"></canvas></div>
        </div>
    </section>

    <section class="card">
        <h2>Indicateurs Nexus Graphique</h2>
        <p>Les indicateurs sont calculés à partir des données enregistrées dans Nexus Gestion.</p>
        <div class="metrics">
            <div class="metric"><span>Marge nette</span><strong>{{ margin }} %</strong></div>
            <div class="metric"><span>Achats cumulés</span><strong>{{ total_purchases|money }} FCFA</strong></div>
            <div class="metric"><span>Bénéfice brut</span><strong>{{ total_gross_profit|money }} FCFA</strong></div>
            <div class="metric"><span>Nombre de mois</span><strong>{{ months_count }}</strong></div>
            <div class="metric"><span>CA moyen mensuel</span><strong>{{ (total_revenue / months_count if months_count else 0)|money }} FCFA</strong></div>
            <div class="metric"><span>Bénéfice net moyen mensuel</span><strong>{{ (total_net_profit / months_count if months_count else 0)|money }} FCFA</strong></div>
        </div>
    </section>
</main>

<script>
const labels = {{ month_labels|tojson }};
const revenue = {{ revenue|tojson }};
const cogs = {{ cogs|tojson }};
const purchases = {{ purchases|tojson }};
const expenses = {{ expenses|tojson }};
const grossProfit = {{ gross_profit|tojson }};
const netProfit = {{ net_profit|tojson }};

function formatFCFA(value) {
    return new Intl.NumberFormat('fr-FR').format(value) + ' FCFA';
}

new Chart(document.getElementById('financialChart'), {
    type: 'line',
    data: {
        labels,
        datasets: [
            { label: 'Chiffre d’affaires', data: revenue, tension: 0.25, borderWidth: 2, fill: false },
            { label: 'Coût des ventes', data: cogs, tension: 0.25, borderWidth: 2, fill: false },
            { label: 'Dépenses', data: expenses, tension: 0.25, borderWidth: 2, fill: false },
            { label: 'Bénéfice net', data: netProfit, tension: 0.25, borderWidth: 3, fill: false }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            tooltip: { callbacks: { label: (ctx) => ctx.dataset.label + ': ' + formatFCFA(ctx.raw) } },
            legend: { position: 'bottom' }
        },
        scales: { y: { ticks: { callback: (value) => formatFCFA(value) } } }
    }
});

new Chart(document.getElementById('flowChart'), {
    type: 'doughnut',
    data: {
        labels: ['CA', 'Coût des ventes', 'Achats', 'Dépenses', 'Bénéfice net'],
        datasets: [{
            data: [
                {{ total_revenue }},
                {{ total_cogs }},
                {{ total_purchases }},
                {{ total_expenses }},
                {{ total_net_profit|abs }}
            ],
            borderWidth: 1
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: 'bottom' },
            tooltip: { callbacks: { label: (ctx) => ctx.label + ': ' + formatFCFA(ctx.raw) } }
        }
    }
});

// Expose les données pour d'éventuels modules frontend Nexus.
window.NexusGraphique = {
    labels, revenue, cogs, purchases, expenses, grossProfit, netProfit
};
</script>
</body>
</html>
"""


def _graph_build_data(connection, months):
    sales_rows = many(
        connection,
        """
        SELECT
            s.quantity,
            s.price,
            COALESCE(s.purchase_price_at_sale, p.purchase_price, 0)
                AS purchase_price_at_sale,
            s.date
        FROM sales s
        LEFT JOIN products p ON p.id = s.product_id
        ORDER BY s.date ASC
        """
    )
    purchases_rows = many(
        connection,
        "SELECT quantity, price, date FROM purchases ORDER BY date ASC"
    )
    expenses_rows = many(
        connection,
        "SELECT amount, date FROM expenses ORDER BY date ASC"
    )

    revenue = _graph_aggregate(
        sales_rows, months,
        lambda row: safe_float(row["quantity"]) * safe_float(row["price"]),
    )
    cogs = _graph_aggregate(
        sales_rows, months,
        lambda row: safe_float(row["quantity"]) * safe_float(row["purchase_price_at_sale"]),
    )
    purchases = _graph_aggregate(
        purchases_rows, months,
        lambda row: safe_float(row["quantity"]) * safe_float(row["price"]),
    )
    expenses = _graph_aggregate(
        expenses_rows, months,
        lambda row: safe_float(row["amount"]),
    )
    gross_profit = [round(revenue[i] - cogs[i], 2) for i in range(len(months))]
    net_profit = [round(gross_profit[i] - expenses[i], 2) for i in range(len(months))]

    total_revenue = round(sum(revenue), 2)
    total_cogs = round(sum(cogs), 2)
    total_purchases = round(sum(purchases), 2)
    total_expenses = round(sum(expenses), 2)
    total_gross_profit = round(sum(gross_profit), 2)
    total_net_profit = round(sum(net_profit), 2)
    margin = round((total_net_profit / total_revenue) * 100, 2) if total_revenue > 0 else 0.0

    return {
        "revenue": revenue,
        "cogs": cogs,
        "purchases": purchases,
        "expenses": expenses,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "total_purchases": total_purchases,
        "total_expenses": total_expenses,
        "total_gross_profit": total_gross_profit,
        "total_net_profit": total_net_profit,
        "margin": margin,
    }


@app.route("/nexus-graphique")
def nexus_graphique():
    """Page complète de Nexus Graphique, autonome dans app.py."""
    connection = get_db_connection()
    months_count = safe_int(request.args.get("periode"), 12)
    if months_count not in (6, 12, 24):
        months_count = 12

    try:
        months = _graph_last_months(months_count)
        data = _graph_build_data(connection, months)
        return render_template_string(
            GRAPH_NEXUS_TEMPLATE,
            months=months,
            month_labels=[_graph_month_label(m) for m in months],
            months_count=months_count,
            graphique_error=None,
            **data,
        )
    except Exception as error:
        app.logger.exception("Erreur Nexus Graphique")
        return render_template_string(
            GRAPH_NEXUS_TEMPLATE,
            months=[], month_labels=[], months_count=months_count,
            revenue=[], cogs=[], purchases=[], expenses=[], gross_profit=[], net_profit=[],
            total_revenue=0, total_cogs=0, total_purchases=0, total_expenses=0,
            total_gross_profit=0, total_net_profit=0, margin=0,
            graphique_error=str(error),
        )
    finally:
        connection.close()


@app.route("/api/nexus-graphique")
def api_nexus_graphique():
    """Retourne les séries Nexus Graphique au format JSON."""
    connection = get_db_connection()
    try:
        months_count = safe_int(request.args.get("periode"), 12)
        if months_count not in (6, 12, 24):
            months_count = 12
        months = _graph_last_months(months_count)
        data = _graph_build_data(connection, months)
        return jsonify({
            "application": "Nexus Gestion",
            "module": "Nexus Graphique",
            "period": months_count,
            "months": months,
            "labels": [_graph_month_label(m) for m in months],
            **data,
            "totals": {
                "revenue": data["total_revenue"],
                "cogs": data["total_cogs"],
                "purchases": data["total_purchases"],
                "expenses": data["total_expenses"],
                "gross_profit": data["total_gross_profit"],
                "net_profit": data["total_net_profit"],
            },
        })
    except Exception as error:
        app.logger.exception("Erreur API Nexus Graphique")
        return jsonify({
            "application": "Nexus Gestion",
            "module": "Nexus Graphique",
            "error": str(error),
        }), 500
    finally:
        connection.close()


# ============================================================
# NEXUS GRAPHIQUE - INJECTION AUTOMATIQUE DANS L'INTERFACE
# ============================================================
@app.after_request
def inject_nexus_graphique_link(response):
    """Ajoute automatiquement Nexus Graphique aux pages HTML."""
    try:
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return response

        html = response.get_data(as_text=True)
        if "/nexus-graphique" in html:
            return response

        link = """
        <a href="/nexus-graphique" class="nexus-graphique-auto-link"
           aria-label="Ouvrir Nexus Graphique" title="Nexus Graphique">
            <span aria-hidden="true">📊</span>
            <span>Nexus Graphique</span>
        </a>
        """

        style = """
        <style id="nexus-graphique-auto-style">
            .nexus-graphique-auto-link {
                position: fixed;
                left: 18px;
                bottom: 18px;
                z-index: 99999;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 11px 16px;
                border-radius: 12px;
                background: #111827;
                color: #fff !important;
                text-decoration: none !important;
                font-family: Arial, sans-serif;
                font-size: 14px;
                font-weight: 700;
                box-shadow: 0 8px 24px rgba(0,0,0,.22);
            }
            .nexus-graphique-auto-link:hover { transform: translateY(-2px); }
            @media (max-width: 700px) {
                .nexus-graphique-auto-link { left: 10px; right: 10px; justify-content: center; }
            }
        </style>
        """

        script = """
        <script id="nexus-graphique-auto-script">
        (function () {
            function addNexusGraphiqueMenuItem() {
                if (document.querySelector('a[href="/nexus-graphique"]')) return;
                var candidates = Array.from(document.querySelectorAll('a, button'));
                var target = candidates.find(function (el) {
                    var txt = (el.textContent || '').trim().toLowerCase();
                    return txt.includes('nexus notation') ||
                           txt.includes('simulateur business') ||
                           txt.includes('nexus prix') ||
                           txt.includes('nexus intelligence');
                });
                if (target && target.parentElement) {
                    var item = target.cloneNode(true);
                    item.href = '/nexus-graphique';
                    item.removeAttribute('onclick');
                    item.removeAttribute('data-bs-toggle');
                    item.removeAttribute('data-toggle');
                    item.setAttribute('title', 'Nexus Graphique');
                    var text = item.querySelector('span:last-child');
                    if (text) text.textContent = 'Nexus Graphique';
                    else item.textContent = '📊 Nexus Graphique';
                    var icon = item.querySelector('i, svg');
                    if (icon) icon.outerHTML = '<span aria-hidden="true">📊</span>';
                    target.parentElement.insertBefore(item, target.nextSibling);
                }
            }
            if (document.readyState === 'loading')
                document.addEventListener('DOMContentLoaded', addNexusGraphiqueMenuItem);
            else addNexusGraphiqueMenuItem();
        })();
        </script>
        """

        low = html.lower()
        pos = low.find('</head>')
        if pos >= 0:
            html = html[:pos] + style + html[pos:]
        else:
            html = style + html

        low = html.lower()
        pos = low.find('</body>')
        if pos >= 0:
            html = html[:pos] + link + script + html[pos:]
        else:
            html += link + script

        response.set_data(html)
        return response
    except Exception:
        app.logger.exception("Erreur injection Nexus Graphique")
        return response


@app.errorhandler(404)
def page_not_found(error):

    return """
    <!DOCTYPE html>

    <html lang="fr">

    <head>

        <meta charset="UTF-8">

        <title>
            Nexus Gestion - 404
        </title>

        <style>

            body {
                font-family: Arial;
                background: #f4f6f8;
                text-align: center;
                padding: 80px;
            }

            a {
                color: #2563eb;
                font-weight: bold;
                text-decoration: none;
            }

        </style>

    </head>

    <body>

        <h1>404</h1>

        <p>
            Cette page n'existe pas.
        </p>

        <a href="/">
            ← Retour à Nexus Gestion
        </a>

    </body>

    </html>
    """, 404


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print()

    print("=" * 70)

    print(
        "                    NEXUS GESTION"
    )

    print("=" * 70)

    print(
        f"Backend : "
        f"{'PostgreSQL' if USING_POSTGRES else 'SQLite'}"
    )

    print(
        f"Base : "
        f"{DATABASE if not USING_POSTGRES else 'PostgreSQL via DATABASE_URL'}"
    )

    print(
        "Connexion           : "
        "http://127.0.0.1:5000/login"
    )

    print(
        "Premier admin       : "
        "http://127.0.0.1:5000/setup-admin"
    )

    print(
        "Utilisateurs        : "
        "http://127.0.0.1:5000/users"
    )

    print(
        "Dashboard           : "
        "http://127.0.0.1:5000/"
    )

    print(
        "Produits            : "
        "http://127.0.0.1:5000/products"
    )

    print(
        "Ventes              : "
        "http://127.0.0.1:5000/sales"
    )

    print(
        "Achats              : "
        "http://127.0.0.1:5000/purchases"
    )

    print(
        "Dépenses            : "
        "http://127.0.0.1:5000/expenses"
    )

    print(
        "Clients             : "
        "http://127.0.0.1:5000/customers"
    )

    print(
        "Factures            : "
        "http://127.0.0.1:5000/invoices"
    )

    print(
        "Nexus Intelligence  : "
        "http://127.0.0.1:5000/intelligence"
    )

    print(
        "Nexus Prix          : "
        "http://127.0.0.1:5000/nexus-prix"
    )

    print(
        "Simulateur Business : "
        "http://127.0.0.1:5000/nexus-simulateur"
    )

    print(
        "Nexus Notation      : "
        "http://127.0.0.1:5000/notation"
    )

    print(
        "Notation Admin      : "
        "http://127.0.0.1:5000/notation/admin"
    )

    print(
        "API Notation        : "
        "http://127.0.0.1:5000/api/notation"
    )

    print(
        "API Intelligence    : "
        "http://127.0.0.1:5000/api/intelligence"
    )

    print(
        "Test système        : "
        "http://127.0.0.1:5000/health"
    )

    print("=" * 70)

    print()

    app.run(
        host=(
            "0.0.0.0"
            if os.environ.get("RENDER")
            else "127.0.0.1"
        ),

        port=int(
            os.environ.get(
                "PORT",
                "5000"
            )
        ),

        debug=True,
    )

