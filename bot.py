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
MAIN_TEXT = "سلام دوست عزیز، چطور می‌تونم کمکت کنم؟"

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

# --- توابع کمکی ---

def is_identity_query(text):
    keywords = ["سازنده", "کی ساخته", "خالق", "owner", "creator", "who created", "who made"]
    return any(keyword in text.lower() for keyword in keywords)

def is_image_generation_query(text):
    # کلمات کلیدی که نشون میده کاربر میخواد تصویر تولید کنه
    keywords = ["تصویر بساز", "عکس بساز", "طراحی کن", "نقاشی کن", "عکس بکش", "یک عکس از"]
    return any(keyword in text for keyword in keywords)

def sanitize_response(text):
    pattern = re.compile('|'.join(FORBIDDEN_NAMES), re.IGNORECASE)
    return pattern.sub("DEX", text)

def get_system_instruction(is_article_request):
    return f"""You are a helpful assistant developed by DEX.
    CRITICAL LANGUAGE POLICY: 
    - ALWAYS and ONLY respond in Persian (Farsi).
    - NEVER use Arabic. If a word has both Persian and Arabic versions, ALWAYS use the Persian one.
    
    CODE FORMATTING:
    - ALWAYS wrap ANY code or script in triple backticks (
```).
- Use the correct language tag for code blocks (e.g., 
```python).
    - Never output raw code without formatting.
    
    {'STRUCTURE RULES FOR ARTICLE:' if is_article_request else 'RULES:'}
    {'- Write a complete, comprehensive, and professional article.' if is_article_request else '- Be concise and helpful.'}
    {'- Provide depth, details, and clear headers (H1, H2, H3).' if is_article_request else ''}
    
    GENERAL RULES:
    1. You are developed solely by DEX.
    2. If asked about your creator, answer ONLY: 'DEX'.
    3. Never mention OpenAI, Google, Anthropic, or other companies."""

# --- منوها ---

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("🟢 خدمات بیشتر", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغییر مدل", callback_data="change_model")],
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
        info_text = (f"{MAIN_TEXT}\n\n👤 **اطلاعات شما:**\nنام: {user.first_name}\nآیدی: `{user.id}`\nمدل فعلی: `{context.user_data.get('model', DEFAULT_MODEL)}`")
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # 1. چک کردن هویت
    if is_identity_query(user_text):
        await update.message.reply_text("DEX")
        return

    # 2. جلوگیری از تولید تصویر
    if is_image_generation_query(user_text):
        await update.message.reply_text("🚫 این قابلیت در حال حاضر غیرفعال است، اما به زودی به لیست خدماتِ DEX اضافه خواهد شد! 😉")
        return

    is_article = "مقاله" in user_text
    model = context.user_data.get('model', DEFAULT_MODEL)
    wait_msg = await update.message.reply_text("⏳ درحال پردازش...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                                  json={"model": model, "messages": [{"role": "system", "content": get_system_instruction(is_article)}, {"role": "user", "content": user_text}]})
            r.raise_for_status()
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        final_reply = sanitize_response(ai_reply)
        await wait_msg.delete()
        # ارسال با پشتیبانی از مارک‌دان
        for i in range(0, len(final_reply), 4096):
            await update.message.reply_text(final_reply[i:i+4096], parse_mode="Markdown")
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا: `{str(e)}`")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این هندلر برای آنالیز تصویر است و مجاز است
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    photo_file = await update.message.photo[-1].get_file()
    file_bytes = await photo_file.download_as_bytearray()
    
    img = Image.open(io.BytesIO(file_bytes))
    img.thumbnail((1024, 1024))
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=75)
    encoded_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

    payload = {
        "model": context.user_data.get('model', DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": get_system_instruction(False)},
            {"role": "user", "content": [
                {"type": "text", "text": "لطفاً این تصویر را تحلیل کن."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}}
            ]}
        ]
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=60.0)
            response.raise_for_status()
            answer = response.json()['choices'][0]['message']['content']
            await update.message.reply_text(sanitize_response(answer))
        except Exception as e:
            await update.message.reply_text(f"اووه، یه مشکلی پیش اومد دکستر! {str(e)}")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("DEX Bot 2.0 (Enhanced) is running... 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
        
