import os
import asyncio
import sqlite3
import logging
from decimal import Decimal, InvalidOperation

import aiohttp
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Updated SMM API Key & URL
SMM_API_KEY = os.getenv(
    "SMM_API_KEY",
    "293e167bf0017e7e8b28a7261338b6b6",
).strip()

SMM_API_URL = "https://smmpakpanel.com/api/v2"

ADMIN_ID = 5293614793

BKASH_NUMBER = "01911198221"
NAGAD_NUMBER = "01911198221"
WHATSAPP_URL = "https://wa.me/message/ZFPUNOUHWSWRI1"

USD_TO_BDT = Decimal("120")
PROFIT_MULTIPLIER = Decimal("1.30")

# Set to 0 to disable. Change this number if you want a new-user bonus.
WELCOME_BONUS = Decimal("0.00")  # Default: no welcome bonus

def get_welcome_bonus():
    try:
        raw = get_setting("welcome_bonus", str(WELCOME_BONUS))
        amount = Decimal(str(raw))
        return amount if amount >= 0 else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

DB_FILE = "bot.db"

# =========================================================
# LOGGING
# =========================================================

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
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id TEXT,
            service_name TEXT,
            link TEXT,
            quantity INTEGER,
            charge REAL,
            provider_order_id TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recharge_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT,
            amount REAL NOT NULL,
            transaction_id TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Safe migrations for databases created by older versions.
    if not column_exists(conn, "users", "welcome_bonus_given"):
        cur.execute(
            "ALTER TABLE users ADD COLUMN welcome_bonus_given INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()
    conn.close()


def ensure_user(tg_user):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, welcome_bonus_given FROM users WHERE user_id = ?",
        (tg_user.id,),
    )
    row = cur.fetchone()

    if row is None:
        bonus = get_welcome_bonus()
        cur.execute(
            """
            INSERT INTO users (
                user_id, username, first_name, balance, welcome_bonus_given
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                tg_user.id,
                tg_user.username or "",
                tg_user.first_name or "",
                float(bonus),
                1,
            ),
        )
        is_new = True
    else:
        cur.execute(
            """
            UPDATE users
            SET username = ?, first_name = ?
            WHERE user_id = ?
            """,
            (
                tg_user.username or "",
                tg_user.first_name or "",
                tg_user.id,
            ),
        )
        is_new = False

    conn.commit()
    conn.close()
    return is_new


def get_setting(key, default=""):
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def maintenance_enabled():
    return get_setting("maintenance", "0") == "1"


def get_balance(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()

    if not row:
        return Decimal("0")
    return Decimal(str(row["balance"]))


def change_balance(user_id, amount):
    amount = Decimal(str(amount))
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        cur.execute(
            "INSERT INTO users (user_id, balance) VALUES (?, 0)",
            (user_id,),
        )
        current = Decimal("0")
    else:
        current = Decimal(str(row["balance"]))

    new_balance = current + amount
    cur.execute(
        "UPDATE users SET balance = ? WHERE user_id = ?",
        (float(new_balance), user_id),
    )
    conn.commit()
    conn.close()
    return new_balance


def deduct_balance(user_id, amount):
    amount = Decimal(str(amount))
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT balance FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if not row:
            conn.rollback()
            return None

        current = Decimal(str(row["balance"]))
        if current < amount:
            conn.rollback()
            return None

        new_balance = current - amount
        cur.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (float(new_balance), user_id),
        )
        conn.commit()
        return new_balance
    except Exception:
        conn.rollback()
        logger.exception("Deduct balance failed")
        return None
    finally:
        conn.close()


def save_order(
    user_id,
    service_id,
    service_name,
    link,
    quantity,
    charge,
    provider_order_id,
    status="Pending",
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO orders (
            user_id, service_id, service_name, link, quantity,
            charge, provider_order_id, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            str(service_id),
            service_name,
            link,
            quantity,
            float(charge),
            str(provider_order_id or ""),
            status,
        ),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id


def update_order_status(db_order_id, status):
    conn = get_db()
    conn.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, db_order_id),
    )
    conn.commit()
    conn.close()


def get_order(db_order_id, user_id=None):
    conn = get_db()
    if user_id is None:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (db_order_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_id = ?",
            (db_order_id, user_id),
        ).fetchone()
    conn.close()
    return row


def get_user_info(user_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT user_id, username, first_name, balance,
               created_at, welcome_bonus_given
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return row


def get_trackable_orders(limit=100):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, user_id, provider_order_id, status
        FROM orders
        WHERE provider_order_id IS NOT NULL
          AND provider_order_id != ''
          AND status NOT IN ('Completed', 'Canceled', 'Cancelled', 'Refunded', 'Failed')
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_user_orders(user_id, limit=10):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, service_name, link, quantity, charge,
               provider_order_id, status, created_at
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_all_user_ids():
    conn = get_db()
    rows = conn.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


def get_stats():
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    successful = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status IN ('Success', 'Completed')"
    ).fetchone()["n"]
    sales = conn.execute(
        "SELECT COALESCE(SUM(charge), 0) AS n FROM orders WHERE status IN ('Success', 'Completed')"
    ).fetchone()["n"]
    recharge_pending = conn.execute(
        "SELECT COUNT(*) AS n FROM recharge_requests WHERE status = 'Pending'"
    ).fetchone()["n"]
    conn.close()
    return users, orders, successful, Decimal(str(sales)), recharge_pending


def create_recharge_request(user_id, method, amount, transaction_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO recharge_requests (
            user_id, method, amount, transaction_id, status
        ) VALUES (?, ?, ?, ?, 'Pending')
        """,
        (user_id, method, float(amount), transaction_id),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_recharge(rid):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM recharge_requests WHERE id = ?",
        (rid,),
    ).fetchone()
    conn.close()
    return row


