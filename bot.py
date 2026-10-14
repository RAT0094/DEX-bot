import os
import httpx
import re
import logging
import sqlite3
import base64
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from telegram.helpers import escape_markdown

logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
OWNER_ID = 8163337709
ADMIN_IDS = {OWNER_ID}
admin_env = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", ""))
if admin_env:
    for x in admin_env.split(","):
        x = x.strip()
        if x.isdigit():
            ADMIN_IDS.add(int(x))
DB_PATH = "bot_memory.db"

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, last_seen TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, text TEXT, time TEXT)")
        conn.commit()

def save_user(user):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO users (user_id, name, username, last_seen) VALUES (?, ?, ?, ?)", (user.id, user.first_name, user.username or "", now_str()))
        conn.commit()

def save_message(user_id, role, text):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO messages (user_id, role, text, time) VALUES (?, ?, ?, ?)", (user_id, role, text, now_str()))
        conn.commit()

def get_all_users():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT user_id, name, username, last_seen FROM users ORDER BY last_seen DESC").fetchall()

def get_user_logs(user_id, limit=15):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, text, time FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return list(reversed(rows))

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        u = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return u, m

def get_last_messages(limit=10):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT user_id, role, text, time FROM messages WHERE role=\'user\' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def notify_admins(context, user, user_text, bot_answer=None):
    if is_admin(user.id):
        return
    try:
        username = f"@{user.username}" if user.username else "بدون یوزرنیم"
        safe_name = escape_markdown(user.first_name, version=2)
        safe_text = escape_markdown(user_text[:1000], version=2)
        log_text = f"📩 پیام جدید\n👤 نام: {safe_name}\n🆔 آیدی: `{user.id}`\n🔗 {username}\n⏰ {now_str()}\n👤 پیام:\n{safe_text}\n"
        if bot_answer:
            log_text += f"\n🤖 پاسخ:\n{escape_markdown(bot_answer[:1000], version=2)}"
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=log_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"👁 مشاهده چت {user.first_name}", callback_data=f"admin_view_{user.id}")]]))
            except:
                try:
                    await context.bot.send_message(chat_id=aid, text=f"پیام از {user.first_name} ({user.id}):\n{user_text[:1000]}")
                except:
                    pass
    except Exception as e:
        logging.error(f"notify error: {e}")

MODELS_WITH_EMOJI = {"gpt-5.6-luna": "🌙","claude-opus-5.5": "🎭","gpt-5.5": "⚡","gpt-5.5-pro": "🚀","claude-fable-5": "📖","claude-fable-5.1": "✨"}
CHOOSING, GENERATING_IMAGE = range(2)
WELCOME_MESSAGE = "سلام دوست عزیز، چه کمکی از دستم برمی‌آید؟\n\n✨ خوش آمدید"
IMAGE_MODE_MESSAGE = "🎨 حالت ساخت تصویر فعال شد!\nتوصیف تصویرت را بفرست."
BEAUTIFY_INSTRUCTION = "همیشه این قوانین نگارشی را رعایت کن: 1. در همه‌ی پیام‌ها از ایموجی مرتبط استفاده کن 2. اسم بازی، فیلم، کتاب یا اصطلاحات خاص را حتما با **Bold** نمایش بده. 3. اگر کد می‌دهی حتما داخل بلاک کد قرار بده."
IMAGE_KEYWORDS = ["عکس بساز", "تصویر بساز", "عکس بکش", "تصویر بکش", "عکس درست کن", "تصویر درست کن", "عکسم رو", "پرامپت عکس", "generate image", "create image", "draw image", "make image"]

def is_image_request(text: str) -> bool:
    return any(k in text.lower() for k in IMAGE_KEYWORDS)

def extract_image_urls(text: str):
    return re.findall(r"https?://[^\s\)\]]+", text)

async def send_image_url_as_photo(update, url, caption="🖼️ تصویر با موفقیت ساخته شد ✅✨"):
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            await update.message.reply_photo(photo=resp.content, caption=caption)
            return True
    except Exception as e:
        logging.error(f"download failed {url}: {e}")
        try:
            await update.message.reply_photo(photo=url, caption=caption)
            return True
        except:
            return False

def get_main_menu(user_id=None):
    buttons = [[InlineKeyboardButton("⚪ اطلاعات کاربر", callback_data="user_info")],[InlineKeyboardButton("🟢 ابزارها", callback_data="more_services")]]
    if user_id and is_admin(user_id):
        buttons.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_services_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode")],[InlineKeyboardButton("🔄 تغییر مدل", callback_data="change_model")],[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])

