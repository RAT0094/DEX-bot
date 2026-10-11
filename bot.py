import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# تنظیمات اولیه
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
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

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                     f"آیدی: `{user.id}`")
        await query.edit_message_text(info_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]]), parse_mode="Markdown")

    # مدیریت دکمه "خدمات بیشتر"
    elif query.data == "more_services":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_services_menu())

    # بازگشت به منوی اصلی
    elif query.data == "back_main":
        await query.edit_message_text(MAIN_TEXT, reply_markup=get_main_menu())

    # پیام "به زودی" برای دکمه غیرفعال
    elif query.data == "img_soon":
        await query.answer("به زودی اضافه می‌شود!", show_alert=True)

    # placeholder برای تغییر مدل
    elif query.data == "change_model":
        await query.answer("در حال ساخت این بخش...", show_alert=False)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.run_polling()

if __name__ == "__main__":
    main()
    
