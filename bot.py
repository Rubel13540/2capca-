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

BKASH_NUMBER = "01700000000 (Personal)"
NAGAD_NUMBER = "01700000000 (Personal)"
ROCKET_NUMBER = "01700000000 (Personal)"
BINANCE_ID = "123456789"
BYBIT_ID = "12345688"
USDT_RATE_BDT = Decimal("125")

SUPPORT_USERNAME = "@Rubel1356"
PROFIT_PERCENT = Decimal("10")
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
            balance REAL DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT,
            amount REAL,
            txid TEXT,
            status TEXT DEFAULT 'PENDING',
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

def is_user_banned(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row["is_banned"]) if row else False

def get_user_balance(user_id: int) -> Decimal:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return Decimal(str(row["balance"])) if row else Decimal("0")

def add_balance(user_id: int, amount: Decimal):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (float(amount), user_id))
    conn.commit()
    conn.close()

def create_deposit_record(user_id: int, method: str, amount: Decimal, txid: str) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO deposits (user_id, method, amount, txid) VALUES (?, ?, ?, ?)",
                (user_id, method, float(amount), txid))
    dep_id = cur.lastrowid
    conn.commit()
    conn.close()
    return dep_id

def get_deposit(dep_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM deposits WHERE id = ?", (dep_id,))
    row = cur.fetchone()
    conn.close()
    return row

def update_deposit_status(dep_id: int, status: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE deposits SET status = ? WHERE id = ?", (status, dep_id))
    conn.commit()
    conn.close()

def get_system_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total_users, SUM(balance) as total_bal FROM users")
    u_data = cur.fetchone()
    conn.close()
    return {
        "users": u_data["total_users"] or 0,
        "balance": u_data["total_bal"] or 0.0
    }

# ==========================================
# KEYBOARDS
# ==========================================
def main_menu(user_id: int):
    keyboard = [
        [InlineKeyboardButton("🛍 Shop", callback_data="products")],
        [InlineKeyboardButton("💰 Deposit", callback_data="deposit"), InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        [InlineKeyboardButton("🆘 Support", callback_data="help"), InlineKeyboardButton("⭐ Refer & Earn", callback_data="refer")]
    ]
    # Admin Panel Button added only for Admin
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="home")]])

# ==========================================
# USER & BUTTON HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 Your account has been suspended.")
        return

    create_user(user.id, user.username, user.first_name)
    
    text = (
        f"Hey <b>{user.first_name}</b>! 👋\n\n"
        "We offer premium digital products at the best prices. Fast, secure, and fully automated delivery.\n\n"
        "Choose an option below to continue!\n👇"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu(user.id))

