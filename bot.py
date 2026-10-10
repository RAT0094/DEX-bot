import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# تنظیمات اصلی
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"

logging.basicConfig(level=logging.INFO)

# --- توابع رابط کاربری ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'model' not in context.user_data:
        context.user_data['model'] = DEFAULT_MODEL
        
    keyboard = [
        [InlineKeyboardButton("👤 اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("⚙️ تعویض مدل هوش مصنوعی", callback_data="model_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("سلام دوست عزیز، چجوری می‌تونم کمک کنم؟\n\n💡 می‌تونی با دستور `/img [توضیحات]` عکس هم بسازی!", reply_markup=reply_markup, parse_mode="Markdown")

async def show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (f"🆔 اطلاعات حساب شما:\n"
            f"نام: {user.first_name}\n"
            f"آیدی: `{user.id}`\n"
            f"مدل فعال فعلی: `{context.user_data.get('model', DEFAULT_MODEL)}`")
    await update.callback_query.message.edit_text(text, parse_mode="Markdown")

async def show_model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get('model', DEFAULT_MODEL)
    keyboard = [
        [InlineKeyboardButton(f"🤖 GPT-5.6-Luna {'✅' if current == 'gpt-5.6-luna' else ''}", callback_data="set_gpt-5.6-luna")],
        [InlineKeyboardButton(f"🧠 Claude-Opus-5.5 {'✅' if current == 'claude-opus-5.5' else ''}", callback_data="set_claude-opus-5.5")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.edit_text("💎 مدلِ هوش مصنوعی رو انتخاب کن:", reply_markup=reply_markup)

# --- هندلر دکمه‌ها ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "user_info":
        await show_user_info(update, context)
    elif query.data == "model_menu":
        await show_model_menu(update, context)
    elif query.data.startswith("set_"):
        new_model = query.data.replace("set_", "")
        context.user_data['model'] = new_model
        await query.message.edit_text(f"✅ مدل با موفقیت به `{new_model}` تغییر یافت.", parse_mode="Markdown")
    elif query.data == "back_to_main":
        await query.message.edit_text("چجوری می‌تونم کمک کنم؟", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 اطلاعات کاربر", callback_data="user_info")],
            [InlineKeyboardButton("⚙️ تعویض مدل هوش مصنوعی", callback_data="model_menu")]
        ]))

# --- هندلر تولید تصویر ---

async def generate_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ لطفاً توضیحات عکس رو هم بنویس.\nمثال: `/img a futuristic neon logo`", parse_mode="Markdown")
        return

    prompt = " ".join(context.args)
    wait_msg = await update.message.reply_text("🎨 در حال ترسیم تصویر... لطفاً صبر کن.")

    try:
        # تغییر آدرس به اندپوینت تصویر (اگر CleanApis از استاندارد OpenAI استفاده می‌کند)
        url = f"{CLEANAPIS_BASE_URL}/v1/images/generations"
        payload = {"prompt": prompt, "n": 1, "size": "1024x1024"}
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            image_url = r.json()["data"][0]["url"]
            
        await update.message.reply_photo(photo=image_url, caption=f"✨ نتیجه برای: {prompt}")
        await wait_msg.delete()
        
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطای تولید تصویر:\n`{str(e)}`", parse_mode="Markdown")

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
        
        url = f"{CLEANAPIS_BASE_URL}/v1/chat/completions"
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        await wait_msg.delete()
        await update.message.reply_text(ai_reply)
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا:\n`{str(e)}`", parse_mode="Markdown")

# --- اصلی ---

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("img", generate_image_command)) # دستور جدید
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
    
