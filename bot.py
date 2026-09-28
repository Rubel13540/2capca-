import os
import sqlite3
import logging
import requests
from decimal import Decimal, ROUND_UP

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
# CONFIGURATIONS & ENVIRONMENT VARIABLES
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

raw_admin = os.getenv("ADMIN_CHAT_ID", "0").strip()
try:
    ADMIN_CHAT_ID = int(raw_admin) if raw_admin else 0
except ValueError:
    ADMIN_CHAT_ID = 0

# Provided SMM API Credentials
SMM_API_URL = os.getenv("SMM_API_URL", "https://api.eklas.dev/v1").strip()
SMM_API_KEY = os.getenv("SMM_API_KEY", "tgb_1npNLl39aOHdeYZXs0OeOmu5yv8Jf9uW-qfvMObYAYjXwtec").strip()

BKASH_NUMBER = "01700000000 (Personal)"
NAGAD_NUMBER = "01700000000 (Personal)"
ROCKET_NUMBER = "01700000000 (Personal)"
BINANCE_ID = "123456789"
BYBIT_ID = "12345688"
USDT_RATE_BDT = Decimal("125")

SUPPORT_USERNAME = "@Rubel1356"
DB_FILE = "bot_database.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for storing API services in memory
CACHE_SERVICES = []

# ==========================================
# DATABASE SETUP
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

def get_all_user_ids():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]

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
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="home")]])

# ==========================================
# CALLBACK HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
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

