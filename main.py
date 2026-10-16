import os
import re
import base64
import sqlite3
import logging
import threading
import asyncio
import time
import hmac
import hashlib
import json
from datetime import datetime
from urllib.parse import parse_qsl, unquote
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
CLEANAPIS_API_KEY = os.getenv("CLEANAPIS_API_KEY", "YOUR_API_KEY")
CLEANAPIS_BASE_URL = "https://cleanapis.com"
OWNER_ID = 8163337709
DB_PATH = "bot_memory.db"
DATABASE_URL = os.getenv("DATABASE_URL")
APP_URL = os.getenv("APP_URL", os.getenv("RAILWAY_PUBLIC_DOMAIN", ""))
if APP_URL and not APP_URL.startswith("http"):
    APP_URL = "https://" + APP_URL
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
IS_POSTGRES = bool(DATABASE_URL and "postgresql" in DATABASE_URL)

BEAUTIFY_INSTRUCTION = "پاسخ‌ها را بسیار دقیق، زیبا، ساختاریافته، جذاب و با استفاده از ایموجی‌های مناسب به زبان فارسی روان ارائه بده."
DEFAULT_MODEL = "gpt-5.6-sol"
MODELS_WITH_EMOJI = {
    "gpt-5.6-sol": "☀️",
    "claude-fable-5.1": "✨",
    "claude-fable-5": "📖",
    "gpt-5.5-pro": "🚀",
    "gpt-5.5": "⚡",
}

def get_conn():
    if IS_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
    else:
        return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    if IS_POSTGRES:
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_at TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, user_id BIGINT, role TEXT, content TEXT, timestamp TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS conversations (id SERIAL PRIMARY KEY, user_id BIGINT, title TEXT, created_at TEXT, updated_at TEXT);")
        cur.execute("CREATE TABLE IF NOT EXISTS chat_messages (id SERIAL PRIMARY KEY, conversation_id INTEGER, user_id BIGINT, role TEXT, content TEXT, timestamp TEXT);")
    else:
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_at TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT, timestamp TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, created_at TEXT, updated_at TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, user_id INTEGER, role TEXT, content TEXT, timestamp TEXT)")
    conn.commit()
    conn.close()
    db_name = "PostgreSQL" if IS_POSTGRES else "SQLite"
    logger.info(f"✅ Database initialized: {db_name}")

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

def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    uc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages")
    mc = cur.fetchone()[0]
    conn.close()
    return uc, mc

