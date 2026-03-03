"""
Concrete Logistics Telegram Bot
Admin link:  https://t.me/MaterialConcretebot?start=Admin
Worker link: https://t.me/MaterialConcretebot?start=Worker
"""

import sqlite3
import logging
import io
from datetime import datetime, timedelta, date

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

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states — must not overlap
(ASK_JOB, ASK_PLATE, ASK_PLATE_MANUAL,
 ASK_VOLUME, CONFIRM_TRIP) = range(5)
ASK_NEW_JOB_NAME = 10
ASK_NEW_TRUCK    = 20


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT,
            role TEXT NOT NULL DEFAULT 'worker', joined_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL, job_name TEXT NOT NULL,
            truck_plate TEXT NOT NULL, volume REAL NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT NOT NULL UNIQUE, added_at TEXT NOT NULL)""")
        conn.commit()


def register_user(user_id: int, username: str, role: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""INSERT INTO users (user_id, username, role, joined_at)
            VALUES (?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, username=excluded.username""",
            (user_id, username or "", role,
             datetime.now().isoformat(sep=" ", timespec="seconds")))
        conn.commit()


def get_user_role(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else None


def is_admin(user_id: int) -> bool:
    return get_user_role(user_id) == "admin"


def get_all_trucks():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trucks ORDER BY plate").fetchall()
    return [dict(r) for r in rows]


def add_truck(plate: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("INSERT INTO trucks (plate, added_at) VALUES (?,?)",
                (plate.upper().strip(), datetime.now().isoformat(sep=" ", timespec="seconds")))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def delete_all_trucks():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM trucks")
        conn.commit()


def delete_truck(truck_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM trucks WHERE id=?", (truck_id,))
        conn.commit()


def get_truck_by_id(truck_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM trucks WHERE id=?", (truck_id,)).fetchone()
    return dict(row) if row else None


def get_all_jobs(status_filter=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if status_filter:
            rows = conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC",
                (status_filter,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_job_by_id(job_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def add_job(name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO jobs (name, status, created_at) VALUES (?,?,?)",
            (name, "active", datetime.now().isoformat(sep=" ", timespec="seconds")))
        conn.commit()


def update_job_status(job_id: int, status: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now().isoformat(sep=" ", timespec="seconds"), job_id))
        conn.commit()


def save_trip(user_id: int, job_name: str, truck_plate: str, volume: float):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO trips (user_id, timestamp, job_name, truck_plate, volume) VALUES (?,?,?,?,?)",
            (user_id, datetime.now().isoformat(sep=" ", timespec="seconds"),
             job_name, truck_plate, volume))
        conn.commit()


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
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(q, p)
        conn.commit()
        return cur.rowcount


def fetch_trips(period: str):
    today = date.today()
    if period == "daily":
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)=?", (today.isoformat(),)
    elif period == "weekly":
        monday = today - timedelta(days=today.weekday())
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)>=?", (monday.isoformat(),)
    else:
        q, p = "SELECT * FROM trips WHERE DATE(timestamp)>=?", (today.replace(day=1).isoformat(),)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(q, p).fetchall()
    return [dict(r) for r in rows]


def get_job_trip_summary(job_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COUNT(*) as trips, SUM(volume) as total_volume FROM trips WHERE job_name=?",
            (job_name,)).fetchone()
    return dict(row) if row else {"trips": 0, "total_volume": 0}


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
    else:
        return f"Monthly Report — {today.strftime('%B %Y')}"


def generate_text_report(period: str) -> str:
    trips = fetch_trips(period)
    label = _period_label(period)
    if not trips:
        return f"📋 *{label}*\n\n_No trips recorded for this period._"

    job_totals: dict = {}
    for t in trips:
        j = t["job_name"]
        if j not in job_totals:
            job_totals[j] = {"volume": 0.0, "trips": 0}
        job_totals[j]["volume"] += t["volume"]
        job_totals[j]["trips"]  += 1

    sorted_jobs = sorted(job_totals.items(), key=lambda x: x[1]["volume"], reverse=True)[:5]
    total_vol   = sum(v["volume"] for _, v in job_totals.items())
    total_trips = sum(v["trips"]  for _, v in job_totals.items())
    job_lines   = "\n".join(
        f"  {i+1}. {n}: *{d['volume']:.1f} m³* ({d['trips']} trips)"
        for i, (n, d) in enumerate(sorted_jobs))

    truck_totals: dict = {}
    for t in trips:
        p = t["truck_plate"]
        if p not in truck_totals:
            truck_totals[p] = {"volume": 0.0, "trips": 0}
        truck_totals[p]["volume"] += t["volume"]
        truck_totals[p]["trips"]  += 1

    truck_lines = "\n".join(
        f"  {'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else '▪️'} "
        f"{pl}: *{d['volume']:.1f} m³* ({d['trips']} trips)"
        for i, (pl, d) in enumerate(
            sorted(truck_totals.items(), key=lambda x: x[1]["volume"], reverse=True)))

    return (
        f"📋 *{label}*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Job Site Summary*\n{job_lines}\n"
        f"  ─────────────────\n"
        f"  Total: *{total_vol:.1f} m³* | *{total_trips} trips*\n\n"
        f"🚛 *Truck Performance*\n{truck_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_")


def generate_excel_report(period: str) -> io.BytesIO:
    trips  = fetch_trips(period)
    wb     = openpyxl.Workbook()
    ws     = wb.active
    ws.title = "Raw Trips"
    headers = ["#", "Timestamp", "Job Site", "Truck Plate", "Volume (m³)"]
    hfill   = PatternFill("solid", fgColor="1F4E79")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = hfill
        cell.alignment = Alignment(horizontal="center")
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
    for cell in ws2[1]: cell.font = Font(bold=True)
    jt: dict = {}
    for t in trips:
        j = t["job_name"]
        if j not in jt: jt[j] = {"volume": 0.0, "trips": 0}
        jt[j]["volume"] += t["volume"]; jt[j]["trips"] += 1
    for n, d in sorted(jt.items(), key=lambda x: x[1]["volume"], reverse=True):
        ws2.append([n, round(d["volume"], 2), d["trips"]])

    ws3 = wb.create_sheet("Truck Rankings")
    ws3.append(["Rank", "Truck Plate", "Total Volume (m³)", "Total Trips"])
    for cell in ws3[1]: cell.font = Font(bold=True)
    tt: dict = {}
    for t in trips:
        p = t["truck_plate"]
        if p not in tt: tt[p] = {"volume": 0.0, "trips": 0}
        tt[p]["volume"] += t["volume"]; tt[p]["trips"] += 1
    for rank, (pl, d) in enumerate(
            sorted(tt.items(), key=lambda x: x[1]["volume"], reverse=True), 1):
        ws3.append([rank, pl, round(d["volume"], 2), d["trips"]])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# HELPERS
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


def trucks_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Truck",    callback_data="add_truck")],
        [InlineKeyboardButton("🗑️ Clear Trucks", callback_data="clear_all_trucks")],
        [InlineKeyboardButton("⬅️ Back",         callback_data="back_main")],
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
                f"🔗 *Sharing links:*\n"
                f"Admin:  `https://t.me/{BOT_USERNAME}?start={ADMIN_SECRET}`\n"
                f"Worker: `https://t.me/{BOT_USERNAME}?start={WORKER_SECRET}`",
                parse_mode="Markdown", reply_markup=build_main_menu(user_id))
            return
        elif token == WORKER_SECRET:
            register_user(user_id, user.username or "", "worker")
            await update.message.reply_text(
                f"👷 *Welcome, {user.first_name}!*\n\nYou have worker access.",
                parse_mode="Markdown", reply_markup=build_main_menu(user_id))
            return
        else:
            await update.message.reply_text(
                "❌ *Invalid access link.*\n\nAsk your admin for the correct link.",
                parse_mode="Markdown")
            return

    role = get_user_role(user_id)
    if role:
        role_label = "👑 Admin" if role == "admin" else "👷 Worker"
        await update.message.reply_text(
            f"🏗️ *Concrete Logistics Bot*\n_{role_label}_\n\nWelcome back, {user.first_name}!",
            parse_mode="Markdown", reply_markup=build_main_menu(user_id))
        return

    await update.message.reply_text(
        "🚫 *Access Required*\n\nPlease use the link provided by your admin.",
        parse_mode="Markdown")


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role    = get_user_role(user_id)
    if not role:
        await query.edit_message_text("🚫 Access denied.")
        return
    role_label = "👑 Admin" if role == "admin" else "👷 Worker"
    await query.edit_message_text(
        f"🏗️ *Concrete Logistics Bot*\n_{role_label}_\n\nWhat would you like to do?",
        parse_mode="Markdown", reply_markup=build_main_menu(user_id))


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ─────────────────────────────────────────────
# JOB STATUS
# ─────────────────────────────────────────────
async def job_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not get_user_role(user_id):
        await query.edit_message_text("🚫 Access denied.", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text(
            "🏗️ *Job Status*\n\n_No active jobs._",
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
# MANAGE TRUCKS (admin)
# ─────────────────────────────────────────────
async def manage_trucks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    trucks = get_all_trucks()
    if trucks:
        truck_list = "\n".join(f"🚛  {t['plate']}" for t in trucks)
        text = f"🚛 *Registered Trucks*\n━━━━━━━━━━━━━━━━━━━━\n\n{truck_list}"
    else:
        text = "🚛 *Registered Trucks*\n\n_No trucks registered yet._"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=trucks_keyboard())


async def clear_all_trucks_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        return
    trucks = get_all_trucks()
    if not trucks:
        await query.edit_message_text(
            "⚠️ No trucks to clear.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="manage_trucks")]]))
        return
    truck_list = "\n".join(f"🚛  {t['plate']}" for t in trucks)
    await query.edit_message_text(
        f"⚠️ *Clear ALL Trucks?*\n\nThese will be removed:\n{truck_list}\n\nAre you sure?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, clear all", callback_data="confirm_clear_all_trucks")],
            [InlineKeyboardButton("❌ No, go back",    callback_data="manage_trucks")],
        ]))


