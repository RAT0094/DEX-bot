import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")

CLEANAPIS_BASE_URL = "https://cleanapis.com"

AVAILABLE_MODELS = ["fable-5", "fable-5.1", "opus-5.5"]
DEFAULT_MODEL = "opus-5.5"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تغییر مدل", callback_data="show_models")],
        [InlineKeyboardButton("ℹ️ مدل فعلی", callback_data="show_current")],
        [InlineKeyboardButton("🧪 تست اتصال API", callback_data="run_test")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("model", DEFAULT_MODEL)
    text = f"سلام DEX جان! 👋\n\nمدل فعلی: {current}\nبرای تست سلامت مسیرها می‌تونی دستور /testapi رو بفرستی."
    await update.message.reply_text(text, reply_markup=start_keyboard())

async def show_models(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    keyboard = [[InlineKeyboardButton(m, callback_data=f"select_{m}")] for m in AVAILABLE_MODELS]
    markup = InlineKeyboardMarkup(keyboard)
    if is_callback:
        await update.callback_query.edit_message_text("👇 یک مدل را انتخاب کن:", reply_markup=markup)
    else:
        await update.message.reply_text("👇 یک مدل را انتخاب کن:", reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "show_models":
        await show_models(update, context, is_callback=True)
    elif query.data == "show_current":
        current = context.user_data.get("model", DEFAULT_MODEL)
        await query.answer(f"مدل فعلی: {current}", show_alert=True)
    elif query.data == "run_test":
        await query.message.reply_text("⏳ در حال اجرای تست API...")
        await execute_api_test(query.message, context)
    elif query.data.startswith("select_"):
        model_id = query.data.replace("select_", "")
        context.user_data["model"] = model_id
        await query.edit_message_text(f"✅ مدل شما به {model_id} تغییر کرد.", reply_markup=start_keyboard())

async def execute_api_test(message, context):
    urls = [
        f"{CLEANAPIS_BASE_URL}/v1/chat/completions",
        f"{CLEANAPIS_BASE_URL}/chat/completions"
    ]
    headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": DEFAULT_MODEL, "messages": [{"role": "user", "content": "hi"}]}

    results = []
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        for url in urls:
            try:
                r = await client.post(url, headers=headers, json=payload)
                results.append(f"📌 URL: {url}\nStatus: {r.status_code}\nBody: {r.text[:150]}")
            except Exception as e:
                results.append(f"📌 URL: {url}\nError: {str(e)}")

    await message.reply_text("\n\n".join(results))

async def test_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ در حال تست اتصال به سرور...")
    await execute_api_test(update.message, context)

async def call_cleanapis(payload, headers):
    url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code != 200:
            print(f"🚨 Server returned {r.status_code}: {r.text}")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("model", DEFAULT_MODEL)
    wait_msg = await update.message.reply_text("⏳ در حال اتصال به سرور...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        headers = {
            "Authorization": f"Bearer {CLEANAPIS_API_KEY}", 
            "Content-Type": "application/json"
        }
        payload = {"model": current, "messages": [{"role": "user", "content": update.message.text}]}
        ai_reply = await call_cleanapis(payload, headers)
        
        try: await wait_msg.delete()
        except: pass
        
        for i in range(0, len(ai_reply), 4000):
            await update.message.reply_text(ai_reply[i:i+4000])
    except Exception as e:
        print(f"FINAL ERROR: {e}")
        try: await wait_msg.edit_text(f"❌ خطا:\n{str(e)}")
        except: await update.message.reply_text(f"❌ خطا:\n{str(e)}")

def main():
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        raise ValueError("Variables ست نشده!")

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(var, None)

    request = HTTPXRequest(connection_pool_size=8, connect_timeout=30, read_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", show_models))
    app.add_handler(CommandHandler("testapi", test_api))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("ربات روشن شد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
