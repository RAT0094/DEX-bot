import os
import re
import base64
import sqlite3
import logging
import threading
import asyncio
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY", "YOUR_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
DEFAULT_MODEL = "gpt-5.6-luna"
OWNER_ID = 8163337709
DB_PATH = "bot_memory.db"
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = bool(DATABASE_URL and "postgresql" in DATABASE_URL)

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

# ----------------- دیتابیس هوشمند -----------------
def get_conn():
    if IS_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
    else:
        return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)

def init_db():
    try:
        conn = get_conn()
        cur = conn.cursor()
        if IS_POSTGRES:
            cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_at TEXT);")
            cur.execute("CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, timestamp TEXT);")
        else:
            cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_at TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, timestamp TEXT)")
        conn.commit()
        conn.close()
        db_name = "PostgreSQL" if IS_POSTGRES else "SQLite"
        logger.info(f"✅ Database initialized: {db_name}")
    except Exception as e:
        logger.error(f"❌ DB Init Failed: {e}", exc_info=True)
        raise

def save_user(user):
    try:
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now().isoformat()
        if IS_POSTGRES:
            cur.execute("INSERT INTO users (user_id, username, first_name, last_name, joined_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name", (user.id, user.username, user.first_name, user.last_name, now))
        else:
            cur.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, joined_at) VALUES (?,?,?,?, COALESCE((SELECT joined_at FROM users WHERE user_id=?),?))", (user.id, user.username, user.first_name, user.last_name, user.id, now))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_user error: {e}")

