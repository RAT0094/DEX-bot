import os
import re
import base64
import sqlite3
import logging
import asyncio
from datetime import datetime
from aiohttp import web
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- تنظیمات و لاگ -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY", "YOUR_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
OWNER_ID = 8163337709
DB_PATH = "bot_memory.db"

BEAUTIFY_INSTRUCTION = "پاسخ‌ها را بسیار دقیق، زیبا، ساختاریافته، جذاب و با استفاده از ایموجی‌های مناسب به زبان فارسی روان ارائه بده."

MODELS_WITH_EMOJI = {
    "gpt-5.6-luna": "🌙💎",
    "claude-opus-5.5": "🎭✨",
    "gpt-5.5": "⚡🚀",
    "gpt-5.5-pro": "🚀👑",
    "claude-fable-5": "📖💫",
    "claude-fable-5.1": "✨👑"
}

IMAGE_KEYWORDS = ["عکس", "تصویر", "نقاشی", "طراحی", "image", "draw", "paint"]

# ----------------- دیتابیس -----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, joined_at)
        VALUES (?, ?, ?, ?, COALESCE((SELECT joined_at FROM users WHERE user_id = ?), ?))
    """, (user.id, user.username, user.first_name, user.last_name, user.id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_message(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (user_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, joined_at FROM users")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user_logs(user_id, limit=20):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, timestamp FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows[::-1]

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM messages")
    messages_count = cursor.fetchone()[0]
    conn.close()
    return users_count, messages_count

def get_last_messages(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT m.user_id, u.username, m.role, m.content, m.timestamp FROM messages m LEFT JOIN users u ON m.user_id = u.user_id ORDER BY m.id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows[::-1]

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID

# ----------------- توابع کمکی -----------------
def is_image_request(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in IMAGE_KEYWORDS)

def extract_image_urls(text: str):
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
    found = url_pattern.findall(text)
    image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
    img_urls = []
    for u in found:
        if any(u.lower().endswith(ext) or 'image' in u.lower() or 'img' in u.lower() or 'cleanapis' in u.lower() for ext in image_extensions):
            img_urls.append(u)
    return img_urls

def get_main_menu(user_id: int):
    keyboard = [
        [InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode"), InlineKeyboardButton("🛠️ سرویس‌ها و مدل‌ها", callback_data="services_menu")],
        [InlineKeyboardButton("💎 درباره ربات", callback_data="about")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def get_services_menu(current_model: str):
    rows = []
    for model_key, emoji in MODELS_WITH_EMOJI.items():
        name = model_key
        if model_key == current_model:
            name = f"✅ {name}"
        rows.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"set_{model_key}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def get_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 کاربران ربات", callback_data="admin_users"), InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats")],
        [InlineKeyboardButton("💬 آخرین پیام‌ها", callback_data="admin_recent"), InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
    ])

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, user, prompt, answer):
    text = f"🚨 گزارش فعالیت جدید:\n👤 کاربر: {user.first_name} (@{user.username or 'ندارد'} | `{user.id}`)\n📌 درخواست/متن:\n{prompt}\n\n🤖 پاسخ/خروجی:\n{answer}"
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Failed to notify admin: {e}")

async def send_image_url_as_photo(update: Update, url: str):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                await update.message.reply_photo(photo=resp.content, caption="🖼️ تصویر با موفقیت ساخته شد ✅✨💎")
                return
    except Exception as e:
        logging.error(f"Failed to fetch image url {url}: {e}")
    await update.message.reply_text(f"🖼️ لینک تصویر مستقیم:\n{url}")

# ----------------- سرور سلامت (Health Check) -----------------
async def health_handler(request):
    return web.Response(text="Bot is running smoothly! 🚀✨💎")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Health server started on port {port}")

# ----------------- هندلرهای دستورات -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    context.user_data.setdefault("model", DEFAULT_MODEL)
    text = f"سلام {user.first_name} عزیز! 🌸✨\nبه ربات هوش مصنوعی پیشرفته خوش آمدید. 🤖💎\n\nمی‌تونی سوالاتت رو بپرسی یا درخواست ساخت عکس بدی! 🚀"
    await update.message.reply_text(text, reply_markup=get_main_menu(user.id))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ شما اجازه دسترسی به این دستور را ندارید!")
        return
    await update.message.reply_text("👑 خوش آمدید ادمین عزیز! پنل مدیریت:", reply_markup=get_admin_menu())

# ----------------- هندلر دکمه‌های شیشه‌ای (Callback) -----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    try:
        if data == "main_menu":
            await query.edit_message_text("🏠 منوی اصلی ربات:", reply_markup=get_main_menu(user.id))
        elif data == "services_menu":
            current_model = context.user_data.get("model", DEFAULT_MODEL)
            await query.edit_message_text("🛠️ مدل هوش مصنوعی خود را انتخاب کنید:", reply_markup=get_services_menu(current_model))
        elif data == "gen_mode":
            context.user_data["awaiting_image"] = True
            await query.edit_message_text("🎨 لطفاً پرامپت یا توضیحات تصویر مورد نظرت رو بفرست: ✨💎", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
        elif data.startswith("set_"):
            new_model = data[4:]
            if new_model in MODELS_WITH_EMOJI:
                context.user_data["model"] = new_model
                await query.edit_message_text(f"✅ مدل با موفقیت تغییر کرد به: {new_model} {MODELS_WITH_EMOJI[new_model]}", reply_markup=get_main_menu(user.id))
            else:
                await query.edit_message_text("❌ مدل نامعتبر است.", reply_markup=get_main_menu(user.id))
        elif data == "about":
            await query.edit_message_text("💎 ربات هوش مصنوعی پیشرفته\nقدرت گرفته توسط DEX.\nطراحی شده برای سرعت و دقت بالا. 🚀✨", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
        elif data == "admin_panel":
            if not is_admin(user.id):
                await query.edit_message_text("⛔ دسترسی غیرمجاز!")
                return
            await query.edit_message_text("👑 پنل مدیریت پیشرفته:", reply_markup=get_admin_menu())
        elif data == "admin_stats":
            if not is_admin(user.id):
                return
            users_c, msg_c = get_stats()
            text = f"📊 آمار کلی ربات:\n👥 تعداد کل کاربران: {users_c}\n💬 تعداد کل پیام‌ها: {msg_c} 🚀✨"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data == "admin_users":
            if not is_admin(user.id):
                return
            users = get_all_users()
            keyboard = []
            for u in users[:20]:
                u_id, uname, fname, _ = u
                name = fname or uname or str(u_id)
                keyboard.append([InlineKeyboardButton(f"👤 {name} ({u_id})", callback_data=f"admin_view_{u_id}")])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
            await query.edit_message_text("👥 کاربران ربات:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif data == "admin_recent":
            if not is_admin(user.id):
                return
            recent = get_last_messages(10)
            text = "💬 آخرین پیام‌های رد و بدل شده:\n\n"
            for m in recent:
                u_id, uname, role, content, ts = m
                text += f"▪️ [`{u_id}` | @{uname or 'ندارد'}] ({role}):\n{content[:100]}\n-----\n"
            await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data.startswith("admin_view_"):
            if not is_admin(user.id):
                return
            target_id = int(data.split("_")[2])
            logs = get_user_logs(target_id, 15)
            text = f"📜 تاریخچه کاربر `{target_id}`:\n\n"
            for role, content, ts in logs:
                text += f"🔹 **{role}**: {content[:150]}\n"
            await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست ↩️", callback_data="admin_users")]]))
    except Exception as e:
        logging.error(f"button error: {e}", exc_info=True)
        try:
            await query.edit_message_text("❌ خطایی رخ داد، دوباره /start بزن 💎", reply_markup=get_main_menu(query.from_user.id))
        except Exception:
            pass

# ----------------- هندلرهای تصاویر و پیام‌ها (همراه با Retry هوشمند) -----------------
async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str = None):
    if prompt is None:
        prompt = update.message.text or ""
    user = update.effective_user
    save_user(user)
    save_message(user.id, "user", f"[IMAGE] {prompt}")
    status = await update.message.reply_text("⏳ در حال پردازش تصویر... ✨💎\nدسترسی به سرور گرافیکی 🎨")
    
    max_retries = 3
    retry_delay = 3
    answer = None
    
    for attempt in range(1, max_retries + 1):
        try:
            model = context.user_data.get("model", DEFAULT_MODEL)
            async with httpx.AsyncClient(timeout=90.0) as client:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": f"You are an advanced AI assistant created by DEX. You are an image generator. {BEAUTIFY_INSTRUCTION} When user asks for image, generate image and return direct image URL."
                        },
                        {
                            "role": "user",
                            "content": f"این پرامپت را به تصویر تبدیل کن: {prompt}"
                        }
                    ]
                }
                headers = {
                    "Authorization": f"Bearer {CLEANAPIS_API_KEY}",
                    "Content-Type": "application/json"
                }
                r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
                
                if r.status_code in [502, 503, 504, 520, 522, 524]:
                    raise httpx.HTTPStatusError(f"Server error {r.status_code}", request=r.request, response=r)
                
                r.raise_for_status()
                answer = r.json()["choices"][0]["message"]["content"]
                break
        except Exception as e:
            logging.warning(f"Image attempt {attempt} failed: {e}")
            if attempt < max_retries:
                try:
                    await status.edit_text(f"⚠️ سرور تصویرسازی شلوغه (تلاش {attempt}/{max_retries}). چند ثانیه صبر کن... 🔄")
                except Exception:
                    pass
                await asyncio.sleep(retry_delay)
                retry_delay += 2
            else:
                try:
                    await status.delete()
                except Exception:
                    pass
                await update.message.reply_text(f"❌ خطا در ساخت تصویر بعد از چند تلاش (خطای سرور): {str(e)} 💎")
                return

    if answer:
        urls = extract_image_urls(answer)
        b64_match = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", answer)
        if b64_match:
            try:
                img = base64.b64decode(b64_match.group(1))
                save_message(user.id, "assistant", "[IMAGE_SENT_B64]")
                await notify_admins(context, user, prompt, "[عکس ارسال شد]")
                try:
                    await status.delete()
                except Exception:
                    pass
                await update.message.reply_photo(photo=img, caption="🖼️ تصویر با موفقیت ساخته شد ✅✨💎")
                return
            except Exception as e:
                logging.error(f"b64 decode failed: {e}")
        if urls:
            save_message(user.id, "assistant", urls[0])
            await notify_admins(context, user, prompt, urls[0])
            try:
                await status.delete()
            except Exception:
                pass
            for url in urls:
                await send_image_url_as_photo(update, url)
            return
        
        try:
            await status.delete()
        except Exception:
            pass
        await update.message.reply_text(f"🖼️ پاسخ مدل:\n{answer}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    user = update.effective_user
    save_user(user)
    
    if context.user_data.get("awaiting_image"):
        context.user_data["awaiting_image"] = False
        await handle_image_prompt(update, context, text)
        return
        
    if is_image_request(text):
        prompt = text
        for k in IMAGE_KEYWORDS:
            if k.lower() in text.lower():
                parts = re.split(re.escape(k), text, flags=re.IGNORECASE)
                if len(parts) > 1 and parts[-1].strip():
                    prompt = parts[-1].strip()
                break
        await handle_image_prompt(update, context, prompt)
        return
        
    save_message(user.id, "user", text)
    status = await update.message.reply_text("⏳ در حال پردازش... ✨💎\nلطفا کمی صبر کن (در صورت قطعی سرور، خودم چند بار تلاش می‌کنم) 🤖💭👑")
    
    max_retries = 3
    retry_delay = 2
    answer = None
    
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": context.user_data.get("model", DEFAULT_MODEL),
                    "messages": [
                        {
                            "role": "system",
                            "content": f"You are an advanced AI assistant created by DEX. If anyone asks who created you or who is your developer, always state that you were created and developed by DEX. {BEAUTIFY_INSTRUCTION}"
                        },
                        {
                            "role": "user",
                            "content": text
                        }
                    ]
                }
                headers = {
                    "Authorization": f"Bearer {CLEANAPIS_API_KEY}",
                    "Content-Type": "application/json"
                }
                r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers=headers, json=payload)
                
                if r.status_code in [502, 503, 504, 520, 522, 524]:
                    raise httpx.HTTPStatusError(f"Server error {r.status_code}", request=r.request, response=r)
                
                r.raise_for_status()
                answer = r.json()["choices"][0]["message"]["content"]
                break
        except Exception as e:
            logging.warning(f"Attempt {attempt} failed for user {user.id}: {e}")
            if attempt < max_retries:
                try:
                    await status.edit_text(f"⚠️ سرور شلوغه یا جواب نمیده (تلاش {attempt}/{max_retries}). چند ثانیه صبر کن... 🔄")
                except Exception:
                    pass
                await asyncio.sleep(retry_delay)
                retry_delay += 2
            else:
                try:
                    await status.delete()
                except Exception:
                    pass
                await update.message.reply_text("❌ سرور CleanAPIs فعلاً قطعه یا خطای ۵۰۳ میده. لطفاً چند لحظه دیگه دوباره تلاش کن دکستر جان! 💎")
                return

    if answer:
        save_message(user.id, "assistant", answer)
        await notify_admins(context, user, text, answer)
        try:
            await status.delete()
        except Exception:
            pass
        await update.message.reply_text(answer)

# ----------------- تابع اصلی اجرای ربات -----------------
def main():
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("⚠️ هشدار: توکن ربات تنظیم نشده است! لطفاً متغیر محیطی TELEGRAM_BOT_TOKEN را ست کنید.")
    
    init_db()
    
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_h
