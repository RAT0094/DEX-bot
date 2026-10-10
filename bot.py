import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ChatAction
from telegram.request import HTTPXRequest

# متغیرها
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # تنظیم مدل پیش‌فرض در اولین شروع
    context.user_data['model'] = DEFAULT_MODEL
    await update.message.reply_text("سلام DEX جان! من رباتِ تو هستم. با دستور /model می‌تونی بین مدل‌ها سوییچ کنی.")

async def show_model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get('model', DEFAULT_MODEL)
    keyboard = [
        [InlineKeyboardButton(f"🤖 GPT-5.6-Luna {'✅' if current == 'gpt-5.6-luna' else ''}", callback_data="gpt-5.6-luna")],
        [InlineKeyboardButton(f"🧠 Claude-Opus-5.5 {'✅' if current == 'claude-opus-5.5' else ''}", callback_data="claude-opus-5.5")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💎 یکی از مدل‌های هوش مصنوعی رو انتخاب کن:", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_model = query.data
    context.user_data['model'] = selected_model
    
    await query.edit_message_text(f"🔥 مدلِ فعال با موفقیت ست شد به: `{selected_model}`\nحالا پیام بفرست تا با این مدل جواب بدم!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # دریافت مدل انتخاب شده از حافظه کاربر
    model = context.user_data.get('model', DEFAULT_MODEL)
    
    wait_msg = await update.message.reply_text(f"⏳ در حال پردازش با ({model})...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Always respond in Persian language."},
                {"role": "user", "content": update.message.text}
            ]
        }
        
        url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                raise Exception(f"API Error ({r.status_code}): {r.text}")
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        await wait_msg.delete()
        for i in range(0, len(ai_reply), 4000):
            await update.message.reply_text(ai_reply[i:i+4000])
            
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطای API در مدل `{model}`:\n{str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", show_model_menu))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 ربات آماده شد. دستور /model برای سوییچ مدل...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
