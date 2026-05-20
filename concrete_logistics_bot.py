# Full Production Upgrade — Single File Version

```python
import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties

# =========================
# CONFIGURATION
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
DATABASE = "production.db"
CACHE_TTL_SECONDS = 60

# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# =========================
# CACHE SYSTEM
# =========================

cache_store = {}


def cache(ttl=CACHE_TTL_SECONDS):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{kwargs}"
            now = datetime.now()

            if key in cache_store:
                value, expiry = cache_store[key]
                if now < expiry:
                    return value

            result = await func(*args, **kwargs)
            cache_store[key] = (
                result,
                now + timedelta(seconds=ttl)
            )
            return result

        return wrapper

    return decorator


# =========================
# DATABASE
# =========================


def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def init_database():
    conn = db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT UNIQUE,
            truck_plate TEXT,
            driver_name TEXT,
            project_name TEXT,
            quantity REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()

    logger.info("Database initialized")


# =========================
# HELPERS
# =========================


def admin_only(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            await message.answer("Access denied")
            return

        return await func(message, *args, **kwargs)

    return wrapper


async def safe_answer(target, text, **kwargs):
    try:
        return await target.answer(text, **kwargs)
    except Exception as e:
        logger.error(f"Send message error: {e}")


# =========================
# BOT SETUP
# =========================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)


dp = Dispatcher()

# =========================
# USER COMMANDS
# =========================


@dp.message(Command("start"))
async def start_handler(message: types.Message):
    conn = db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO users (telegram_id, full_name)
        VALUES (?, ?)
        """,
        (
            message.from_user.id,
            message.from_user.full_name
        )
    )

    conn.commit()
    conn.close()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Production Report",
                    callback_data="production_report"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Truck Trips",
                    callback_data="truck_trips"
                )
            ]
        ]
    )

    await message.answer(
        "Welcome to CoBuilt Production System",
        reply_markup=keyboard
    )


# =========================
# CALLBACKS
# =========================


@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    try:
        data = callback.data

        if data == "production_report":
            report = await generate_report()
            await callback.message.answer(report)

        elif data == "truck_trips":
            trips = await fetch_trips()
            await callback.message.answer(trips)

        else:
            await callback.message.answer("Unknown command")

        await callback.answer()

    except Exception as e:
        logger.error(f"Callback error: {e}")
        await callback.answer("Error occurred")


# =========================
# REPORTS
# =========================


@cache(ttl=30)
async def generate_report():
    conn = db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) as total_trips,
            SUM(quantity) as total_quantity
        FROM trips
        """
    )

    row = cursor.fetchone()
    conn.close()

    total_trips = row["total_trips"] or 0
    total_quantity = row["total_quantity"] or 0

    report = (
        f"<b>Daily Production Report</b>

"
        f"Total Trips: {total_trips}
"
        f"Total Concrete: {total_quantity} m³"
    )

    return report


@cache(ttl=30)
async def fetch_trips(page=1, limit=10):
    offset = (page - 1) * limit

    conn = db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM trips
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset)
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No trips found"

    text = "<b>Recent Trips</b>

"

    for row in rows:
        text += (
            f"Truck: {row['truck_plate']}
"
            f"Driver: {row['driver_name']}
"
            f"Project: {row['project_name']}
"
            f"Qty: {row['quantity']} m³
"
            f"-------------------
"
        )

    return text


# =========================
# ADD TRIP COMMAND
# =========================


@dp.message(Command("addtrip"))
@admin_only
async def add_trip(message: types.Message):
    try:
        parts = message.text.split("|")

        if len(parts) != 6:
            await message.answer(
                "Format:
"
                "/addtrip|TRIP001|22936|Jambo|Misrak View|8"
            )
            return

        _, trip_id, truck, driver, project, qty = parts

        conn = db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM trips WHERE trip_id = ?",
            (trip_id,)
        )

        existing = cursor.fetchone()

        if existing:
            await message.answer("Duplicate trip ID")
            conn.close()
            return

        cursor.execute(
            """
            INSERT INTO trips (
                trip_id,
                truck_plate,
                driver_name,
                project_name,
                quantity
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                truck,
                driver,
                project,
                float(qty)
            )
        )

        conn.commit()
        conn.close()

        cache_store.clear()

        await message.answer("Trip added successfully")

    except Exception as e:
        logger.error(f"Add trip error: {e}")
        await message.answer("Failed to add trip")


# =========================
# AUTO REPORT SCHEDULER
# =========================


async def scheduled_reports():
    while True:
        try:
            now = datetime.now()

            if now.hour == 20 and now.minute == 0:
                report = await generate_report()
                await bot.send_message(ADMIN_ID, report)
                await asyncio.sleep(60)

            await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(30)


# =========================
# RENDER DEPLOYMENT NOTES
# =========================

"""
Render Environment Variables:

BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_id

Start Command:
python main.py
"""


# =========================
# MAIN
# =========================


async def main():
    init_database()

    asyncio.create_task(scheduled_reports())

    logger.info("Bot started")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```
