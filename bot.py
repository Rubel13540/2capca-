import os
import uuid
import json
import sqlite3
import logging
from decimal import Decimal, ROUND_UP
from typing import Optional

import aiohttp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# RAILWAY VARIABLES - ONLY THESE 4 ARE REQUIRED
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
EKLAS_API_KEY = os.getenv("EKLAS_API_KEY", "").strip()
EKLAS_BASE_URL = os.getenv(
    "EKLAS_BASE_URL",
    "https://api.eklas.dev/v1"
).rstrip("/")


# =========================================================
# YOUR BOT CONFIGURATION
# =========================================================

BKASH_NUMBER = "0123445678"
NAGAD_NUMBER = "0123445678"
BINANCE_ID = "123456789"
BYBIT_ID = "123456789"

SUPPORT_USERNAME = "@Rubel1356"

# API price + 10%
PROFIT_PERCENT = Decimal("10")

# Currency displayed to users
DISPLAY_CURRENCY = "USDT"

# Database
DB_FILE = "bot_database.db"

# Product list page size
PRODUCT_LIMIT = 50


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
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            eklas_order_id TEXT,
            client_order_id TEXT UNIQUE,
            product_id INTEGER,
            product_name TEXT,
            quantity INTEGER,
            api_price REAL,
            customer_price REAL,
            status TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT,
            amount REAL,
            trx_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def create_user(user_id: int, username: str, first_name: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
    """, (
        user_id,
        username or "",
        first_name or "",
    ))

    cur.execute("""
        UPDATE users
        SET username = ?, first_name = ?
        WHERE user_id = ?
    """, (
        username or "",
        first_name or "",
        user_id,
    ))

    conn.commit()
    conn.close()


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

    return Decimal(str(row["balance"]))


def add_balance(user_id: int, amount: Decimal):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    """, (
        float(amount),
        user_id,
    ))

    conn.commit()
    conn.close()