async def clear_all_trucks_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        return
    delete_all_trucks()
    await query.edit_message_text(
        "🗑️ *All trucks cleared.*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚛 Manage Trucks", callback_data="manage_trucks")],
            [InlineKeyboardButton("🏠 Main Menu",     callback_data="back_main")],
        ]))


async def add_truck_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END
    await query.message.reply_text("🚛 *Add New Truck*\n\nEnter the truck plate number:", parse_mode="Markdown")
    return ASK_NEW_TRUCK


async def save_new_truck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plate = update.message.text.strip().upper()
    added = add_truck(plate)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Another Truck", callback_data="add_truck")],
        [InlineKeyboardButton("🚛 Manage Trucks",     callback_data="manage_trucks")],
        [InlineKeyboardButton("🏠 Main Menu",          callback_data="back_main")],
    ])
    msg = f"✅ *Truck Added!*\n\n🚛 Plate: `{plate}`" if added else f"⚠️ Truck `{plate}` already exists."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# ADD NEW JOB (admin)
# ─────────────────────────────────────────────
async def add_job_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END
    await query.message.reply_text("🆕 *Add New Job*\n\nEnter the Job Site Name:", parse_mode="Markdown")
    return ASK_NEW_JOB_NAME


async def save_new_job(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    add_job(name)
    await update.message.reply_text(
        f"✅ *Job Added!*\n\n🏗️ Name: `{name}`\n🟢 Status: `ACTIVE`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Add Another Job", callback_data="add_job")],
            [InlineKeyboardButton("🏠 Main Menu",        callback_data="back_main")],
        ]))
    return ConversationHandler.END