def review_recharge(rid, approve):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT * FROM recharge_requests WHERE id = ?",
            (rid,),
        ).fetchone()

        if not row or row["status"] != "Pending":
            conn.rollback()
            return None, "already_reviewed"

        if approve:
            current_row = cur.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (row["user_id"],),
            ).fetchone()
            current = Decimal(str(current_row["balance"])) if current_row else Decimal("0")
            new_balance = current + Decimal(str(row["amount"]))

            if current_row:
                cur.execute(
                    "UPDATE users SET balance = ? WHERE user_id = ?",
                    (float(new_balance), row["user_id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO users(user_id, balance) VALUES (?, ?)",
                    (row["user_id"], float(new_balance)),
                )

            cur.execute(
                """
                UPDATE recharge_requests
                SET status = 'Approved', reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (rid,),
            )
            conn.commit()
            return new_balance, "approved"

        cur.execute(
            """
            UPDATE recharge_requests
            SET status = 'Rejected', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (rid,),
        )
        conn.commit()
        return None, "rejected"

    except Exception:
        conn.rollback()
        logger.exception("Recharge review failed")
        return None, "error"
    finally:
        conn.close()


# =========================================================
# HELPERS
# =========================================================

def money(value):
    return f"{Decimal(str(value)):.2f}"


def customer_price_per_1000(provider_rate_usd):
    """Customer price in BDT for 1000 quantity."""
    return (
        Decimal(str(provider_rate_usd))
        * USD_TO_BDT
        * PROFIT_MULTIPLIER
    )


def order_charge(provider_rate_usd, quantity):
    return (
        customer_price_per_1000(provider_rate_usd)
        * Decimal(str(quantity))
        / Decimal("1000")
    ).quantize(Decimal("0.01"))


def parse_amount(text):
    try:
        amount = Decimal(text.strip())
        if amount <= 0:
            return None
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_quantity(text):
    try:
        qty = int(text.strip())
        return qty if qty > 0 else None
    except ValueError:
        return None


def is_admin(user_id):
    return user_id == ADMIN_ID


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def maintenance_guard(update):
    if not maintenance_enabled():
        return False
    if update.effective_user and is_admin(update.effective_user.id):
        return False
    if update.message:
        await update.message.reply_text(
            "🛠️ Bot maintenance mode-এ আছে।\n"
            "কিছুক্ষণ পরে আবার চেষ্টা করুন।"
        )
    elif update.callback_query:
        await update.callback_query.answer(
            "🛠️ Maintenance mode চলছে।",
            show_alert=True,
        )
    return True


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(user_id=None):
    rows = [
        [KeyboardButton("🛍 Services"), KeyboardButton("👤 Account")],
        [KeyboardButton("📦 My Orders"), KeyboardButton("💳 Recharge")],
        [KeyboardButton("📞 Helpline"), KeyboardButton("📜 Terms")],
    ]
    if user_id == ADMIN_ID:
        rows.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="admin_add"),
            InlineKeyboardButton("➖ Deduct Balance", callback_data="admin_deduct"),
        ],
        [
            InlineKeyboardButton("👤 User Info", callback_data="admin_user_info"),
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("💳 Recharge Requests", callback_data="admin_recharges"),
        ],
        [
            InlineKeyboardButton("🛠 Maintenance", callback_data="admin_maintenance"),
            InlineKeyboardButton("🎁 Welcome Bonus", callback_data="admin_welcome_bonus"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="admin_close"),
        ],
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ])


