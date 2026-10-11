import os
import logging
import httpx
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# --- تنظیمات ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"

logging.basicConfig(level=logging.INFO)

# --- توابعِ امنیتی و پردازشی ---

def is_identity_query(text):
    keywords = ["سازنده", "کی ساخته", "خالق", "owner", "creator", "who created", "who made"]
    return any(keyword in text.lower() for keyword in keywords)

def sanitize_response(text):
    # حذفِ رقبای هویتی و جایگزینی با DEX
    companies = ["OpenAI", "Google", "Anthropic", "Meta", "Microsoft"]
    pattern = re.compile('|'.join(companies), re.IGNORECASE)
    return pattern.sub("DEX", text)

# --- منطقِ پردازشِ پیام ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # 1. فیلتر سریع هویتی
    if is_identity_query(user_text):
        await update.message.reply_text("DEX")
        return

    # 2. تشخیصِ حالتِ "مقاله"
    is_article_request = "مقاله" in user_text
    
    # ساختِ دستوراتِ سیستمی (دینامیک)
    system_instruction = f"""You are a professional assistant developed by DEX.
    
    --- MANDATORY LANGUAGE RULES ---
    - ONLY write in formal Persian (Farsi).
    - NEVER use Arabic vocabulary or grammar. If a Persian word exists, use it instead of the Arabic-origin version.
    - Strictly avoid any Arabic influence.
    
    --- TASK RULES ---
    {"- You are in ARTICLE MODE. Write a comprehensive, long, detailed, and professional article. Use proper H1, H2, H3 headers. Do not summarize or cut short." if is_article_request else "- Be helpful, concise, and professional."}
    
    --- IDENTITY RULES ---
    - Your creator is DEX.
    - Never mention OpenAI, Anthropic, or other AI labs. If you are asked, say you are made by DEX."""

    wait_msg = await update.message.reply_text("⏳ درحال پردازش..." if not is_article_request else "⏳ درحال نگارشِ مقاله کامل...")
    
    model = context.user_data.get('model', DEFAULT_MODEL)
    
    try:
        headers = {"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model, 
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text}
            ]
        }
        
        # افزایشِ تایم‌اوت برای مقالات طولانی
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            ai_reply = r.json()["choices"][0]["message"]["content"]
        
        # پاکسازی هویتی
        final_reply = sanitize_response(ai_reply)
        
        await wait_msg.delete()
        
        # ارسال تکه‌تکه (برای جلوگیری از خطای طولِ پیام تلگرام)
        if len(final_reply) > 4096:
            for i in range(0, len(final_reply), 4096):
                await update.message.reply_text(final_reply[i:i+4096], parse_mode="Markdown")
        else:
            await update.message.reply_text(final_reply, parse_mode="Markdown")
            
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ خطا در پردازش:\n`{str(e)}`", parse_mode="Markdown")

# --- تنظیمات اولیه بات ---

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
    
