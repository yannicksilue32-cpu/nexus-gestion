
import sqlite3

connection = sqlite3.connect("database.db")

# ==========================================
# CLIENTS
# ==========================================

connection.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    address TEXT,
    created_at TEXT NOT NULL
)
""")

# ==========================================
# PRODUITS
# ==========================================

connection.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    purchase_price REAL NOT NULL,
    selling_price REAL NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    stock_alert INTEGER NOT NULL DEFAULT 5
)
""")

# ==========================================
# VENTES
# ==========================================

connection.execute("""
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    date TEXT NOT NULL,
    customer_id INTEGER,
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id)
)
""")

# Ajouter customer_id aux anciennes bases
columns = connection.execute(
    "PRAGMA table_info(sales)"
).fetchall()

column_names = [column[1] for column in columns]

if "customer_id" not in column_names:
    connection.execute("""
        ALTER TABLE sales
        ADD COLUMN customer_id INTEGER
    """)

# ==========================================
# ACHATS
# ==========================================

connection.execute("""
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    date TEXT NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id)
)
""")

# ==========================================
# DEPENSES
# ==========================================

connection.execute("""
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    date TEXT NOT NULL
)
""")

# =========================
# TABLE DES FACTURES
# =========================

connection.execute("""
CREATE TABLE IF NOT EXISTS invoices (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    invoice_number TEXT NOT NULL UNIQUE,

    customer_id INTEGER NOT NULL,

    total REAL NOT NULL DEFAULT 0,

    status TEXT NOT NULL DEFAULT 'Payée',

    date TEXT NOT NULL,

    FOREIGN KEY (customer_id)
        REFERENCES customers(id)
)
""")


# =========================
# TABLE DES LIGNES DE FACTURE
# =========================

connection.execute("""
CREATE TABLE IF NOT EXISTS invoice_items (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    invoice_id INTEGER NOT NULL,

    product_id INTEGER NOT NULL,

    quantity INTEGER NOT NULL,

    price REAL NOT NULL,

    subtotal REAL NOT NULL,

    FOREIGN KEY (invoice_id)
        REFERENCES invoices(id),

    FOREIGN KEY (product_id)
        REFERENCES products(id)
)
""")


connection.commit()
connection.close()

print("Base de données Nexus Gestion prête !")

