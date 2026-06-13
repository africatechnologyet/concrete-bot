#!/usr/bin/env python3
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.utils import executor

# ========== CONFIGURATION ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")

# Single admin ID (as integer) – keep it exactly as original
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
if ADMIN_ID == 0:
    logging.warning("ADMIN_ID not set – no admin commands will work")

# Database
DB_FILE = 'concrete.db'

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== DATABASE INIT ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  status TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trips
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  trip_id TEXT,
                  truck_plate TEXT,
                  driver TEXT,
                  project TEXT,
                  quantity REAL,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ========== AIOGRAM SETUP ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# ========== HELPER: Admin check ==========
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ========== JOB COMMANDS ==========
@dp.message_handler(commands=['addjob'])
async def add_job(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ You are not authorized.")
        return
    args = message.get_args()
    if not args:
        await message.reply("Usage: /addjob <job name>")
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO jobs (name, status) VALUES (?, 'pending')", (args,))
        conn.commit()
        conn.close()
        await message.reply(f"✅ Job '{args}' added.")
    except sqlite3.IntegrityError:
        await message.reply(f"❌ Job '{args}' already exists.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message_handler(commands=['completejob'])
async def complete_job(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized.")
        return
    args = message.get_args()
    if not args:
        await message.reply("Usage: /completejob <job name>")
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE jobs SET status = 'completed' WHERE name = ? AND status != 'cancelled'", (args,))
    conn.commit()
    if c.rowcount == 0:
        await message.reply(f"❌ Job '{args}' not found or already cancelled.")
    else:
        await message.reply(f"✅ Job '{args}' completed.")
    conn.close()

@dp.message_handler(commands=['canceljob'])
async def cancel_job(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Unauthorized.")
        return
    args = message.get_args()
    if not args:
        await message.reply("Usage: /canceljob <job name>")
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE jobs SET status = 'cancelled' WHERE name = ? AND status != 'completed'", (args,))
    conn.commit()
    if c.rowcount == 0:
        await message.reply(f"❌ Job '{args}' not found or already completed.")
    else:
        await message.reply(f"🚫 Job '{args}' cancelled.")
    conn.close()

@dp.message_handler(commands=['listjobs'])
async def list_jobs(message: types.Message):
    """Show only pending and completed jobs (cancelled hidden)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, status FROM jobs WHERE status != 'cancelled' ORDER BY created_at DESC")
    jobs = c.fetchall()
    conn.close()
    if not jobs:
        await message.reply("📭 No active jobs (pending/completed).")
        return
    msg = "📋 *Active Jobs (pending/completed):*\n"
    for name, status in jobs:
        emoji = "✅" if status == "completed" else "⏳"
        msg += f"{emoji} {name} – {status}\n"
    await message.reply(msg, parse_mode="Markdown")

@dp.message_handler(commands=['alljobs'])
async def admin_list_all_jobs(message: types.Message):
    """Admin only: show all jobs including cancelled (audit)."""
    if not is_admin(message.from_user.id):
        await message.reply("⛔ Admins only.")
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, status, created_at FROM jobs ORDER BY created_at DESC")
    jobs = c.fetchall()
    conn.close()
    if not jobs:
        await message.reply("📭 No jobs found.")
        return
    msg = "📋 *All Jobs (including cancelled):*\n"
    for name, status, created_at in jobs:
        emoji = "✅" if status == "completed" else "🚫" if status == "cancelled" else "⏳"
        date_str = created_at[:10] if created_at else "unknown"
        msg += f"{emoji} {name} – {status} (created: {date_str})\n"
    await message.reply(msg, parse_mode="Markdown")

# ========== TRIP COMMANDS (your existing logic) ==========
@dp.message_handler(commands=['addtrip'])
async def add_trip(message: types.Message):
    # Replace with your actual implementation
    await message.reply("Trip logging command – implement as needed.")

@dp.message_handler(commands=['report'])
async def report(message: types.Message):
    await message.reply("Report feature – implement as needed.")

# ========== START ==========
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