# ─────────────────────────────────────────────
# COMPLETE / CANCEL JOB (admin)
# ─────────────────────────────────────────────
async def complete_job_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text("✅ *Complete Job*\n\n_No active jobs._",
            parse_mode="Markdown", reply_markup=back_kb())
        return
    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"do_complete_{j['id']}")] for j in jobs]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await query.edit_message_text("✅ *Select job to mark COMPLETE:*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def do_complete_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    job_id = int(query.data.replace("do_complete_", ""))
    await query.answer()
    job = get_job_by_id(job_id)
    if job:
        update_job_status(job_id, "completed")
        s = get_job_trip_summary(job["name"])
        await query.edit_message_text(
            f"✅ *Job Completed!*\n\n🏗️ *{job['name']}*\n🧱 Total: *{s['total_volume'] or 0:.1f} m³* ({s['trips'] or 0} trips)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]]))


async def cancel_job_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    jobs = get_all_jobs(status_filter="active")
    if not jobs:
        await query.edit_message_text("❌ *Cancel Job*\n\n_No active jobs._",
            parse_mode="Markdown", reply_markup=back_kb())
        return
    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"do_cancel_{j['id']}")] for j in jobs]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await query.edit_message_text("❌ *Select job to CANCEL:*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def do_cancel_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    job_id = int(query.data.replace("do_cancel_", ""))
    await query.answer()
    job = get_job_by_id(job_id)
    if job:
        update_job_status(job_id, "cancelled")
        await query.edit_message_text(
            f"❌ *Job Cancelled*\n\n🏗️ *{job['name']}*\nStatus: `CANCELLED`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="back_main")]]))


# ─────────────────────────────────────────────
# DELETE REPORTS (admin)
# ─────────────────────────────────────────────
async def delete_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if not is_admin(user_id):
        await query.edit_message_text("🚫 *Access Denied*", parse_mode="Markdown", reply_markup=back_kb())
        return
    await query.edit_message_text(
        "🗑️ *Delete Reports*\n\n⚠️ Permanently deletes trip records.\nSelect which to delete:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Delete Today's Trips",     callback_data="del_rep_daily")],
            [InlineKeyboardButton("🗑️ Delete This Week's Trips",  callback_data="del_rep_weekly")],
            [InlineKeyboardButton("🗑️ Delete This Month's Trips", callback_data="del_rep_monthly")],
            [InlineKeyboardButton("⚠️ Delete ALL Trips",          callback_data="del_rep_all")],
            [InlineKeyboardButton("⬅️ Back",                      callback_data="back_main")],
        ]))


