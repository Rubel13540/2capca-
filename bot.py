import os
import sqlite3
import logging
import html
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0").strip())
except ValueError:
    ADMIN_CHAT_ID = 0

# Payment information - আপাতত তোমার দেওয়া তথ্যই রাখা হয়েছে
BKASH_NUMBER = "01700000000 (Personal)"
NAGAD_NUMBER = "01700000000 (Personal)"
ROCKET_NUMBER = "01700000000 (Personal)"

BINANCE_ID = "123456789"
BYBIT_ID = "12345688"

# 1 USDT = 130 BDT
USDT_RATE_BDT = Decimal("130")

SUPPORT_USERNAME = "@Rubel1356"

DB_FILE = "bot_database.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row

    # SQLite stability
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            amount REAL NOT NULL,
            txid TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            stock TEXT NOT NULL,
            is_sold INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_title TEXT,
            item_delivered TEXT,
            price REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def create_user(user_id: int, username: str, first_name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (
        user_id,
        username or "",
        first_name or "",
    ))

    conn.commit()
    conn.close()


def user_exists(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def is_user_banned(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT is_banned FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()
    conn.close()

    return bool(row["is_banned"]) if row else False


def get_user_balance(user_id: int) -> Decimal:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return Decimal("0")

    return Decimal(str(row["balance"] or 0))


def add_balance(user_id: int, amount: Decimal) -> bool:
    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,)
        )

        if not cur.fetchone():
            conn.close()
            return False

        cur.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (float(amount), user_id)
        )

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_all_user_ids():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users")

    rows = cur.fetchall()
    conn.close()

    return [row["user_id"] for row in rows]


# =========================================================
# DEPOSIT FUNCTIONS
# =========================================================

def create_deposit_record(
    user_id: int,
    method: str,
    amount: Decimal,
    txid: str
) -> int:

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO deposits
        (user_id, method, amount, txid)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        method,
        float(amount),
        txid
    ))

    dep_id = cur.lastrowid

    conn.commit()
    conn.close()

    return dep_id


def get_deposit(dep_id: int):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM deposits WHERE id = ?",
        (dep_id,)
    )

    row = cur.fetchone()

    conn.close()

    return row


def update_deposit_status(dep_id: int, status: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE deposits
        SET status = ?
        WHERE id = ?
        AND status = 'PENDING'
        """,
        (status, dep_id)
    )

    changed = cur.rowcount

    conn.commit()
    conn.close()

    return changed > 0


# =========================================================
# CATEGORY / PRODUCT FUNCTIONS
# =========================================================

def get_categories():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM categories ORDER BY id ASC"
    )

    rows = cur.fetchall()

    conn.close()

    return rows


def add_category(name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO categories (name) VALUES (?)",
        (name,)
    )

    conn.commit()
    conn.close()


def get_products(category_id: int):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM products
        WHERE category_id = ?
        AND is_sold = 0
        ORDER BY id ASC
    """, (category_id,))

    rows = cur.fetchall()

    conn.close()

    return rows


