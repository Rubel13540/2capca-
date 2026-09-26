import os
import time
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ================= Configuration =================
API_KEY = "021dc722c9ff6b2c1280e86afbfbc101"

# Railway-এর Environment Variables থেকে Bot Token নেবে
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# আপনার নির্দিষ্ট Chat ID
AUTHORIZED_CHAT_ID = 5293614793

TARGET_URL = "https://your-website.com/login"
SITE_KEY = "YOUR_TEST_SITE_KEY"
# =================================================

user_states = {}

def get_2captcha_balance():
    """2Captcha API থেকে অ্যাকাউন্টের বর্তমান ব্যালেন্স চেক করে"""
    url = "https://api.2captcha.com/getBalance"
    payload = {
        "clientKey": API_KEY
    }
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        if response.get("errorId") == 0:
            return response.get("balance")
    except Exception as e:
        print(f"Error fetching balance: {e}")
    return None

def create_captcha_task():
    """2Captcha API-তে ক্যাপচা সলভিং টাস্ক পাঠায়"""
    url = "https://api.2captcha.com/createTask"
    payload = {
        "clientKey": API_KEY,
        "task": {
            "type": "ReCaptchaV2TaskProxyless",
            "websiteURL": TARGET_URL,
            "websiteKey": SITE_KEY
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=10).json()
        if response.get("errorId") == 0:
            return response.get("taskId")
    except Exception as e:
        print(f"Error creating task: {e}")
    return None

def check_captcha_result(task_id):
    """2Captcha থেকে ক্যাপচার উত্তর চেক করে"""
    url = "https://api.2captcha.com/getTaskResult"
    payload = {
        "clientKey": API_KEY,
        "taskId": task_id
    }
    
    for _ in range(10):
        try:
            response = requests.post(url, json=payload, timeout=10).json()
            if response.get("errorId") != 0:
                return None
            
            status = response.get("status")
            if status == "ready":
                return response.get("solution", {}).get("gRecaptchaResponse")
            elif status == "processing":
                time.sleep(5)
        except Exception as e:
            print(f"Error checking status: {e}")
            break
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Chat ID যাচাই
    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("❌ আপনার এই বটটি ব্যবহার করার অনুমতি নেই।")
        return

    keyboard = [
        [
            InlineKeyboardButton("▶️ Start Task", callback_data="start_task"),
            InlineKeyboardButton("⏹️ Off", callback_data="stop_task")
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="check_balance")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("কন্ট্রোল প্যানেল:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.message.chat_id != AUTHORIZED_CHAT_ID:
        await query.edit_message_text("❌ অনুমতি নেই।")
        return

    user_id = query.from_user.id

    if query.data == "start_task":
        if not user_states.get(user_id, False):
            user_states[user_id] = True
            await query.edit_message_text("✅ কাজ চালু করা হয়েছে। প্রসেসিং শুরু হচ্ছে...")
            asyncio.create_task(process_loop(user_id, context))
        else:
            await query.edit_message_text("⚠️ কাজ ইতিমধ্যেই চালু আছে!")

    elif query.data == "stop_task":
        user_states[user_id] = False
        await query.edit_message_text("🛑 কাজ বন্ধ করা হয়েছে।")

    elif query.data == "check_balance":
        loop = asyncio.get_event_loop()
        balance = await loop.run_in_executor(None, get_2captcha_balance)
        
        if balance is not None:
            await query.message.reply_text(f"💳 **আপনার 2Captcha ব্যালেন্স:** ${balance:.4f}", parse_mode="Markdown")
        else:
            await query.message.reply_text("❌ ব্যালেন্স নিয়ে আসতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

async def process_loop(user_id, context):
    while user_states.get(user_id, False):
        await context.bot.send_message(
            chat_id=AUTHORIZED_CHAT_ID, 
            text="🔄 নতুন ক্যাপচা প্রসেস করার চেষ্টা করা হচ্ছে..."
        )
        
        task_id = create_captcha_task()
        if not task_id:
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID, 
                text="❌ টাস্ক তৈরি করতে ব্যর্থ হয়েছে। ৩ সেকেন্ড পর আবার চেষ্টা করা হবে..."
            )
            await asyncio.sleep(3)
            continue

        loop = asyncio.get_event_loop()
        solution = await loop.run_in_executor(None, check_captcha_result, task_id)

        if solution:
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID, 
                text=f"✅ ক্যাপচা সফলভাবে সলভ হয়েছে!\n\nToken: `{solution[:30]}...`", 
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=AUTHORIZED_CHAT_ID, 
                text="❌ সমাধান পাওয়া যায়নি।"
            )

        await asyncio.sleep(3)

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN পরিবেশ ভেরিয়েবলে সেট করা হয়নি!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