def subtract_balance(user_id: int, amount: Decimal) -> bool:
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance = balance - ?
        WHERE user_id = ?
        AND balance >= ?
    """, (
        float(amount),
        user_id,
        float(amount),
    ))

    success = cur.rowcount > 0

    conn.commit()
    conn.close()

    return success


# =========================================================
# Eklas API
# =========================================================

def api_headers():
    return {
        "Authorization": f"Bearer {EKLAS_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def eklas_get(endpoint: str, params=None):
    url = f"{EKLAS_BASE_URL}{endpoint}"

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            url,
            headers=api_headers(),
            params=params,
        ) as response:

            try:
                data = await response.json()
            except Exception:
                data = {
                    "success": False,
                    "error": {
                        "code": "invalid_response",
                        "message": await response.text(),
                    }
                }

            return response.status, data


async def eklas_post(endpoint: str, payload: dict):
    url = f"{EKLAS_BASE_URL}{endpoint}"

    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            url,
            headers=api_headers(),
            json=payload,
        ) as response:

            try:
                data = await response.json()
            except Exception:
                data = {
                    "success": False,
                    "error": {
                        "code": "invalid_response",
                        "message": await response.text(),
                    }
                }

            return response.status, data


# =========================================================
# PRICE
# =========================================================

def customer_price(api_price) -> Decimal:
    price = Decimal(str(api_price))

    multiplier = Decimal("1") + (
        PROFIT_PERCENT / Decimal("100")
    )

    result = price * multiplier

    return result.quantize(
        Decimal("0.01"),
        rounding=ROUND_UP
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🛍 Products",
                callback_data="products"
            ),
            InlineKeyboardButton(
                "📦 My Orders",
                callback_data="orders"
            ),
        ],
        [
            InlineKeyboardButton(
                "💰 My Balance",
                callback_data="balance"
            ),
            InlineKeyboardButton(
                "💳 Deposit",
                callback_data="deposit"
            ),
        ],
        [
            InlineKeyboardButton(
                "👤 My Account",
                callback_data="account"
            ),
        ],
        [
            InlineKeyboardButton(
                "🆘 Help Center",
                callback_data="help"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def back_home():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home"
            )
        ]
    ])


# =========================================================
# /START & HOME
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    create_user(
        user.id,
        user.username,
        user.first_name,
    )

    text = (
        "🛍 <b>Welcome!</b>\n\n"
        "🌐 International Digital Products\n"
        "⚡ Fast & Secure Delivery\n\n"
        "Choose an option below:"
    )

    if update.message:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    text = (
        "🛍 <b>Welcome!</b>\n\n"
        "🌐 International Digital Products\n"
        "⚡ Fast & Secure Delivery\n\n"
        "Choose an option below:"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# =========================================================
# PRODUCTS
# =========================================================

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    status, result = await eklas_get(
        "/products",
        {
            "in_stock": "true",
            "page": 1,
            "limit": PRODUCT_LIMIT,
        }
    )

    if not result.get("success"):
        await query.edit_message_text(
            "❌ Products load করা যায়নি।\n\n"
            "Please try again later.",
            reply_markup=back_home(),
        )
        return

    products = result.get("data", [])

    if not products:
        await query.edit_message_text(
            "📦 বর্তমানে কোনো product available নেই।",
            reply_markup=back_home(),
        )
        return

    keyboard = []

    for product in products:
        product_id = product.get("id")
        name = product.get("name", "Unknown")
        price = customer_price(product.get("price", 0))

        keyboard.append([
            InlineKeyboardButton(
                f"🛒 {name[:35]} — {price} USDT",
                callback_data=f"product:{product_id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🏠 Home",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "🛍 <b>Available Products</b>\n\n"
        "Select a product:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# PRODUCT DETAILS
# =========================================================

async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        product_id = int(query.data.split(":")[1])
    except Exception:
        await query.edit_message_text(
            "❌ Invalid product.",
            reply_markup=back_home(),
        )
        return

    status, result = await eklas_get(
        f"/products/{product_id}"
    )

    if not result.get("success"):
        await query.edit_message_text(
            "❌ Product information পাওয়া যায়নি।",
            reply_markup=back_home(),
        )
        return

    product = result.get("data", {})

    name = product.get("name", "Unknown")
    description = product.get("description", "")
    api_price = Decimal(str(product.get("price", 0)))
    price = customer_price(api_price)

    stock = product.get("stock")
    unlimited = product.get("unlimited_stock", False)
    max_quantity = product.get("max_quantity", 1)
    delivery = product.get("delivery", "unknown")
    requires = product.get("requires", [])

    if unlimited:
        stock_text = "Unlimited"
    else:
        stock_text = str(stock if stock is not None else "N/A")

    requires_text = ""

    if requires:
        requires_text = (
            "\n\n<b>Required information:</b>\n"
            + "\n".join(
                f"• {str(x)}"
                for x in requires
            )
        )

    text = (
        f"📦 <b>{name}</b>\n\n"
        f"{description}\n\n"
        f"💰 Price: <b>{price} USDT</b>\n"
        f"📦 Stock: {stock_text}\n"
        f"🔢 Max Quantity: {max_quantity}\n"
        f"⚡ Delivery: {delivery}"
        f"{requires_text}\n\n"
        "Press Buy to continue."
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 Buy Now",
                callback_data=f"buy:{product_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Products",
                callback_data="products"
            ),
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home"
            ),
        ]
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# BUY
# =========================================================

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split(":")[1])

    context.user_data["buy_product_id"] = product_id
    context.user_data["state"] = "waiting_quantity"

    await query.edit_message_text(
        "🔢 <b>Quantity</b>\n\n"
        "আপনি কতটি নিতে চান?\n\n"
        "Example: <code>1</code>",
        parse_mode="HTML",
        reply_markup=back_home(),
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    create_user(
        user.id,
        user.username,
        user.first_name,
    )

    state = context.user_data.get("state")

    # -----------------------------------------
    # QUANTITY
    # -----------------------------------------

    if state == "waiting_quantity":

        try:
            quantity = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ শুধু সংখ্যা দিন।\nExample: 1"
            )
            return

        if quantity <= 0:
            await update.message.reply_text(
                "❌ Quantity 1 বা তার বেশি হতে হবে।"
            )
            return

        product_id = context.user_data.get(
            "buy_product_id"
        )

        status, result = await eklas_get(
            f"/products/{product_id}"
        )

        if not result.get("success"):
            await update.message.reply_text(
                "❌ Product information পাওয়া যায়নি।"
            )
            context.user_data.clear()
            return

        product = result["data"]

        max_quantity = int(
            product.get("max_quantity") or 1
        )

        if quantity > max_quantity:
            await update.message.reply_text(
                f"❌ Maximum quantity: {max_quantity}"
            )
            return

        api_price = Decimal(
            str(product.get("price", 0))
        )

        total_api = api_price * quantity
        total_customer = customer_price(
            total_api
        )

        user_balance = get_user_balance(
            user.id
        )

        context.user_data["quantity"] = quantity
        context.user_data["product"] = product
        context.user_data["total_price"] = str(
            total_customer
        )

        text_confirm = (
            "🧾 <b>Order Confirmation</b>\n\n"
            f"📦 Product: <b>{product.get('name')}</b>\n"
            f"🔢 Quantity: <b>{quantity}</b>\n"
            f"💰 Total: <b>{total_customer} USDT</b>\n"
            f"👛 Your Balance: <b>{user_balance} USDT</b>\n\n"
        )

        if user_balance >= total_customer:
            text_confirm += (
                "Press Confirm Order to continue."
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Confirm Order",
                        callback_data="confirm_order",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="home"
                    )
                ],
            ]

        else:
            text_confirm += (
                "❌ আপনার balance যথেষ্ট নয়।\n"
                "আগে Deposit করুন।"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "💳 Deposit",
                        callback_data="deposit",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Home",
                        callback_data="home"
                    )
                ],
            ]

        await update.message.reply_text(
            text_confirm,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        context.user_data["state"] = (
            "waiting_confirmation"
        )

        return

    # -----------------------------------------
    # REQUIRED CUSTOMER PAYLOAD
    # -----------------------------------------

    if state == "waiting_required":
        product = context.user_data.get("product")

        if not product:
            await update.message.reply_text(
                "❌ Order session expired."
            )
            context.user_data.clear()
            return

        requires = product.get("requires", [])

        customer_payload = {}

        if len(requires) == 1:
            customer_payload[
                requires[0]
            ] = text

        else:
            first_field = (
                requires[0]
                if requires
                else "value"
            )

            customer_payload[
                first_field
            ] = text

        context.user_data[
            "customer_payload"
        ] = customer_payload

        await execute_order(
            update,
            context,
        )

        return

    # -----------------------------------------
    # DEFAULT
    # -----------------------------------------

    await update.message.reply_text(
        "🏠 Main Menu",
        reply_markup=main_menu(),
    )


# =========================================================
# CONFIRM ORDER
# =========================================================

async def confirm_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    product = context.user_data.get("product")

    if not product:
        await query.edit_message_text(
            "❌ Order session expired.",
            reply_markup=back_home(),
        )
        return

    requires = product.get("requires", [])

    if requires:
        context.user_data["state"] = (
            "waiting_required"
        )

        fields = "\n".join(
            f"• {field}"
            for field in requires
        )

        await query.edit_message_text(
            "📝 <b>Required Information</b>\n\n"
            f"{fields}\n\n"
            "এক লাইনে প্রয়োজনীয় তথ্য পাঠান।",
            parse_mode="HTML",
        )

        return

    await execute_order(
        query,
        context,
    )


# =========================================================
# EXECUTE ORDER
# =========================================================

async def execute_order(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update_or_query.from_user