# ==========================================
# SHOP API INTEGRATION HANDLER
# ==========================================
async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CACHE_SERVICES
    query = update.callback_query
    await query.answer("Fetching products...")

    try:
        # Requesting API services
        payload = {"key": SMM_API_KEY, "action": "services"}
        response = requests.post(SMM_API_URL, data=payload, timeout=12)
        
        # Standard API handling (checking JSON or list)
        try:
            services = response.json()
        except Exception:
            # Fallback if GET is required
            response = requests.get(f"{SMM_API_URL}?key={SMM_API_KEY}&action=services", timeout=12)
            services = response.json()

        if isinstance(services, list) and len(services) > 0:
            CACHE_SERVICES = services
            
            # Extract Categories
            categories = list(set([str(s.get("category", "General Services")) for s in services]))
            categories.sort()

            keyboard = []
            # Showing top 10 categories
            for idx, cat in enumerate(categories[:10]):
                keyboard.append([InlineKeyboardButton(f"📁 {cat}", callback_data=f"cat_{idx}")])

            keyboard.append([InlineKeyboardButton("◀️ Back to Home", callback_data="home")])
            
            text = "🛍 <b>Shop Categories</b>\n\nPlease select a category below to view services:"
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("❌ No services returned from API provider. Please try again later.", reply_markup=back_home())

    except Exception as e:
        logger.error(f"SMM API Error: {e}")
        await query.edit_message_text("⚠️ Connection error with API Server! Check API Key or endpoint URL.", parse_mode="HTML", reply_markup=back_home())

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cat_idx = int(query.data.split("_")[1])
    categories = list(set([str(s.get("category", "General Services")) for s in CACHE_SERVICES]))
    categories.sort()

    if cat_idx >= len(categories):
        await query.edit_message_text("Category not found!", reply_markup=back_home())
        return

    target_cat = categories[cat_idx]
    
    # Filter services under selected category
    matched_services = [s for s in CACHE_SERVICES if str(s.get("category")) == target_cat]

    text = f"📂 <b>Category:</b> {target_cat}\n\n<b>Available Services:</b>\n\n"
    for s in matched_services[:10]: # Displaying top 10
        service_id = s.get("service")
        name = s.get("name")
        rate = s.get("rate")
        min_q = s.get("min")
        max_q = s.get("max")
        
        text += f"🔹 <b>ID {service_id}:</b> {name}\n💰 Rate: ${rate} / 1k | Min: {min_q} - Max: {max_q}\n\n"

    keyboard = [
        [InlineKeyboardButton("🛍 Back to Categories", callback_data="products")],
        [InlineKeyboardButton("◀️ Main Menu", callback_data="home")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

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
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
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

# ==========================================
# ADMIN PANEL HANDLERS
# ==========================================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if ADMIN_CHAT_ID != 0 and user_id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized!", show_alert=True)
        return

    await query.answer()

    stats = get_system_stats()
    text = (
        "👑 <b>ADMIN CONTROL PANEL</b>\n\n"
        f"• Total Users: <b>{stats['users']}</b>\n"
        f"• Total User Balance: <b>${stats['balance']:.2f} USDT</b>\n\n"
        "Control options:"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="adm_addbal"), InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton("◀️ Back to Home", callback_data="home")]
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_actions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if ADMIN_CHAT_ID != 0 and query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("Unauthorized!", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "adm_addbal":
        context.user_data["adm_step"] = "AWAIT_ADD_USER_ID"
        text = "➕ <b>Add Balance to User</b>\n\nPlease enter the <b>Target User ID</b>:"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancel", callback_data="admin_panel")]]))

    elif data == "adm_broadcast":
        context.user_data["adm_step"] = "AWAIT_BROADCAST_MSG"
        text = "📢 <b>Broadcast Message</b>\n\nPlease enter the message you want to send to all users:"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancel", callback_data="admin_panel")]]))

async def handle_all_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    
    dep_step = user_data.get("dep_step")
    if dep_step == "AWAIT_AMOUNT":
        try:
            val = Decimal(update.message.text.strip())
            if val <= 0:
                raise ValueError()
        except Exception:
            await update.message.reply_text("❌ Invalid amount! Please enter a valid number.")
            return

        method = user_data.get("dep_method")
        if method == "bKash/Nagad/Rocket":
            usdt_amount = (val / USDT_RATE_BDT).quantize(Decimal("0.01"), rounding=ROUND_UP)
            user_data["dep_amount"] = usdt_amount
            msg = f"✅ Amount: <b>{val} BDT</b> (~<b>${usdt_amount} USDT</b>)\n\nNow, send your <b>TrxID</b> or Sender Mobile Number:"
        else:
            user_data["dep_amount"] = val
            msg = f"✅ Amount: <b>${val} USDT</b>\n\nNow, paste your <b>Transaction ID / Order ID</b>:"

        user_data["dep_step"] = "AWAIT_TXID"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    elif dep_step == "AWAIT_TXID":
        txid = update.message.text.strip()
        method = user_data.get("dep_method")
        amount = user_data.get("dep_amount")
        user = update.effective_user

        dep_id = create_deposit_record(user.id, method, amount, txid)
        user_data.clear()

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
            except Exception as e:
                logger.error(f"Failed to send admin alert: {e}")
        return

    adm_step = user_data.get("adm_step")
    if adm_step == "AWAIT_ADD_USER_ID":
        try:
            target_id = int(update.message.text.strip())
            user_data["target_user_id"] = target_id
            user_data["adm_step"] = "AWAIT_ADD_AMOUNT"
            await update.message.reply_text(f"✅ User ID: <code>{target_id}</code>\n\nNow enter the <b>Amount in USDT</b> to add:", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid User ID!")
        return

    elif adm_step == "AWAIT_ADD_AMOUNT":
        try:
            amt = Decimal(update.message.text.strip())
            target_id = user_data.get("target_user_id")
            add_balance(target_id, amt)
            user_data.clear()
            await update.message.reply_text(f"🎉 Successfully added <b>${amt} USDT</b> to user <code>{target_id}</code>!", parse_mode="HTML")
            try:
                await context.bot.send_message(chat_id=target_id, text=f"🎉 <b>Balance Credited!</b>\n\nAdmin added <b>${amt} USDT</b> to your wallet balance.", parse_mode="HTML")
            except Exception:
                pass
        except Exception:
            await update.message.reply_text("❌ Invalid amount!")
        return

    elif adm_step == "AWAIT_BROADCAST_MSG":
        broadcast_text = update.message.text.strip()
        users = get_all_user_ids()
        count = 0
        for u_id in users:
            try:
                await context.bot.send_message(chat_id=u_id, text=broadcast_text, parse_mode="HTML")
                count += 1
            except Exception:
                pass
        user_data.clear()
        await update.message.reply_text(f"📢 Bro
