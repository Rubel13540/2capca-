import os
import sqlite3
import logging
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            stock TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_title TEXT,
            item_delivered TEXT,
            price REAL,
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

def get_categories():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories")
    rows = cur.fetchall()
    conn.close()
    return rows

def add_category(name: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()

def get_products(category_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE category_id = ?", (category_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def add_product(category_id: int, title: str, description: str, price: Decimal, stock: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (category_id, title, description, price, stock) VALUES (?, ?, ?, ?, ?)",
                (category_id, title, description, float(price), stock))
    conn.commit()
    conn.close()

def get_product_by_id(prod_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = ?", (prod_id,))
    row = cur.fetchone()
    conn.close()
    return row

def record_order(user_id: int, title: str, delivered: str, price: float):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (user_id, product_title, item_delivered, price) VALUES (?, ?, ?, ?)",
                (user_id, title, delivered, price))
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
        [InlineKeyboardButton("🛍 Digital Shop", callback_data="products")],
        [InlineKeyboardButton("💰 Deposit", callback_data="deposit"), InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        [InlineKeyboardButton("🆘 Support", callback_data="help"), InlineKeyboardButton("⭐ Refer & Earn", callback_data="refer")]
    ]
    if user_id == ADMIN_CHAT_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="home")]])

# ==========================================
# HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username, user.first_name)
    
    text = (
        f"Hey <b>{user.first_name}</b>! 👋\n\n"
        "Welcome to our <b>Digital Product Store</b>!\n"
        "Get instant automated delivery for subscription accounts, gift cards, licenses, and premium digital items.\n\n"
        "Select an option below to get started:"
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
        "Welcome to our <b>Digital Product Store</b>!\n"
        "Get instant automated delivery for subscription accounts, gift cards, licenses, and premium digital items.\n\n"
        "Select an option below to get started:"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu(user.id))