def save_message(user_id, role, content):
    try:
        conn = get_conn()
        cur = conn.cursor()
        q = "INSERT INTO messages (user_id, role, content, timestamp) VALUES (%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?,?,?,?)"
        cur.execute(q, (user_id, role, content, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_message error: {e}")

def get_all_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, joined_at FROM users")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_user_logs(user_id, limit=20):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT role, content, timestamp FROM messages WHERE user_id=%s ORDER BY id DESC LIMIT %s" if IS_POSTGRES else "SELECT role, content, timestamp FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?"
    cur.execute(q, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows[::-1]

def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    uc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages")
    mc = cur.fetchone()[0]
    conn.close()
    return uc, mc

def get_last_messages(limit=10):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT m.user_id, u.username, m.role, m.content, m.timestamp FROM messages m LEFT JOIN users u ON m.user_id=u.user_id ORDER BY m.id DESC LIMIT %s" if IS_POSTGRES else "SELECT m.user_id, u.username, m.role, m.content, m.timestamp FROM messages m LEFT JOIN users u ON m.user_id=u.user_id ORDER BY m.id DESC LIMIT ?"
    cur.execute(q, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows[::-1]

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID

# ----------------- توابع کمکی -----------------
def is_image_request(text: str) -> bool:
    return any(kw in text.lower() for kw in IMAGE_KEYWORDS)

def extract_image_urls(text: str):
    found = re.findall(r\'https?://\S+|www\.\S+\', text)
    image_extensions = (\'.png\', \'.jpg\', \'.jpeg\', \'.webp\', \'.gif\')
    img_urls = []
    for u in found:
        low = u.lower()
        if any(low.endswith(ext) for ext in image_extensions) or \'image\' in low or \'img\' in low or \'cleanapis\' in low:
            img_urls.append(u)
    return img_urls

def get_main_menu(user_id: int):
    kb = [[InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode"), InlineKeyboardButton("🛠️ سرویس‌ها و مدل‌ها", callback_data="services_menu")],[InlineKeyboardButton("💎 درباره ربات", callback_data="about")]]
    if is_admin(user_id):
        kb.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

def get_services_menu(current_model: str):
    rows = [[InlineKeyboardButton(f"{emoji} {\'✅ \'+k if k==current_model else k}", callback_data=f"set_{k}")] for k, emoji in MODELS_WITH_EMOJI.items()]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def get_admin_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("👥 کاربران", callback_data="admin_users"), InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],[InlineKeyboardButton("💬 آخرین پیام‌ها", callback_data="admin_recent"), InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])

async def notify_admins(context, user, prompt, answer):
    try:
        txt = f"🚨 گزارش:\n👤 {user.first_name} (@{user.username or \'ندارد\'} | `{user.id}`)\n📌 درخواست:\n{prompt}\n\n🤖 پاسخ:\n{str(answer)[:1000]}"
        await context.bot.send_message(chat_id=OWNER_ID, text=txt, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"notify failed: {e}")

async def send_image_url_as_photo(update: Update, url: str):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                await update.message.reply_photo(photo=r.content, caption="🖼️ تصویر ساخته شد ✅✨💎")
                return
    except Exception as e:
        logger.error(f"fetch img failed: {e}")
    await update.message.reply_text(f"🖼️ لینک تصویر:\n{url}")

# ----------------- سرور سلامت بدون کرش -----------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot is running smoothly! 🚀✨💎".encode())
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server started on port {port}")
    server.serve_forever()

# ----------------- هندلرها -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    context.user_data.setdefault("model", DEFAULT_MODEL)
    await update.message.reply_text(f"سلام {update.effective_user.first_name} عزیز! 🌸✨\nبه ربات هوش مصنوعی خوش آمدید 🤖💎", reply_markup=get_main_menu(update.effective_user.id))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی ندارید!")
        return
    await update.message.reply_text("👑 پنل مدیریت:", reply_markup=get_admin_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    try:
        if data == "main_menu":
            await query.edit_message_text("🏠 منوی اصلی:", reply_markup=get_main_menu(user.id))
        elif data == "services_menu":
            await query.edit_message_text("🛠️ مدل را انتخاب کنید:", reply_markup=get_services_menu(context.user_data.get("model", DEFAULT_MODEL)))
        elif data == "gen_mode":
            context.user_data["awaiting_image"] = True
            await query.edit_message_text("🎨 پرامپت تصویر رو بفرست:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
        elif data.startswith("set_"):
            m = data[4:]
            if m in MODELS_WITH_EMOJI:
                context.user_data["model"] = m
                await query.edit_message_text(f"✅ مدل شد: {m} {MODELS_WITH_EMOJI[m]}", reply_markup=get_main_menu(user.id))
        elif data == "about":
            await query.edit_message_text("💎 ربات هوش مصنوعی پیشرفته\nقدرت گرفته توسط DEX 🚀✨", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
        elif data == "admin_panel" and is_admin(user.id):
            await query.edit_message_text("👑 پنل مدیریت:", reply_markup=get_admin_menu())
        elif data == "admin_stats" and is_admin(user.id):
            uc, mc = get_stats()
            await query.edit_message_text(f"📊 آمار:\n👥 کاربران: {uc}\n💬 پیام‌ها: {mc}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data == "admin_users" and is_admin(user.id):
            users = get_all_users()
            kb = [[InlineKeyboardButton(f"👤 {fname or uname or uid} ({uid})", callback_data=f"admin_view_{uid}")] for uid, uname, fname, _ in users[:20]]
            kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
            await query.edit_message_text("👥 کاربران:", reply_markup=InlineKeyboardMarkup(kb))
        elif data == "admin_recent" and is_admin(user.id):
            recent = get_last_messages(10)
            text = "💬 آخرین پیام‌ها:\n\n" + "\n".join([f"▪️ [{uid}|@{uname or \'ندارد\'}] ({role}): {content[:100]}\n-----" for uid, uname, role, content, ts in recent])
            await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data.startswith("admin_view_") and is_admin(user.id):
            tid = int(data.split("_")[2])
            logs = get_user_logs(tid, 15)
            text = f"📜 تاریخچه `{tid}`:\n\n" + "\n".join([f"🔹 **{r}**: {c[:150]}" for r, c, ts in logs])
            await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست ↩️", callback_data="admin_users")]]))
    except Exception as e:
        logger.error(f"button error: {e}", exc_info=True)

async def handle_image_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    save_user(update.effective_user)
    save_message(update.effective_user.id, "user", f"[IMAGE] {prompt}")
    status = await update.message.reply_text("⏳ در حال ساخت تصویر... ✨💎")
    answer = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                payload = {"model": context.user_data.get("model", DEFAULT_MODEL), "messages": [{"role": "system", "content": f"You are an advanced AI assistant created by DEX. You are an image generator. {BEAUTIFY_INSTRUCTION}"}, {"role": "user", "content": f"این پرامپت را به تصویر تبدیل کن: {prompt}"}]}
                r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}, json=payload)
                if r.status_code in [502, 503, 504, 520, 522, 524]:
                    raise httpx.HTTPStatusError(f"Server error {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                answer = r.json()["choices"][0]["message"]["content"]
                break
        except Exception as e:
            logger.warning(f"Image attempt {attempt} failed: {e}")
            if attempt < 3:
                await asyncio.sleep(3)
            else:
                await status.delete()
                await update.message.reply_text(f"❌ خطا در ساخت تصویر: {str(e)[:200]} 💎")
                return
    if answer:
        urls = extract_image_urls(answer)
        b64 = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", answer)
        if b64:
            try:
                img = base64.b64decode(b64.group(1))
                save_message(update.effective_user.id, "assistant", "[IMAGE_SENT]")
                await notify_admins(context, update.effective_user, prompt, "[عکس]")
                await status.delete()
                await update.message.reply_photo(photo=img, caption="🖼️ تصویر ساخته شد ✅✨💎")
                return
            except Exception:
                pass
        if urls:
            save_message(update.effective_user.id, "assistant", urls[0])
            await notify_admins(context, update.effective_user, prompt, urls[0])
            await status.delete()
        else:
            await status.delete()
            await update.message.reply_text(f"🖼️ پاسخ مدل:\n{answer}")
            return
        for url in urls:
            await send_image_url_as_photo(update, url)

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
    status = await update.message.reply_text("⏳ در حال پردازش... ✨💎")
    answer = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {"model": context.user_data.get("model", DEFAULT_MODEL), "messages": [{"role": "system", "content": f"You are an advanced AI assistant created by DEX. If anyone asks who created you, say DEX. {BEAUTIFY_INSTRUCTION}"}, {"role": "user", "content": text}]}
                r = await client.post(f"{CLEANAPIS_BASE_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {CLEANAPIS_API_KEY}", "Content-Type": "application/json"}, json=payload)
                if r.status_code in [502, 503, 504, 520, 522, 524]:
                    raise httpx.HTTPStatusError(f"Server error {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                answer = r.json()["choices"][0]["message"]["content"]
                break
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
            else:
                await status.delete()
                await update.message.reply_text("❌ سرور شلوغه، لطفاً دوباره تلاش کن 💎")
                return
    if answer:
        save_message(user.id, "assistant", answer)
        await notify_admins(context, user, text, answer)
        await status.delete()
        await update.message.reply_text(answer)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        logger.error("❌ TELEGRAM_BOT_TOKEN ست نشده! Variables رو چک کن")
        threading.Thread(target=start_health_server, daemon=True).start()
        while True:
            time.sleep(3600)
        return
    try:
        init_db()
    except Exception as e:
        logger.error(f"DB init fallback to SQLite: {e}")
        global DATABASE_URL, IS_POSTGRES
        DATABASE_URL = None
        IS_POSTGRES = False
        init_db()
    threading.Thread(target=start_health_server, daemon=True).start()
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is starting... 🚀 Polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
