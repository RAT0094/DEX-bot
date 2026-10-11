import os
import logging
import httpx
import re
import io
import base64
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# --- کانفیگ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
WELCOME_TEXT = "سلام دوست عزیز چه کمکی از دستم برمیاد"

MODEL_EMOJIS = {"gpt-5.6-luna": "🌙", "claude-opus-5.5": "🧠", "gpt-5.5": "⚡", "gpt-5.5-pro": "🚀", "claude-fable-5": "📖"}
MODELS = list(MODEL_EMOJIS.keys())
FORBIDDEN_NAMES = ["OpenAI", "Google", "Anthropic", "Meta", "Microsoft"]

logging.basicConfig(level=logging.INFO)

# --- توابعِ منطقی ---
def is_identity_query(text):
    return any(k in text.lower() for k in ["سازنده", "کی ساخته", "خالق", "owner", "creator"])

def sanitize_response(text):
    pattern = re.compile('|'.join(FORBIDDEN_NAMES), re.IGNORECASE)
    return pattern.sub("DEX", text)

def get_system_instruction():
    return "You are a helpful assistant developed by DEX. Always respond in Persian. Never use Arabic. Always format code in Markdown."

# --- منوها ---
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("🟢 ابزارها", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغییر مدل", callback_data="change_model")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])

# --- هندلرها ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'model' not in context.user_data: context.user_data['model'] = DEFAULT_MODEL
    await update.message.reply_text(WELCOME_TEXT, reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "user_info":
        user = update.effective_user
        text = f"👤 نام: {user.first_name}\nآیدی: `{user.id}`\nمدل: `{context.user_data.get('model', DEFAULT_MODEL)}`"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")
    elif query.data == "more_services":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=get_services_menu())
    elif query.data == "back_main":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=get_main_menu())
    elif query.data == "change_model":
        await query.edit_message_text("یک مدل برگزین:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(m, callback_data=f"set_{m}")] for m in MODELS]))
    elif query.data.startswith("set_"):
        context.user_data['model'] = query.data.replace("set_", "")
        await query.edit_message_text("مدل با موفقیت تغییر کرد!", reply_markup=get_main_menu())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if is_identity_query(text):
        await update.message.reply_text("DEX")
        return
    if any(k in text for k in ["تصویر بساز", "عکس بساز"]):
        await update.message.reply_text("این قابلیت به‌زودی اضافه می‌شود")
        return
    
    wait_msg = await update.message.reply_text("⏳ در حال پردازش...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", 
                              headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                              json={"model": context.user_data.get('model', DEFAULT_MODEL), 
                                    "messages": [{"role": "system", "content": get_system_instruction()}, {"role": "user", "content": text}]})
        answer = r.json()["choices"][0]["message"]["content"]
        await wait_msg.delete()
        await update.message.reply_text(sanitize_response(answer), parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    ext = doc.file_name.split('.')[-1].lower()
    allowed = ['pdf', 'docx', 'doc', 'txt', 'py', 'json', 'csv']
    
    if ext not in allowed:
        await update.message.reply_text(f"🚫 این نوع فایل (`.{ext}`) پشتیبانی نمی‌شود.")
        return

    await update.message.reply_text("✅ پرونده دریافت شد. در حال تحلیل محتوا...")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("DEX Bot is running... 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
                         
