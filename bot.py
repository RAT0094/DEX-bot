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
CLEANAPIS_BASE_URL = "https://api.cleanapis.com/v1"

AVAILABLE_MODELS = ["fable-5", "fable-5.1", "opus-5.5"]
DEFAULT_MODEL = "opus-5.5"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تغییر مدل", callback_data="show_models")],
        [InlineKeyboardButton("ℹ️ مدل فعلی", callback_data="show_current")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("model", DEFAULT_MODEL)
    text = f"سلام DEX امروز چیکار کنیم؟ 👋\n\nهر سوالی داری بفرست جواب میدم.\nمدل فعلی: {current}"
    await update.message.reply_text(text, reply_markup=start_keyboard())

async def show_models(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    keyboard = [[InlineKeyboardButton(m, callback_data=f"select_{m}")] for m in AVAILABLE_MODELS]
    markup = InlineKeyboardMarkup(keyboard)
    if is_callback:
        await update.callback_query.edit_message_text("👇 یک مدل را انتخاب کن:", reply_markup=markup)
    else:
        await update.message.reply_text("👇 یک مدل را انتخاب کن:", reply_markup=markup)

async def get_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_models(update, context, is_callback=False)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "show_models":
        await show_models(update, context, is_callback=True)
    elif query.data == "show_current":
        current = context.user_data.get("model", DEFAULT_MODEL)
        await query.answer(f"مدل فعلی: {current}", show_alert=True)
    elif query.data.startswith("select_"):
        model_id = query.data.replace("select_", "")
        context.user_data["model"] = model_id
        await query.edit_message_text(f"✅ مدل شما به {model_id} تغییر کرد.", reply_markup=start_keyboard())

async def current_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("model", DEFAULT_MODEL)
    await update.message.reply_text(f"مدل فعلی شما: {current}")

async def call_cleanapis(payload, headers):
    timeout = httpx.Timeout(120.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        r = await client.post(f"{CLEANAPIS_BASE_URL}/chat/completions", headers=headers, json=payload)
        print(f"STATUS {r.status_code}")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("model", DEFAULT_MODEL)
    wait_msg = await update.message.reply_text("⏳ لطفاً صبر کنید...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": current, "messages": [{"role": "user", "content": update.message.text}]}
        ai_reply = await call_cleanapis(payload, headers)
        try:
            await wait_msg.delete()
        except:
            pass
        for i in range(0, len(ai_reply), 4000):
            await update.message.reply_text(ai_reply[i:i+4000])
    except Exception as e:
        print(f"FINAL ERROR {type(e).__name__}: {e}")
        try:
            await wait_msg.edit_text("❌ خطا: " + str(e))
        except:
            await update.message.reply_text("❌ خطا: " + str(e))

def main():
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        raise ValueError("TELEGRAM_BOT_TOKEN یا CLEANAPIS_API_KEY در Railway Variables ست نشده!")

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)

    # درست شد - بدون trust_env
    request = HTTPXRequest(connection_pool_size=8, connect_timeout=30, read_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("models", get_models))
    app.add_handler(CommandHandler("current", current_model))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("ربات روشن شد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