async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    categories = get_categories()

    if not categories:
        await query.edit_message_text("🛍 <b>Store Category is currently empty!</b>\n\nCheck back soon.", parse_mode="HTML", reply_markup=back_home())
        return

    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"📁 {cat['name']}", callback_data=f"cat_{cat['id']}")])

    keyboard.append([InlineKeyboardButton("◀️ Back to Home", callback_data="home")])
    text = "🛍 <b>Digital Product Categories</b>\n\nSelect a category to view products:"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cat_id = int(query.data.split("_")[1])
    products = get_products(cat_id)

    if not products:
        await query.edit_message_text("❌ No products available in this category yet.", reply_markup=back_home())
        return

    keyboard = []
    text = "📦 <b>Available Digital Products:</b>\n\n"
    for prod in products:
        text += f"🔹 <b>{prod['title']}</b>\n💰 Price: <b>${prod['price']:.2f} USDT</b>\n📝 {prod['description']}\n\n"
        keyboard.append([InlineKeyboardButton(f"🛒 Buy {prod['title']} (${prod['price']:.2f})", callback_data=f"buy_{prod['id']}")])

    keyboard.append([InlineKeyboardButton("◀️ Back to Categories", callback_data="products")])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def buy_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.split("_")[1])
    
    prod = get_product_by_id(prod_id)
    if not prod:
        await query.edit_message_text("❌ Product not found!", reply_markup=back_home())
        return

    user_id = query.from_user.id
    bal = get_user_balance(user_id)
    price = Decimal(str(prod["price"]))

    if bal < price:
        text = f"❌ <b>Insufficient Balance!</b>\n\nProduct Price: <b>${price:.2f} USDT</b>\nYour Balance: <b>${bal:.2f} USDT</b>\n\nPlease add deposit first."
        keyboard = [[InlineKeyboardButton("💰 Deposit Funds", callback_data="deposit")], [InlineKeyboardButton("◀️ Back", callback_data="products")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    add_balance(user_id, -price)
    record_order(user_id, prod["title"], prod["stock"], float(price))

    text = (
        f"🎉 <b>Purchase Successful!</b>\n\n"
        f"📦 <b>Item:</b> {prod['title']}\n"
        f"💰 <b>Paid:</b> ${price:.2f} USDT\n\n"
        f"📬 <b>Your Digital Item Details:</b>\n"
        f"<code>{prod['stock']}</code>\n\n"
        "Thank you for purchasing with us!"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bal = get_user_balance(user.id)

    text = (
        f"👤 <b>My Profile</b>\n\n"
        f"• <b>Name:</b> {user.first_name}\n"
        f"• <b>User ID:</b> <code>{user.id}</code>\n"
        f"• <b>Wallet Balance:</b> <b>${bal:.2f} USDT</b>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🆘 <b>Customer Support</b>\n\n"
        f"For queries, order issues or assistance, contact: {SUPPORT_USERNAME}"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    text = (
        "⭐ <b>Refer & Earn Program</b>\n\n"
        "Invite your friends to buy digital products and earn commission on their top-ups!\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_home())

async def show_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bal = get_user_balance(user.id)

    text = (
        "💰 <b>Deposit Wallet Funds</b>\n\n"
        f"Current Balance: <b>${bal:.2f} USDT</b>\n\n"
        "Select your preferred payment method below:"
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
            "2. Enter the <b>Amount in USDT</b> you sent (e.g., <code>10</code>):"
        )
    elif method == "dep_bybit":
        context.user_data["dep_method"] = "Bybit"
        text = (
            "🟡 <b>Bybit Internal Transfer</b>\n\n"
            f"• Bybit UID: <code>{BYBIT_ID}</code> (Tap to copy)\n\n"
            "<b>Steps:</b>\n"
            "1. Send USDT using Internal Transfer to the UID above.\n"
            "2. Enter the <b>Amount in USDT</b> you sent (e.g., <code>10</code>):"
        )
    elif method == "dep_mfs":
        context.user_data["dep_method"] = "bKash/Nagad/Rocket"
        text = (
            "📱 <b>Mobile Banking (bKash / Nagad / Rocket)</b>\n\n"
            f"• Conversion Rate: <b>1 USDT = {USDT_RATE_BDT} BDT</b>\n\n"
            f"• bKash: <code>{BKASH_NUMBER}</code>\n"
            f"• Nagad: <code>{NAGAD_NUMBER}</code>\n"
            f"• Rocket: <code>{ROCKET_NUMBER}</code>\n\n"
            "<b>Steps:</b>\n"
            "1. Send Money / Cash Out to any number above.\n"
            "2. Enter the <b>Amount in BDT</b> you sent (e.g., <code>500</code>):"
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
        "👑 <b>ADMIN PANEL MANAGEMENT</b>\n\n"
        f"• Total Users: <b>{stats['users']}</b>\n"
        f"• Total User Balance: <b>${stats['balance']:.2f} USDT</b>\n\n"
        "Control options:"
    )
    keyboard = [
        [InlineKeyboardButton("📁 Add Category", callback_data="adm_addcat"), InlineKeyboardButton("📦 Add Product", callback_data="adm_addprod")],
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

    if data == "adm_addcat":
        context.user_data["adm_step"] = "AWAIT_CAT_NAME"
        await query.edit_message_text("📁 <b>Enter Category Name:</b> (e.g. Netflix, Spotify, Canva)", parse_mode="HTML")

    elif data == "adm_addprod":
        cats = get_categories()
        if not cats:
            await query.edit_message_text("❌ Create a category first!", reply_markup=back_home())
            return
        
        keyboard = [[InlineKeyboardButton(c["name"], callback_data=f"adm_pcat_{c['id']}")] for c in cats]
        await query.edit_message_text("📦 Select Category to add product under:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_addbal":
        context.user_data["adm_step"] = "AWAIT_ADD_USER_ID"
        await query.edit_message_text("➕ Enter Target User ID:", parse_mode="HTML")

    elif data == "adm_broadcast":
        context.user_data["adm_step"] = "AWAIT_BROADCAST_MSG"
        await query.edit_message_text("📢 Enter broadcast message to send to all users:", parse_mode="HTML")

async def admin_cat_select_for_prod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[2])
    context.user_data["new_prod_cat_id"] = cat_id
    context.user_data["adm_step"] = "AWAIT_PROD_TITLE"
    await query.edit_message_text("📦 Enter Product Title (e.g., 1 Month Premium):")

async def handle_all_text_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    
    # Deposit Flow
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
            msg = f"✅ Amount: <b>{val} BDT</b> (~<b>${usdt_amount} USDT</b>)\n\nNow send your <b>TrxID</b> or Sender Mobile Number:"
        else:
            user_data["dep_amount"] = val
            msg = f"✅ Amount: <b>${val} USDT</b>\n\nNow enter your <b>Transaction ID / TxID</b>:"

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
            "⏳ <b>Deposit Submit
