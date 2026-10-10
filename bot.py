import os
import logging
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest

# بارگذاری متغیرهای محیطی
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")

CLEANAPIS_BASE_URL = "https://cleanapis.com"
# مدلِ جدیدِ قدرتمندِ کلاود
DEFAULT_MODEL = "claude-opus-5.5"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"سلام DEX جان! ربات با مدلِ قدرتمند {DEFAULT_MODEL} و تنظیماتِ فارسی آماده‌ست. بزن بریم!"
    await update.message.reply_text(text)

async def execute_api_test(message, context):
    url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": DEFAULT_MODEL, 
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Always respond in Persian."},
            {"role": "user", "content": "سلام، وضعیت مدل؟"}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            r = await client.post(url, headers=headers, json=payload)
            response_text = f"Status: {r.status_code}\nResponse: {r.text[:200]}"
            await message.reply_text(f"📌 تست مدل {DEFAULT_MODEL}:\n{response_text}")
    except Exception as e:
        await message.reply_text(f"❌ خطای اتصال:\n{str(e)}")

async def call_cleanapis(payload, headers):
    url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code != 200:
            raise Exception(f"API Error ({r.status_code}): {r.text}")
        return r.json()["choices"][0]["message"]["content"]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text("⏳ در حال پردازش با کلاود...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": DEFAULT_MODEL, 
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Always respond in Persian language."},
                {"role": "user", "content": update.message.text}
            ]
        }
        ai_reply = await call_cleanapis(payload, headers)
        
        await wait_msg.delete()
        for i in range(0, len(ai_reply), 4000):
            await update.message.reply_text(ai_reply[i:i+4000])
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطای API:\n{str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        raise ValueError("متغیرهای محیطی ست نشده‌اند!")

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(var, None)

    request = HTTPXRequest(connection_pool_size=8, connect_timeout=30, read_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("testapi", lambda u, c: execute_api_test(u.message, c)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"🤖 ربات با مدل {DEFAULT_MODEL} روشن شد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
