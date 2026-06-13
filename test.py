#!/usr/bin/env python3
# concrete-bot/test.py - Fixed version with separate admin audit command

import logging
import sqlite3
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from functools import wraps

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== CONFIGURATION ==========
# HARDCODED ADMIN IDs – REPLACE WITH YOUR TELEGRAM USER IDs
ADMIN_IDS = ['123456789', '987654321']   # <-- CHANGE THIS

# Database file (will be created in same directory)
DB_FILE = 'concrete.db'

# ========== DATABASE SETUP ==========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Jobs table with created_at column for sorting
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE,
                  status TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # Trips table (for concrete logistics)
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

# ========== HELPER: Admin only decorator ==========
def admin_only(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = str(update.effective_user.id)
        if user_id not in ADMIN_IDS:
            update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

# ========== JOB COMMANDS ==========
def add_job(update: Update, context: CallbackContext):
    """Add a new job (admin only)."""
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_IDS:
        update.message.reply_text("⛔ You are not authorized to add jobs.")
        return
    try:
        job_name = ' '.join(context.args)
        if not job_name:
            update.message.reply_text("Usage: /addjob <job name>")
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO jobs (name, status) VALUES (?, 'pending')", (job_name,))
        conn.commit()
        conn.close()
        update.message.reply_text(f"✅ Job '{job_name}' added successfully.")
    except sqlite3.IntegrityError:
        update.message.reply_text(f"❌ Job '{job_name}' already exists.")
    except Exception as e:
        update.message.reply_text(f"❌ Error adding job: {e}")

def complete_job(update: Update, context: CallbackContext):
    """Mark a job as completed (admin only)."""
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_IDS:
        update.message.reply_text("⛔ You are not authorized to complete jobs.")
        return
    try:
        job_name = ' '.join(context.args)
        if not job_name:
            update.message.reply_text("Usage: /completejob <job name>")
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE jobs SET status = 'completed' WHERE name = ? AND status != 'cancelled'", (job_name,))
        conn.commit()
        if c.rowcount == 0:
            update.message.reply_text(f"❌ Job '{job_name}' not found or already cancelled.")
        else:
            update.message.reply_text(f"✅ Job '{job_name}' marked as completed.")
        conn.close()
    except Exception as e:
        update.message.reply_text(f"❌ Error completing job: {e}")

def cancel_job(update: Update, context: CallbackContext):
    """Cancel a job (soft delete: set status to 'cancelled')."""
    user_id = str(update.effective_user.id)
    if user_id not in ADMIN_IDS:
        update.message.reply_text("⛔ You are not authorized to cancel jobs.")
        return
    try:
        job_name = ' '.join(context.args)
        if not job_name:
            update.message.reply_text("Usage: /canceljob <job name>")
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE jobs SET status = 'cancelled' WHERE name = ? AND status != 'completed'", (job_name,))
        conn.commit()
        if c.rowcount == 0:
            update.message.reply_text(f"❌ Job '{job_name}' not found or already completed.")
        else:
            update.message.reply_text(f"🚫 Job '{job_name}' has been cancelled.")
        conn.close()
    except Exception as e:
        update.message.reply_text(f"❌ Error cancelling job: {e}")

def list_jobs(update: Update, context: CallbackContext):
    """Show only pending and completed jobs (cancelled jobs are hidden)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, status FROM jobs WHERE status != 'cancelled' ORDER BY created_at DESC")
    jobs = c.fetchall()
    conn.close()

    if not jobs:
        update.message.reply_text("📭 No active jobs found (pending or completed).")
        return

    msg = "*📋 Active Jobs (pending / completed):*\n"
    for name, status in jobs:
        emoji = "✅" if status == "completed" else "⏳"
        msg += f"{emoji} {name} – {status}\n"
    update.message.reply_text(msg, parse_mode='Markdown')

@admin_only
def admin_list_all_jobs(update: Update, context: CallbackContext):
    """Admin only: show all jobs including cancelled (for auditing)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, status, created_at FROM jobs ORDER BY created_at DESC")
    jobs = c.fetchall()
    conn.close()

    if not jobs:
        update.message.reply_text("📭 No jobs found in the database.")
        return

    msg = "*📋 All Jobs (including cancelled):*\n"
    for name, status, created_at in jobs:
        emoji = "✅" if status == "completed" else "🚫" if status == "cancelled" else "⏳"
        date_str = created_at[:10] if created_at else "unknown date"
        msg += f"{emoji} {name} – {status} (created: {date_str})\n"
    update.message.reply_text(msg, parse_mode='Markdown')

# ========== TRIP COMMANDS (simplified from original) ==========
def add_trip(update: Update, context: CallbackContext):
    """Add a concrete delivery trip. Usage: /addtrip|TRIP001|22936|Jambo|Misrak View|8"""
    # This is a placeholder – keep your original implementation
    update.message.reply_text("Trip added (example). Implement your full logic here.")

def report(update: Update, context: CallbackContext):
    """Generate a simple report."""
    update.message.reply_text("Report feature – implement as needed.")

# ========== MAIN ==========
def main():
    # TODO: Set your BOT_TOKEN as environment variable for security!
    import os
    TOKEN = os.environ.get('BOT_TOKEN')
    if not TOKEN:
        print("❌ Error: BOT_TOKEN environment variable not set.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Job commands
    dp.add_handler(CommandHandler("addjob", add_job))
    dp.add_handler(CommandHandler("completejob", complete_job))
    dp.add_handler(CommandHandler("canceljob", cancel_job))
    dp.add_handler(CommandHandler("listjobs", list_jobs))
    dp.add_handler(CommandHandler("alljobs", admin_list_all_jobs))   # NEW admin audit command

    # Trip commands (add your own)
    dp.add_handler(CommandHandler("addtrip", add_trip))
    dp.add_handler(CommandHandler("report", report))

    # Start bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