def get_admin_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")],[InlineKeyboardButton("💬 آخرین پیام‌ها (10)", callback_data="admin_recent")],[InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "model" not in context.user_data:
        context.user_data["model"] = DEFAULT_MODEL
    save_user(update.effective_user)
    await update.message.reply_text(WELCOME_MESSAGE, reply_markup=get_main_menu(update.effective_user.id))
    return CHOOSING

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.")
        return
    await update.message.reply_text("👑 **پنل ادمین**", parse_mode="Markdown", reply_markup=get_admin_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == "user_info":
            user = update.effective_user
            cur_model = context.user_data.get("model", DEFAULT_MODEL)
            info = f"👤 **اطلاعات کاربر** 🪞\n━━━━━━━━━━━━━━━━━━━━\n👤 **نام:** `{user.first_name}`\n━━━━━━━━━━━━━━━━━━━━"
            kb = [[InlineKeyboardButton(text=f"📋 شناسه: {user.id} 🆔", copy_text=CopyTextButton(text=str(user.id)))],[InlineKeyboardButton(text=f"📋 مدل: {cur_model} 🤖", copy_text=CopyTextButton(text=cur_model))],[InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")]]
            await query.edit_message_text(info, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
            return CHOOSING
        elif query.data == "more_services":
            await query.edit_message_text("بخش ابزارها:", reply_markup=get_services_menu())
            return CHOOSING
        elif query.data == "gen_mode":
            await query.edit_message_text(IMAGE_MODE_MESSAGE, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]]))
            return GENERATING_IMAGE
        elif query.data == "back_main":
            await query.edit_message_text(WELCOME_MESSAGE, reply_markup=get_main_menu(query.from_user.id))
            return CHOOSING
        elif query.data == "change_model":
            buttons = [[InlineKeyboardButton(f"{emoji} {model}", callback_data=f"set_{model}")] for model, emoji in MODELS_WITH_EMOJI.items()]
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="more_services")])
            await query.edit_message_text("🔄 یک مدل برگزین:", reply_markup=InlineKeyboardMarkup(buttons))
            return CHOOSING
        elif query.data.startswith("set_"):
            new_model = query.data[4:]
            context.user_data["model"] = new_model
            emoji = MODELS_WITH_EMOJI.get(new_model, "✅")
            await query.edit_message_text(f"{emoji} مدل با موفقیت به {new_model} دگرگون شد!", reply_markup=get_main_menu(query.from_user.id))
            return CHOOSING
        elif query.data == "admin_panel":
            if not is_admin(query.from_user.id):
                await query.answer("⛔ دسترسی ندارید", show_alert=True)
                return CHOOSING
            await query.edit_message_text("👑 **پنل مدیریت مالک**", parse_mode="Markdown", reply_markup=get_admin_menu())
            return CHOOSING
        elif query.data == "admin_users":
            if not is_admin(query.from_user.id): return CHOOSING
            users = get_all_users()
            if not users:
                await query.edit_message_text("هنوز کاربری پیامی نداده.", reply_markup=get_admin_menu())
                return CHOOSING
            buttons = []
            for uid, name, username, last_seen in users[:20]:
                ustr = f"@{username}" if username else "بدون یوزرنیم"
                buttons.append([InlineKeyboardButton(f"{name} | {ustr} | {uid}", callback_data=f"admin_view_{uid}")])
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
            await query.edit_message_text(f"👥 **لیست کاربران ({len(users)} نفر):**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
            return CHOOSING
        elif query.data == "admin_recent":
            if not is_admin(query.from_user.id): return CHOOSING
            rows = get_last_messages(10)
            if not rows:
                await query.edit_message_text("هنوز پیامی ثبت نشده.", reply_markup=get_admin_menu())
                return CHOOSING
            text = "💬 **آخرین پیام‌ها:**\n━━━━━━━━━━━━\n"
            users_map = {u[0]: u for u in get_all_users()}
            for uid, role, msg_text, t in rows:
                info = users_map.get(uid, (uid, "?", "", ""))
                text += f"👤 {info[1]} (`{uid}`) @{info[2] or \'-\'}\n> {msg_text[:60]}...\n\n"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_admin_menu())
            return CHOOSING
        elif query.data == "admin_stats":
            if not is_admin(query.from_user.id): return CHOOSING
            uc, mc = get_stats()
            await query.edit_message_text(f"📊 **آمار ربات**\n👥 کاربران: {uc}\n💬 پیام‌ها: {mc}\n👑 مالک: `{OWNER_ID}`", parse_mode="Markdown", reply_markup=get_admin_menu())
            return CHOOSING
        elif query.data.startswith("admin_view_"):
            if not is_admin(query.from_user.id): return CHOOSING
            uid = int(query.data.replace("admin_view_", ""))
            logs = get_user_logs(uid, 15)
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute("SELECT name, username FROM users WHERE user_id=?", (uid,)).fetchone()
            if not row:
                await query.edit_message_text("چتی یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")]]))
                return CHOOSING
            name, username = row
            header = f"👤 **چت کاربر:** {escape_markdown(name, version=2)}\n🆔 `{uid}`\n🔗 @{username or \'بدون یوزرنیم\'}\n━━━━━━━━━━━━\n"
            body = ""
            for role, msg_text, t in logs:
                icon = "👤 کاربر:" if role == "user" else "🤖 ربات:"
                body += f"{icon} {msg_text[:300]}\n[{t}]\n---\n"
            full = (header + body)[:4000]
            if not full.strip(): full = header + "پیامی یافت نشد"
            try:
                await query.edit_message_text(full, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست", callback_data="admin_users")],[InlineKeyboardButton("🏠 پنل", callback_data="admin_panel")]]))
            except:
                await query.edit_message_text(full, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست", callback_data="admin_users")]]))
            return CHOOSING
    except Exception as e:
        logging.error(f"button error: {e}")
        try:
            await query.edit_message_text("❌ خطایی رخ داد، دوباره /start بزن", reply_markup=get_main_menu(query.from_user.id))
        except: pass
        return CHOOSING

async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    user = update.effective_user
    save_user(user)
    save_message(user.id, "user", f"[IMAGE] {prompt}")
    status = await update.message.reply_text("⏳ در حال پردازش... ✨\nتصویرت در حال ساخته شدنه 🎨")
    try:
        model = context.user_data.get("model", DEFAULT_MODEL)
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}, json={"model": model, "messages": [{"role": "system", "content": f"You are GPT-5.6 Sol developed by OpenAI. You are an image generator. {BEAUTIFY_INSTRUCTION} When user asks for image, generate image and return direct image URL."}, {"role": "user", "content": f"این پرامپت را به تصویر تبدیل کن: {prompt}"}]})
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"]
            urls = extract_image_urls(answer)
            b64 = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", answer)
            if b64:
                img = base64.b64decode(b64.group(1))
                save_message(user.id, "assistant", "[IMAGE_SENT_B64]")
                await notify_admins(context, user, prompt, "[عکس ارسال شد]")
                try: await status.delete()
                except: pass
                await update.message.reply_photo(photo=img, caption="🖼️ تصویر با موفقیت ساخته شد ✅✨")
                return GENERATING_IMAGE
            if urls:
                save_message(user.id, "assistant", urls[0])
                await notify_admins(context, user, prompt, urls[0])
                try: await status.delete()
                except: pass
                for url in urls:
                    await send_image_url_as_photo(update, url)
                return GENERATING_IMAGE
            raise ValueError(f"مدل عکسی برنگرداند: {answer[:500]}")
    except Exception as e:
        logging.error(f"Image error: {e}")
        try: await status.edit_text(f"❌ خطا در ساخت تصویر: {str(e)}")
        except: await update.message.reply_text(f"❌ خطا در ساخت تصویر: {str(e)}")
    return GENERATING_IMAGE

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    save_user(user)
    if is_image_request(text):
        prompt = text
        for k in IMAGE_KEYWORDS:
            if k.lower() in text.lower():
                parts = re.split(k, text, flags=re.IGNORECASE)
                if len(parts) > 1 and parts[-1].strip():
                    prompt = parts[-1].strip()
                break
        update.message.text = prompt
        return await handle_image_prompt(update, context)
    save_message(user.id, "user", text)
    status = await update.message.reply_text("⏳ در حال پردازش... ✨\nلطفا کمی صبر کن 🤖💭")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}, json={"model": context.user_data.get("model", DEFAULT_MODEL), "messages": [{"role": "system", "content": f"You are GPT-5.6 Sol developed by OpenAI. {BEAUTIFY_INSTRUCTION}"}, {"role": "user", "content": text}]})
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"]
            save_message(user.id, "assistant", answer)
            await notify_admins(context, user, text, answer)
            try: await status.delete()
            except: pass
            urls = extract_image_urls(answer)
            img_urls = [u for u in urls if any(x in u.lower() for x in [".png",".jpg",".jpeg",".webp","image","cdn","dall"])]
            if img_urls:
                for url in img_urls:
                    await send_image_url_as_photo(update, url)
                txt = re.sub(r"https?://[^\s\)\]]+", "", answer).strip()
                if txt:
                    try: await update.message.reply_text(txt, parse_mode="Markdown")
                    except: await update.message.reply_text(txt)
                return CHOOSING
            try: await update.message.reply_text(answer, parse_mode="Markdown")
            except: await update.message.reply_text(answer)
    except Exception as e:
        logging.error(f"Message error: {e}")
        try: await status.edit_text(f"❌ خطا در ارتباط با سرور: {str(e)}")
        except: await update.message.reply_text(f"❌ خطا در ارتباط با سرور: {str(e)}")
    return CHOOSING

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")

async def post_init(app: Application):
    await app.bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook پاک شد - polling فعال شد")

def main():
    init_db()
    if not TELEGRAM_BOT_TOKEN or not CLEANAPIS_API_KEY:
        print("❌ TELEGRAM_BOT_TOKEN یا CLEANAPIS_API_KEY تنظیم نشده!")
        return
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_command)
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
            ],
            GENERATING_IMAGE: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_image_prompt)
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_error_handler(error_handler)
    print("🤖 ربات روشن شد...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