def services_category_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📘 Facebook", callback_data="category_facebook"),
            InlineKeyboardButton("🎵 TikTok", callback_data="category_tiktok"),
        ],
        [
            InlineKeyboardButton("▶️ YouTube", callback_data="category_youtube"),
            InlineKeyboardButton("🚦 Traffic", callback_data="category_traffic"),
        ],
        [InlineKeyboardButton("📱 Telegram", callback_data="category_telegram")],
        [InlineKeyboardButton("❌ Close", callback_data="close_services")],
    ])


def recharge_method_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("bKash", callback_data="recharge_bkash"),
            InlineKeyboardButton("Nagad", callback_data="recharge_nagad"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")],
    ])


# =========================================================
# SERVICES
# =========================================================

SERVICE_CATEGORIES = {
    "facebook": "📘 Facebook",
    "tiktok": "🎵 TikTok",
    "youtube": "▶️ YouTube",
    "traffic": "🚦 Traffic",
    "telegram": "📱 Telegram",
}


def service_category(service):
    text = " ".join(
        str(service.get(key, "") or "")
        for key in ("name", "category", "type", "desc")
    ).lower()

    if any(k in text for k in ("facebook", "facebook.com", " fb ", "fb.", "fb_")):
        return "facebook"
    if "tiktok" in text or "tik tok" in text:
        return "tiktok"
    if "youtube" in text or "youtu.be" in text or " yt " in text:
        return "youtube"
    if any(k in text for k in (
        "traffic", "website visitor", "website visitors",
        "web traffic", "site traffic", "seo traffic"
    )):
        return "traffic"
    if any(k in text for k in (
        "telegram", "t.me", "telegram.me", "telegram channel",
        "telegram group", "telegram member", "telegram members",
        "telegram view", "telegram views", "telegram reaction",
        "telegram reactions", "telegram post"
    )):
        return "telegram"
    return None


def filter_services_by_category(services, category):
    return [s for s in services if service_category(s) == category]


def services_keyboard(services):
    buttons = []

    for service in services[:50]:
        sid = str(service.get("service", ""))
        name = str(service.get("name", "Service"))

        raw_rate = service.get("rate", "-")
        try:
            api_rate = Decimal(str(raw_rate))
            rate_text = f" | Rate: ${api_rate:g}/1K"
        except Exception:
            rate_text = f" | Rate: ${raw_rate}/1K"

        display_name = f"{name}{rate_text}"
        if len(display_name) > 55:
            display_name = display_name[:52] + "..."

        callback = f"service_{sid}"
        if len(callback.encode("utf-8")) <= 64:
            buttons.append([
                InlineKeyboardButton(display_name, callback_data=callback)
            ])

    buttons.append([
        InlineKeyboardButton("⬅️ Categories", callback_data="service_categories"),
        InlineKeyboardButton("❌ Close", callback_data="close_services"),
    ])
    return InlineKeyboardMarkup(buttons)


# =========================================================
# SMM API
# =========================================================

async def api_request(action, data=None):
    payload = {"key": SMM_API_KEY, "action": action}
    if data:
        payload.update(d
