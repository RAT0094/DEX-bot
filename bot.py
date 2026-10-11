import os
import httpx
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, 
                          MessageHandler, ContextTypes, filters, ConversationHandler)

logging.basicConfig(level=logging.INFO)

# --- کانفیگ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
IMAGE_MODEL = "claude-opus-5.5" 

# لیست مدل‌ها همراه با ایموجی
MODELS_WITH_EMOJI = {
    "gpt-5.6-luna": "🌙",
    "claude-opus-5.5": "🎭",
    "gpt-5.5": "⚡",
    "gpt-5.5-pro": "🚀",
    "claude-fable-5": "📖",
    "claude-fable-5.1": "✨"
}

# وضعیت‌ها
CHOOSING, GENERATING_IMAGE = range(2)

# --- پیام‌ها ---
WELCOME_MESSAGE = "سلام دوست عزیز، چه کمکی از دستم برمی‌آید؟\n\n✨ به دنیای DEX خوش آمدید"
IMAGE_MODE_MESSAGE = "🎨 حالت ساخت تصویر فعال شد!\nتوصیف تصویرت را بفرست."

# --- پرامپت جدید برای زیباسازی پیام - اضافه شده ---
BEAUTIFY_INSTRUCTION = """
همیشه این قوانین نگارشی را رعایت کن:
1. در همه‌ی پیام‌ها از ایموجی مرتبط استفاده کن تا پیام زنده و زیبا باشد.
2. اسم بازی، فیلم، کتاب یا اصطلاحات خاص را حتما با **Bold** یا `mono` یا > نقل قول نمایش بده.
3. اگر کد، اسکریپت یا دستور برنامه‌نویسی می‌دهی حتما آن را داخل بلاک کد  قرار بده.
4. برای نقل قول از > در ابتدای خط استفاده کن.
5. از Markdown تلگرام استفاده کن.
"""

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚪ اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("🟢 ابزارها", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode")],
        [InlineKeyboardButton("🔄 تغییر مدل", callback_data="change_model")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])

# --- هندلرها ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "model" not in context.user_data: 
        context.user_data["model"] = DEFAULT_MODEL
    await update.message.reply_text(WELCOME_MESSAGE, reply_markup=get_main_menu())
    return CHOOSING

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data == "user_info":
            # === ویرایش شده: حالت شیشه‌ای ===
            user = update.effective_user
            current_model = context.user_data.get("model", DEFAULT_MODEL)
            emoji = MODELS_WITH_EMOJI.get(current_model, "✨")
            
            info = (
                f"✨ **پروفایل شیشه‌ای DEX** ✨\n"
                f"╭─────────── 🪞 ───────────╮\n"
                f"│ 👤 **نام:** `{user.first_name}`\n"
                f"│ 🆔 **شناسه:** `{user.id}`\n"
                f"│ {emoji} **مدل فعال:** `{current_model}`\n"
                f"╰───────────────────────────╯\n"
                f"_🔮 شفاف مثل شیشه، براق مثل الماس_"
            )
            await query.edit_message_text(
                info,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
            )
            return CHOOSING
            
        elif query.data == "more_services":
            await query.edit_message_text("بخش ابزارهای DEX:", reply_markup=get_services_menu())
            return CHOOSING
            
        elif query.data == "gen_mode":
            await query.edit_message_text(IMAGE_MODE_MESSAGE, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]]))
            return GENERATING_IMAGE
            
        elif query.data == "back_main":
            await query.edit_message_text(WELCOME_MESSAGE, reply_markup=get_main_menu())
            return CHOOSING
            
        elif query.data == "change_model":
            buttons = [[InlineKeyboardButton(f"{emoji} {model}", callback_data=f"set_{model}")] for model, emoji in MODELS_WITH_EMOJI.items()]
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="more_services")])
            await query.edit_message_text("🔄 یک مدل برگزین:", reply_markup=InlineKeyboardMarkup(buttons))
            return CHOOSING
            
        elif query.data.startswith("set_"):
            new_model = query.data[4:]
            context.user_data["model"] = new_model
            selected_emoji = MODELS_WITH_EMOJI.get(new_model, "✅")
            text = f"{selected_emoji} مدل با موفقیت به {new_model} دگرگون شد!"
            await query.edit_message_text(text, reply_markup=get_main_menu())
            return CHOOSING
    except Exception as e:
        logging.error(f"Error in button_handler: {e}")
        try:
            await query.edit_message_text("❌ خطایی رخ داد، دوباره /start بزن", reply_markup=get_main_menu())
        except:
            pass
        return CHOOSING

async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    status_msg = await update.message.reply_text("⏳ در حال پردازش... ✨\nتصویرت در حال ساخته شدنه 🎨")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{CLEANAPIS_BASE_URL}/v1/chat/completions", 
                headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": IMAGE_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a creative visual engine. If you can provide a direct image URL, do so. If not, describe the scene."},
                        {"role": "user", "content": f"Generate a visual representation for: {prompt}"}
                    ]
                }
            )
            r.raise_for_status()
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            
            url_pattern = r"https?://[^\s<>\"\)]+\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s<>\"\)]*)?"
            urls = re.findall(url_pattern, answer, re.IGNORECASE)
            if not urls:
                urls = re.findall(r"https?://[^\s<>\"\)]+", answer)
            
            try:
                await status_msg.delete()
            except:
                pass

            if urls:
                image_url = urls[0].strip().rstrip(").>")
                await update.message.reply_photo(photo=image_url, caption="🖼️ تصویر با موفقیت ساخته شد ✅✨")
            else:
                await update.message.reply_text(f"🖼 پاسخِ {IMAGE_MODEL}:\n\n{answer}")
            
                
    except Exception as e:
        logging.error(f"Image error: {e}")
        try:
            await status_msg.edit_text(f"❌ خطای سیستم: {str(e)}")
        except:
            await update.message.reply_text(f"❌ خطای سیستم: {str(e)}")
        
    return GENERATING_IMAGE

# --- هندلر پیام اصلی ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    status_msg = await update.message.reply_text("⏳ در حال پردازش... ✨\nلطفا کمی صبر کن 🤖💭")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", 
                                  headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                                  json={"model": context.user_data.get("model", DEFAULT_MODEL), 
                                        "messages": [
                                            {"role": "system", "content": f"You are a helpful assistant developed by DEX. {BEAUTIFY_INSTRUCTION}"}, 
                                            {"role": "user", "content": text}
                                        ]})
            
            r.raise_for_status()
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            answer = answer.replace("OpenAI", "DEX").replace("Google", "DEX").replace("Anthropic", "DEX")
            
            try:
                await status_msg.delete()
            except:
                pass

            try:
                await update.message.reply_text(answer, parse_mode="Markdown")
            except:
                await update.message.reply_text(answer)

    except Exception as e:
        logging.error(f"Message error: {e}")
        try:
            await status_msg.edit_text(f"❌ خطا در ارتباط با سرور: {str(e)}")
        except:
            await update.message.reply_text(f"❌ خطا در ارتباط با سرور: {str(e)}")
    return CHOOSING

def main():
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        print("❌ TELEGRAM_BOT_TOKEN یا CLEANAPIS_API_KEY تنظیم نشده!")
        return
        
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [CallbackQueryHandler(button_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            GENERATING_IMAGE: [CallbackQueryHandler(button_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_prompt)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    print("DEX Bot (Fixed Edition) is running... 🚀")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