async def delete_reports_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("del_rep_", "")
    await query.answer()
    labels = {"daily": "Today's trips", "weekly": "This week's trips",
              "monthly": "This month's trips", "all": "ALL trips ever"}
    label = labels.get(period, period)
    await query.edit_message_text(
        f"⚠️ *Are you sure?*\n\nYou are about to permanently delete *{label}*.\n\nThis cannot be undone.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Yes, delete", callback_data=f"confirm_del_rep_{period}")],
            [InlineKeyboardButton("❌ No, go back",  callback_data="delete_reports_menu")],
        ]))


async def delete_reports_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    period = query.data.replace("confirm_del_rep_", "")
    await query.answer()
    count  = delete_trips_by_period(period)
    labels = {"daily": "Today's trips", "weekly": "This week's trips",
              "monthly": "This month's trips", "all": "All trips"}
    await query.edit_message_text(
        f"🗑️ *Deleted Successfully*\n\n*{labels.get(period, period)}* — `{count}` records removed.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Delete More", callback_data="delete_reports_menu")],
            [InlineKeyboardButton("🏠 Main Menu",   callback_data="back_main")],
        ]))


# ─────────────────────────────────────────────
# REPORT / EXPORT
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
    await query.edit_message_text("📥 *Export to Excel — Select Period:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Today (Excel)",      callback_data="exp_daily")],
            [InlineKeyboardButton("🗓️ This Week (Excel)",  callback_data="exp_weekly")],
            [InlineKeyboardButton("📆 This Month (Excel)", callback_data="exp_monthly")],
            [InlineKeyboardButton("⬅️ Back",               callback_data="back_main")],
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
    await query.answer("Generating Excel file…")
    buf = generate_excel_report(period)
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=InputFile(buf, filename=f"logistics_{period}_{date.today().isoformat()}.xlsx"),
        caption=f"📥 *{_period_label(period)}* — Excel Export",
        parse_mode="Markdown")


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
        await query.message.reply_text(
            "⚠️ *No active jobs available.*\n\nAsk an admin to add a job first.",
            parse_mode="Markdown", reply_markup=back_kb())
        return ConversationHandler.END

    kb = [[InlineKeyboardButton(f"🏗️ {j['name']}", callback_data=f"tripjob_{j['id']}")] for j in jobs]
    await query.message.reply_text(
        "📍 *Step 1 of 3 — Select Job Site:*",
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
    kb.append([InlineKeyboardButton("✏️ Enter plate manually", callback_data="truckpick_manual")])

    await query.message.reply_text(
        f"🚛 *Step 2 of 3 — Select Truck:*\n\nJob: `{job['name']}`",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_PLATE


async def truck_selected_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    plate = query.data.replace("truckpick_", "")
    await query.answer()

    if plate == "manual":
        await query.message.reply_text("✏️ *Type the truck plate number:*", parse_mode="Markdown")
        return ASK_PLATE_MANUAL

    context.user_data["truck_plate"] = plate
    await query.message.reply_text(
        f"⚠️ *Confirm Truck Plate:*\n\n🚛 Plate: `{plate}`\n🏗️ Job: `{context.user_data['job_name']}`\n\nIs this correct?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, correct",     callback_data="plate_confirm_yes")],
            [InlineKeyboardButton("🔄 Choose different", callback_data="plate_confirm_no")],
        ]))
    return CONFIRM_TRIP


