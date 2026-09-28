import os
import uuid
import json
import sqlite3
import logging
from decimal import Decimal, ROUND_UP

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# ENV VARIABLES & CONFIGS
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

raw_admin = os.getenv("ADMIN_CHAT_ID", "0").strip()
try:
    ADMIN_CHAT_ID = int(raw_admin) if raw_admin else 0
except ValueError:
    ADMIN_CHAT_ID = 0

EKLAS_API_KEY = os.getenv("EKLAS_API_KEY", "").strip()
EKLAS_BASE_URL = os.getenv("EKLAS_BASE_URL", "https://api.eklas.dev/v1").rstrip("/")

BKASH_NUMBER = "0123445678"
NAGAD_NUMBER = "0123445678"
BINANCE_ID = "123456789"
BYBIT_ID = "123456789"
SUPPORT_USERNAME = "@Rubel1356"
PROFIT_PERCENT = Decimal("10")
DISPLAY_CURRENCY = "USDT"
DB_FILE = "bot_database.db"
PRODUCT_LIMIT = 50

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# DATABASE FUNCTIONS
# ==========================================
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
            balance REAL DEFAULT 0
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
    conn.commit()
    conn.close()

def create_user(user_id: int, username: str, first_name: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", 
                (user_id, username or "", first_name or ""))
    conn.commit()
    conn.close()

def get_user_balance(user_id: int) -> Decimal:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return Decimal(str(row["balance"])) if row else Decimal("0")

def subtract_balance(user_id: int, amount: Decimal) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", 
                (float(amount), user_id, float(amount)))
    success = cur.rowcount > 0
    conn.commit()
    conn.close()
    return success

# ==========================================
# EKLAS API HELPERS
# ==========================================
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
        async with session.get(url, headers=api_headers(), params=params) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {"success": False, "error": {"message": await resp.text()}}
            return resp.status, data

async def eklas_post(endpoint: str, payload: dict):
    url = f"{EKLAS_BASE_URL}{endpoint}"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=api_headers(), json=payload) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {"success": False, "error": {"message": await resp.text()}}
            return resp.status, data

def customer_price(api_price) -> Decimal:
    price = Decimal(str(api_price))
    result = price * (Decimal("1") + (PROFIT_PERCENT / Decimal("100")))
    return result.quantize(Decimal("0.01"), rounding=ROUND_UP)

