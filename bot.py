import os
import time
import random
import asyncio
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ================= Configuration =================
API_KEY = "021dc722c9ff6b2c1280e86afbfbc101"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_CHAT_ID = 5293614793

# টেস্ট ওয়েবসাইট URL এবং Test Site Key
TARGET_URL = "https://2captcha.com/demo/recaptcha-v2"
SITE_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
# =================================================

user_states = {}

def get_2captcha_balance():
    url = "https://api.2captcha.com/getBalance"
    payload = {"clientKey": API_KEY}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15).json()
        if response.get("errorId") == 0:
            return response.get("balance")
    except Exception as e:
        print(f"Error fetching balance: {e}")
    return None

def create_captcha_task():
    url = "https://api.2captcha.com/createTask"
    payload = {
        "clientKey": API_KEY,
        "task": {
            "type": "ReCaptchaV2TaskProxyless",
            "websiteURL": TARGET_URL,
            "websiteKey": SITE_KEY
        }
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15).json()
        if response.get("errorId") == 0:
            return response.get("taskId"), None
        else:
            error_msg = response.get("errorDescription") or response.get("errorCode") or "Unknown API Error"
            return None, error_msg
    except Exception as e:
        return None, str(e)

def check_captcha_result(task_id):
    url = "https://api.2captcha.com/getTaskResult"
    payload = {
        "clientKey": API_KEY,
        "taskId": task_id
    }
    headers = {"Content-Type": "application/json"}
    
    # মানুষের মতো কিছুটা সময় নিয়ে (৮ সেকেন্ড পর পর) চেক করবে
    for _ in range(15):
        try:
            time.sleep(8)
            response = requests.post(url, json=payload, headers=headers, timeout=15).json()
            if response.get("errorId") != 0:
                return None
            
            status = response.get("status")
            if status == "ready":
                return response.get("solution", {}).get("gRecaptchaResponse")
        except Exception as e:
            print(f"Error checking status: {e}")
            break
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        await update.message.reply_text("❌ আপনার এই বটটি ব্যবহার করার অনুমতি নেই।")
        return

    keyboard = [
        ["▶️ Start Task", "⏹️ Off"],
        ["💰 Balance"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("কন্ট্রোল প্যানেল রেডি। নিচের বাটনগুলো ব্যবহার করুন:", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != AUTHORIZED_CHAT_ID:
        return

    text = update.message.text
    user_id = update.effective_user.id

    if text == "▶️ Start Task":
        if not user_states.get(user_id, False):
            user_states[user_id] = True
            msg = await update.message.reply_text("✅ কাজ শুরু হচ্ছে...")
            asyncio.create_task(process_loop(user_id, context, msg.message_id))
        else:
            await update.message.reply_text("⚠️ কাজ ইতিমধ্যেই চালু আছে!")

    elif text == "⏹️ Off":
        user_states[user_id] = False
        await update.message.reply_text("🛑 কাজ বন্ধ করা হয়েছে।")

    elif text == "💰 Balance":
        loop = asyncio.get_event_loop()
        balance = await loop.run_in_executor(None, get_2captcha_balance)
        if balance is not None:
            await update.message.reply_text(f"💳 **2Captcha Balance:** ${balance:.4f}", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ ব্যালেন্স চেক করতে সমস্যা হয়েছে।")

async def process_loop(user_id, context, status_msg_id):
    while user_states.get(user_id, False):
        try:
            await context.bot.edit_message_text(
                chat_id=AUTHORIZED_CHAT_ID,
                message_id=status_msg_id,
                text="🔄 নতুন ক্যাপচা প্রসেস করার চেষ্টা করা হচ্ছে..."
            )
        except Exception:
            pass
        
        loop = asyncio.get_event_loop()
        task_id, err_desc = await loop.run_in_executor(None, create_captcha_task)

        if not task_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=AUTHORIZED_CHAT_ID,
                    message_id=status_msg_id,
                    text=f"❌ টাস্ক তৈরি করতে ব্যর্থ হয়েছে!\nকারণ: {err_desc}\n৫ সেকেন্ড পর আবার চেষ্টা করা হবে..."
                )
            except Exception:
                pass
            await asyncio.sleep(5)
            continue

        solution = await loop.run_in_executor(None, check_captcha_result, task_id)

        if solution:
            try:
                await context.bot.edit_message_text(
                    chat_id=AUTHORIZED_CHAT_ID,
                    message_id=status_msg_id,
                    text=f"✅ ক্যাপচা সফলভাবে সলভ হয়েছে!\n\nToken: `{solution[:30]}...`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            try:
                await context.bot.edit_message_text(
                    chat_id=AUTHORIZED_CHAT_ID,
                    message_id=status_msg_id,
                    text="❌ সমাধান পাওয়া যায়নি। আবার চেষ্টা করা হচ্ছে..."
                )
            except Exception:
                pass

        # মানুষের মতো ধীরগতি রাখতে ১০ থেকে ১৫ সেকেন্ড বিরতি
        delay = random.randint(10, 15)
        await asyncio.sleep(delay)

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN সেট করা হয়নি!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
