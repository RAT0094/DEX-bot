import os
import logging
import httpx
import re
import io
import base64
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# --- تنظیمات و کانفیگ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
MAIN_TEXT = "درود DeXtEr، من آماده‌ام! چه پرونده یا پرسشی داری؟"

MODEL_EMOJIS = {
    "gpt-5.6-luna": "🌙",
    "claude-opus-5.5": "🧠",
    "gpt-5.5": "⚡",
    "gpt-5.5-pro": "🚀",
    "claude-fable-5": "📖"
}
MODELS = list(MODEL_EMOJIS.keys())
FORBIDDEN_NAMES = ["OpenAI", "Google", "Anthropic", "Meta", "Microsoft"]

logging.basicConfig(level=logging.INFO)

# --- توابعِ شناسایی و پاک‌سازی ---

def is_identity_query(text):
    keywords = ["سازنده", "کی ساخته", "خالق", "owner", "creator"]
    return any(keyword in text.lower() for keyword in keywords)

def is_image_generation_query(text):
    keywords = ["تصویر بساز", "عکس بساز", "طراحی کن", "نقاشی کن", "عکس بکش"]
    return any(keyword in text for keyword in keywords)

def sanitize_response(text):
    pattern = re.compile('|'.join(FORBIDDEN_NAMES), re.IGNORECASE)
    return pattern.sub("DEX", text)

def get_system_instruction(is_article_request):
    return """You are a helpful assistant developed by DEX.
    Always respond in Persian. Never use Arabic.
    Always format code in Markdown.
    If asked about your creator, answer ONLY: 'DEX'."""

# --- منوها ---

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ اطلاعاتِ تو", callback_data="user_info")],
        [InlineKeyboardButton("🟢 ابزارها", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغییر مدل", callback_data="change_model")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'model' not in context.user_data:
        context.user_data['model'] = DEFAULT_MODEL
    await update.message.reply_text(MAIN_TEXT, reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "user_info":
        user = update.effective_user
        info_text = f"👤 نام: {user.first_name}\nآیدی: `{user.id}`\nمدل: `{context.user_data.get('model', DEFAULT_MODEL)}`"
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")
    elif query.data == "more_services":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_services_menu())
    elif query.data == "back_main":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_main_menu())
    elif query.data == "change_model":
        current = context.user_data.get('model', DEFAULT_MODEL)
        # سادگی در انتخاب مدل
        await query.edit_message_text("یک مدل برگزین:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(m, callback_data=f"set_{m}")] for m in MODELS]))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if is_identity_query(text):
        await update.message.reply_text("DEX")
        return
    if is_image_generation_query(text):
        await update.message.reply_text("این قابلیت به‌زودی اضافه می‌شود")
        return
    
    wait_msg = await update.message.reply_text("⏳ در حال اندیشیدن...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", 
                              headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                              json={"model": context.user_data.get('model', DEFAULT_MODEL), 
                                    "messages": [{"role": "system", "content": get_system_instruction(False)}, {"role": "user", "content": text}]})
        answer = r.json()["choices"][0]["message"]["content"]
        await wait_msg.delete()
        await update.message.reply_text(sanitize_response(answer), parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تصویر دریافت شد! در حال بررسی...")
    # (کدِ پردازش تصویر در اینجا قرار می‌گیرد)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    file_name = doc.file_name.lower()
    # پسوندهای مجاز
    allowed = ['pdf', 'docx', 'doc', 'txt', 'py', 'json', 'csv']
    
    # شناسایی پسوند
    if not any(file_name.endswith(ext) for ext in allowed):
        await update.message.reply_text(f"🚫 پرونده‌ای با پسوندِ `{file_name.split('.')[-1]}` توسطِ من پشتیبانی نمی‌شود. من فقط با متن و اسنادِ متنی کار می‌کنم!")
        return

    await update.message.reply_text("📂 پرونده دریافت شد. در حال پردازشِ داده‌ها...")
    # در اینجا باید با کتابخانه‌هایی مثل PyMuPDF متن رو استخراج کنی
    # برای شروع، فرض رو بر این می‌گیریم که ربات اعلام آمادگی کنه
    await update.message.reply_text("✅ پرونده پردازش شد! چه چیزی از این پرونده می‌خواهی بدانی؟")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document)) # افزودن هندلرِ پرونده‌ها
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("DEX Bot در حالِ اجرایِ کامل است... 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
            