# ==========================================
# KEYBOARDS & UI
# ==========================================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("🛍 Products", callback_data="products"), InlineKeyboardButton("📦 My Orders", callback_data="orders")],
        [InlineKeyboardButton("💰 My Balance", callback_data="balance"), InlineKeyboardButton("💳 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("🆘 Help Center", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])

# ==========================================
# BOT HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username, user.first_name)
    text = "🛍 <b>Welcome!</b>\n\nChoose an option below:"
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())

async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🛍 <b>Welcome!</b>\n\nChoose an option below:", parse_mode="HTML", reply_markup=main_menu())

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status, result = await eklas_get("/products", {"in_stock": "true", "page": 1, "limit": PRODUCT_LIMIT})
    
    if not result.get("success"):
        await query.edit_message_text("❌ Products load kora jayni.", reply_markup=back_home())
        return

    products = result.get("data", [])
    if not products:
        await query.edit_message_text("📦 Kono product available nei.", reply_markup=back_home())
        return

    keyboard = []
    for p in products:
        p_id = p.get("id")
        p_name = p.get("name", "Unknown")
        p_price = customer_price(p.get("price", 0))
        keyboard.append([InlineKeyboardButton(f"🛒 {p_name[:30]} — {p_price} USDT", callback_data=f"product:{p_id}")])
    
    keyboard.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    await query.edit_message_text("🛍 <b>Available Products</b>\n\nSelect a product:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        p_id = int(query.data.split(":")[1])
    except Exception:
        await query.edit_message_text("❌ Invalid product.", reply_markup=back_home())
        return

    status, result = await eklas_get(f"/products/{p_id}")
    if not result.get("success"):
        await query.edit_message_text("❌ Product info pawa jayni.", reply_markup=back_home())
        return

    p = result.get("data", {})
    price = customer_price(p.get("price", 0))
    text = (
        f"📦 <b>{p.get('name')}</b>\n\n"
        f"{p.get('description', '')}\n\n"
        f"💰 Price: <b>{price} USDT</b>\n"
        f"🔢 Max Quantity: {p.get('max_quantity', 1)}"
    )
    keyboard = [
        [InlineKeyboardButton("🛒 Buy Now", callback_data=f"buy:{p_id}")],
        [InlineKeyboardButton("⬅️ Products", callback_data="products"), InlineKeyboardButton("🏠 Home", callback_data="home")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p_id = int(query.data.split(":")[1])
    context.user_data["buy_product_id"] = p_id
    context.user_data["state"] = "waiting_quantity"
    await query.edit_message_text("🔢 <b>Quantity</b>\n\nKoto pis nite chan? (Example: 1)", parse_mode="HTML", reply_markup=back_home())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    txt = (update.message.text or "").strip()
    create_user(user.id, user.username, user.first_name)
    state = context.user_data.get("state")

    if state == "waiting_quantity":
        try:
            qty = int(txt)
            if qty <= 0: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Valid number din.")
            return

        p_id = context.user_data.get("buy_product_id")
        status, result = await eklas_get(f"/products/{p_id}")
        if not result.get("success"):
            await update.message.reply_text("❌ Product info error.")
            context.user_data.clear()
            return

        p = result["data"]
        tot_customer = customer_price(Decimal(str(p.get("price", 0))) * qty)
        bal = get_user_balance(user.id)

        context.user_data["quantity"] = qty
        context.user_data["product"] = p
        context.user_data["total_price"] = str(tot_customer)

        msg = (
            "🧾 <b>Order Summary</b>\n\n"
            f"📦 Product: <b>{p.get('name')}</b>\n"
            f"🔢 Qty: <b>{qty}</b>\n"
            f"💰 Total: <b>{tot_customer} USDT</b>\n"
            f"👛 Your Balance: <b>{bal} USDT</b>\n\n"
        )
        if bal >= tot_customer:
            kb = [[InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")], [InlineKeyboardButton("❌ Cancel", callback_data="home")]]
        else:
            msg += "❌ Insufficient balance! Please deposit."
            kb = [[InlineKeyboardButton("💳 Deposit", callback_data="deposit")], [InlineKeyboardButton("🏠 Home", callback_data="home")]]

        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "waiting_required":
        p = context.user_data.get("product")
        reqs = p.get("requires", []) if p else []
        payload = {reqs[0]: txt} if reqs else {"field": txt}
        context.user_data["customer_payload"] = payload
        await execute_order(update, context)
        return

    await update.message.reply_text("🏠 Main Menu", reply_markup=main_menu())

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p = context.user_data.get("product")
    if not p:
        await query.edit_message_text("❌ Session expired.", reply_markup=back_home())
        return

    if p.get("requires"):
        context.user_data["state"] = "waiting_required"
        await query.edit_message_text(f"📝 <b>Required Info:</b>\n{p.get('requires')}\n\nEkhane reply din:")
        return

    await execute_order(query, context)

async def execute_order(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user = update_or_query.from_user
    p = context.user_data.get("product")
    qty = int(context.user_data.get("quantity", 1))
    tot_price = Decimal(str(context.user_data.get("total_price", "0")))

    if get_user_balance(user.id) < tot_price:
        text = "❌ Insufficient balance!"
    else:
        client_id = str(uuid.uuid4())
        payload = {"product_id": p.get("id"), "quantity": qty, "client_order_id": client_id}
        if context.user_data.get("customer_payload"):
            payload["customer_payload"] = context.user_data.get("customer_payload")

        status, response = await eklas_post("/orders", payload)
        if response.get("success"):
            subtract_balance(user.id, tot_price)
            order_data = response.get("data", {})
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO orders (user_id, eklas_order_id, client_order_id, product_id, product_name, quantity, api_price, customer_price, status, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user.id, str(order_data.get("id", "")), client_id, p.get("id"), p.get("name"), qty, float(p.get("price", 0)), float(tot_price), order_data.get("status", "completed"), json.dumps(order_data.get("content", {}))))
            conn.commit()
            conn.close()
            text = f"✅ <b>Order Successful!</b>\n\nProduct: {p.get('name')}\nTotal: {tot_price} USDT"
        else:
            text = f"❌ <b>Order Failed:</b> {response.get('error', {}).get('message', 'Error')}"

    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())
    else:
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=back_home())
    context.user_data.clear()

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bal = get_user_balance(query.from_user.id)
    await query.edit_message_text(f"💰 Balance: <b>{bal} {DISPLAY_CURRENCY}</b>", parse_mode="HTML", reply_markup=back_home())

async def show_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    txt = f"💳 <b>Deposit</b>\n\nBkash: <code>{BKASH_NUMBER}</code>\nNagad: <code>{NAGAD_NUMBER}</code>\nSupport: {SUPPORT_USERNAME}"
    await query.edit_message_text(txt, parse_mode="HTML", reply_markup=back_home())

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"🆘 Support: {SUPPORT_USERNAME}", parse_mode="HTML", reply_markup=back_home())

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(home_callback, pattern="^home$"))
    app.add_handler(CallbackQueryHandler(show_products, pattern="^products$"))
    app.add_handler(CallbackQueryHandler(show_product, pattern="^product:"))
    app.add_handler(CallbackQueryHandler(start_buy, pattern="^buy:"))
    app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm_order$"))
    app.add_handler(CallbackQueryHandler(show_balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(show_deposit, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(show_help, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