def get_all_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, first_name, joined_at FROM users")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_last_messages(limit=10):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT m.user_id, u.username, m.role, m.content, m.timestamp FROM messages m LEFT JOIN users u ON m.user_id=u.user_id ORDER BY m.id DESC LIMIT %s" if IS_POSTGRES else "SELECT m.user_id, u.username, m.role, m.content, m.timestamp FROM messages m LEFT JOIN users u ON m.user_id=u.user_id ORDER BY m.id DESC LIMIT ?"
    cur.execute(q, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows[::-1]

def get_user_logs(user_id, limit=20):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT role, content, timestamp FROM messages WHERE user_id=%s ORDER BY id DESC LIMIT %s" if IS_POSTGRES else "SELECT role, content, timestamp FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?"
    cur.execute(q, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows[::-1]

def is_admin(uid: int) -> bool:
    return uid == OWNER_ID

def create_conversation(user_id, title="چت جدید"):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    if IS_POSTGRES:
        cur.execute("INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (%s,%s,%s,%s) RETURNING id", (user_id, title, now, now))
        cid = cur.fetchone()[0]
    else:
        cur.execute("INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?,?,?,?)", (user_id, title, now, now))
        cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid

def get_conversations(user_id):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT id, title, updated_at FROM conversations WHERE user_id=%s ORDER BY updated_at DESC LIMIT 50" if IS_POSTGRES else "SELECT id, title, updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 50"
    cur.execute(q, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_chat_messages(conv_id, user_id):
    conn = get_conn()
    cur = conn.cursor()
    q = "SELECT role, content FROM chat_messages WHERE conversation_id=%s AND user_id=%s ORDER BY id ASC" if IS_POSTGRES else "SELECT role, content FROM chat_messages WHERE conversation_id=? AND user_id=? ORDER BY id ASC"
    cur.execute(q, (conv_id, user_id))
    rows = cur.fetchall()
    conn.close()
    return rows

def save_chat_message(conv_id, user_id, role, content):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    q = "INSERT INTO chat_messages (conversation_id, user_id, role, content, timestamp) VALUES (%s,%s,%s,%s,%s)" if IS_POSTGRES else "INSERT INTO chat_messages (conversation_id, user_id, role, content, timestamp) VALUES (?,?,?,?,?)"
    cur.execute(q, (conv_id, user_id, role, content, now))
    q2 = "UPDATE conversations SET updated_at=%s WHERE id=%s" if IS_POSTGRES else "UPDATE conversations SET updated_at=? WHERE id=?"
    cur.execute(q2, (now, conv_id))
    if role == "user" and len(content) < 50:
        short = content[:30]
        q3 = "UPDATE conversations SET title=%s WHERE id=%s AND title=%s" if IS_POSTGRES else "UPDATE conversations SET title=? WHERE id=? AND title=?"
        cur.execute(q3, (short, conv_id, "چت جدید"))
    conn.commit()
    conn.close()

def delete_conversation(conv_id, user_id):
    conn = get_conn()
    cur = conn.cursor()
    q = "DELETE FROM chat_messages WHERE conversation_id=%s AND user_id=%s" if IS_POSTGRES else "DELETE FROM chat_messages WHERE conversation_id=? AND user_id=?"
    cur.execute(q, (conv_id, user_id))
    q2 = "DELETE FROM conversations WHERE id=%s AND user_id=%s" if IS_POSTGRES else "DELETE FROM conversations WHERE id=? AND user_id=?"
    cur.execute(q2, (conv_id, user_id))
    conn.commit()
    conn.close()

def validate_init_data(init_data: str):
    try:
        vals = dict(parse_qsl(init_data))
        hash_val = vals.pop("hash", None)
        if not hash_val:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k,v in sorted(vals.items()))
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if h != hash_val:
            return None
        if "auth_date" in vals and time.time() - int(vals["auth_date"]) > 86400:
            return None
        return json.loads(unquote(vals.get("user", "{}")))
    except Exception as e:
        logger.error(f"validate error: {e}")
        return None

def extract_image_urls(text: str):
    found = re.findall(r"https?://\S+|www\.\S+", text)
    exts = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    out = []
    for u in found:
        low = u.lower()
        if any(low.endswith(e) for e in exts) or "image" in low or "cleanapis" in low:
            out.append(u)
    return out

def is_explicit_image_request(text: str) -> bool:
    low = text.lower()
    triggers = ["عکس بساز", "تصویر بساز", "نقاشی بکش", "طراحی کن", "برام بکش", "برام بساز", "generate image", "create image", "draw "]
    return any(t in low for t in triggers)

def get_main_menu(user_id: int):
    kb = []
    if APP_URL:
        kb.append([InlineKeyboardButton("🌐 باز کردن اپ چت ✨", web_app=WebAppInfo(url=f"{APP_URL}/miniapp/"))])
    kb.append([InlineKeyboardButton("🎨 ساخت تصویر", callback_data="gen_mode"), InlineKeyboardButton("🛠️ مدل‌ها", callback_data="services_menu")])
    kb.append([InlineKeyboardButton("💎 درباره ربات", callback_data="about")])
    if is_admin(user_id):
        kb.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

def get_services_menu(current_model: str):
    rows = []
    for k, emoji in MODELS_WITH_EMOJI.items():
        prefix = "✅ " if k == current_model else ""
        label = f"{emoji} {prefix}{k}"
        rows.append([InlineKeyboardButton(label, callback_data=f"set_{k}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def get_admin_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("👥 کاربران", callback_data="admin_users"), InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],[InlineKeyboardButton("💬 آخرین پیام‌ها", callback_data="admin_recent"), InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])

async def notify_admins(context, user, prompt, answer):
    try:
        disp = user.username if user.username else "ندارد"
        ans = str(answer)[:1000]
        txt = f"🚨 گزارش:\n👤 {user.first_name} (@{disp} | `{user.id}`)\n📌 درخواست:\n{prompt}\n\n🤖 پاسخ:\n{ans}"
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    context.user_data.setdefault("model", DEFAULT_MODEL)
    await update.message.reply_text(f"سلام {update.effective_user.first_name} عزیز! 🌸✨\nبه ربات هوش مصنوعی خوش آمدید 🤖💎", reply_markup=get_main_menu(update.effective_user.id))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ دسترسی ندارید!")
        return
    await update.message.reply_text("👑 پنل مدیریت:", reply_markup=get_admin_menu())

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("🎨 پرامپت رو بعد از دستور بنویس:\nمثال: /image a cute cat in space")
        return
    await handle_image_prompt(update, context, prompt)

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
            kb = []
            for uid, uname, fname, _ in users[:20]:
                disp = fname or uname or str(uid)
                kb.append([InlineKeyboardButton(f"👤 {disp} ({uid})", callback_data=f"admin_view_{uid}")])
            kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])
            await query.edit_message_text("👥 کاربران:", reply_markup=InlineKeyboardMarkup(kb))
        elif data == "admin_recent" and is_admin(user.id):
            recent = get_last_messages(10)
            lines = []
            for uid, uname, role, content, ts in recent:
                disp = uname if uname else "ندارد"
                lines.append(f"▪️ [{uid}|@{disp}] ({role}): {content[:100]}\n-----")
            text = "💬 آخرین پیام‌ها:\n\n" + "\n".join(lines)
            await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data.startswith("admin_view_") and is_admin(user.id):
            tid = int(data.split("_")[2])
            logs = get_user_logs(tid, 15)
            parts = []
            for r, c, ts in logs:
                parts.append(f"🔹 {r}: {c[:150]}")
            text = f"📜 تاریخچه `{tid}`:\n\n" + "\n".join(parts)
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
                if r.status_code in [502,503,504,520,522,524]:
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
    text = update.message.text.strip()
    user = update.effective_user
    save_user(user)
    if context.user_data.get("awaiting_image"):
        context.user_data["awaiting_image"] = False
        await handle_image_prompt(update, context, text)
        return
    if is_explicit_image_request(text):
        await handle_image_prompt(update, context, text)
        return
    save_message(user.id, "user", text)
    status = await update.message.reply_text("⏳ در حال پردازش... ✨💎")
    answer = None
    for attempt in range(1, 4)