def add_product(
    category_id: int,
    title: str,
    description: str,
    price: Decimal,
    stock: str
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO products
        (category_id, title, description, price, stock)
        VALUES (?, ?, ?, ?, ?)
    """, (
        category_id,
        title,
        description,
        float(price),
        stock
    ))

    conn.commit()
    conn.close()


def get_product_by_id(prod_id: int):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (prod_id,)
    )

    row = cur.fetchone()

    conn.close()

    return row


# =========================================================
# SAFE PURCHASE
# =========================================================

def purchase_product(user_id: int, product_id: int):
    conn = get_db()

    try:
        cur = conn.cursor()

        # Transaction শুরু
        cur.execute("BEGIN IMMEDIATE")

        # User balance
        cur.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,)
        )

        user = cur.fetchone()

        if not user:
            conn.rollback()
            return False, "USER_NOT_FOUND", None

        balance = Decimal(str(user["balance"] or 0))

        # Product
        cur.execute(
            """
            SELECT *
            FROM products
            WHERE id = ?
            AND is_sold = 0
            """,
            (product_id,)
        )

        product = cur.fetchone()

        if not product:
            conn.rollback()
            return False, "SOLD", None

        price = Decimal(str(product["price"]))

        if balance < price:
            conn.rollback()
            return False, "BALANCE", product

        # Balance কমানো
        cur.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE user_id = ?
            AND balance >= ?
            """,
            (
                float(price),
                user_id,
                float(price)
            )
        )

        if cur.rowcount != 1:
            conn.rollback()
            return False, "BALANCE", product

        # Product sold
        cur.execute(
            """
            UPDATE products
            SET is_sold = 1
            WHERE id = ?
            AND is_sold = 0
            """,
            (product_id,)
        )

        if cur.rowcount != 1:
            conn.rollback()
            return False, "SOLD", None

        # Order save
        cur.execute(
            """
            INSERT INTO orders
            (user_id, product_title, item_delivered, price)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                product["title"],
                product["stock"],
                float(price)
            )
        )

        conn.commit()

        return True, "SUCCESS", product

    except Exception:
        conn.rollback()
        logger.exception("Purchase error")
        return False, "ERROR", None

    finally:
        conn.close()


# =========================================================
# STATS
# =========================================================

def get_system_stats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) AS total_users,
            COALESCE(SUM(balance), 0) AS total_balance
        FROM users
    """)

    row = cur.fetchone()

    conn.close()

    return {
        "users": row["total_users"] or 0,
        "balance": row["total_balance"] or 0
    }


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(user_id: int) -> bool:
    return (
        ADMIN_CHAT_ID != 0
        and user_id == ADMIN_CHAT_ID
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu(user_id: int):

    keyboard = [
        [
            InlineKeyboardButton(
                "🛍 Digital Shop",
                callback_data="products"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Deposit",
                callback_data="deposit"
            ),
            InlineKeyboardButton(
                "👤 My Profile",
                callback_data="profile"
            )
        ],
        [
            InlineKeyboardButton(
                "🆘 Support",
                callback_data="help"
            ),
            InlineKeyboardButton(
                "⭐ Refer & Earn",
                callback_data="refer"
            )
        ]
    ]

    if is_admin(user_id):
        keyboard.append([
            InlineKeyboardButton(
                "👑 Admin Panel",
                callback_data="admin_panel"
            )
        ])

    return InlineKeyboardMarkup(keyboard)


def back_home():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "◀️ Back",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# HOME TEXT
# =========================================================

def home_text(first_name: str):

    safe_name = html.escape(first_name or "User")

    return (
        f"Hey <b>{safe_name}</b>! 👋\n\n"
        "Welcome to our <b>Digital Product Store</b>!\n\n"
        "Get instant automated delivery for "
        "subscription accounts, gift cards, licenses "
        "and premium digital products.\n\n"
        "Select an option below to get started:"
    )


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(
        user.id,
        user.username,
        user.first_name
    )

    if is_user_banned(user.id):
        await update.message.reply_text(
            "🚫 Your account is currently restricted."
        )
        return

    if update.message:
        await update.message.reply_text(
            home_text(user.first_name),
            parse_mode="HTML",
            reply_markup=main_menu(user.id)
        )


# =========================================================
# HOME
# =========================================================

async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    user = query.from_user

    await query.edit_message_text(
        home_text(user.first_name),
        parse_mode="HTML",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# SHOP
# =========================================================

async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    categories = get_categories()

    if not categories:

        await query.edit_message_text(
            "🛍 <b>Store is currently empty.</b>\n\n"
            "Please check again later.",
            parse_mode="HTML",
            reply_markup=back_home()
        )

        return

    keyboard = []

    for cat in categories:

        keyboard.append([
            InlineKeyboardButton(
                f"📁 {cat['name']}",
                callback_data=f"cat_{cat['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "◀️ Back to Home",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "🛍 <b>Digital Product Categories</b>\n\n"
        "Select a category:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# CATEGORY
# =========================================================

async def category_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    try:
        cat_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):
        await query.answer(
            "Invalid category.",
            show_alert=True
        )
        return

    products = get_products(cat_id)

    if not products:

        await query.edit_message_text(
            "❌ No products available in this category.",
            reply_markup=back_home()
        )

        return

    keyboard = []

    text = "📦 <b>Available Products</b>\n\n"

    for product in products:

        title = html.escape(product["title"])
        desc = html.escape(product["description"] or "")

        price = Decimal(str(product["price"]))

        text += (
            f"🔹 <b>{title}</b>\n"
            f"💰 Price: <b>${price:.2f} USDT</b>\n"
            f"📝 {desc}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"🛒 Buy {product['title']} "
                f"(${price:.2f})",
                callback_data=f"buy_{product['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "◀️ Back to Categories",
            callback_data="products"
        )
    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# BUY PRODUCT
# =========================================================

async def buy_product_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    try:
        prod_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):

        await query.answer(
            "Invalid product.",
            show_alert=True
        )

        return

    user_id = query.from_user.id

    success, status, product = purchase_product(
        user_id,
        prod_id
    )

    if status == "USER_NOT_FOUND":

        create_user(
            user_id,
            query.from_user.username,
            query.from_user.first_name
        )

        await query.edit_message_text(
            "⚠️ Please press /start once and try again.",
            reply_markup=back_home()
        )

        return

    if status == "SOLD":

        await query.edit_message_text(
            "❌ Sorry! This product has already been sold.",
            reply_markup=back_home()
        )

        return

    if status == "BALANCE":

        product = get_product_by_id(prod_id)

        if not product:
            await query.edit_message_text(
                "❌ Product is no longer available.",
                reply_markup=back_home()
            )
            return

        price = Decimal(str(product["price"]))
        balance = get_user_balance(user_id)

        keyboard = [
            [
                InlineKeyboardButton(
                    "💰 Deposit Funds",
                    callback_data="deposit"
                )
            ],
            [
                InlineKeyboardButton(
                    "◀️ Back",
                    callback_data="products"
                )
            ]
        ]

        await query.edit_message_text(
            f"❌ <b>Insufficient Balance!</b>\n\n"
            f"Product Price: <b>${price:.2f} USDT</b>\n"
            f"Your Balance: <b>${balance:.2f} USDT</b>\n\n"
            "Please deposit funds first.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if not success:

        await query.edit_message_text(
            "⚠️ Purchase could not be completed.\n"
            "Please try again.",
            reply_markup=back_home()
        )

        return

    price = Decimal(str(product["price"]))

    title = html.escape(product["title"])

    stock = product["stock"]

    text = (
        "🎉 <b>Purchase Successful!</b>\n\n"
        f"📦 <b>Item:</b> {title}\n"
        f"💰 <b>Paid:</b> ${price:.2f} USDT\n\n"
        "📬 <b>Your Digital Item:</b>\n"
        f"<code>{html.escape(stock)}</code>\n\n"
        "Thank you for purchasing with us! ❤️"
    )

    await query.edit_message_text(
        text,
 