async def truck_entered_manually(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plate = update.message.text.strip().upper()
    context.user_data["truck_plate"] = plate
    await update.message.reply_text(
        f"⚠️ *Confirm Truck Plate:*\n\n🚛 Plate: `{plate}`\n🏗️ Job: `{context.user_data['job_name']}`\n\nIs this correct?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, correct",     callback_data="plate_confirm_yes")],
            [InlineKeyboardButton("🔄 Choose different", callback_data="plate_confirm_no")],
        ]))
    return CONFIRM_TRIP


async def plate_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "plate_confirm_no":
        trucks = get_all_trucks()
        kb = [[InlineKeyboardButton(f"🚛 {t['plate']}", callback_data=f"truckpick_{t['plate']}")] for t in trucks]
        kb.append([InlineKeyboardButton("✏️ Enter plate manually", callback_data="truckpick_manual")])
        await query.message.reply_text("🚛 *Select Truck again:*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return ASK_PLATE

    await query.message.reply_text(
        f"🧱 *Step 3 of 3 — Enter Volume poured (m³):*\n\n"
        f"🚛 Truck: `{context.user_data['truck_plate']}`\n"
        f"🏗️ Job:   `{context.user_data['job_name']}`",
        parse_mode="Markdown")
    return ASK_VOLUME


async def ask_volume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        volume = float(update.message.text.strip())
        if volume <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number (e.g. 8.5)")
        return ASK_VOLUME

    job_name    = context.user_data["job_name"]
    truck_plate = context.user_data["truck_plate"]
    save_trip(update.effective_user.id, job_name, truck_plate, volume)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ *Trip Saved!*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Job Site:  `{job_name}`\n"
        f"🚛 Truck:     `{truck_plate}`\n"
        f"🧱 Volume:    `{volume} m³`\n"
        f"🕐 Time:      `{datetime.now().strftime('%H:%M, %d %b %Y')}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Log Another Trip", callback_data="log_trip")],
            [InlineKeyboardButton("📊 View Reports",     callback_data="menu_reports")],
            [InlineKeyboardButton("🏠 Main Menu",        callback_data="back_main")],
        ]))
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Action cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_job_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_job_start, pattern="^add_job$")],
        states={ASK_NEW_JOB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_job)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    add_truck_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_truck_start, pattern="^add_truck$")],
        states={ASK_NEW_TRUCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_truck)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
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
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_job_conv)
    app.add_handler(add_truck_conv)
    app.add_handler(log_trip_conv)

    # Trucks
    app.add_handler(CallbackQueryHandler(manage_trucks,            pattern="^manage_trucks$"))
    app.add_handler(CallbackQueryHandler(clear_all_trucks_confirm, pattern="^clear_all_trucks$"))
    app.add_handler(CallbackQueryHandler(clear_all_trucks_execute, pattern="^confirm_clear_all_trucks$"))

    # Reports delete
    app.add_handler(CallbackQueryHandler(delete_reports_menu,    pattern="^delete_reports_menu$"))
    app.add_handler(CallbackQueryHandler(delete_reports_confirm, pattern="^del_rep_(daily|weekly|monthly|all)$"))
    app.add_handler(CallbackQueryHandler(delete_reports_execute, pattern="^confirm_del_rep_(daily|weekly|monthly|all)$"))

    # Jobs
    app.add_handler(CallbackQueryHandler(job_status,        pattern="^job_status$"))
    app.add_handler(CallbackQueryHandler(complete_job_menu, pattern="^complete_job$"))
    app.add_handler(CallbackQueryHandler(cancel_job_menu,   pattern="^cancel_job$"))
    app.add_handler(CallbackQueryHandler(do_complete_job,   pattern="^do_complete_\\d+$"))
    app.add_handler(CallbackQueryHandler(do_cancel_job,     pattern="^do_cancel_\\d+$"))

    # Navigation
    app.add_handler(CallbackQueryHandler(back_main,         pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(menu_reports,      pattern="^menu_reports$"))
    app.add_handler(CallbackQueryHandler(menu_export,       pattern="^menu_export$"))
    app.add_handler(CallbackQueryHandler(send_text_report,  pattern="^rep_(daily|weekly|monthly)$"))
    app.add_handler(CallbackQueryHandler(send_excel_report, pattern="^exp_(daily|weekly|monthly)$"))
    app.add_handler(CallbackQueryHandler(noop,              pattern="^noop$"))

    logger.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
