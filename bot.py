import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# تنظیمات اولیه
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = "*******" # اینجا جایگزین کن
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
MAIN_TEXT = "سلام دوست عزیز، چطور می‌تونم کمکت کنم؟"

logging.basicConfig(level=logging.INFO)

# --- منوهای شیشه‌ای ---

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("🟢 خدمات بیشتر", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغییر مدل", callback_data="change_model")],
        [InlineKeyboardButton("🖼 ساخت تصویر (به زودی)", callback_data="img_soon")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])

def get_model_menu(current_model):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 GPT-5.6-Luna {'✅' if current_model == 'gpt-5.6-luna' else ''}", callback_data="set_gpt-5.6-luna")],
        [InlineKeyboardButton(f"🧠 Claude-Opus-5.5 {'✅' if current_model == 'claude-opus-5.5' else ''}", callback_data="set_claude-opus-5.5")],
        [InlineKeyboardButton("🔙 بازگشت به خدمات", callback_data="more_services")]
    ])

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'model' not in context.user_data:
        context.user_data['model'] = DEFAULT_MODEL
    await update.message.reply_text(MAIN_TEXT, reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # مدیریت دکمه "اطلاعات کاربر"
    if query.data == "user_info":
        user = update.effective_user
        info_text = (f"{MAIN_TEXT}\n\n"
                     f"👤 **اطلاعات شما:**\n"
                     f"نام: {user.first_name}\n"
                     f"آیدی: `{user.id}`\n"
                     f"مدل فعلی: `{context.user_data.get('model', DEFAULT_MODEL)}`")
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")

    # مدیریت دکمه "خدمات بیشتر"
    elif query.data == "more_services":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_services_menu())

    # بازگشت به منوی اصلی
    elif query.data == "back_main":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_main_menu())

    # تغییر مدل
    elif query.data == "change_model":
        current = context.user_data.get('model', DEFAULT_MODEL)
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_model_menu(current))

    elif query.data.startswith("set_"):
        new_model = query.data.replace("set_", "")
        context.user_data['model'] = new_model
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_model_menu(new_model))

    # پیام "به زودی"
    elif query.data == "img_soon":
        await query.answer("به زودی اضافه می‌شود!", show_alert=True)

# --- هندلر چت ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    model = context.user_data.get('model', DEFAULT_MODEL)
    wait_msg = await update.message.reply_text(f"⏳ پردازش با ({model})...")
    
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Always respond in Persian language."},
                {"role": "user", "content": update.message.text}
            ]
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        await wait_msg.delete()
        await update.message.reply_text(ai_reply)
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا در پاسخگویی:\n`{str(e)}`", parse_mode="Markdown")

# --- اصلی ---

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()

if __name__ == "__main__":
    main()
    
