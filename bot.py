import os
import httpx
import re
import io
import time
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, 
                          MessageHandler, ContextTypes, filters, ConversationHandler)

# --- کانفیگ ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
IMAGE_MODEL = "claude-opus-5.5" 

CHOOSING, GENERATING_IMAGE = range(2)

# --- پیام‌های اصلی (تغییر ناپذیر) ---
WELCOME_MESSAGE = "سلام دوست عزیز، چطور می‌تونم کمکت کنم؟\n\n✨ به دنیای DEX خوش آمدید"
IMAGE_MODE_MESSAGE = f"🎨 حالت ساخت تصویر با مدلِ {IMAGE_MODEL} فعال شد!\nتوصیفِ تصویرت رو بفرست تا برات خلقش کنم."

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 اطلاعات کاربر", callback_data="user_info")],
        [InlineKeyboardButton("🟢 ابزارها", callback_data="more_services")]
    ])

def get_services_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode")],
        [InlineKeyboardButton("⚙️ گزینش مدل", callback_data="change_model")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])

# --- هندلرها ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'model' not in context.user_data: context.user_data['model'] = DEFAULT_MODEL
    await update.message.reply_text(WELCOME_MESSAGE, reply_markup=get_main_menu())
    return CHOOSING

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "user_info":
        user = update.effective_user
        info = f"👤 اطلاعات کاربر\nنام: {user.first_name}\nشناسه: `{user.id}`\nمدل فعال: `{context.user_data.get('model', DEFAULT_MODEL)}`"
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")
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
        buttons = [[InlineKeyboardButton(m, callback_data=f"set_{m}")] for m in ["gpt-5.6-luna", "claude-opus-5.5", "gpt-5.5"]]
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="more_services")])
        await query.edit_message_text("یک مدل برگزین:", reply_markup=InlineKeyboardMarkup(buttons))
        return CHOOSING
        
    elif query.data.startswith("set_"):
        context.user_data['model'] = query.data.replace("set_", "")
        await query.edit_message_text("مدل با موفقیت دگرگون شد!", reply_markup=get_main_menu())
        return CHOOSING

# --- هندلر تصویرِ ضدِ کش (Anti-Cache) ---
async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    status_msg = await update.message.reply_text("⏳ در حال تولید یک تصویرِ کاملاً جدید...")
    
    try:
        # 1. تولید seed تصادفی برای شکستنِ کشِ سرور
        unique_seed = int(time.time())
        
        # 2. تقویتِ پرامپت برای دقتِ بالاتر
        enhanced_prompt = f"{prompt}, highly detailed, unique digital art, 8k, photorealistic"
        encoded_prompt = urllib.parse.quote(enhanced_prompt)
        
        # 3. ساخت URL با پارامترهای اجبار‌کننده‌ی بازتولید
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={unique_seed}"
        
        async with httpx.AsyncClient(timeout=45.0) as img_client:
            # 4. درخواست با هدرِ غیرکش‌شونده
            img_response = await img_client.get(image_url, headers={"Cache-Control": "no-cache"})
            
            if img_response.status_code == 200:
                photo_bytes = io.BytesIO(img_response.content)
                photo_bytes.name = "image.png"
                await update.message.reply_photo(photo=photo_bytes, caption="عکس ساخته شد")
            else:
                await update.message.reply_text(f"❌ خطای سرور تصویر: کد {img_response.status_code}")
        
        await status_msg.delete()
                
    except Exception as e:
        await status_msg.edit_text(f"❌ خطای سیستم: {str(e)}")
        
    return GENERATING_IMAGE

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", 
                              headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"},
                              json={"model": context.user_data.get('model', DEFAULT_MODEL), 
                                    "messages": [{"role": "system", "content": "You are a helpful assistant developed by DEX."}, {"role": "user", "content": text}]})
        
        answer = r.json()["choices"][0]["message"]["content"]
        answer = answer.replace("OpenAI", "DEX").replace("Google", "DEX").replace("Anthropic", "DEX")
        await update.message.reply_text(answer, parse_mode="Markdown")
    return CHOOSING

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [CallbackQueryHandler(button_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            GENERATING_IMAGE: [CallbackQueryHandler(button_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_prompt)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    app.add_handler(conv_handler)
    print("DEX Bot (Anti-Cache, Forced Generation Mode) is running... 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
  
