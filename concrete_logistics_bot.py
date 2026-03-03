"""
Concrete Logistics Telegram Bot  — Optimized + Web Service (Render free)
Admin link:  https://t.me/MaterialConcretebot?start=Admin
Worker link: https://t.me/MaterialConcretebot?start=Worker
"""

import sqlite3
import logging
import io
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from typing import Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN     = "8468077984:AAG_VE2T7oH2y337Tlr7BhX3jmPVAZ0thME"
BOT_USERNAME  = "MaterialConcretebot"
ADMIN_SECRET  = "Admin"
WORKER_SECRET = "Worker"
DB_PATH       = "logistics.db"
PORT          = 10000   # Render requires port 10000

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

# Conversation states
(ASK_JOB, ASK_PLATE, ASK_PLATE_MANUAL, ASK_VOLUME, CONFIRM_TRIP) = range(5)
ASK_NEW_JOB_NAME = 10
ASK_NEW_TRUCK    = 20


# ─────────────────────────────────────────────
# KEEP-ALIVE HTTP SERVER  (required for Render free)
# ─────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, *args):
        pass  # silence HTTP logs

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# ─────────────────────────────────────────────
# PERSISTENT DB CONNECTION
# ─────────────────────────────────────────────
_db: Optional[sqlite3.Connection] = None

def get_db() -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("PRAGMA synchronous=NORMAL")
        _db.execute("PRAGMA cache_size=-8000")
        _db.execute("PRAGMA temp_store=MEMORY")
    return _db