async def home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    user = query.from_user
    
    text = (
        f"Hey <b>{user.first_name}</b>! 👋\n\n"
        "We offer premium digital products at the best prices. Fast, secure, and fully automated delivery.\n\n"
        "Choose an option below to continue!\n👇"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu(user.id))

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bal = get_user_balance(user.id)

    text = (
        f"👤 <b>My Profile</b>\n\n"
        f"• <b>Name:</b> {user.first_name}\n"
        f"• <b>User ID:</b> <code>{user.id}</code>\n"
        f"• <b>Balance:</b> <b>${bal:.2f} USDT</b>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🆘 <b>Support & Help</b>\n\n"
        f"If you need any help, contact our live support admin: {SUPPORT_USERNAME}"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ref_link = f"https://t.me/{(await context.bot.get_me()).username}?start={user.id}"
    text = (
        "⭐ <b>Refer & Earn</b>\n\n"
        "Invite your friends and earn rewards on their top-ups!\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bal = get_user_balance(user.id)

    text = (
        "💰 <b>Deposit Funds</b>\n\n"
        f"Current Balance: <b>${bal:.2f} USDT</b>\n\n"
        "Please select your preferred payment method below:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🟡 Binance Pay", callback_data="dep_binance"), InlineKeyboardButton("🟡 Bybit Transfer", callback_data="dep_bybit")],
        [InlineKeyboardButton("📱 bKash / Nagad / Rocket", callback_data="dep_mfs")],
        [InlineKeyboardButton("🛟 Support", callback_data="help"), InlineKeyboardButton("◀️ Back", callback_data="home")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def deposit_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data

    if method == "dep_binance":
        context.user_data["dep_method"] = "Binance Pay"
        text = (
            "🟡 <b>Binance Pay Deposit</b>\n\n"
            f"• Binance Pay ID: <code>{BINANCE_ID}</code> (Tap to copy)\n\n"
            "<b>Steps:</b>\n"
            "1. Send USDT to the Pay ID above.\n"
            "2. Type the <b>Amount in USDT</b> you sent in this chat now (e.g., <code>10</code>)."
        )
    elif method == "dep_bybit":
        context.user_data["dep_method"] = "Bybit"
        text = (
            "🟡 <b>Bybit Internal Transfer</b>\n\n"
            f"• Bybit UID: <code>{BYBIT_ID}</code> (Tap to copy)\n\n"
            "<b>Steps:</b>\n"
            "1. Send USDT using Internal Transfer to the UID above.\n"
            "2. Type the <b>Amount in USDT</b> you sent in this chat now (e.g., <code>10</code>)."
        )
    elif method == "dep_mfs":
        context.user_data["dep_method"] = "bKash/Nagad/Rocket"
        text = (
            "📱 <b>Mobile Banking (bKash / Nagad / Rocket)</b>\n\n"
            f"• Rate: <b>1 USDT = {USDT_RATE_BDT} BDT</b>\n\n"
            f"• bKash: <code>{BKASH_NUMBER}</code>\n"
            f"• Nagad: <code>{NAGAD_NUMBER}</code>\n"
            f"• Rocket: <code>{ROCKET_NUMBER}</code>\n\n"
            "<b>Steps:</b>\n"
            "1. Send Money / Cash Out to any number above.\n"
            "2. Type the <b>Amount in BDT</b> you sent in this chat now (e.g., <code>500</code>)."
        )

    context.user_data["dep_step"] = "AWAIT_AMOUNT"
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="deposit")]]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_deposit_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("dep_step")
    if not step:
        return

    text_input = update.message.text.strip()

    if step == "AWAIT_AMOUNT":
        try:
            val = Decimal(text_input)
            if val <= 0:
                raise ValueError()
        except Exception:
            await update.message.reply_text("❌ Invalid amount! Please enter a valid number.")
            return

        method = context.user_data.get("dep_method")
        if method == "bKash/Nagad/Rocket":
            usdt_amount = (val / USDT_RATE_BDT).quantize(Decimal("0.01"), rounding=ROUND_UP)
            context.user_data["dep_amount"] = usdt_amount
            msg = f"✅ Amount: <b>{val} BDT</b> (~<b>${usdt_amount} USDT</b>)\n\nNow, send your <b>TrxID</b> or Sender Mobile Number:"
        else:
            context.user_data["dep_amount"] = val
            msg = f"✅ Amount: <b>${val} USDT</b>\n\nNow, paste your <b>Transaction ID / Order ID</b>:"

        context.user_data["dep_step"] = "AWAIT_TXID"
        await update.message.reply_text(msg, parse_mode="HTML")

    elif step == "AWAIT_TXID":
        txid = text_input
        method = context.user_data.get("dep_method")
        amount = context.user_data.get("dep_amount")
        user = update.effective_user

        dep_id = create_deposit_record(user.id, method, amount, txid)
        context.user_data.clear()

        await update.message.reply_text(
            "⏳ <b>Deposit Submitted!</b>\n\nYour request has been sent for verification.",
            parse_mode="HTML",
            reply_markup=main_menu(user.id)
        )

        if ADMIN_CHAT_ID:
            admin_msg = (
                "📥 <b>NEW DEPOSIT REQUEST</b>\n\n"
                f"• User: {user.first_name} (@{user.username or 'N/A'})\n"
                f"• User ID: <code>{user.id}</code>\n"
                f"• Method: <b>{method}</b>\n"
                f"• Amount: <b>${amount} USDT</b>\n"
                f"• TxID: <code>{txid}</code>"
            )
            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"dep_app_{dep_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"dep_rej_{dep_id}")
            ]]
            try:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                pass

# ==========================================
# ADMIN PANEL INTERFACE BUTTONS
# ==========================================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized!", show_alert=True)
        return
    await query.answer()

    stats = get_system_stats()
    text = (
        "👑 <b>ADMIN CONTROL PANEL</b>\n\n"
        f"• Total Users: <b>{stats['users']}</b>\n"
        f"• Total User Balance: <b>${stats['balance']:.2f} USDT</b>\n\n"
        "Choose an action below:"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="adm_cmd_addbal"), InlineKeyboardButton("📢 Broadcast", callback_data="adm_cmd_broadcast")],
        [InlineKeyboardButton("◀️ Back to Home", callback_data="home")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_deposit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized!", show_alert=True)
        return

    data = query.data
    dep_id = int(data.split("_")[2])
    dep = get_deposit(dep_id)

    if not dep or dep["status"] != "PENDING":
        await query.answer("Invalid or already processed request!", show_alert=True)
        return

    user_id = dep["user_id"]
    amount = Decimal(str(dep["amount"]))

    if data.startswith("dep_app_"):
        update_deposit_status(dep_id, "APPROVED")
        add_balance(user_id, amount)
        await query.edit_message_text(f"{query.message.text_html}\n\n<b>✅ APPROVED</b>", parse_mode="HTML")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 <b>Deposit Approved!</b>\n\n<b>${amount} USDT</b> added to your wallet.", parse_mode="HTML")
        except Exception:
            pass

    elif data.startswith("dep_rej_"):
        update_deposit_status(dep_id, "REJECTED")
        await query.edit_message_text(f"{query.message.text_html}\n\n<b>❌ REJECTED</b>", parse_mode="HTML")
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ <b>Deposit Rejected!</b>", parse_mode="HTML")
        except Exception:
            pass

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    init_db()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", lambda u, c: admin_panel_callback(u, c)))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(home_callback, pattern="^home$"))
    app.add_handler(CallbackQueryHandler(show_deposit, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(show_support, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(show_refer, pattern="^refer$"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(deposit_method_selected, pattern="^dep_(binance|bybit|mfs)$"))
    app.add_handler(CallbackQueryHandler(admin_deposit_action, pattern="^dep_(app|rej)_"))

    # Message Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deposit_text_inputs))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
