import os
import logging
import httpx
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# --- تنظیمات و کانفیگ ---
# حتما توکن‌ها رو در Environment Variables ست کن، نه اینجا!
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
MAIN_TEXT = "سلام دوست عزیز، چطور می‌تونم کمکت کنم؟"

MODEL_EMOJIS = {
    "gpt-5.6-luna": "🌙",
    "claude-opus-5.5": "🧠",
    "gpt-5.5": "⚡",
    "gpt-5.5-pro": "🚀",
    "claude-fable-5": "📖"
}
MODELS = list(MODEL_EMOJIS.keys())

logging.basicConfig(level=logging.INFO)

# --- توابع کمکی ---

def is_identity_query(text):
    keywords = ["سازنده", "کی ساخته", "خالق", "owner", "creator", "who created", "who made"]
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)

def sanitize_response(text):
    companies = ["OpenAI", "Google", "Anthropic", "Meta", "Microsoft"]
    pattern = re.compile('|'.join(companies), re.IGNORECASE)
    return pattern.sub("DEX", text)

# --- منوها ---

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
    buttons = []
    for model in MODELS:
        emoji = MODEL_EMOJIS.get(model, "🤖")
        status = '✅' if current_model == model else ''
        buttons.append([InlineKeyboardButton(f"{emoji} {model.upper()} {status}", callback_data=f"set_{model}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به خدمات", callback_data="more_services")])
    return InlineKeyboardMarkup(buttons)

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
        info_text = (f"{MAIN_TEXT}\n\n👤 **اطلاعات شما:**\n"
                     f"نام: {user.first_name}\n"
                     f"آیدی: `{user.id}`\n"
                     f"مدل فعلی: `{context.user_data.get('model', DEFAULT_MODEL)}`")
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")

    elif query.data == "more_services":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_services_menu())

    elif query.data == "back_main":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_main_menu())

    elif query.data == "change_model":
        current = context.user_data.get('model', DEFAULT_MODEL)
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_model_menu(current))

    elif query.data.startswith("set_"):
        new_model = query.data.replace("set_", "")
        context.user_data['model'] = new_model
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_model_menu(new_model))

    elif query.data == "img_soon":
        await query.answer("به زودی اضافه می‌شود!", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    if is_identity_query(user_text):
        await update.message.reply_text("DEX")
        return

    is_article_request = "مقاله" in user_text
    
    system_instruction = f"""You are a helpful assistant developed by DEX.
    
    CRITICAL LANGUAGE POLICY: 
    - ALWAYS and ONLY respond in Persian (Farsi).
    - NEVER use Arabic, even if asked. Strictly reject Arabic grammar or vocabulary influence.
    - If a word has both Persian and Arabic versions, ALWAYS use the Persian one.
    
    {'STRUCTURE RULES FOR ARTICLE:' if is_article_request else 'RULES:'}
    {'- Write a complete, comprehensive, and professional article.' if is_article_request else '- Be concise and helpful.'}
    {'- Do not summarize. Provide depth, details, and clear headers (H1, H2, H3).' if is_article_request else ''}
    
    GENERAL RULES:
    1. You are developed solely by DEX.
    2. If asked about your creator, answer ONLY: 'DEX'.
    3. Never mention OpenAI, Google, Anthropic, or other companies as your creator.
    4. Wrap code snippets in triple backticks (
```code```)."""

    model = context.user_data.get('model', DEFAULT_MODEL)
    wait_msg = await update.message.reply_text("⏳ درحال پردازش..." if not is_article_request else "⏳ درحال نوشتن مقاله کامل...")
    
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text}
            ]
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        final_reply = sanitize_response(ai_reply)
        await wait_msg.delete()
        
        # مدیریت محدودیت طول تلگرام
        if len(final_reply) > 4096:
            for i in range(0, len(final_reply), 4096):
                await update.message.reply_text(final_reply[i:i+4096], parse_mode="Markdown")
        else:
            await update.message.reply_text(final_reply, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطا در پردازش:\n`{str(e)}`", parse_mode="Markdown")

# --- نقطه شروع ---
def main():
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        print("خطا: توکن‌ها تنظیم نشده‌اند!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("رباتِ DEX با موفقیت اجرا شد! 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
    