def init_db():
    get_db().executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT,
            role TEXT NOT NULL DEFAULT 'worker', joined_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL, job_name TEXT NOT NULL,
            truck_plate TEXT NOT NULL, volume REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT NOT NULL UNIQUE, added_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_trips_timestamp ON trips(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trips_job       ON trips(job_name);
        CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
    """)
    get_db().commit()


# ─────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────
_cache: dict = {}

def cache_get(key): return _cache.get(key)
def cache_set(key, value): _cache[key] = value
def cache_clear(*keys):
    for k in keys: _cache.pop(k, None)


# ─────────────────────────────────────────────
# DATABASE FUNCTIONS
# ─────────────────────────────────────────────
def now_str() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def register_user(user_id: int, username: str, role: str):
    get_db().execute("""INSERT INTO users (user_id, username, role, joined_at)
        VALUES (?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, username=excluded.username""",
        (user_id, username or "", role, now_str()))
    get_db().commit()
    cache_clear(f"role_{user_id}")


def get_user_role(user_id: int) -> Optional[str]:
    key = f"role_{user_id}"
    cached = cache_get(key)
    if cached is not None: return cached
    row = get_db().execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    result = row[0] if row else None
    cache_set(key, result or "")
    return result


def is_admin(user_id: int) -> bool:
    return get_user_role(user_id) == "admin"


def get_all_trucks() -> list:
    cached = cache_get("trucks")
    if cached is not None: return cached
    rows = get_db().execute("SELECT * FROM trucks ORDER BY plate").fetchall()
    result = [dict(r) for r in rows]
    cache_set("trucks", result)
    return result


def add_truck(plate: str) -> bool:
    try:
        get_db().execute("INSERT INTO trucks (plate, added_at) VALUES (?,?)",
            (plate.upper().strip(), now_str()))
        get_db().commit()
        cache_clear("trucks")
        return True
    except sqlite3.IntegrityError:
        return False


def delete_all_trucks():
    get_db().execute("DELETE FROM trucks")
    get_db().commit()
    cache_clear("trucks")


def get_all_jobs(status_filter=None) -> list:
    key = f"jobs_{status_filter}"
    cached = cache_get(key)
    if cached is not None: return cached
    if status_filter:
        rows = get_db().execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC", (status_filter,)).fetchall()
    else:
        rows = get_db().execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    result = [dict(r) for r in rows]
    cache_set(key, result)
    return result


def get_job_by_id(job_id: int) -> Optional[dict]:
    row = get_db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def add_job(name: str):
    get_db().execute("INSERT INTO jobs (name, status, created_at) VALUES (?,?,?)",
        (name, "active", now_str()))
    get_db().commit()
    cache_clear("jobs_active", "jobs_None")


def update_job_status(job_id: int, status: str):
    get_db().execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
        (status, now_str(), job_id))
    get_db().commit()
    cache_clear("jobs_active", "jobs_None")


def save_trip(user_id: int, job_name: str, truck_plate: str, volume: float):
    get_db().execute(
        "INSERT INTO trips (user_id, timestamp, job_name, truck_plate, volume) VALUES (?,?,?,?,?)",
        (user_id, now_str(), job_name, truck_plate, volume))
    get_db().commit()
    for k in list(_cache.keys()):
        if k.startswith("trips_") or k.startswith("summary_"):
            _cache.pop(k, None)


def delete_trips_by_period(period: str) -> int:
    today = date.today()
    if period == "daily":
        q, p = "DELETE FROM trips WHERE DATE(timestamp)=?", (today.isoformat(),)
    elif period == "weekly":
        monday = today - timedelta(days=today.weekday())
        q, p = "DELETE FROM trips WHERE DATE(timestamp)>=?", (monday.isoformat(),)
    elif period == "monthly":
        q, p = "DELETE FROM trips WHERE DATE(timestamp)>=?", (today.replace(day=1).isoformat(),)
    else:
        q, p = "DELETE FROM trips", ()
    cur = get_db().execute(q, p)
    get_db().commit()
    for k in list(_cache.keys()):
        if k.startswith("trips_") or k.startswith("summary_"):
            _cache.pop(k, None)
    return cur.rowcount


def fetch_trips(period: str) -> list:
    key = f"trips_{period}_{date.today().isoformat()}"
    cached = cache_get(key)
    if cached is not None: return cached
    today = date.today()
    if period == "daily":
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)=?", (today.isoformat(),)
    elif period == "weekly":
        monday = today - timedelta(days=today.weekday())
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)>=?", (monday.isoformat(),)
    else:
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)>=?", (today.replace(day=1).isoformat(),)
    rows = get_db().execute(q, p).fetchall()
    result = [dict(r) for r in rows]
    cache_set(key, result)
    return result


def get_job_trip_summary(job_name: str) -> dict:
    key = f"summary_{job_name}"
    cached = cache_get(key)
    if cached is not None: return cached
    row = get_db().execute(
        "SELECT COUNT(*) as trips, SUM(volume) as total_volume FROM trips WHERE job_name=?",
        (job_name,)).fetchone()
    result = dict(row) if row else {"trips": 0, "total_volume": 0}
    cache_set(key, result)
    return result


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────
def _period_label(period: str) -> str:
    today = date.today()
    if period == "daily":
        return f"Daily Report — {today.strftime('%B %d, %Y')}"
    elif period == "weekly":
        monday = today - timedelta(days=today.weekday())
        return f"Weekly Report ({monday.strftime('%b %d')}–{(monday+timedelta(days=6)).strftime('%b %d, %Y')})"
    return f"Monthly Report — {today.strftime('%B %Y')}"


def generate_text_report(period: str) -> str:
    trips = fetch_trips(period)
    label = _period_label(period)
    if not trips:
        return f"📋 *{label}*\n\n_No trips recorded for this period._"

    job_totals:   dict = {}
    truck_totals: dict = {}
    for t in trips:
        j, p, v = t["job_name"], t["truck_plate"], t["volume"]
        if j not in job_totals:   job_totals[j]   = [0.0, 0]
        if p not in truck_totals: truck_totals[p] = [0.0, 0]
        job_totals[j][0]   += v; job_totals[j][1]   += 1
        truck_totals[p][0] += v; truck_totals[p][1] += 1

    sorted_jobs   = sorted(job_totals.items(),   key=lambda x: x[1][0], reverse=True)[:5]
    sorted_trucks = sorted(truck_totals.items(), key=lambda x: x[1][0], reverse=True)
    total_vol     = sum(v[0] for _, v in job_totals.items())
    total_trips   = sum(v[1] for _, v in job_totals.items())
    medals        = ["🥇", "🥈", "🥉"]

    job_lines   = "\n".join(f"  {i+1}. {n}: *{d[0]:.1f} m³* ({d[1]} trips)"
                            for i, (n, d) in enumerate(sorted_jobs))
    truck_lines = "\n".join(f"  {medals[i] if i<3 else '▪️'} {pl}: *{d[0]:.1f} m³* ({d[1]} trips)"
                            for i, (pl, d) in enumerate(sorted_trucks))

    return (f"📋 *{label}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 *Job Summary*\n{job_lines}\n"
            f"  ─────────\n  Total: *{total_vol:.1f} m³* | *{total_trips} trips*\n\n"
            f"🚛 *Truck Rankings*\n{truck_lines}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Generated {datetime.now().strftime('%H:%M %d %b %Y')}_")


def generate_excel_report(period: str) -> io.BytesIO:
    trips = fetch_trips(period)
    wb    = openpyxl.Workbook()
    ws    = wb.active
    ws.title = "Raw Trips"
    hfill = PatternFill("solid", fgColor="1F4E79")
    hfont = Font(bold=True, color="FFFFFF")
    for col, h in enumerate(["#", "Timestamp", "Job Site", "Truck Plate", "Volume (m³)"], 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = hfont; c.fill = hfill
        c.alignment = Alignment(horizontal="center")
    for i, t in enumerate(trips, 2):
        ws.cell(row=i, column=1, value=i-1)
        ws.cell(row=i, column=2, value=t["timestamp"])
        ws.cell(row=i, column=3, value=t["job_name"])
        ws.cell(row=i, column=4, value=t["truck_plate"])
        ws.cell(row=i, column=5, value=t["volume"])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 20

    ws2 = wb.create_sheet("Job Summary")
    ws2.append(["Job Site", "Total Volume (m³)", "Total Trips"])
    for c in ws2[1]: c.font = Font(bold=True)
    jt: dict = {}
    for t in trips:
        j = t["job_name"]
        if j not in jt: jt[j] = [0.0, 0]
        jt[j][0] += t["volume"]; jt[j][1] += 1
    for n, (v, tr) in sorted(jt.items(), key=lambda x: x[1][0], reverse=True):
        ws2.append([n, round(v, 2), tr])

    ws3 = wb.create_sheet("Truck Rankings")
    ws3.append(["Rank", "Truck Plate", "Total Volume (m³)", "Total Trips"])
    for c in ws3[1]: c.font = Font(bold=True)
    tt: dict = {}
    for t in trips:
        p = t["truck_plate"]
        if p not in tt: tt[p] = [0.0, 0]
        tt[p][0] += t["volume"]; tt[p][1] += 1
    for rank, (pl, (v, tr)) in enumerate(
            sorted(tt.items(), key=lambda x: x[1][0], reverse=True), 1):
        ws3.append([rank, pl, round(v, 2), tr])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────
def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_main")]])

def build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    admin = is_admin(user_id)
    kb = []
    if admin:
        kb.append([InlineKeyboardButton("🆕 Add New Job",     callback_data="add_job")])
        kb.append([InlineKeyboardButton("🚛 Manage Trucks",   callback_data="manage_trucks")])
    kb.append([InlineKeyboardButton("➕ Log New Trip",     callback_data="log_trip")])
    kb.append([InlineKeyboardButton("🏗️ Job Status",       callback_data="job_status")])
    kb.append([InlineKeyboardButton("📊 View Reports",     callback_data="menu_reports")])
    kb.append([InlineKeyboardButton("📥 Export to Excel",  callback_data="menu_export")])
    if admin:
        kb.append([InlineKeyboardButton("🗑️ Delete Reports", callback_data="delete_reports_menu")])
        kb.append([InlineKeyboardButton("✅ Complete Job",    callback_data="complete_job")])
        kb.append([InlineKeyboardButton("❌ Cancel Job",      callback_data="cancel_job")])
    return InlineKeyboardMarkup(kb)

def trucks_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Truck",    callback_data="add_truck")],
        [InlineKeyboardButton("🗑️ Clear Trucks", callback_data="clear_all_trucks")],
        [InlineKeyboardButton("⬅️ Back",         callback_data="back_main")],
    ])

def confirm_plate_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, correct",     callback_data="plate_confirm_yes")],
        [InlineKeyboardButton("🔄 Choose different", callback_data="plate_confirm_no")],
    ])

def trip_done_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Log Another Trip", callback_data="log_trip")],
        [InlineKeyboardButton("📊 View Reports",     callback_data="menu_reports")],
        [InlineKeyboardButton("🏠 Main Menu",        callback_data="back_main")],
    ])


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    args    = context.args
    if args:
        token = args[0]
        if token == ADMIN_SECRET:
            register_user(user_id, user.username or "", "admin")
            await update.message.reply_text(
                f"👑 *Welcome, Admin {user.first_name}!*\n\n"
                f"🔗 Admin:  `https://t.me/{BOT_USERNAME}?start={ADMIN_SECRET}`\n"
                f"🔗 Worker: `https://t.me/{BOT_USERNAME}?start={WORKER_SECRET}`",
                parse_mode="Markdown", reply_markup=build_main_menu(user_id))
        elif token == WORKER_SECRET:
            register_user(user_id, user.username or "", "worker")
            await update.message.reply_text(
                f"👷 *Welcome, {user.first_name}!*\n\nYou have worker access.",
                parse_mode="Markdown", reply_markup=build_main_menu(user_id))
        else:
            await update.message.reply_text(
                "❌ *Invalid access link.*", parse_mode="Markdown")
        return
    role = get_user_role(user_id)
    if role:
        label = "👑 Admin" if role == "admin" else "👷 Worker"
        await update.message.reply_text(
            f"🏗️ *Concrete Logistics Bot*\n_{label}_\n\nWelcome back, {user.first_name}!",
            parse_mode="Markdown", reply_markup=build_main_menu(user_id))
    else:
        await update.message.reply_text(
            "🚫 *Access Required*\n\nUse the link from your admin.",
            parse_mode="Markdown")


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = get_user_role(user_id)
    if not role:
        await query.edit_message_text("🚫 Access denied.")
        return
    label = "👑 Admin" if role == "admin" else "👷 Worker"
    await query.edit_message_text(
        f"🏗️ *Concrete Logistics Bot*\n_{label}_\n\nWhat would you like to do?",
        parse_mode="Markdown", reply_markup=build_main_menu(user_id))

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ─────────────────────────────────────────────
# JOB STATUS
# ─────────────────────────────────────────────
async def job_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not get_user_role(query.from_user.id):
        await query.edit_message_text("🚫 Access denied.", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text("🏗️ *Job Status*\n\n_No active jobs._",
            parse_mode="Markdown", reply_markup=back_kb())
        return
    lines = []
    for j in jobs:
        s = get_job_trip_summary(j["name"])
        lines.append(f"🟢 *{j['name']}*\n   🧱 {s['total_volume'] or 0:.1f} m³ | {s['trips'] or 0} trips")
    await query.edit_message_text(
        "🏗️ *Active Job Sites*\n━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines),
        parse_mode="Markdown", reply_markup=back_kb())


# ─────────────────────────────────────────────
# MANAGE TRUCKS
# ─────────────────────────────────────────────
async def manage_trucks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    trucks = get_all_trucks()
    text = ("🚛 *Registered Trucks*\n━━━━━━━━━━━━━━━━━━━━\n\n" +
            "\n".join(f"🚛  {t['plate']}" for t in trucks)
            if trucks else "🚛 *Registered Trucks*\n\n_No trucks yet._")
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=trucks_keyboard())


async def clear_all_trucks_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id): return
    trucks = get_all_trucks()
    if not trucks:
        await query.edit_message_text("⚠️ No trucks to clear.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="manage_trucks")]]))
        return
    truck_list = "\n".join(f"🚛  {t['plate']}" for t in trucks)
    await query.edit_message_text(
        f"⚠️ *Clear ALL Trucks?*\n\n{truck_list}\n\nAre you sure?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, clear all", callback_data="confirm_clear_all_trucks")],
            [InlineKeyboardButton("❌ No, go back",    callback_data="manage_trucks")],
        ]))


async def clear_all_trucks_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id): return
    delete_all_trucks()
    await query.edit_message_text("🗑️ *All trucks cleared.*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚛 Manage Trucks", callback_data="manage_trucks")],
            [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_main")],
        ]))


async def add_truck_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END
    await query.message.reply_text("🚛 Enter the truck plate number:")
    return ASK_NEW_TRUCK


async def save_new_truck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plate = update.message.text.strip().upper()
    added = add_truck(plate)
    msg = f"✅ *Truck Added!*\n\n🚛 `{plate}`" if added else f"⚠️ `{plate}` already exists."
    await update.message.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Another",   callback_data="add_truck")],
            [InlineKeyboardButton("🚛 Manage Trucks", callback_data="manage_trucks")],
            [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_main")],
        ]))
    return ConversationHandler.END


# ─────────────────────────────────────────────
# ADD JOB
# ─────────────────────────────────────────────
async def add_job_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END
    await query.message.reply_text("🆕 Enter the Job Site Name:")
    return ASK_NEW_JOB_NAME


async def save_new_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    add_job(name)
    await update.message.reply_text(
        f"✅ *Job Added!*\n\n🏗️ `{name}`\n🟢 ACTIVE",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Add Another", callback_data="add_job")],
            [InlineKeyboardButton("🏠 Main Menu",   callback_data="back_main")],
        ]))
    return ConversationHandler.END


# ─────────────────────────────────────────────
# COMPLETE / CANCEL JOB
# ─────────────────────────────────────────────
async def complete_job_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text("_No active jobs._", parse_mode="Markdown", reply_markup=back_kb())
        return
    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"do_complete_{j['id']}")] for j in jobs]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await query.edit_message_text("✅ *Mark job COMPLETE:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb))


async def do_complete_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    job_id = int(query.data.replace("do_complete_", ""))
    await query.answer()
    job = get_job_by_id(job_id)
    if job:
        update_job_status(job_id, "completed")
        s = get_job_trip_summary(job["name"])
        await query.edit_message_text(
            f"✅ *Completed!*\n\n🏗️ *{job['name']}*\n🧱 {s['total_volume'] or 0:.1f} m³ | {s['trips'] or 0} trips",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]]))


async def cancel_job_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text("_No active jobs._", parse_mode="Markdown", reply_markup=back_kb())
        return
    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"do_cancel_{j['id']}")] for j in jobs]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await query.edit_message_text("❌ *Select job to CANCEL:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb))


async def do_cancel_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    job_id = int(query.data.replace("do_cancel_", ""))
    await query.answer()
    job = get_job_by_id(job_id)
    if job:
        update_job_status(job_id, "cancelled")
        await query.edit_message_text(
            f"❌ *Cancelled*\n\n🏗️ *{job['name']}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]]))


# ─────────────────────────────────────────────
# DELETE REPORTS
# ─────────────────────────────────────────────
PERIOD_LABELS = {
    "daily": "Today's trips", "weekly": "This week's trips",
    "monthly": "This month's trips", "all": "ALL trips ever",
}

async def delete_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    await query.edit_message_text("🗑️ *Delete Reports*\n\n⚠️ Permanently deletes trip records.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Today",      callback_data="del_rep_daily")],
            [InlineKeyboardButton("🗑️ This Week",  callback_data="del_rep_weekly")],
            [InlineKeyboardButton("🗑️ This Month", callback_data="del_rep_monthly")],
            [InlineKeyboardButton("⚠️ Delete ALL",  callback_data="del_rep_all")],
            [InlineKeyboardButton("⬅️ Back",        callback_data="back_main")],
        ]))


async def delete_reports_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("del_rep_", "")
    await query.answer()
    await query.edit_message_text(
        f"⚠️ Delete *{PERIOD_LABELS.get(period)}*?\n\nThis cannot be undone.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, delete", callback_data=f"confirm_del_rep_{period}")],
            [InlineKeyboardButton("❌ Go back",     callback_data="delete_reports_menu")],
        ]))


async def delete_reports_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("confirm_del_rep_", "")
    await query.answer()
    count  = delete_trips_by_period(period)
    await query.edit_message_text(
        f"🗑️ *Done!* `{count}` records deleted.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Delete More", callback_data="delete_reports_menu")],
            [InlineKeyboardButton("🏠 Main Menu",   callback_data="back_main")],
        ]))


# ─────────────────────────────────────────────
# REPORTS / EXPORT
# ─────────────────────────────────────────────
async def menu_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📊 *Select Report Period:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Today",      callback_data="rep_daily")],
            [InlineKeyboardButton("🗓️ This Week",  callback_data="rep_weekly")],
            [InlineKeyboardButton("📆 This Month", callback_data="rep_monthly")],
            [InlineKeyboardButton("⬅️ Back",       callback_data="back_main")],
        ]))


async def menu_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📥 *Export to Excel:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Today",      callback_data="exp_daily")],
            [InlineKeyboardButton("🗓️ This Week",  callback_data="exp_weekly")],
            [InlineKeyboardButton("📆 This Month", callback_data="exp_monthly")],
            [InlineKeyboardButton("⬅️ Back",       callback_data="back_main")],
        ]))


async def send_text_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("rep_", "")
    await query.answer()
    await query.edit_message_text(generate_text_report(period), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu_reports")]]))


async def send_excel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("exp_", "")
    await query.answer("Generating…")
    buf = generate_excel_report(period)
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=InputFile(buf, filename=f"logistics_{period}_{date.today().isoformat()}.xlsx"),
        caption=f"📥 *{_period_label(period)}*", parse_mode="Markdown")


# ─────────────────────────────────────────────
# LOG TRIP CONVERSATION
# ─────────────────────────────────────────────
async def log_trip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not get_user_role(user_id):
        await query.edit_message_text("🚫 Access denied. Use your access link.")
        return ConversationHandler.END
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.message.reply_text("⚠️ *No active jobs.*\n\nAsk admin to add a job first.",
            parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"tripjob_{j['id']}")] for j in jobs]
    await query.message.reply_text("📍 *Select Job Site:*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_JOB


async def job_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query  = update.callback_query
    job_id = int(query.data.replace("tripjob_", ""))
    await query.answer()
    job = get_job_by_id(job_id)
    context.user_data["job_name"] = job["name"]
    trucks = get_all_trucks()
    kb = [[InlineKeyboardButton(f"🚛 {t['plate']}", callback_data=f"truckpick_{t['plate']}")] for t in trucks]
    kb.append([InlineKeyboardButton("✏️ Enter manually", callback_data="truckpick_manual")])
    await query.message.reply_text(f"🚛 *Select Truck:*\nJob: `{job['name']}`",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_PLATE


async def truck_selected_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    plate = query.data.replace("truckpick_", "")
    await query.answer()
    if plate == "manual":
        await query.message.reply_text("✏️ Type the truck plate:")
        return ASK_PLATE_MANUAL
    context.user_data["truck_plate"] = plate
    await query.message.reply_text(
        f"⚠️ *Confirm:*\n🚛 `{plate}`\n🏗️ `{context.user_data['job_name']}`\n\nCorrect?",
        parse_mode="Markdown", reply_markup=confirm_plate_kb())
    return CONFIRM_TRIP


async def truck_entered_manually(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plate = update.message.text.strip().upper()
    context.user_data["truck_plate"] = plate
    await update.message.reply_text(
        f"⚠️ *Confirm:*\n🚛 `{plate}`\n🏗️ `{context.user_data['job_name']}`\n\nCorrect?",
        parse_mode="Markdown", reply_markup=confirm_plate_kb())
    return CONFIRM_TRIP


async def plate_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "plate_confirm_no":
        trucks = get_all_trucks()
        kb = [[InlineKeyboardButton(f"🚛 {t['plate']}", callback_data=f"truckpick_{t['plate']}")] for t in trucks]
        kb.append([InlineKeyboardButton("✏️ Enter manually", callback_data="truckpick_manual")])
        await query.message.reply_text("🚛 *Select Truck:*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return ASK_PLATE
    await query.message.reply_text(
        f"🧱 *Enter Volume (m³):*\n🚛 `{context.user_data['truck_plate']}`  🏗️ `{context.user_data['job_name']}`",
        parse_mode="Markdown")
    return ASK_VOLUME


async def ask_volume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        volume = float(update.message.text.strip())
        if volume <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number (e.g. 8.5)")
        return ASK_VOLUME
    job_name    = context.user_data["job_name"]
    truck_plate = context.user_data["truck_plate"]
    save_trip(update.effective_user.id, job_name, truck_plate, volume)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ *Trip Saved!*\n"
        f"📍 `{job_name}`  🚛 `{truck_plate}`  🧱 `{volume} m³`\n"
        f"🕐 `{datetime.now().strftime('%H:%M, %d %b %Y')}`",
        parse_mode="Markdown", reply_markup=trip_done_kb())
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_db()

    # Start health server in background thread (keeps Render free tier alive)
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()
    logger.warning(f"Health server running on port {PORT}")

    app = (Application.builder()
           .token(BOT_TOKEN)
           .concurrent_updates(True)
           .connection_pool_size(16)
           .build())

    add_job_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_job_start, pattern="^add_job$")],
        states={ASK_NEW_JOB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_job)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True,
    )
    add_truck_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_truck_start, pattern="^add_truck$")],
        states={ASK_NEW_TRUCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_truck)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True,
    )
    log_trip_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(log_trip_start, pattern="^log_trip$")],
        states={
            ASK_JOB:          [CallbackQueryHandler(job_selected,             pattern="^tripjob_\\d+$")],
            ASK_PLATE:        [CallbackQueryHandler(truck_selected_from_list, pattern="^truckpick_")],
            ASK_PLATE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, truck_entered_manually)],
            CONFIRM_TRIP:     [CallbackQueryHandler(plate_confirmed,           pattern="^plate_confirm_")],
            ASK_VOLUME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_volume)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_job_conv,   group=0)
    app.add_handler(add_truck_conv, group=0)
    app.add_handler(log_trip_conv,  group=0)

    app.add_handler(CallbackQueryHandler(manage_trucks,            pattern="^manage_trucks$"))
    app.add_handler(CallbackQueryHandler(clear_all_trucks_confirm, pattern="^clear_all_trucks$"))
    app.add_handler(CallbackQueryHandler(clear_all_trucks_execute, pattern="^confirm_clear_all_trucks$"))
    app.add_handler(CallbackQueryHandler(delete_reports_menu,    pattern="^delete_reports_menu$"))
    app.add_handler(CallbackQueryHandler(delete_reports_confirm, pattern="^del_rep_(daily|weekly|monthly|all)$"))
    app.add_handler(CallbackQueryHandler(delete_reports_execute, pattern="^confirm_del_rep_(daily|weekly|monthly|all)$"))
    app.add_handler(CallbackQueryHandler(job_status,        pattern="^job_status$"))
    app.add_handler(CallbackQueryHandler(complete_job_menu, pattern="^complete_job$"))
    app.add_handler(CallbackQueryHandler(cancel_job_menu,   pattern="^cancel_job$"))
    app.add_handler(CallbackQueryHandler(do_complete_job,   pattern="^do_complete_\\d+$"))
    app.add_handler(CallbackQueryHandler(do_cancel_job,     pattern="^do_cancel_\\d+$"))
    app.add_handler(CallbackQueryHandler(back_main,         pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(menu_reports,      pattern="^menu_reports$"))
    app.add_handler(CallbackQueryHandler(menu_export,       pattern="^menu_export$"))
    app.add_handler(CallbackQueryHandler(send_text_report,  pattern="^rep_(daily|weekly|monthly)$"))
    app.add_handler(CallbackQueryHandler(send_excel_report, pattern="^exp_(daily|weekly|monthly)$"))
    app.add_handler(CallbackQueryHandler(noop,              pattern="^noop$"))

    logger.warning("Bot is running…")
    app.run_polling(
        poll_interval=0.5,
        timeout=10,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
