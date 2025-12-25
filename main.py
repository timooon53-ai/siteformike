from cfg import *
import os
import sys
import asyncio
import sqlite3
import logging
import requests
import random
import time
import json
import re
import warnings
import shutil
from datetime import datetime
from functools import wraps
from pathlib import Path


DEFAULT_CHANNEL_URL = "https://t.me/TaxiFromMike"
DEFAULT_OPERATOR_URL = "https://t.me/TakeMaxist"
DEFAULT_CHAT_URL = "https://t.me/+z_S1iZMVW-ZmMzBi"
FAQ_URL = "https://telegra.ph/FAQ-12-19-16"

REQUIRED_CHANNEL = -1003460665929

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, Bot, ReplyKeyboardRemove, ForceReply, InputFile,
)
from telegram.constants import ChatAction
from telegram.error import Forbidden, InvalidToken, Conflict
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler, ConversationHandler,
)
from telegram.request import HTTPXRequest
from telegram.warnings import PTBUserWarning

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_DIR = BASE_DIR / "db"
DEFAULT_SCREENSHOTS_DIR = BASE_DIR / "screens"

TOKEN = os.getenv("BOT_TOKEN") or locals().get("TOKEN")
PRIMARY_BOT_TOKEN = (
    locals().get("PRIMARY_BOT_TOKEN") or os.getenv("PRIMARY_BOT_TOKEN") or TOKEN
)
ADMIN_IDS = locals().get("ADMIN_IDS", [])
SCREENSHOTS_DIR = Path(
    os.getenv("SCREENSHOTS_DIR")
    or locals().get("SCREENSHOTS_DIR")
    or DEFAULT_SCREENSHOTS_DIR
)
DB_DIR = Path(os.getenv("DB_DIR") or locals().get("DB_DIR") or DEFAULT_DB_DIR)

DB_PATH = Path(os.getenv("DB_PATH") or locals().get("DB_PATH") or DB_DIR / "bot.db")
USERS_DB = ORDERS_DB = BANNED_DB = DB_PATH
SECONDARY_DB_PATH = Path(
    os.getenv("SECONDARY_DB_PATH")
    or locals().get("SECONDARY_DB_PATH")
    or DB_DIR / "bot_secondary.db"
)

PODMENA_DB_PATH = DB_DIR / "podmena.db"

TRANSFER_DETAILS = (os.getenv("TRANSFER_DETAILS") or locals().get("TRANSFER_DETAILS") or "2200248021994636").strip()
SBP_DETAILS = (os.getenv("SBP_DETAILS") or locals().get("SBP_DETAILS") or "+79088006072").strip()
SBP_BANK_INFO = (os.getenv("SBP_BANK_INFO") or locals().get("SBP_BANK_INFO") or "❄️ Банк ВТБ").strip()
LTC_WALLET = (
    os.getenv("LTC_WALLET")
    or locals().get("LTC_WALLET")
    or "ltc1q9l65njf0cx2jypuvhtmkkjzrf9aq7ylgfku786"
).strip()
USDT_TRC20_WALLET = (
    os.getenv("USDT_TRC20_WALLET")
    or locals().get("USDT_TRC20_WALLET")
    or "TJRe5tyJXMDp7PkUhKN97SQjpV2PR5VRR2"
).strip()
USDT_TRX_WALLET = (
    os.getenv("USDT_TRX_WALLET")
    or locals().get("USDT_TRX_WALLET")
    or "TJRe5tyJXMDp7PkUhKN97SQjpV2PR5VRR2"
).strip()

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore", category=PTBUserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

REQUEST_TIMEOUTS = dict(connect_timeout=15, read_timeout=30, write_timeout=30)

primary_bot = Bot(token=PRIMARY_BOT_TOKEN, request=HTTPXRequest(**REQUEST_TIMEOUTS))
bot_clients: dict[str, Bot] = {}
bot_link_cache: dict[str, str] = {}


def _markup_to_dict(markup):
    if markup is None:
        return None
    try:
        return markup.to_dict()
    except Exception:
        return markup


async def safe_edit_message(target, text: str | None = None, reply_markup=None):
    """Редактирует сообщение только если есть изменения."""
    message = getattr(target, "message", None) or target
    if not message:
        return None

    current_text = message.caption if message.caption is not None else (message.text or "")
    if (text is None or text == current_text) and _markup_to_dict(message.reply_markup) == _markup_to_dict(reply_markup):
        return message

    try:
        if message.photo:
            return await message.edit_caption(caption=text, reply_markup=reply_markup)
        return await message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning("Не удалось обновить сообщение: %s", e)
        return message


async def safe_delete_message(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("Не удалось удалить сообщение %s в чате %s: %s", message_id, chat_id, e)


def get_bot_client(token: str | None) -> Bot:
    token = (token or PRIMARY_BOT_TOKEN).strip()

    if token == PRIMARY_BOT_TOKEN:
        return primary_bot

    if token in bot_clients:
        return bot_clients[token]

    try:
        bot_clients[token] = Bot(token=token, request=HTTPXRequest(**REQUEST_TIMEOUTS))
    except InvalidToken as e:
        logger.error("Недействительный токен бота %s: %s", token, e)
        return primary_bot
    except Exception as e:
        logger.error("Не удалось создать клиента бота %s: %s", token, e)
        return primary_bot

    return bot_clients[token]


def get_order_bot(order: dict | None) -> Bot:
    token = None
    if order:
        token = order.get("bot_token") or PRIMARY_BOT_TOKEN
    return get_bot_client(token)

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


CHANNEL_URL = (os.getenv("CHANNEL_URL") or DEFAULT_CHANNEL_URL).strip()
OPERATOR_URL = (os.getenv("OPERATOR_URL") or DEFAULT_OPERATOR_URL).strip()
CHAT_URL = (os.getenv("CHAT_URL") or DEFAULT_CHAT_URL).strip()

PROFILE_BTN = "Профиль ✨"
ORDER_BTN = "Заказать такси 🎄🛷"
HELP_BTN = "Помощь ❄️"
PRICE_BTN = "Проверить цену 💸"
ADMIN_BTN = "Админка 🎅"
BACK_BTN = "Назад ⛄️"
FAQ_BTN = "FAQ 📚"

MAIN_MENU_BUTTONS = {
    PROFILE_BTN,
    ORDER_BTN,
    HELP_BTN,
    PRICE_BTN,
    ADMIN_BTN,
    BACK_BTN,
    FAQ_BTN,
}

YANDEX_TAXI_TOKEN = (
    os.getenv("YANDEX_TAXI_TOKEN")
    or locals().get("YANDEX_TAXI_TOKEN")
    or "y0_AgAAAAB1g7gdAAU0HAAAAAECOUIwAAAYjdKIuM9IEZ2DXVd1oG4LOWpPrg"
)
YANDEX_PRICE_CLASS = "comfortplus"
PRICE_TARIFFS = [
    ("econom", "🚕 Эконом"),
    ("business", "🚘 Комфорт"),
    ("comfortplus", "🚗 Комфорт+"),
    ("minivan", "🚐 Минивэн"),
    ("vip", "💼 Бизнес"),
    ("ultimate", "✨ Премьер"),
    ("maybach", "👑 Элит"),
]

ORDER_TARIFF_PRICE_CLASS = {
    "Эконом": "econom",
    "Комфорт": "business",
    "Комфорт+": "comfortplus",
    "Бизнес": "vip",
    "Премьер": "ultimate",
    "Элит": "maybach",
}

# ==========================
# Инициализация БД
# ==========================
def init_db(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS banned (
                tg_id INTEGER PRIMARY KEY
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.00,
                orders_count INTEGER DEFAULT 0,
                coefficient REAL DEFAULT 0.55,
                city TEXT,
                referral_code TEXT,
                referred_by INTEGER,
                referral_balance REAL DEFAULT 0.00
            )
        """)

        existing_columns = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
        if "city" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN city TEXT")
        if "referral_code" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
        if "referred_by" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        if "referral_balance" not in existing_columns:
            c.execute("ALTER TABLE users ADD COLUMN referral_balance REAL DEFAULT 0.00")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                bot_token TEXT,
                type TEXT,
                screenshot_path TEXT,
                city TEXT,
                address_from TEXT,
                address_to TEXT,
                address_extra TEXT,
                tariff TEXT,
                child_seat TEXT,
                child_seat_type TEXT,
                wishes TEXT,
                comment TEXT,
                status TEXT DEFAULT 'pending',
                amount REAL,
                base_amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        """)

        existing_columns = {row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()}
        new_columns = {
            "address_extra": "TEXT",
            "tariff": "TEXT",
            "child_seat": "TEXT",
            "child_seat_type": "TEXT",
            "wishes": "TEXT",
            "base_amount": "REAL",
            "bot_token": "TEXT",
        }
        for column, definition in new_columns.items():
            if column not in existing_columns:
                c.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")

        c.execute("""
            CREATE TABLE IF NOT EXISTS orders_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                tg_id INTEGER,
                order_number TEXT,
                token2 TEXT,
                card_x TEXT,
                external_id TEXT,
                link TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        info_columns = {row[1] for row in c.execute("PRAGMA table_info(orders_info)").fetchall()}
        needed_info_columns = {
            "order_number": "TEXT",
            "token2": "TEXT",
            "card_x": "TEXT",
            "external_id": "TEXT",
            "link": "TEXT",
            "is_active": "INTEGER DEFAULT 1",
            "tg_id": "INTEGER",
        }
        for column, definition in needed_info_columns.items():
            if column not in info_columns:
                c.execute(f"ALTER TABLE orders_info ADD COLUMN {column} {definition}")

        c.execute("""
            CREATE TABLE IF NOT EXISTS favorite_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                address TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        c.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('ordering_enabled', '1')"
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                order_id INTEGER,
                type TEXT,
                method TEXT,
                amount REAL,
                currency TEXT,
                comment_code TEXT,
                requisites TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )

        payment_columns = {row[1] for row in c.execute("PRAGMA table_info(payments)").fetchall()}
        extra_payment_columns = {
            "original_amount": "REAL",
            "original_currency": "TEXT",
        }
        for column, definition in extra_payment_columns.items():
            if column not in payment_columns:
                c.execute(f"ALTER TABLE payments ADD COLUMN {column} {definition}")

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_user_id INTEGER,
                order_id INTEGER,
                amount REAL,
                base_amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_referral_history_referrer ON referral_history(referrer_id)"
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                token TEXT UNIQUE,
                db_path TEXT,
                title TEXT,
                pending_reward REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        bot_columns = {row[1] for row in c.execute("PRAGMA table_info(user_bots)").fetchall()}
        if "title" not in bot_columns:
            c.execute("ALTER TABLE user_bots ADD COLUMN title TEXT")
        if "pending_reward" not in bot_columns:
            c.execute("ALTER TABLE user_bots ADD COLUMN pending_reward REAL DEFAULT 0")

        conn.commit()


def init_podmena_db(db_path=PODMENA_DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS podmena (
                orderid TEXT UNIQUE,
                token2 TEXT,
                id TEXT,
                card_x TEXT
            )
            """
        )
        conn.commit()
    logger.info("Инициализация podmena.db завершена")


def get_setting(key, default=None, db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        return row[0] if row else default


def set_setting(key, value, db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def is_ordering_enabled():
    return get_setting("ordering_enabled", "1") == "1"

# ==========================
# Работа с пользователями
# ==========================
def safe_token_slug(token: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (token or ""))[:32] or "bot"


def get_bot_db_path(token: str) -> str:
    record = get_bot_by_token(token)
    if record and record.get("db_path"):
        return record["db_path"]
    return DB_PATH


def add_user(tg_id, username):
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO users (tg_id, username)
            VALUES (?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET username = COALESCE(excluded.username, users.username)
            """,
            (tg_id, username),
        )
        conn.commit()


def add_user_to_bot_db(tg_id: int, username: str | None, bot_token: str | None):
    if not bot_token:
        return
    add_user(tg_id, username)
    if not get_bot_by_token(bot_token) and bot_token != PRIMARY_BOT_TOKEN:
        create_bot_storage(bot_token, 0, "Подключённый бот")
    bot_db = get_bot_db_path(bot_token)
    init_db(bot_db)
    log_franchise_user_by_token(bot_token, tg_id, username)
    with sqlite3.connect(bot_db) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO users (tg_id, username)
            VALUES (?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET username = COALESCE(excluded.username, users.username)
            """,
            (tg_id, username),
        )
        conn.commit()

def get_user(tg_id):
    with sqlite3.connect(USERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
        row = c.fetchone()
        return dict(row) if row else None


def ensure_referral_code(tg_id: int) -> str:
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT referral_code FROM users WHERE tg_id=?", (tg_id,))
        row = c.fetchone()
        if row and row[0]:
            return row[0]

        base_code = f"u{tg_id:x}"
        code = base_code
        suffix = 0
        while True:
            c.execute("SELECT tg_id FROM users WHERE referral_code=?", (code,))
            existing = c.fetchone()
            if not existing:
                break
            suffix += 1
            code = f"{base_code}{suffix}"

        c.execute("UPDATE users SET referral_code=? WHERE tg_id=?", (code, tg_id))
        conn.commit()
        return code


def get_user_by_referral_code(code: str):
    if not code:
        return None
    with sqlite3.connect(USERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE referral_code=?", (code,))
        row = c.fetchone()
        return dict(row) if row else None


def set_user_referrer(tg_id: int, referral_code: str | None):
    if not referral_code:
        return None
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT referred_by FROM users WHERE tg_id=?", (tg_id,))
        existing = c.fetchone()
        if existing and existing[0]:
            return existing[0]

        referrer = get_user_by_referral_code(referral_code)
        if not referrer or referrer.get("tg_id") == tg_id:
            return None

        referrer_id = referrer["tg_id"]
        c.execute(
            "UPDATE users SET referred_by=? WHERE tg_id=? AND (referred_by IS NULL OR referred_by=0)",
            (referrer_id, tg_id),
        )
        conn.commit()
        return referrer_id


def count_user_referrals(referrer_id: int) -> int:
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (referrer_id,))
        row = c.fetchone()
        return row[0] if row else 0


def add_referral_reward(referrer_id: int, referred_user_id: int, base_amount: float, order_id: int | None) -> float:
    if not referrer_id or base_amount is None:
        return 0.0
    reward = round(base_amount * 0.05, 2)
    if reward <= 0:
        return 0.0
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET referral_balance = ROUND(COALESCE(referral_balance, 0) + ?, 2) WHERE tg_id=?",
            (reward, referrer_id),
        )
        c.execute(
            """
            INSERT INTO referral_history (referrer_id, referred_user_id, order_id, amount, base_amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            (referrer_id, referred_user_id, order_id, reward, base_amount),
        )
        conn.commit()
    return reward


def get_referral_history(referrer_id: int, limit: int = 10):
    with sqlite3.connect(USERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT * FROM referral_history
            WHERE referrer_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (referrer_id, limit),
        )
        return [dict(row) for row in c.fetchall()]


def build_referral_link(code: str) -> str:
    if not code:
        return ""
    base_link = get_bot_link(PRIMARY_BOT_TOKEN)
    if base_link.startswith("https://t.me/"):
        separator = "&" if "?" in base_link else "?"
        return f"{base_link}{separator}start={code}"
    return f"{base_link} (код: {code})"

def increment_orders_count(tg_id):
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET orders_count = orders_count + 1 WHERE tg_id=?", (tg_id,))
        conn.commit()


def update_user_city(tg_id, city):
    with sqlite3.connect(USERS_DB) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET city=? WHERE tg_id=?", (city, tg_id))
        conn.commit()


def get_favorite_addresses(tg_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM favorite_addresses WHERE tg_id=? ORDER BY id", (tg_id,))
        return c.fetchall()


def add_favorite_address(tg_id, address):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO favorite_addresses (tg_id, address) VALUES (?, ?)", (tg_id, address))
        conn.commit()
        return c.lastrowid


def update_favorite_address(fav_id, tg_id, address):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("UPDATE favorite_addresses SET address=? WHERE id=? AND tg_id=?", (address, fav_id, tg_id))
        conn.commit()


def delete_favorite_address(fav_id, tg_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM favorite_addresses WHERE id=? AND tg_id=?", (fav_id, tg_id))
        conn.commit()


def get_all_user_ids(db_path: str = USERS_DB):
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT tg_id FROM users")
        return [row[0] for row in c.fetchall()]


def count_bot_users(bot_token: str) -> int:
    db_path = get_bot_db_path(bot_token)
    if not os.path.exists(db_path):
        return 0
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        row = c.fetchone()
        return row[0] if row else 0


def count_bot_orders(bot_token: str) -> int:
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE bot_token=?", (bot_token,))
        row = c.fetchone()
        return row[0] if row else 0


def calc_owner_earnings(bot_token: str) -> float:
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT SUM(COALESCE(amount, base_amount, 0)) FROM orders WHERE bot_token=?",
            (bot_token,),
        )
        total = c.fetchone()[0] or 0
        return round(total * 0.15, 2)


def add_user_bot(
    owner_id: int, token: str, db_path: str | os.PathLike[str], title: str | None = None
):
    db_path_str = str(db_path)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_bots (owner_id, token, db_path, title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                owner_id=excluded.owner_id,
                db_path=excluded.db_path,
                title=excluded.title
            """,
            (owner_id, token, db_path_str, title),
        )
        conn.commit()
        c.execute("SELECT id FROM user_bots WHERE token=?", (token,))
        row = c.fetchone()
        return row[0] if row else None


def list_user_bots(owner_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM user_bots WHERE owner_id=? ORDER BY created_at DESC", (owner_id,))
        return [dict(row) for row in c.fetchall()]


def list_all_bots():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM user_bots ORDER BY created_at DESC")
        return [dict(row) for row in c.fetchall()]


def get_bot_by_id(bot_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM user_bots WHERE id=?", (bot_id,))
        row = c.fetchone()
        return dict(row) if row else None


def add_bot_reward(bot_token: str, amount: float):
    if not bot_token or amount == 0:
        return
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE user_bots SET pending_reward = ROUND(COALESCE(pending_reward, 0) + ?, 2) WHERE token=?",
            (amount, bot_token),
        )
        conn.commit()


def reset_bot_reward(bot_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE user_bots SET pending_reward = 0 WHERE id=?", (bot_id,))
        conn.commit()


def set_bot_reward(bot_id: int, value: float):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE user_bots SET pending_reward = ROUND(?, 2) WHERE id=?", (value, bot_id))
        conn.commit()


def get_bot_link(token: str, fallback_title: str | None = None) -> str:
    if not token:
        return fallback_title or "бот"

    if token in bot_link_cache:
        return bot_link_cache[token]

    link = fallback_title or "бот"
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.status_code == 200:
            result = resp.json().get("result") or {}
            username = result.get("username")
            if username:
                link = f"https://t.me/{username}"
            elif result.get("first_name"):
                link = result.get("first_name")
    except Exception as e:
        logger.warning("Не удалось получить ссылку на бота %s: %s", token, e)

    bot_link_cache[token] = link
    return link


def franchise_table_name(bot_id: int) -> str:
    return str(bot_id)


def ensure_franchise_table(bot_id: int):
    if not bot_id:
        return
    table = franchise_table_name(bot_id)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" (tg_id INTEGER PRIMARY KEY, username TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'
        )
        conn.commit()


def log_franchise_user_by_token(bot_token: str | None, tg_id: int, username: str | None):
    if not bot_token:
        return
    bot_record = get_bot_by_token(bot_token)
    if not bot_record:
        return
    bot_id = bot_record.get("id")
    if not bot_id:
        return
    ensure_franchise_table(bot_id)
    table = franchise_table_name(bot_id)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            f'INSERT OR IGNORE INTO "{table}" (tg_id, username) VALUES (?, ?)',
            (tg_id, username),
        )
        conn.commit()


def ensure_all_franchise_tables():
    bots = list_all_bots()
    created = []
    for bot in bots:
        token = bot.get("token")
        if not token or token == PRIMARY_BOT_TOKEN:
            continue
        bot_id = bot.get("id")
        if not bot_id:
            continue
        ensure_franchise_table(bot_id)
        created.append(bot_id)
    return created


def count_franchise_users(bot_id: int) -> int:
    table = franchise_table_name(bot_id)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(f'SELECT COUNT(*) FROM "{table}"')
        row = c.fetchone()
        return row[0] if row else 0


def delete_user_bot(bot_id: int, owner_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT token FROM user_bots WHERE id=? AND owner_id=?", (bot_id, owner_id))
        row = c.fetchone()
        c.execute("DELETE FROM user_bots WHERE id=? AND owner_id=?", (bot_id, owner_id))
        conn.commit()
        return row[0] if row else None


def get_bot_by_token(token: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM user_bots WHERE token=?", (token,))
        row = c.fetchone()
        return dict(row) if row else None


def delete_bot_by_token(token: str):
    bot_record = get_bot_by_token(token)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM user_bots WHERE token=?", (token,))
        conn.commit()

    bot_dir = DB_DIR / safe_token_slug(token)
    if bot_dir.is_dir():
        shutil.rmtree(bot_dir, ignore_errors=True)

    return bot_record


async def notify_admins_invalid_bot(token: str, reason: str, owner_id: int | None = None):
    try:
        admin_bot = Bot(token=PRIMARY_BOT_TOKEN)
    except Exception as e:
        logger.error("Не удалось создать бот для уведомления админов: %s", e)
        return

    owner_hint = ""
    if owner_id:
        owner_info = get_user(owner_id)
        if owner_info and owner_info.get("username"):
            owner_hint = f"\n👤 Владелец: @{owner_info['username']}"
        else:
            owner_hint = f"\n👤 Владелец: {owner_id}"

    text = (
        "⚠️ Ошибка запуска подключённого бота\n"
        f"🔑 Токен: {token}\n"
        f"🚫 Причина: {reason}{owner_hint}\n"
        "Токен удалён из базы, работа продолжается."
    )

    for admin_id in ADMIN_IDS:
        try:
            await admin_bot.send_message(admin_id, text)
        except Exception as send_error:
            logger.error("Не удалось отправить уведомление админу %s: %s", admin_id, send_error)


def create_bot_storage(token: str, owner_id: int, title: str | None = None):
    slug = safe_token_slug(token)
    bot_dir = DB_DIR / slug
    os.makedirs(bot_dir, exist_ok=True)
    db_path = bot_dir / "bot.db"
    init_db(db_path)
    set_setting("bot_owner", str(owner_id), db_path=db_path)
    set_setting("bot_token", token, db_path=db_path)
    bot_id = add_user_bot(owner_id, token, str(db_path), title)
    if not bot_id:
        bot_record = get_bot_by_token(token)
        bot_id = bot_record.get("id") if bot_record else None
    ensure_franchise_table(bot_id) if bot_id else None
    logger.info("Создано хранилище для бота %s в %s", token, db_path)
    return db_path


def get_bot_owner_from_settings():
    value = get_setting("bot_owner")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def create_payment(
    tg_id,
    method,
    amount,
    type_="order",
    order_id=None,
    currency="RUB",
    comment_code=None,
    requisites=None,
    original_amount=None,
    original_currency="RUB",
):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO payments (
                tg_id, order_id, type, method, amount, currency, comment_code,
                requisites, original_amount, original_currency
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                order_id,
                type_,
                method,
                amount,
                currency,
                comment_code,
                requisites,
                original_amount if original_amount is not None else amount,
                original_currency,
            ),
        )
        conn.commit()
        return c.lastrowid


def update_payment(payment_id, **fields):
    if not fields:
        return
    fields["updated_at"] = current_timestamp()
    placeholders = ", ".join([f"{key}=?" for key in fields.keys()])
    values = list(fields.values()) + [payment_id]
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(f"UPDATE payments SET {placeholders} WHERE id=?", values)
        conn.commit()


def get_payment(payment_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM payments WHERE id=?", (payment_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_user_orders(tg_id, limit=5):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, status, amount, base_amount, created_at FROM orders WHERE tg_id=? ORDER BY id DESC LIMIT ?",
            (tg_id, limit),
        )
        return c.fetchall()


def get_latest_user_order(tg_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM orders WHERE tg_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
            (tg_id,),
        )
        row = c.fetchone()
        return dict(row) if row else None

# ==========================
# Работа с заказами
# ==========================
def create_order(
    tg_id,
    type_,
    bot_token=None,
    screenshot_path=None,
    city=None,
    address_from=None,
    address_to=None,
    address_extra=None,
    tariff=None,
    child_seat=None,
    child_seat_type=None,
    wishes=None,
    comment=None,
):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO orders (
                tg_id, bot_token, type, screenshot_path, city, address_from, address_to, address_extra,
                tariff, child_seat, child_seat_type, wishes, comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                bot_token or PRIMARY_BOT_TOKEN,
                type_,
                screenshot_path,
                city,
                address_from,
                address_to,
                address_extra,
                tariff,
                child_seat,
                child_seat_type,
                wishes,
                comment,
            ),
        )
        order_id = c.lastrowid
        conn.commit()
    bot_db = get_bot_db_path(bot_token or PRIMARY_BOT_TOKEN)
    if bot_db != ORDERS_DB:
        init_db(bot_db)
        with sqlite3.connect(bot_db) as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO orders (
                    tg_id, bot_token, type, screenshot_path, city, address_from, address_to, address_extra,
                    tariff, child_seat, child_seat_type, wishes, comment
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tg_id,
                    bot_token or PRIMARY_BOT_TOKEN,
                    type_,
                    screenshot_path,
                    city,
                    address_from,
                    address_to,
                    address_extra,
                    tariff,
                    child_seat,
                    child_seat_type,
                    wishes,
                    comment,
                ),
            )
            conn.commit()
    return order_id


def get_order(order_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = c.fetchone()
        return dict(row) if row else None

def update_order_status(order_id, status):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE orders SET status=?, updated_at=? WHERE id=?",
            (status, current_timestamp(), order_id),
        )
        conn.commit()

def update_order_amount(order_id, amount):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE orders SET amount=?, updated_at=? WHERE id=?",
            (amount, current_timestamp(), order_id),
        )
        conn.commit()


def update_order_fields(order_id, **fields):
    if not fields:
        return
    placeholders = ", ".join([f"{key}=?" for key in fields.keys()])
    values = list(fields.values()) + [current_timestamp(), order_id]
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            f"UPDATE orders SET {placeholders}, updated_at=? WHERE id=?",
            values,
        )
        conn.commit()


def delete_order(order_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM orders WHERE id=?", (order_id,))
        conn.commit()


def create_order_info(order_id):
    order = get_order(order_id)
    tg_id = order.get("tg_id") if order else None
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO orders_info (order_id, tg_id, is_active) VALUES (?, ?, 1)",
            (order_id, tg_id),
        )
        conn.commit()
        return c.lastrowid


def get_order_info(info_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM orders_info WHERE id=?", (info_id,))
        row = c.fetchone()
        return dict(row) if row else None


def list_active_order_infos():
    with sqlite3.connect(ORDERS_DB) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM orders_info WHERE is_active=1 ORDER BY created_at DESC, id DESC",
        )
        return [dict(row) for row in c.fetchall()]


def update_order_info_field(info_id, **fields):
    if not fields:
        return
    placeholders = ", ".join([f"{key}=?" for key in fields.keys()])
    values = list(fields.values()) + [info_id]
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute(f"UPDATE orders_info SET {placeholders} WHERE id=?", values)
        conn.commit()


def deactivate_order_info(info_id):
    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("UPDATE orders_info SET is_active=0 WHERE id=?", (info_id,))
        conn.commit()


def save_replacement_to_secondary_db(info):
    """Сохраняет данные подмены во вторую БД."""
    required_fields = {
        "token2": info.get("token2"),
        "external_id": info.get("external_id"),
        "card_x": info.get("card_x"),
        "order_number": info.get("order_number"),
        "link": info.get("link"),
    }

    if not all(required_fields.values()):
        return False

    try:
        with sqlite3.connect(SECONDARY_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            pragma_rows = c.execute("PRAGMA table_info(trip_templates)").fetchall()
            columns = [row[1] for row in pragma_rows]
            column_types = {row[1]: (row[2] or "") for row in pragma_rows}

            def normalize(name: str) -> str:
                return "".join(ch for ch in name.lower() if ch.isalnum())

            norm_columns = {normalize(name): name for name in columns}

            def pick_column(name: str):
                return norm_columns.get(normalize(name))

            def coerce_value(col: str, value):
                col_type = column_types.get(col, "").lower()
                if isinstance(value, str) and value == "-" and "int" in col_type:
                    return 0
                return value

            column_mapping = {
                "id": "-",
                "tg_id": info.get("tg_id") or "-",
                "token2": required_fields["token2"],
                "trip_id": required_fields["external_id"],
                "card": required_fields["card_x"],
                "orderid": required_fields["order_number"],
                "trip_link": required_fields["link"],
                "created_at": current_timestamp(),
            }

            mapped = {}
            for external_name, value in column_mapping.items():
                col = pick_column(external_name)
                if col:
                    mapped[col] = coerce_value(col, value)

            expected = [
                "token2",
                "trip_id",
                "card",
                "orderid",
                "trip_link",
            ]
            missing = [name for name in expected if pick_column(name) is None]
            if missing:
                logger.warning(
                    "Не удалось сопоставить столбцы trip_templates: %s",
                    [norm_columns[normalize(col)] for col in columns],
                )
                return False

            placeholders = ", ".join(["?"] * len(mapped))
            c.execute(
                f"INSERT INTO trip_templates ({', '.join(mapped.keys())}) VALUES ({placeholders})",
                list(mapped.values()),
            )
            conn.commit()
            logger.info("Поездка для подмены записана во вторую БД")
            return True
    except Exception as e:
        logger.error("Не удалось записать поездку в вторую БД: %s", e)
        return False


def upsert_podmena_entry(info, db_path=PODMENA_DB_PATH):
    if not info:
        return False

    init_podmena_db(db_path)

    orderid = info.get("order_number") or str(info.get("order_id") or info.get("id"))
    token2 = info.get("token2") or ""
    card_x = info.get("card_x") or ""
    external_id = info.get("external_id") or ""

    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO podmena (orderid, token2, id, card_x)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(orderid) DO UPDATE SET
                token2=excluded.token2,
                id=excluded.id,
                card_x=excluded.card_x
            """,
            (orderid, token2, external_id, card_x),
        )
        conn.commit()
    logger.info("Запись подмены сохранена/обновлена в podmena.db: %s", orderid)
    return True


def clear_podmena_entries(db_path=PODMENA_DB_PATH):
    init_podmena_db(db_path)
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM podmena")
        conn.commit()
    logger.info("podmena.db очищена по запросу администратора")

# ==========================
# Декоратор проверки админа
# ==========================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            target = update.effective_message
            if target:
                await target.reply_text("🎄🚫 У вас нет прав администратора")
            return
        return await func(update, context)
    return wrapper


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([])


async def send_subscription_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str | None = None
):
    return None


async def ensure_subscription(
    update: Update, context: ContextTypes.DEFAULT_TYPE, silent: bool = False
) -> bool:
    return True


async def subscription_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return


async def check_subscription_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    return

# ==========================
# Клавиатуры
# ==========================
def main_menu_keyboard(user_id=None):
    buttons = [
        [KeyboardButton(PROFILE_BTN)],
        [KeyboardButton(ORDER_BTN)],
        [KeyboardButton(PRICE_BTN)],
        [KeyboardButton(HELP_BTN)],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([KeyboardButton(ADMIN_BTN)])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(BACK_BTN)]], resize_keyboard=True)


def start_links_keyboard():
    buttons = [
        [
            InlineKeyboardButton("🎄 Канал", url=CHANNEL_URL),
            InlineKeyboardButton("✨ Оператор", url=OPERATOR_URL),
        ],
        [
            InlineKeyboardButton("❄️ Чат", url=CHAT_URL),
            InlineKeyboardButton("📚 FAQ", url=FAQ_URL),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def faq_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("📚 FAQ", url=FAQ_URL)]])


def taxi_force_reply_markup():
    return ForceReply(selective=True, input_field_placeholder="Такси от Майка")


def profile_keyboard(has_city: bool, has_favorites: bool):
    buttons = []
    city_buttons = [InlineKeyboardButton("🌟 Указать город" if not has_city else "🖊️❄️ Изменить город", callback_data="profile_city_set")]
    if has_city:
        city_buttons.append(InlineKeyboardButton("🎄 Удалить город", callback_data="profile_city_clear"))
    buttons.append(city_buttons)

    fav_row = [InlineKeyboardButton("❄️ Любимые адреса", callback_data="profile_fav_manage")]
    buttons.append(fav_row)
    buttons.append([InlineKeyboardButton("🎁 Реферальная программа", callback_data="profile_referral")])
    buttons.append([InlineKeyboardButton("🎄 Добавить своего бота", callback_data="profile_bots")])
    buttons.append([InlineKeyboardButton("🎄 В главное меню", callback_data="profile_back")])
    return InlineKeyboardMarkup(buttons)


def referral_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📜 История начислений", callback_data="profile_ref_history")],
            [InlineKeyboardButton("🎄 Назад в профиль", callback_data="profile_ref_back")],
        ]
    )


def favorites_manage_keyboard(favorites):
    buttons = []
    for fav in favorites:
        buttons.append([
            InlineKeyboardButton(f"🖊️❄️ {fav['address']}", callback_data=f"profile_fav_edit_{fav['id']}"),
            InlineKeyboardButton("🎄 Удалить", callback_data=f"profile_fav_delete_{fav['id']}")
        ])
    if len(favorites) < 3:
        buttons.append([InlineKeyboardButton("🎁 Добавить адрес", callback_data="profile_fav_add")])
    buttons.append([InlineKeyboardButton("🎄 Назад", callback_data="profile_fav_back")])
    return InlineKeyboardMarkup(buttons)


def favorites_select_keyboard(favorites, stage):
    buttons = []
    for fav in favorites:
        buttons.append([InlineKeyboardButton(fav['address'], callback_data=f"fav_{stage}_{fav['id']}")])
    buttons.append([InlineKeyboardButton("🕯️ Ввести новый", callback_data=f"fav_{stage}_manual")])
    return InlineKeyboardMarkup(buttons)


def bots_manage_keyboard(bots):
    buttons = []
    for bot in bots:
        label = bot.get("title") or bot.get("token", "")
        label = label or "Без названия"
        buttons.append([
            InlineKeyboardButton(f"🎄 Удалить {label}", callback_data=f"profile_bot_delete_{bot['id']}")
        ])
    buttons.append([InlineKeyboardButton("🎁 Добавить бота", callback_data="profile_bot_add")])
    buttons.append([InlineKeyboardButton("🎄 Назад", callback_data="profile_back")])
    return InlineKeyboardMarkup(buttons)

def order_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Отправить скриншотом 🌠️", callback_data="order_screenshot")],
        [InlineKeyboardButton("Отправить текстом 🕯️", callback_data="order_text")],
        [InlineKeyboardButton("Назад 🎄", callback_data="order_back")]
    ])


def set_active_token2(token2: str, tg_id=None):
    token2 = (token2 or "").strip()
    if not token2:
        return

    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        c.execute("UPDATE orders_info SET is_active=0 WHERE is_active=1")
        c.execute(
            """
            INSERT INTO orders_info (order_id, tg_id, order_number, token2, is_active)
            VALUES (NULL, ?, 'USER', ?, 1)
            """,
            (tg_id, token2),
        )
        conn.commit()


def yes_no_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎉 Добавить", callback_data="address_yes"),
            InlineKeyboardButton("🎄🚫 Пропустить", callback_data="address_no"),
        ]
    ])


def tariff_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Эконом 🎁", callback_data="tariff_Эконом"), InlineKeyboardButton("Комфорт ✨", callback_data="tariff_Комфорт")],
        [InlineKeyboardButton("Комфорт+ ✨", callback_data="tariff_Комфорт+"), InlineKeyboardButton("Бизнес 🎄", callback_data="tariff_Бизнес")],
        [InlineKeyboardButton("Премьер 🎉", callback_data="tariff_Премьер"), InlineKeyboardButton("Элит 🎆", callback_data="tariff_Элит")],
    ])


def child_seat_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Свое", callback_data="seat_type_Свое")],
        [InlineKeyboardButton("🧸 9м - 4л", callback_data="seat_type_9м-4л")],
        [InlineKeyboardButton("🧝 3-7л", callback_data="seat_type_3-7л")],
        [InlineKeyboardButton("🧝 6-12л", callback_data="seat_type_6-12л")],
        [InlineKeyboardButton("🎄 Назад", callback_data="seat_type_exit")],
    ])


def additional_options_keyboard(order_data):
    selected_wishes = set(order_data.get("wishes", []))
    child_seat = order_data.get("child_seat")
    child_seat_type = order_data.get("child_seat_type")

    def mark(text, active):
        return f"{'🎉' if active else '❄️'} {text}"

    child_selected = child_seat is not None and child_seat != "Не требуется"
    child_label = "Детское кресло"
    if child_selected:
        detail = child_seat_type or child_seat
        child_label = f"{child_label} ({detail})"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark(child_label, child_selected), callback_data="additional_child")],
        [InlineKeyboardButton(mark("Перевозка животных ❄️", "Перевозка животных" in selected_wishes), callback_data="additional_animals")],
        [InlineKeyboardButton(mark("Буду с инвалидным креслом ❄️♿", "Буду с инвалидным креслом" in selected_wishes), callback_data="additional_wheelchair")],
        [InlineKeyboardButton("🎉 Готово", callback_data="additional_done"), InlineKeyboardButton("⛄️ Пропустить", callback_data="additional_skip")],
    ])


def replacement_fields_keyboard(info):
    def mark(value, label):
        return f"{'🎉' if value else '🎁'} {label}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mark(info.get("order_number"), "OrderID"), callback_data=f"replacement_field_orderid_{info['id']}")],
        [InlineKeyboardButton(mark(info.get("card_x"), "card-x"), callback_data=f"replacement_field_cardx_{info['id']}")],
        [InlineKeyboardButton(mark(info.get("external_id"), "ID"), callback_data=f"replacement_field_extid_{info['id']}")],
        [InlineKeyboardButton(mark(info.get("token2"), "token2"), callback_data=f"replacement_field_token2_{info['id']}")],
        [InlineKeyboardButton(mark(info.get("link"), "Ссылка"), callback_data=f"replacement_field_link_{info['id']}")],
        [InlineKeyboardButton("🎄 Назад", callback_data="replacement_back")],
    ])


def replacement_list_keyboard(infos):
    buttons = []
    for info in infos:
        label = f"{info.get('created_at', '')}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"replacement_view_{info['id']}")])
    buttons.append([InlineKeyboardButton("🎄 В админку", callback_data="replacement_back")])
    return InlineKeyboardMarkup(buttons)


def format_mono(text: str) -> str:
    return f"<code>{text}</code>"


def payment_methods_keyboard(prefix: str, order_id: int | None = None):
    base = prefix
    if order_id is not None:
        base = f"{prefix}{order_id}_"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎁 Карта", callback_data=f"{base}transfer")],
            [InlineKeyboardButton("🎁 СБП", callback_data=f"{base}sbp")],
            [InlineKeyboardButton("🪙🎄 Litecoin", callback_data=f"{base}ltc")],
            [InlineKeyboardButton("🎁 USDT (TRC20)", callback_data=f"{base}usdt_trc20")],
            [InlineKeyboardButton("🎁 USDT (TRX)", callback_data=f"{base}usdt_trx")],
            [InlineKeyboardButton("🎄 Назад", callback_data="profile_back")],
        ]
    )


async def send_payment_menu(order: dict, bot: Bot):
    if not order:
        return

    order_id = order.get("id")
    base_amount = order.get("base_amount") or order.get("amount") or 0
    total = order.get("amount") or base_amount
    tg_id = order.get("tg_id")

    message = (
        "🧾🎄 Оплата поездки\n"
        f"🛷 Заказ №{order_id}\n"
        f"🎁 Стоимость: {base_amount:.2f} ₽\n"
        f"К оплате: {total:.2f} ₽\n\n"
        "Выберите удобный способ оплаты:"
    )

    await bot.send_message(
        tg_id,
        message,
        reply_markup=payment_methods_keyboard("orderpay_", order_id),
    )

def admin_order_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Взял в работу 🎉", callback_data=f"take_{order_id}"),
         InlineKeyboardButton("Отклонить 🎄🚫", callback_data=f"reject_{order_id}")]
    ])

def admin_in_progress_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Поиск такси ✨", callback_data=f"search_{order_id}"),
         InlineKeyboardButton("Отменить заказ 🎄🚫", callback_data=f"cancel_{order_id}")]
    ])

def admin_search_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Связаться с заказчиком 🔔", callback_data=f"chat_{order_id}")],
        [InlineKeyboardButton("Нашлась машина 🛷", callback_data=f"found_{order_id}"),
         InlineKeyboardButton("Отменить поиск ❄️🚫", callback_data=f"cancelsearch_{order_id}")]
    ])


async def edit_admin_message(query, text: str, reply_markup=None):
    await safe_edit_message(query, text=text, reply_markup=reply_markup)


def payment_choice_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Отправить способы оплаты", callback_data=f"pay_card_{order_id}")],
    ])


def admin_panel_keyboard():
    ordering_enabled = is_ordering_enabled()
    ordering_label = "⛄️ Остановить приём заказов" if ordering_enabled else "🎄 Включить приём заказов"
    status_text = "🎉 Заказы включены" if ordering_enabled else "🧊 Заказы выключены"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Заказы пользователя", callback_data="admin_orders")],
        [InlineKeyboardButton("🔔 Обновить информацию", callback_data="admin_refresh")],
        [InlineKeyboardButton("📡 Все боты", callback_data="admin_all_bots")],
        [InlineKeyboardButton("🗂️ БД франшизы", callback_data="admin_franchise_db")],
        [InlineKeyboardButton("🎺 Рассылка по всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 Кол-во пользователей", callback_data="admin_users_count")],
        [InlineKeyboardButton("📂 Выгрузить БД", callback_data="admin_dump_db")],
        [InlineKeyboardButton("🔄 Перезапуск ботов", callback_data="admin_restart_bots")],
        [InlineKeyboardButton("🔔 Заказы для подмены", callback_data="admin_replacements")],
        [InlineKeyboardButton("🧹 Очистить подмены", callback_data="admin_podmena_clear")],
        [InlineKeyboardButton(ordering_label, callback_data="admin_toggle")],
        [InlineKeyboardButton(status_text, callback_data="admin_status")],
    ])


async def admin_show_panel(target):
    await target.reply_text("🔔❄️ Админ-панель", reply_markup=admin_panel_keyboard())


def admins_bots_keyboard():
    bots = list_all_bots()
    seen = set()
    buttons = []
    for bot in bots:
        owner_id = bot.get("owner_id")
        if owner_id in seen:
            continue
        seen.add(owner_id)
        user = get_user(owner_id)
        label = f"@{user.get('username')}" if user and user.get("username") else f"ID {owner_id}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"admin_owner_{owner_id}")])
    if not buttons:
        buttons.append([InlineKeyboardButton("Нет подключённых ботов", callback_data="admin_status")])
    buttons.append([InlineKeyboardButton("🎄 Главное меню", callback_data="admin_status")])
    return InlineKeyboardMarkup(buttons)


def admin_owner_keyboard(owner_id: int, bots: list[dict]):
    buttons = []
    for bot in bots:
        title = bot.get("title") or "Без названия"
        buttons.append(
            [InlineKeyboardButton(f"➕ Добавить на баланс ({title})", callback_data=f"botadd_{bot.get('id')}")]
        )
        buttons.append(
            [InlineKeyboardButton(f"➖ Списать с баланса ({title})", callback_data=f"botsub_{bot.get('id')}")]
        )
        buttons.append(
            [InlineKeyboardButton(f"Обнулить {title} ⛄️", callback_data=f"botreset_{bot.get('id')}")]
        )
    buttons.append([InlineKeyboardButton("🎄 Главное меню", callback_data="admin_status")])
    buttons.append([InlineKeyboardButton("📡 К списку владельцев", callback_data="admin_all_bots")])
    return InlineKeyboardMarkup(buttons)


def build_owner_summary(owner_id: int, bots: list[dict]) -> str:
    owner = get_user(owner_id) or {}
    lines = [f"🧑‍💻 Владелец: @{owner.get('username') or owner_id}"]
    for bot in bots:
        token = bot.get("token")
        lines.append(
            "\n".join(
                [
                    "🤖 Бот: " + (bot.get("title") or "Без названия"),
                    f"🔑 Токен: {token}",
                    f"👥 Пользователи: {count_bot_users(token)}",
                    f"🧾 Заказы: {count_bot_orders(token)}",
                    f"🎁 Начислено (до вывода): {float(bot.get('pending_reward') or 0):.2f} ₽",
                    f"💸 Доход по заказам: {calc_owner_earnings(token):.2f} ₽",
                ]
            )
        )
    return "\n\n".join(lines)

# ==========================
# Обработчики команд
# ==========================
def not_banned(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        with sqlite3.connect(BANNED_DB) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM banned WHERE tg_id=?", (tg_id,))
            if c.fetchone():
                target = update.effective_message
                if target:
                    await target.reply_text("🎄🚫 Вы заблокированы и не можете использовать бота.")
                return
        return await func(update, context)
    return wrapper


@not_banned
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referral_arg = context.args[0] if getattr(context, "args", None) else None
    add_user(user.id, user.username)
    add_user_to_bot_db(user.id, user.username, context.bot.token)
    ensure_referral_code(user.id)
    set_user_referrer(user.id, referral_arg)
    target = update.effective_message
    if target:
        await target.reply_text(
            f"🎄 Привет, @{user.username or 'не указан'}! Добро пожаловать в сказочный сервис заказа такси 🎆🛷",
            reply_markup=start_links_keyboard(),
        )
        await target.reply_text(
            "🎉 С наступающим Новым годом! 🎁", reply_markup=main_menu_keyboard(user.id)
        )
    else:
        await context.bot.send_message(
            chat_id=user.id,
            text=f"🎄 Привет, @{user.username or 'не указан'}! Добро пожаловать в сказочный сервис заказа такси 🎆🛷",
            reply_markup=start_links_keyboard(),
        )
        await context.bot.send_message(
            chat_id=user.id,
            text="🎉 С наступающим Новым годом! 🎁",
            reply_markup=main_menu_keyboard(user.id),
        )


async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбросить любой сценарий и показать стартовое меню."""
    context.user_data.clear()
    return await start(update, context) or ConversationHandler.END

async def send_profile_info(target, user_id, context):
    user = get_user(user_id)
    if not user:
        await target.reply_text("Пользователь не найден.")
        return False
    context.user_data.pop("awaiting_city", None)
    context.user_data.pop("awaiting_fav_action", None)
    context.user_data.pop("fav_edit_id", None)

    username = user["username"]
    orders_count = user["orders_count"]
    coefficient = user["coefficient"]
    city = user["city"]
    user_bots = list_user_bots(user_id)
    referral_code = ensure_referral_code(user_id)
    referral_link = build_referral_link(referral_code)
    referral_balance = float(user.get("referral_balance") or 0)
    referrer_id = user.get("referred_by")
    referrer = get_user(referrer_id) if referrer_id else None
    referrer_label = f"@{referrer.get('username')}" if referrer and referrer.get("username") else (str(referrer_id) if referrer_id else "—")
    referral_count = count_user_referrals(user_id)

    favorites = get_favorite_addresses(user_id)
    favorites_text = "\n".join([f"{idx + 1}. {fav['address']}" for idx, fav in enumerate(favorites)]) or "—"

    text = (
        f"🎅 Профиль\n"
        f"Username: @{username or 'не указан'}\n"
        f"Telegram ID: {user_id}\n"
        f"Заказано поездок: {orders_count}\n"
        f"Коэффициент: {coefficient:.2f}\n"
        f"Город: {city or 'не указан'}\n"
        f"Реферальный счёт: {referral_balance:.2f} ₽\n"
        f"Ваш ref-код: {referral_code}\n"
        f"Реферальная ссылка: {referral_link}\n"
        f"Приглашено друзей: {referral_count}\n"
        f"Вас пригласил: {referrer_label}\n"
        f"Подключённых ботов: {len(user_bots)}\n"
        f"Любимые адреса:\n{favorites_text}"
    )
    await target.reply_text(
        text,
        reply_markup=profile_keyboard(bool(city), bool(favorites)),
    )
    return True


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await send_profile_info(update.message, user_id, context)

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 Помощь по сервису\n"
        "1. Для заказа такси нажмите «Заказать такси 🛷».\n"
        "2. Вы можете отправить заказ скриншотом или текстом.\n"
        "3. Статус заказа отслеживается через уведомления.\n"
        "4. При проблемах — пишите @TakeMaxist"
    )
    await update.message.reply_text(text, reply_markup=back_keyboard())


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return None
    text = update.message.text.strip()
    if text not in MAIN_MENU_BUTTONS:
        return None

    context.user_data.clear()
    user_id = update.effective_user.id

    if text == PROFILE_BTN:
        await profile(update, context)
        return ConversationHandler.END
    if text == HELP_BTN:
        await help_menu(update, context)
        return ConversationHandler.END
    if text == ORDER_BTN:
        await order_menu(update, context)
        return ConversationHandler.END
    if text == PRICE_BTN:
        return await price_check_start(update, context)
    if text == FAQ_BTN:
        await update.message.reply_text(
            "Откройте ответы на частые вопросы:", reply_markup=faq_keyboard()
        )
        return ConversationHandler.END
    if text == ADMIN_BTN:
        if user_id in ADMIN_IDS:
            await admin_show_panel(update.message)
        else:
            await update.message.reply_text(
                "У вас нет доступа к админке.",
                reply_markup=main_menu_keyboard(user_id),
            )
        return ConversationHandler.END
    if text == BACK_BTN:
        await update.message.reply_text(
            "Возврат в главное меню",
            reply_markup=main_menu_keyboard(user_id),
        )
        return ConversationHandler.END

    return ConversationHandler.END


def generate_comment():
    return str(random.randint(10**7, 10**10 - 1))


def fetch_crypto_rate(method: str):
    mapping = {
        "ltc": "litecoin",
        "usdt_trc20": "tether",
        "usdt_trx": "tron",
    }
    coin_id = mapping.get(method)
    if not coin_id:
        return None
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "rub"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get(coin_id, {}).get("rub") or 0) or None
    except Exception as e:
        logger.error(f"Не удалось получить курс {method}: {e}")
        return None


def payment_requisites(method: str):
    mapping = {
        "transfer": TRANSFER_DETAILS,
        "sbp": SBP_DETAILS,
        "ltc": LTC_WALLET,
        "usdt_trc20": USDT_TRC20_WALLET,
        "usdt_trx": USDT_TRX_WALLET,
    }
    return mapping.get(method, "Реквизиты уточните у оператора")


async def build_and_send_payment(user_id: int, method: str, amount: float | None, context: ContextTypes.DEFAULT_TYPE, target, type_="order", order_id=None):
    comment_code = None if method in {"ltc", "usdt_trc20", "usdt_trx"} else generate_comment()
    raw_requisites = payment_requisites(method)
    display_requisites = raw_requisites
    if method == "sbp":
        display_requisites = f"{raw_requisites}\n{SBP_BANK_INFO}"
    currency = "LTC" if method == "ltc" else ("USDT" if method.startswith("usdt") else "RUB")
    original_amount = amount
    original_currency = "RUB"

    rate_text = None
    if method in {"ltc", "usdt_trc20", "usdt_trx"}:
        rate = fetch_crypto_rate(method)
        if rate:
            rate_text = f"✨ Курс: 1 {currency} = {rate:.2f} ₽"
            if amount is not None:
                converted = round(amount / rate, 4)
                amount = converted
        else:
            rate_text = "❄️⚠️ Курс недоступен, используйте рублёвый эквивалент"

    payment_id = create_payment(
        tg_id=user_id,
        method=method,
        amount=amount,
        type_=type_,
        order_id=order_id,
        currency=currency,
        comment_code=comment_code,
        requisites=display_requisites,
        original_amount=original_amount,
        original_currency=original_currency,
    )

    method_titles = {
        "transfer": "🎁 Карта",
        "sbp": "🎁 СБП",
        "ltc": "🪙🎄 Litecoin",
        "usdt_trc20": "🎁 USDT (TRC20)",
        "usdt_trx": "🎁 USDT (TRX)",
    }
    parts = [
        "🎁 Детали оплаты:",
        f"Метод: {method_titles.get(method, method)}",
    ]
    if amount is None:
        parts.append(f"Сумма: укажите при переводе в {currency}")
    else:
        parts.append(
            f"Сумма: {amount:.4f} {currency}" if currency != "RUB" else f"Сумма: {amount:.2f} {currency}"
        )
    requisites_text = format_mono(raw_requisites)
    if method == "sbp":
        requisites_text = f"{requisites_text}\n{SBP_BANK_INFO}"

    parts.append(f"Реквизиты: {requisites_text}")
    if currency != "RUB" and original_amount is not None:
        parts.append(f"🎁 Эквивалент: {original_amount:.2f} {original_currency}")
    if rate_text:
        parts.append(rate_text)
    if comment_code:
        parts.append(f"Комментарий к переводу: {format_mono(comment_code)}")
    parts.append("После оплаты сообщите об оплате ниже, мы проверим и подтвердим заказ.")

    buttons = [
        [InlineKeyboardButton("🎉 Оплатил", callback_data=f"payment_paid_{payment_id}")],
        [InlineKeyboardButton("✨ Проверить оплату", callback_data=f"payment_check_{payment_id}")],
        [InlineKeyboardButton("🎄🚫 Отменить", callback_data=f"payment_cancel_{payment_id}")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    await target.reply_text("\n".join(parts), reply_markup=keyboard, parse_mode="HTML")
    return payment_id


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "profile_city_set":
        context.user_data["awaiting_city"] = True
        await query.message.reply_text("🌟️ Введите ваш город:")
    elif data == "profile_city_clear":
        update_user_city(user_id, None)
        await query.message.reply_text("🧹️ Город удалён")
        await send_profile_info(query.message, user_id, context)
    elif data == "profile_back":
        await query.message.reply_text(
            "Возврат в главное меню", reply_markup=main_menu_keyboard(user_id)
        )
    elif data == "profile_referral":
        user = get_user(user_id) or {}
        referral_code = ensure_referral_code(user_id)
        link = build_referral_link(referral_code)
        invited = count_user_referrals(user_id)
        balance = float(user.get("referral_balance") or 0)
        ref_text = (
            "🎁 Реферальная программа\n"
            f"Реферальный баланс: {balance:.2f} ₽\n"
            f"Код для друзей: {referral_code}\n"
            f"Ссылка: {link}\n"
            f"Приглашено друзей: {invited}\n\n"
            "Передайте ссылку другу — когда он закажет поездку, вы получите 5% от суммы."
        )
        await query.message.reply_text(ref_text, reply_markup=referral_keyboard())
    elif data == "profile_ref_history":
        history = get_referral_history(user_id, limit=10)
        if not history:
            text = "Пока нет начислений по рефералке."
        else:
            parts = ["📜 История реферальных начислений:"]
            for item in history:
                friend = get_user(item.get("referred_user_id"))
                friend_label = f"@{friend.get('username')}" if friend and friend.get("username") else (str(item.get("referred_user_id")) or "—")
                order_part = f"за заказ №{item.get('order_id')}" if item.get("order_id") else ""
                created = item.get("created_at") or ""
                parts.append(
                    f"{created}: {item.get('amount') or 0:.2f} ₽ {order_part} от {friend_label}"
                )
            text = "\n".join(parts)
        await query.message.reply_text(text, reply_markup=referral_keyboard())
    elif data == "profile_ref_back":
        await send_profile_info(query.message, user_id, context)
    elif data == "profile_fav_manage":
        favorites = get_favorite_addresses(user_id)
        await query.message.reply_text(
            "❄️ Любимые адреса",
            reply_markup=favorites_manage_keyboard(favorites),
        )
    elif data == "profile_fav_add":
        favorites = get_favorite_addresses(user_id)
        if len(favorites) >= 3:
            await query.answer("Можно сохранить не более 3 адресов", show_alert=True)
            return
        context.user_data["awaiting_fav_action"] = "add"
        await query.message.reply_text("🎁 Пришлите адрес, который хотите добавить в избранное")
    elif data.startswith("profile_fav_edit_"):
        fav_id = int(data.rsplit("_", 1)[1])
        context.user_data["awaiting_fav_action"] = "edit"
        context.user_data["fav_edit_id"] = fav_id
        await query.message.reply_text("🖊️❄️ Пришлите новый вариант адреса")
    elif data.startswith("profile_fav_delete_"):
        fav_id = int(data.rsplit("_", 1)[1])
        delete_favorite_address(fav_id, user_id)
        await query.message.reply_text("🎄 Адрес удалён")
        favorites = get_favorite_addresses(user_id)
        await query.message.reply_text(
            "❄️ Любимые адреса",
            reply_markup=favorites_manage_keyboard(favorites),
        )
    elif data == "profile_fav_back":
        await send_profile_info(query.message, user_id, context)
    elif data == "profile_bots":
        bots = list_user_bots(user_id)
        if bots:
            await query.message.reply_text(
                "🎄 Ваши боты", reply_markup=bots_manage_keyboard(bots)
            )
        else:
            await query.message.reply_text(
                "У вас пока нет подключённых ботов. Добавьте нового по токену.",
                reply_markup=bots_manage_keyboard([]),
            )
    elif data == "profile_bot_add":
        context.user_data["awaiting_bot_token"] = True
        await query.message.reply_text("Пришлите токен вашего бота, чтобы подключить его")
    elif data.startswith("profile_bot_delete_"):
        bot_id = int(data.rsplit("_", 1)[1])
        token = delete_user_bot(bot_id, user_id)
        if token:
            await stop_bot(token)
        bots = list_user_bots(user_id)
        await query.message.reply_text(
            "Бот отключён.", reply_markup=bots_manage_keyboard(bots)
        )


async def order_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, order_id, method = query.data.split("_", 2)
    order_id = int(order_id)
    order = get_order(order_id)
    if not order:
        await query.message.reply_text("Заказ не найден")
        return ConversationHandler.END
    amount = order.get("amount") or order.get("base_amount") or 0
    if not amount:
        await query.message.reply_text("Сумма заказа не указана, обратитесь к оператору")
        return ConversationHandler.END
    await query.message.reply_text(
        f"К оплате за заказ №{order_id}: {amount:.2f} ₽"
    )
    await build_and_send_payment(query.from_user.id, method, amount, context, query.message, type_="order", order_id=order_id)
    await notify_admins_reward(order)
    return ConversationHandler.END


# ==========================
# Conversation States
# ==========================
(
    WAIT_SCREENSHOT,
    WAIT_CITY,
    WAIT_ADDRESS_FROM,
    WAIT_ADDRESS_TO,
    WAIT_ADDRESS_THIRD_DECISION,
    WAIT_ADDRESS_THIRD,
    WAIT_TARIFF,
    WAIT_ADDITIONAL,
    WAIT_CHILD_SEAT_TYPE,
    WAIT_COMMENT,
    WAIT_PRICE_CITY_FROM,
    WAIT_PRICE_ADDRESS_FROM,
    WAIT_PRICE_CITY_TO,
    WAIT_PRICE_ADDRESS_TO,
    WAIT_PRICE_TARIFF,
    WAIT_PRICE_DECISION,
    WAIT_ORDER_CONFIRM,
    WAIT_REPLACEMENT_FIELD,
    WAIT_ADMIN_MESSAGE,
    WAIT_ADMIN_SUM,
    WAIT_ADMIN_ORDERS,
    WAIT_ADMIN_BROADCAST,
    WAIT_PAYMENT_PROOF,
    WAIT_BOT_BALANCE,
) = range(24)

# ==========================
# Пользовательский сценарий заказа
# ==========================
async def order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_ordering_enabled():
        await update.message.reply_text(
            "🔔 Заказ такси временно недоступен. Бот на технических работах, попробуйте позже.",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
        return
    await update.message.reply_text("Выберите способ заказа:", reply_markup=order_type_keyboard())


async def price_check_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["price_check"] = {}
    await update.message.reply_text(
        "💸 <b>Проверка цены</b>\n\n🏙️ Введите город/посёлок для точки А:",
        reply_markup=taxi_force_reply_markup(),
        parse_mode="HTML",
    )
    return WAIT_PRICE_CITY_FROM


async def price_city_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault("price_check", {})["city_from"] = update.message.text.strip()
    await update.message.reply_text(
        "🏠 Введите адрес и дом для точки А (пример: Ленина, 26)",
        reply_markup=taxi_force_reply_markup(),
    )
    return WAIT_PRICE_ADDRESS_FROM


async def price_address_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault("price_check", {})["address_from"] = update.message.text.strip()
    await update.message.reply_text(
        "🏙️ Введите город/посёлок для точки Б:",
        reply_markup=taxi_force_reply_markup(),
    )
    return WAIT_PRICE_CITY_TO


async def price_city_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault("price_check", {})["city_to"] = update.message.text.strip()
    await update.message.reply_text(
        "🏠 Введите адрес и дом для точки Б (пример: Ленина, 26)",
        reply_markup=taxi_force_reply_markup(),
    )
    return WAIT_PRICE_ADDRESS_TO


async def price_address_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    data = context.user_data.setdefault("price_check", {})
    data["address_to"] = update.message.text.strip()
    await update.message.reply_text(
        "🚘 Выберите тариф:",
        reply_markup=price_tariff_keyboard(),
    )
    return WAIT_PRICE_TARIFF


async def price_tariff_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data.setdefault("price_check", {})
    tariff = query.data.split("_", 2)[2]
    data["tariff_code"] = tariff
    data["tariff_label"] = get_price_tariff_label(tariff)

    city_from = data.get("city_from")
    address_from = data.get("address_from")
    city_to = data.get("city_to")
    address_to = data.get("address_to")
    if not all([city_from, address_from, city_to, address_to]):
        await query.message.reply_text(
            "Не удалось прочитать адреса. Попробуйте снова.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

    full_from = f"{address_from}, {city_from}"
    full_to = f"{address_to}, {city_to}"
    data["full_from"] = full_from
    data["full_to"] = full_to

    await query.message.reply_text("⏳ Считаю стоимость, подождите немного...")
    try:
        price, price_class = fetch_yandex_price(full_from, full_to, price_class=tariff)
    except Exception as exc:
        logger.warning("Ошибка расчёта цены: %s", exc)
        await query.message.reply_text(
            "Не удалось получить цену. Попробуйте позже.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

    if not price:
        await query.message.reply_text(
            "😔 Не удалось найти цену по указанным адресам.\n"
            "Проверьте написание или добавьте город.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

    price_value = _parse_price_value(price)

    if price_value is None:
        await query.message.reply_text(
            "😔 Не удалось распознать цену. Попробуйте уточнить адреса.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

    our_price = round(price_value * 0.55, 2)
    data["app_price"] = price_value
    data["our_price"] = our_price
    data["price_class"] = price_class
    data["price_label"] = get_price_tariff_label(price_class) or data.get("tariff_label")

    await query.message.reply_text(
        (
            "✅ <b>Цена найдена</b>\n\n"
            f"🚩 <b>Откуда:</b> {full_from}\n"
            f"🎯 <b>Куда:</b> {full_to}\n"
            f"🚘 <b>Тариф:</b> {data.get('price_label') or price_class}\n\n"
            f"💰 <b>Цена в приложении:</b> <s>~{price_value:.2f} ₽</s>\n"
            f"💸 <b>Наша цена:</b> ~{our_price:.2f} ₽"
        ),
        reply_markup=price_decision_keyboard(),
        parse_mode="HTML",
    )
    return WAIT_PRICE_DECISION


async def price_order_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "price_back":
        await query.message.reply_text(
            "Возврат в главное меню.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END
    return ConversationHandler.END
async def order_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_ordering_enabled():
        await query.message.reply_text(
            "🔔 Заказ такси временно недоступен. Бот на технических работах, попробуйте позже.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END
    data = query.data
    context.user_data.clear()
    context.user_data['order_data'] = {}
    if data == "order_screenshot":
        await query.edit_message_text("🖼️ Пришлите скриншот маршрута 🎀")
        return WAIT_SCREENSHOT
    elif data == "order_text":
        context.user_data['order_type'] = "text"
        saved_user = get_user(query.from_user.id)
        if saved_user and saved_user.get("city"):
            context.user_data.setdefault('order_data', {})['city'] = saved_user.get("city")
            await ask_address_from(query, context)
            return WAIT_ADDRESS_FROM
        await query.edit_message_text("🌆 Укажи город для поездки (Такси от Майка)")
        await query.message.reply_text(
            "Напишите город отправления ✨",
            reply_markup=taxi_force_reply_markup(),
        )
        return WAIT_CITY
    elif data == "order_back":
        await query.message.reply_text(
            "Возврат в главное меню",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

# ---- Клавиатура "Пропустить" ----
def skip_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("Пропустить 🎿")]], resize_keyboard=True)


def order_confirmation_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Отправить", callback_data="order_confirm_send")],
        [InlineKeyboardButton("Отменить", callback_data="order_confirm_cancel")],
    ])


def get_price_tariff_label(tariff_code: str | None) -> str | None:
    if not tariff_code:
        return None
    for code, label in PRICE_TARIFFS:
        if code == tariff_code:
            return label
    return tariff_code


def price_tariff_keyboard():
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"price_tariff_{code}")]
        for code, label in PRICE_TARIFFS
    ]
    buttons.append([InlineKeyboardButton("🏠 В меню", callback_data="price_order_cancel")])
    return InlineKeyboardMarkup(buttons)


def price_decision_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏠 Возврат в меню", callback_data="price_back")],
        ]
    )


def _normalize_point(value) -> list[float] | None:
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return [float(value[0]), float(value[1])]
    if (
        isinstance(value, list)
        and value
        and isinstance(value[0], list)
        and len(value[0]) == 2
        and all(isinstance(v, (int, float)) for v in value[0])
    ):
        return [float(value[0][0]), float(value[0][1])]
    return None


def _find_point_in_json(payload, keys: tuple[str, ...]) -> list[float] | None:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                normalized = _normalize_point(payload.get(key))
                if normalized:
                    return normalized
        for value in payload.values():
            found = _find_point_in_json(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_point_in_json(item, keys)
            if found:
                return found
    return None


def _extract_suggest_point(payload) -> list[float] | None:
    if isinstance(payload, dict):
        suggests = payload.get("suggests") or payload.get("results") or payload.get("items")
        if isinstance(suggests, list):
            for item in suggests:
                if not isinstance(item, dict):
                    continue
                for key in ("point", "position", "center", "geo_point", "geopoint"):
                    normalized = _normalize_point(item.get(key))
                    if normalized:
                        return normalized
                for key in ("point", "position"):
                    inner = item.get(key)
                    if isinstance(inner, dict):
                        for inner_key in ("point", "position", "pos", "coords", "coordinates"):
                            normalized = _normalize_point(inner.get(inner_key))
                            if normalized:
                                return normalized
    return _find_point_in_json(payload, ("point", "position", "geopoint", "geo_point", "center"))


def _extract_price_from_json(payload, preferred_class: str | None = None) -> tuple[str | None, str | None]:
    candidates: list[tuple[str, str | None]] = []

    def _walk(value):
        if isinstance(value, dict):
            if "pin_description" in value:
                pin = value.get("pin_description")
                class_name = value.get("class")
                if isinstance(pin, str):
                    match = re.search(r"Отсюда[\\s\\u00A0\\u202F]*([0-9]+)", pin)
                    if match:
                        candidates.append((match.group(1), class_name))
            if "price" in value and "class" in value:
                class_name = value.get("class")
                price_value = value.get("price")
                if isinstance(price_value, dict):
                    for key in ("value", "amount", "price", "raw", "int"):
                        if key in price_value and isinstance(price_value[key], (int, float, str)):
                            candidates.append((str(price_value[key]), class_name))
                elif isinstance(price_value, (int, float, str)):
                    candidates.append((str(price_value), class_name))
            if "formatted_price" in value and "class" in value:
                class_name = value.get("class")
                formatted = value.get("formatted_price")
                if isinstance(formatted, str):
                    match = re.search(r"([0-9]+)", formatted)
                    if match:
                        candidates.append((match.group(1), class_name))
            if "formatted_prices" in value and isinstance(value.get("formatted_prices"), list):
                for item in value.get("formatted_prices"):
                    if not isinstance(item, dict):
                        continue
                    class_name = item.get("class")
                    formatted = item.get("formatted_price")
                    if isinstance(formatted, str):
                        candidates.append((formatted, class_name))
            for item in value.values():
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)

    if preferred_class:
        for price, class_name in candidates:
            if class_name == preferred_class:
                return price, class_name

    if candidates:
        return candidates[0][0], candidates[0][1]
    return None, None


def _parse_price_value(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        matches = re.findall(r"[0-9]+(?:[\\.,][0-9]+)?", value)
        if not matches:
            return None
        normalized = matches[0].replace(",", ".")
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def fetch_yandex_price(part_a: str, part_b: str, price_class: str | None = None) -> tuple[str | None, str | None]:
    token = YANDEX_TAXI_TOKEN
    price_class = price_class or YANDEX_PRICE_CLASS
    suggest_url = (
        "https://tc.mobile.yandex.net/4.0/persuggest/v1/suggest"
        "?mobcf=russia%25go_ru_by_geo_hosts_2%25default&mobpr=go_ru_by_geo_hosts_2_TAXI_V4_0"
    )
    suggest_headers = {
        "User-Agent": "ru.yandex.ytaxi/700.116.0.501961 (iPhone; iPhone13,2; iOS 18.6; Darwin)",
        "Pragma": "no-cache",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "X-YaTaxi-UserId": "08a2d06810664758a42dee25bb0220ec",
        "X-Ya-Go-Superapp-Session": "06F16257-7919-4052-BB9A-B96D22FE9B79",
        "X-YaTaxi-Last-Zone-Names": "novosibirsk,moscow,omsk",
        "X-Yandex-Jws": (
            "eyJhbGciOiJIUzI1NiIsImtpZCI6Im5hcndoYWwiLCJ0eXAiOiJKV1QifQ."
            "eyJkZXZpY2VfaW50ZWdyaXR5Ijp0cnVlLCJleHBpcmVzX2F0X21zIjoxNzY0NjUzNzcyNDY4LCJpcCI6"
            "IjJhMDI6NmI4OmMzNzo4YmE5OjdhMDA6NGMxYjozM2Q3OjAiLCJ0aW1lc3RhbXBfbXMiOjE3NjQ2NTAxNzI0Njgs"
            "InV1aWQiOiIxMmRjY2EzZGUwYmU0NDhjOGVmZDRmMmFiNjhiZjAwNyJ9.H8Izcf7uXk80ZFVKRElhDyabqcBVKTMsa45oeXQmgIs"
        ),
        "X-Perf-Class": "medium",
        "Connection": "keep-alive",
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru;q=1, ru-RU;q=0.9",
        "X-Yataxi-Ongoing-Orders-Statuses": "none",
        "Content-Type": "application/json",
        "X-VPN-Active": "1",
        "X-Mob-ID": "c76e6e2552f348b898891dd672fa5daa",
        "X-YaTaxi-Has-Ongoing-Orders": "false",
    }
    suggest_payload_a = {
        "type": "a",
        "part": part_a,
        "client_reqid": "1764650675979_ebb57515c4883b271c4dce99ace5f11b",
        "session_info": {},
        "action": "user_input",
        "state": {
            "bbox": [73.44446455010228, 54.9072988605965, 73.44655181916946, 54.904995264809976],
            "location_available": False,
            "coord_providers": [],
            "precise_location_available": False,
            "wifi_networks": [],
            "fields": [
                {
                    "position": [73.44550818463587, 54.90664973530346],
                    "metrica_method": "pin_drop",
                    "finalsuggest_method": "fs_not_sticky",
                    "log": (
                        "{\"uri\":\"ymapsbm1://geo?data=Cgg1NzExODE5NhJv0KDQvtGB0YHQuNGPLCDQntC80YHQuiwg0LzQuNC60YDQvtGA0LDQudC-0L0g0JzQvtGB0LrQvtCy0LrQsC0yLCDRg9C70LjRhtCwINCv0YDQvtGB0LvQsNCy0LAg0JPQsNGI0LXQutCwLCAxMy8xIgoN_OOSQhVDoFtC\","
                        "\"trace_id\":\"dcf2c5d465ce4b918a3641547ceed8cb\"}"
                    ),
                    "metrica_action": "manual",
                    "type": "a",
                }
            ],
            "selected_class": "econom",
            "l10n": {
                "countries": {"system": ["RU"]},
                "languages": {"system": ["ru-RU"], "app": ["ru"]},
                "mapkit_lang_region": "ru_RU",
            },
            "app_metrica": {"uuid": "12dcca3de0be448c8efd4f2ab68bf007", "device_id": "818182718hffy"},
            "main_screen_version": "flex_main",
            "screen": "main.addresses",
        },
        "suggest_serpid": "8aa2d1a77c60db11e2fa8cac6016ac2a",
    }
    suggest_payload_b = {
        "action": "user_input",
        "suggest_serpid": "1fffc1028b7f9f7bfc80b0ac30417df1",
        "client_reqid": "1764651135479_cd7cb200336a407eba8b5cd895cbe44c",
        "part": part_b,
        "session_info": {},
        "state": {
            "selected_class": "econom",
            "coord_providers": [],
            "fields": [
                {
                    "entrance": "4",
                    "metrica_method": "suggest",
                    "position": [37.63283473672819, 55.81002045183566],
                    "log": (
                        "{\"suggest_reqid\":\"1764650676398765-287523944-suggest-maps-yp-22\",\"user_params\":{\"request\":\"Бочкова 5\",\"ll\":\"73.445511,54.906147\",\"spn\":\"0.00208282,0.00230408\",\"ull\":\"73.445511,54.906147\",\"lang\":\"ru\"},\"client_reqid\":\"1764650675979_ebb57515c4883b271c4dce99ace5f11b\",\"server_reqid\":\"1764650676398765-287523944-suggest-maps-yp-22\",\"pos\":0,\"type\":\"toponym\",\"where\":{\"name\":\"Россия, Москва, улица Бочкова, 5\",\"source_id\":\"56760816\",\"mutable_source_id\":\"56760816\",\"title\":\"улица Бочкова, 5\"},\"uri\":\"ymapsbm1://geo?data=Cgg1Njc2MDgxNhI40KDQvtGB0YHQuNGPLCDQnNC-0YHQutCy0LAsINGD0LvQuNGG0LAg0JHQvtGH0LrQvtCy0LAsIDUiCg3whxZCFYY9X0I,\",\"method\":\"suggest.geosuggest\",\"trace_id\":\"cb7de160c386df3ca6958bfd5850e8eb\"}"
                    ),
                    "type": "a",
                    "finalsuggest_method": "np_entrances",
                }
            ],
            "l10n": {
                "countries": {"system": ["RU"]},
                "languages": {"app": ["ru"], "system": ["ru-RU"]},
                "mapkit_lang_region": "ru_RU",
            },
            "bbox": [37.63176701134504, 55.81066951258319, 37.63390246211134, 55.80836614425004],
            "screen": "main.addresses",
            "main_screen_version": "flex_main",
            "location_available": False,
            "app_metrica": {"device_id": "818182718hffy", "uuid": "12dcca3de0be448c8efd4f2ab68bf007"},
            "precise_location_available": False,
            "wifi_networks": [],
        },
        "type": "b",
    }

    response_a = requests.post(
        suggest_url,
        data=json.dumps(suggest_payload_a),
        headers=suggest_headers,
        timeout=20,
    )
    response_a.raise_for_status()
    point_a = _extract_suggest_point(response_a.json())
    if not point_a:
        return None, None

    response_b = requests.post(
        suggest_url,
        data=json.dumps(suggest_payload_b),
        headers=suggest_headers,
        timeout=20,
    )
    response_b.raise_for_status()
    point_b = _extract_suggest_point(response_b.json())
    if not point_b:
        return None, None

    route_stats_url = (
        "https://tc.mobile.yandex.net/3.0/routestats"
        "?mobcf=russia%25go_ru_by_geo_hosts_2%25default&mobpr=go_ru_by_geo_hosts_2_TAXI_0"
    )
    route_stats_headers = {
        "X-YaTaxi-UserId": "08a2d06810664758a42dee25bb0220ec",
        "User-Agent": "ru.yandex.ytaxi/700.116.0.501961 (iPhone; iPhone13,2; iOS 18.6; Darwin)",
        "X-YaTaxi-Has-Ongoing-Orders": "false",
        "X-Ya-Go-Superapp-Session": "06F16257-7919-4052-BB9A-B96D22FE9B79",
        "X-YaTaxi-Last-Zone-Names": "novosibirsk,omsk,moscow",
        "X-Yandex-Jws": (
            "eyJhbGciOiJIUzI1NiIsImtpZCI6Im5hcndoYWwiLCJ0eXAiOiJKV1QifQ."
            "eyJkZXZpY2VfaW50ZWdyaXR5Ijp0cnVlLCJleHBpcmVzX2F0X21zIjoxNzY0NjUzNzcyNDY4LCJpcCI6"
            "IjJhMDI6NmI4OmMzNzo4YmE5OjdhMDA6NGMxYjozM2Q3OjAiLCJ0aW1lc3RhbXBfbXMiOjE3NjQ2NTAxNzI0Njgs"
            "InV1aWQiOiIxMmRjY2EzZGUwYmU0NDhjOGVmZDRmMmFiNjhiZjAwNyJ9.H8Izcf7uXk80ZFVKRElhDyabqcBVKTMsa45oeXQmgIs"
        ),
        "X-Perf-Class": "medium",
        "Connection": "keep-alive",
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru;q=1, ru-RU;q=0.9",
        "Accept": "*/*",
        "X-Yataxi-Ongoing-Orders-Statuses": "none",
        "Content-Type": "application/json",
        "X-VPN-Active": "1",
        "Accept-Encoding": "gzip, deflate, br",
        "X-Mob-ID": "c76e6e2552f348b898891dd672fa5daa",
    }
    route_zone = "moscow"
    combined = f"{part_a} {part_b}".lower()
    if "омск" in combined:
        route_zone = "omsk"
    elif "москва" in combined or "moscow" in combined:
        route_zone = "moscow"

    route_payload = {
        "supports_verticals_selector": True,
        "id": "08a2d06810664758a42dee25bb0220ec",
        "supported_markup": "tml-0.1",
        "selected_class": "econom",
        "supported_verticals": [
            "drive",
            "transport",
            "hub",
            "intercity",
            "maas",
            "taxi",
            "ultima",
            "child",
            "delivery",
            "rest_tariffs",
        ],
        "supports_no_cars_available": True,
        "supports_unavailable_alternatives": True,
        "suggest_alternatives": True,
        "skip_estimated_waiting": False,
        "supports_paid_options": True,
        "supports_explicit_antisurge": True,
        "parks": [],
        "is_lightweight": False,
        "tariff_requirements": [
            {"class": "econom", "requirements": {}},
            {"class": "lite_b2b", "requirements": {}},
            {"class": "business", "requirements": {}},
            {"class": "standart_b2b", "requirements": {}},
            {"class": "comfortplus", "requirements": {}},
            {"class": "optimum_b2b", "requirements": {}},
            {"class": "vip", "requirements": {}},
            {"class": "ultimate", "requirements": {}},
            {"class": "maybach", "requirements": {}},
            {"class": "child_tariff", "requirements": {}},
            {"class": "minivan", "requirements": {}},
            {"class": "premium_van", "requirements": {}},
            {"class": "personal_driver", "requirements": {}},
            {"class": "express", "requirements": {}},
            {"class": "courier", "requirements": {}},
            {"class": "cargo", "requirements": {}},
            {"class": "selfdriving", "requirements": {}},
        ],
        "enable_fallback_for_tariffs": True,
        "supported": [
            {"type": "formatted_prices"},
            {"type": "multiclass_requirements"},
            {"type": "multiclasses"},
            {
                "type": "verticals_multiclass",
                "payload": {
                    "classes": [
                        "courier",
                        "cargo",
                        "ndd",
                        "express_d2d",
                        "express_outdoor",
                        "express_d2d_slow",
                        "sdd_short",
                        "sdd_evening",
                        "sdd_long",
                        "express_fast",
                    ]
                },
            },
            {"type": "plus_promo_alternative"},
            {
                "type": "order_flow_delivery",
                "payload": {
                    "classes": [
                        "courier",
                        "cargo",
                        "ndd",
                        "express_d2d",
                        "express_outdoor",
                        "express_d2d_slow",
                        "sdd_short",
                        "sdd_evening",
                        "sdd_long",
                        "express_fast",
                    ]
                },
            },
            {"type": "requirements_v2"},
        ],
        "with_title": True,
        "supports_multiclass": True,
        "supported_vertical_types": ["group"],
        "supported_features": [
            {"type": "order_button_actions", "values": ["open_tariff_card", "deeplink"]},
            {"type": "swap_summary", "values": ["high_tariff_selector"]},
        ],
        "delivery_extra": {
            "door_to_door": False,
            "is_delivery_business_account_enabled": False,
            "insurance": {"selected": False},
            "pay_on_delivery": False,
        },
        "route": [point_a, point_b],
        "payment": {"type": "cash"},
        "zone_name": route_zone,
        "account_type": "lite",
        "summary_version": 2,
        "format_currency": True,
        "supports_hideable_tariffs": True,
        "force_soon_order": False,
        "use_toll_roads": False,
        "estimate_waiting_selected_only": False,
        "selected_class_only": False,
        "position_accuracy": 0,
        "size_hint": 300,
        "extended_description": True,
        "requirements": {},
        "multiclass_options": {"selected": False, "class": [], "verticals": []},
    }

    route_response = requests.post(
        route_stats_url,
        data=json.dumps(route_payload),
        headers=route_stats_headers,
        timeout=25,
    )
    route_response.raise_for_status()
    price, class_name = _extract_price_from_json(route_response.json(), price_class)
    return price, class_name or price_class


def map_order_tariff_to_price_class(tariff_label: str | None) -> str | None:
    if not tariff_label:
        return None
    return ORDER_TARIFF_PRICE_CLASS.get(tariff_label.strip())


async def ensure_text_order_price(order_data: dict) -> None:
    city = order_data.get("city")
    addr_from = order_data.get("address_from")
    addr_to = order_data.get("address_to")
    if not (city and addr_from and addr_to):
        return

    price_key = (city, addr_from, addr_to, order_data.get("tariff"))
    if order_data.get("price_key") == price_key and order_data.get("app_price") is not None:
        return

    price_class = map_order_tariff_to_price_class(order_data.get("tariff")) or YANDEX_PRICE_CLASS
    full_from = f"{city}, {addr_from}"
    full_to = f"{city}, {addr_to}"

    try:
        price, class_name = await asyncio.to_thread(
            fetch_yandex_price,
            full_from,
            full_to,
            price_class=price_class,
        )
    except Exception as exc:
        logger.error("Не удалось получить цену для заказа: %s", exc)
        return

    price_value = _parse_price_value(price)
    if price_value is None:
        return

    our_price = round(price_value * 0.55, 2)
    order_data["price_key"] = price_key
    order_data["app_price"] = price_value
    order_data["our_price"] = our_price
    order_data["price_class"] = class_name or price_class
    order_data["price_label"] = get_price_tariff_label(class_name or price_class)


def build_order_preview_text(order_data, order_type):
    parts = ["🎄✨ Проверьте данные заказа:"]
    parts.append(f"📸 Формат: {'🖼️ Скриншот' if order_type == 'screenshot' else '📝 Текст'}")

    if order_data.get('city'):
        parts.append(f"🏙️ Город: {order_data['city']}")
    if order_data.get('address_from'):
        parts.append(f"🎁 Откуда: {order_data['address_from']}")
    if order_data.get('address_to'):
        parts.append(f"🎁 Куда: {order_data['address_to']}")
    if order_data.get('address_extra'):
        parts.append(f"🧭 Доп. адрес: {order_data['address_extra']}")
    if order_data.get('tariff'):
        parts.append(f"⛄️ Тариф: {order_data['tariff']}")
    if order_data.get('child_seat'):
        parts.append(f"🛷 Детское кресло: {order_data['child_seat']}")
    if order_data.get('child_seat_type'):
        parts.append(f"❄️ Тип кресла: {order_data['child_seat_type']}")
    if order_data.get('wishes'):
        wishes = order_data.get('wishes')
        wishes_text = ", ".join(wishes) if isinstance(wishes, (list, tuple, set)) else wishes
        parts.append(f"🎇 Пожелания: {wishes_text}")

    comment = order_data.get('comment')
    parts.append(f"📝 Комментарий: {comment if comment else 'не указан'}")

    if order_data.get("app_price") is not None and order_data.get("our_price") is not None:
        price_label = order_data.get("price_label") or order_data.get("tariff")
        if price_label:
            parts.append(f"🚘 Тариф для цены: {price_label}")
        parts.append(f"💰 Цена в приложении: ~{order_data['app_price']:.2f} ₽")
        parts.append(f"🎁 Наша цена: {order_data['our_price']:.2f} ₽")

    if order_type == "screenshot":
        parts.append("🖼️ Скриншот: прикреплён")

    parts.append("\n✨ Если всё верно — отправляйте заказ!")

    return "\n".join(parts)


async def send_order_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_data = context.user_data.get('order_data', {})
    order_type = context.user_data.get('order_type', 'text')
    text = build_order_preview_text(order_data, order_type)

    if update.message:
        await update.message.reply_text("Комментарий сохранён.", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text(text, reply_markup=order_confirmation_keyboard())
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=order_confirmation_keyboard())

# ---- Скриншотный заказ (приём фото) ----
async def screenshot_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    tg_id = update.effective_user.id

    order_id = create_order(tg_id, type_="screenshot", bot_token=context.bot.token)
    path = SCREENSHOTS_DIR / f"{order_id}.jpg"
    await file.download_to_drive(path)

    update_order_fields(order_id, screenshot_path=str(path))
    context.user_data['order_id'] = order_id
    context.user_data['order_type'] = "screenshot"
    context.user_data['order_data'] = {}

    await update.message.reply_text("Выберите тариф 🛷", reply_markup=tariff_keyboard())
    return WAIT_TARIFF

# ---- Текстовый заказ: последовательность шагов ----
async def ask_address_from(update_or_query, context):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id
    favorites = get_favorite_addresses(user_id)
    target = update_or_query.message
    if favorites:
        await target.reply_text("Адрес откуда ❄️", reply_markup=favorites_select_keyboard(favorites, "from"))
    else:
        await target.reply_text(
            "🧭 Введите адрес отправления (Такси от Майка)",
            reply_markup=taxi_force_reply_markup(),
        )


async def ask_address_to(update_or_query, context):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id
    favorites = get_favorite_addresses(user_id)
    target = update_or_query.message
    if favorites:
        await target.reply_text("Адрес куда ❄️", reply_markup=favorites_select_keyboard(favorites, "to"))
    else:
        await target.reply_text(
            "📍 Введите адрес назначения (Такси от Майка)",
            reply_markup=taxi_force_reply_markup(),
        )


async def ask_address_third(update_or_query, context):
    user_id = update_or_query.effective_user.id if isinstance(update_or_query, Update) else update_or_query.from_user.id
    favorites = get_favorite_addresses(user_id)
    target = update_or_query.message
    if favorites:
        await target.reply_text("Введите третий адрес 🧭❄️", reply_markup=favorites_select_keyboard(favorites, "third"))
    else:
        await target.reply_text(
            "Введите дополнительный адрес 🧭 (Такси от Майка)",
            reply_markup=taxi_force_reply_markup(),
        )


async def text_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    city = update.message.text
    context.user_data.setdefault('order_data', {})['city'] = city
    update_user_city(update.effective_user.id, city)
    await ask_address_from(update, context)
    return WAIT_ADDRESS_FROM

async def text_address_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault('order_data', {})['address_from'] = update.message.text
    await ask_address_to(update, context)
    return WAIT_ADDRESS_TO

async def text_address_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault('order_data', {})['address_to'] = update.message.text
    await update.message.reply_text("Хотите добавить ещё один адрес?", reply_markup=yes_no_keyboard())
    return WAIT_ADDRESS_THIRD_DECISION


async def text_address_third(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    context.user_data.setdefault('order_data', {})['address_extra'] = update.message.text
    await ask_tariff(update, context)
    return WAIT_TARIFF


async def address_third_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "address_yes":
        await ask_address_third(query, context)
        return WAIT_ADDRESS_THIRD
    await ask_tariff(query, context)
    return WAIT_TARIFF


async def ask_tariff(update_or_query, context):
    if isinstance(update_or_query, Update):
        target = update_or_query.message
    else:
        target = update_or_query.message
    await target.reply_text("Выберите тариф 🛷", reply_markup=tariff_keyboard())


async def favorite_address_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, stage, payload = query.data.split("_", 2)
    user_id = query.from_user.id
    favorites = {fav['id']: fav for fav in get_favorite_addresses(user_id)}

    if payload == "manual":
        prompt = {
            "from": "Введите адрес откуда ❄️ (Такси от Майка)",
            "to": "Введите адрес куда ❄️ (Такси от Майка)",
            "third": "Введите третий адрес 🧭❄️ (Такси от Майка)",
        }.get(stage, "Введите адрес")
        await query.message.reply_text(prompt, reply_markup=taxi_force_reply_markup())
        return {
            "from": WAIT_ADDRESS_FROM,
            "to": WAIT_ADDRESS_TO,
            "third": WAIT_ADDRESS_THIRD,
        }.get(stage, ConversationHandler.END)

    fav_id = int(payload)
    fav = favorites.get(fav_id)
    if not fav:
        await query.answer("Адрес не найден", show_alert=True)
        return ConversationHandler.END

    data = context.user_data.setdefault('order_data', {})
    if stage == "from":
        data['address_from'] = fav['address']
        await query.message.reply_text(f"Адрес откуда выбран: {fav['address']}")
        await ask_address_to(query, context)
        return WAIT_ADDRESS_TO
    if stage == "to":
        data['address_to'] = fav['address']
        await query.message.reply_text(f"Адрес куда выбран: {fav['address']}")
        await query.message.reply_text("Хотите добавить ещё один адрес?", reply_markup=yes_no_keyboard())
        return WAIT_ADDRESS_THIRD_DECISION
    if stage == "third":
        data['address_extra'] = fav['address']
        await ask_tariff(query, context)
        return WAIT_TARIFF
    return ConversationHandler.END

async def text_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_result = await handle_menu_button(update, context)
    if menu_result is not None:
        return menu_result
    raw_comment = (update.message.text or "").strip()
    comment = None if raw_comment.lower() == "пропустить 🎿" or raw_comment == "" else raw_comment

    order_type = context.user_data.get('order_type')
    data = context.user_data.get('order_data', {})
    data['comment'] = comment

    if order_type == "text":
        city = data.get('city')
        addr_from = data.get('address_from')
        addr_to = data.get('address_to')

        if not (city and addr_from and addr_to):
            await update.message.reply_text(
                "Ошибка: не все поля введены. Попробуйте снова.",
                reply_markup=main_menu_keyboard(update.effective_user.id),
            )
            context.user_data.clear()
            return ConversationHandler.END

        await ensure_text_order_price(data)

    await send_order_preview(update, context)
    return WAIT_ORDER_CONFIRM


async def order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    order_type = context.user_data.get('order_type')
    data = context.user_data.get('order_data', {})

    if action == "order_confirm_cancel":
        order_id = context.user_data.get('order_id')
        if order_type == "screenshot" and order_id:
            order = get_order(order_id)
            screenshot_path = order.get("screenshot_path") if order else None
            if screenshot_path and os.path.exists(screenshot_path):
                os.remove(screenshot_path)
            delete_order(order_id)

        context.user_data.clear()
        await query.message.reply_text(
            "Заказ отменён. Возвращаю в главное меню.",
            reply_markup=main_menu_keyboard(query.from_user.id),
        )
        return ConversationHandler.END

    if action != "order_confirm_send":
        return WAIT_ORDER_CONFIRM

    comment = data.get('comment')
    wishes = data.get('wishes')
    wishes_text = ", ".join(wishes) if isinstance(wishes, (list, tuple, set)) else wishes

    if order_type == "text":
        order_id = create_order(
            tg_id=query.from_user.id,
            type_="text",
            bot_token=context.bot.token,
            city=data.get('city'),
            address_from=data.get('address_from'),
            address_to=data.get('address_to'),
            address_extra=data.get('address_extra'),
            tariff=data.get('tariff'),
            child_seat=data.get('child_seat'),
            child_seat_type=data.get('child_seat_type'),
            wishes=wishes_text,
            comment=comment,
        )
        if data.get("app_price") is not None and data.get("our_price") is not None:
            update_order_fields(
                order_id,
                base_amount=data.get("app_price"),
                amount=data.get("our_price"),
            )
    else:
        order_id = context.user_data.get('order_id')
        if not order_id:
            await query.message.reply_text("Произошла ошибка: заказ не найден.")
            context.user_data.clear()
            return ConversationHandler.END
        update_order_fields(
            order_id,
            tariff=data.get('tariff'),
            child_seat=data.get('child_seat'),
            child_seat_type=data.get('child_seat_type'),
            wishes=wishes_text,
            comment=comment,
        )

    increment_orders_count(query.from_user.id)
    await query.message.reply_text(
        f"🎉 Ваш заказ №{order_id} создан",
        reply_markup=main_menu_keyboard(query.from_user.id),
    )
    await notify_admins(context, order_id)

    context.user_data.clear()
    return ConversationHandler.END


async def tariff_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tariff = query.data.split("_", 1)[1]
    context.user_data.setdefault('order_data', {})['tariff'] = tariff
    await query.message.reply_text(
        "Выберите доп. опции по необходимости",
        reply_markup=additional_options_keyboard(context.user_data.get('order_data', {})),
    )
    return WAIT_ADDITIONAL


async def child_seat_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "seat_type_exit":
        await query.edit_message_text(
            "Выберите доп. опции по необходимости",
            reply_markup=additional_options_keyboard(context.user_data.get('order_data', {})),
        )
        return WAIT_ADDITIONAL

    seat_type = data.split("_", 2)[2]
    order_data = context.user_data.setdefault('order_data', {})
    order_data['child_seat'] = "Нужно"
    order_data['child_seat_type'] = seat_type
    await query.edit_message_text(
        "Выберите доп. опции по необходимости",
        reply_markup=additional_options_keyboard(order_data),
    )
    return WAIT_ADDITIONAL

async def additional_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    order_data = context.user_data.setdefault('order_data', {})
    current_wishes = set(order_data.get('wishes', []))

    if data == "additional_child":
        await query.edit_message_text(
            "Выберите тип детского кресла",
            reply_markup=child_seat_type_keyboard(),
        )
        return WAIT_CHILD_SEAT_TYPE

    if data in {"additional_animals", "additional_wheelchair"}:
        label = "Перевозка животных" if data == "additional_animals" else "Буду с инвалидным креслом"
        if label in current_wishes:
            current_wishes.remove(label)
        else:
            current_wishes.add(label)
        order_data['wishes'] = list(current_wishes)
        await query.edit_message_reply_markup(reply_markup=additional_options_keyboard(order_data))
        return WAIT_ADDITIONAL

    if data in {"additional_done", "additional_skip"}:
        await query.message.reply_text(
            "Добавьте комментарий для админа или нажмите «Пропустить 🎿»",
            reply_markup=skip_keyboard(),
        )
        return WAIT_COMMENT

    return WAIT_ADDITIONAL


# ==========================
# Админ уведомление
# ==========================
async def notify_admins(context, order_id):
    order = get_order(order_id)

    if not order:
        return

    tg_id = order.get("tg_id")
    type_ = order.get("type")
    user_info = get_user(tg_id)
    username = user_info.get("username") if user_info else None
    username_label = f"@{username}" if username else "не указан"

    bot_token = order.get("bot_token") or PRIMARY_BOT_TOKEN
    bot_record = get_bot_by_token(bot_token)
    owner_id = bot_record.get("owner_id") if bot_record else None
    owner_user = get_user(owner_id) if owner_id else None
    owner_username = owner_user.get("username") if owner_user else None
    bot_title = bot_record.get("title") if bot_record else None
    bot_label = bot_title or (bot_record.get("token") if bot_record else "Основной бот")
    owner_label = "Основной бот" if bot_token == PRIMARY_BOT_TOKEN or owner_id in {None, 0} else f"@{owner_username or 'не указан'} (ID: {owner_id})"

    parts = [
        f"НОВЫЙ ЗАКАЗ №{order_id}",
        f"Тип: {type_}",
        f"Пользователь: {username_label} (ID: {tg_id})",
        f"Бот: {bot_label}",
        f"Владелец бота: {owner_label}",
    ]
    if order.get("city"):
        parts.append(f"Город: {order.get('city')}")
    if order.get("address_from"):
        parts.append(f"Откуда: {order.get('address_from')}")
    if order.get("address_to"):
        parts.append(f"Куда: {order.get('address_to')}")
    if order.get("address_extra"):
        parts.append(f"Доп. адрес: {order.get('address_extra')}")
    if order.get("tariff"):
        parts.append(f"Тариф: {order.get('tariff')}")
    if order.get("child_seat"):
        parts.append(f"Детское кресло: {order.get('child_seat')}")
    if order.get("child_seat_type"):
        parts.append(f"Тип кресла: {order.get('child_seat_type')}")
    if order.get("wishes"):
        parts.append(f"Пожелания: {order.get('wishes')}")
    if order.get("comment"):
        parts.append(f"Комментарий: {order.get('comment')}")
    if order.get("base_amount") or order.get("amount"):
        base_amount = order.get("base_amount") or 0
        amount = order.get("amount") or 0
        parts.append(f"Цена в приложении: {base_amount:.2f} ₽")
        parts.append(f"Наша цена: {amount:.2f} ₽")

    text = "\n".join(parts)

    for admin_id in ADMIN_IDS:
        try:
            screenshot_path = order.get("screenshot_path")
            keyboard = admin_order_buttons(order_id)
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    with open(screenshot_path, "rb") as photo:
                        await primary_bot.send_photo(
                            admin_id,
                            photo=photo,
                            caption=text,
                            reply_markup=keyboard,
                        )
                except Exception as photo_error:
                    logger.error(
                        "Не удалось отправить фото заказа %s админу %s: %s",
                        order_id,
                        admin_id,
                        photo_error,
                    )
                    await primary_bot.send_message(
                        admin_id,
                        text,
                        reply_markup=keyboard,
                    )
            else:
                await primary_bot.send_message(
                    admin_id,
                    text,
                    reply_markup=keyboard,
                )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа {admin_id}: {e}")


async def notify_admins_reward(order: dict):
    if not order:
        return

    order_id = order.get("id")
    amount = order.get("base_amount") or order.get("amount") or 0
    bot_token = order.get("bot_token") or PRIMARY_BOT_TOKEN
    bot_record = get_bot_by_token(bot_token)
    owner_id = bot_record.get("owner_id") if bot_record else None

    if bot_token == PRIMARY_BOT_TOKEN or owner_id in {None, 0}:
        text = (
            f"Заказ №{order_id}: сумма {amount:.2f} ₽. 15% не начисляются, так как заказ оформлен через основной бот."
        )
    else:
        reward = round((amount or 0) * 0.15, 2)
        owner_user = get_user(owner_id) or {}
        username = owner_user.get("username")
        user_ref = f"@{username}" if username else f"ID {owner_id}"
        link = f"https://t.me/{username}" if username else None
        link_text = f"Ссылка: {link}" if link else "Ссылка недоступна"
        text = (
            f"Заказ №{order_id}: сумма {amount:.2f} ₽, начисление 15% — {reward:.2f} ₽.\n"
            f"Получатель: {user_ref}. {link_text}"
        )

    for admin_id in ADMIN_IDS:
        try:
            await primary_bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Не удалось уведомить админа {admin_id} о комиссионном вознаграждении: {e}")


def replacement_info_text(info):
    user = get_user(info.get("tg_id")) if info.get("tg_id") else None
    username = user.get("username") if user else None
    parts = [
        f"✨ Заказ для подмены #{info['id']}",
        f"Создан: {info.get('created_at') or '—'}",
        f"Заказчик: @{username or 'не указан'} (ID: {info.get('tg_id') or '—'})",
        f"OrderID: {info.get('order_number') or '—'}",
        f"card-x: {info.get('card_x') or '—'}",
        f"ID: {info.get('external_id') or '—'}",
        f"token2: {info.get('token2') or '—'}",
        f"Ссылка: {info.get('link') or '—'}",
        f"Связан с заказом №{info.get('order_id') or '—'}",
    ]
    return "\n".join(parts)


async def notify_replacement_done(info, context):
    tg_id = info.get("tg_id")
    if not tg_id:
        return
    related_order = get_order(info.get("order_id")) if info.get("order_id") else None
    order_bot = get_order_bot(related_order)
    text = (
        "✨ Поездка успешно завершена!\n\n"
        "Спасибо, что выбрали нас.\n"
        "🎺 Канал: @TaxiFromMike\n"
        "🧑‍🎄‍🎄 Админ: @TakeMaxist\n\n"
        "Нажмите /start, чтобы вернуться в главное меню.\n"
        "Поделитесь, пожалуйста, отзывом в чате — нам важно ваше мнение! 🔔"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Оставить отзыв", url="https://t.me/+z_S1iZMVW-ZmMzBi")]
    ])
    try:
        await order_bot.send_message(tg_id, text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {tg_id} о завершении: {e}")


async def notify_admins_payment(context: ContextTypes.DEFAULT_TYPE, payment_id: int):
    payment = get_payment(payment_id)
    if not payment:
        return
    user = get_user(payment.get("tg_id")) or {}
    method = payment.get("method")
    method_titles = {
        "transfer": "🎁 Карта",
        "sbp": "🎁 СБП",
        "ltc": "🪙🎄 Litecoin",
        "usdt_trc20": "🎁 USDT (TRC20)",
        "usdt_trx": "🎁 USDT (TRX)",
    }
    original_amount = payment.get("original_amount")
    original_currency = payment.get("original_currency") or "RUB"
    display_currency = payment.get("currency") or "RUB"
    amount_value = payment.get("amount")
    amount_text = (
        (f"{amount_value:.4f}" if display_currency != "RUB" else f"{amount_value:.2f}")
        if amount_value is not None
        else "не указана"
    )
    parts = [
        "🎁 Новая оплата",
        f"Пользователь: @{user.get('username') or 'не указан'} (ID: {payment.get('tg_id')})",
        "Тип: Оплата заказа",
        f"Метод: {method_titles.get(method, method)}",
        f"Сумма: {amount_text} {display_currency if amount_value is not None else ''}",
        f"Реквизиты: {payment.get('requisites')}",
    ]
    if original_amount and display_currency != original_currency:
        parts.append(f"🎁 Эквивалент: {original_amount:.2f} {original_currency}")
    if payment.get("comment_code"):
        parts.append(f"Комментарий: {payment.get('comment_code')}")
    if payment.get("order_id"):
        parts.append(f"Заказ: #{payment.get('order_id')}")

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Зачислить 🎉", callback_data=f"payapprove_{payment_id}")],
            [InlineKeyboardButton("Нет 🎄🚫", callback_data=f"paydecline_{payment_id}")],
        ]
    )
    for admin_id in ADMIN_IDS:
        try:
            await primary_bot.send_message(admin_id, "\n".join(parts), reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Не удалось уведомить админа {admin_id}: {e}")


async def animate_status_message(
    message, frames: list[str], delay: int = 4, cycles: int = 3
):
    """Плавно обновляет текст сообщения для создания вау-эффекта."""
    total_steps = max(1, cycles) * len(frames)
    for step in range(total_steps):
        await asyncio.sleep(delay)
        text = frames[step % len(frames)]
        await safe_edit_message(message, text=text)


# ==========================
# CallbackQuery обработка (админ)
# ==========================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("🎄🚫 Нет доступа", show_alert=True)
        return ConversationHandler.END
    # Взял в работу
    if data.startswith("take_"):
        order_id = int(data.split("_")[1])
        order = get_order(order_id)
        order_bot = get_order_bot(order)

        if order.get("status") != "pending":
            await query.answer("🎄🚫 Этот заказ уже в работе или отменён", show_alert=True)
            return

        update_order_status(order_id, "in_progress")
        await query.edit_message_reply_markup(reply_markup=admin_in_progress_buttons(order_id))

        user_id = order.get("tg_id")
        status_frames = [
            "🚕 Уже взяли в работу ваш заказ",
            "🛠️ Трудимся над вашим заказом",
            "🚦 Скоро начнём поиск такси",
        ]
        status_message = await order_bot.send_message(user_id, status_frames[0])
        context.application.create_task(
            animate_status_message(status_message, status_frames)
        )

        # удаляем сообщение у других админов
        for admin_id in ADMIN_IDS:
            if admin_id != query.from_user.id:
                await safe_delete_message(context.bot, chat_id=admin_id, message_id=query.message.message_id)

    # Отклонить
    elif data.startswith("reject_"):
        order_id = int(data.split("_")[1])
        update_order_status(order_id, "cancelled")
        await edit_admin_message(query, "Заказ отклонён 🎄🚫")
        order = get_order(order_id)
        order_bot = get_order_bot(order)
        user_id = order.get("tg_id")
        await order_bot.send_message(user_id, f"Ваш заказ №{order_id} отклонён ❄️")
    # Поиск
    elif data.startswith("search_"):
        order_id = int(data.split("_")[1])
        update_order_status(order_id, "search")
        await query.edit_message_reply_markup(reply_markup=admin_search_buttons(order_id))
        order = get_order(order_id)
        order_bot = get_order_bot(order)
        user_id = order.get("tg_id")
        search_frames = [
            "🔍 Поиск машины",
            "🚗 Ищем вам машину",
            "🚕 Поиск такси",
        ]
        search_message = await order_bot.send_message(user_id, search_frames[0])
        context.application.create_task(
            animate_status_message(search_message, search_frames)
        )
    # Отмена поиска / заказ
    elif data.startswith("cancel_") or data.startswith("cancelsearch_"):
        order_id = int(data.split("_")[1])
        order = get_order(order_id)
        if not order:
            await query.answer("Заказ не найден", show_alert=True)
            return ConversationHandler.END

        order_bot = get_order_bot(order)

        update_order_status(order_id, "cancelled")
        await edit_admin_message(query, "Заказ отменён 🎄🚫")
        user_id = order.get("tg_id")
        await order_bot.send_message(user_id, f"Ваш заказ №{order_id} отменён ❄️")

        for admin_id in ADMIN_IDS:
            if admin_id != query.from_user.id:
                await safe_delete_message(
                    context.bot, chat_id=admin_id, message_id=query.message.message_id
                )
    # Нашлась машина
    elif data.startswith("found_"):
        order_id = int(data.split("_")[1])
        context.user_data['order_id'] = order_id
        order = get_order(order_id)
        if not order:
            await query.answer("Заказ не найден", show_alert=True)
            return ConversationHandler.END
        order_bot = get_order_bot(order)
        tg_id = order.get("tg_id")
        found_frames = [
            "✅ Машина успешно найдена",
            "📨 Сейчас отправим вам ссылку на машину",
            "🛣️ Машина едет к вам",
        ]
        found_message = await order_bot.send_message(tg_id, found_frames[0])
        context.application.create_task(
            animate_status_message(found_message, found_frames)
        )
        await query.message.reply_text("Введите сообщение пользователю:")
        return WAIT_ADMIN_MESSAGE

    elif data.startswith("chat_"):
        order_id = int(data.split("_")[1])
        context.user_data['order_id'] = order_id
        await query.message.reply_text("Введите сообщение пользователю:")
        return WAIT_ADMIN_MESSAGE
    elif data.startswith("pay_card_"):
        order_id = int(data.split("_")[2])
        order = get_order(order_id)
        if not order:
            await query.answer("Заказ не найден", show_alert=True)
            return ConversationHandler.END
        order_bot = get_order_bot(order)
        await send_payment_menu(order, order_bot)
        await query.message.reply_text("Меню оплаты отправлено клиенту")
    elif data.startswith("replacement_offer_add_"):
        order_id = int(data.rsplit("_", 1)[1])
        info_id = create_order_info(order_id)
        info = get_order_info(info_id)
        upsert_podmena_entry(info)
        await query.message.reply_text(
            "Заполните данные заказа для подмены:",
            reply_markup=replacement_fields_keyboard(info),
        )
    elif data.startswith("replacement_offer_skip_"):
        await query.message.reply_text("Добавление заказа для подмены пропущено.")
    elif data == "admin_replacements":
        infos = list_active_order_infos()
        if not infos:
            await query.message.reply_text(
                "Список заказов для подмены пуст", reply_markup=admin_panel_keyboard()
            )
            return ConversationHandler.END
        await query.message.reply_text(
            "Активные заказы для подмены:", reply_markup=replacement_list_keyboard(infos)
        )
    elif data.startswith("replacement_view_"):
        info_id = int(data.rsplit("_", 1)[1])
        info = get_order_info(info_id)
        if not info:
            await query.answer("Запись не найдена", show_alert=True)
            return ConversationHandler.END
        await query.message.reply_text(
            replacement_info_text(info),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎄 Назад", callback_data="replacement_back")],
                [InlineKeyboardButton("Завершить заказ 🎉", callback_data=f"replacement_finish_{info_id}")],
            ]),
        )
    elif data.startswith("replacement_field_"):
        parts = data.split("_")
        field_key = parts[2]
        info_id = int(parts[3])
        context.user_data['replacement_field'] = field_key
        context.user_data['replacement_info_id'] = info_id
        prompts = {
            "orderid": "Пришлите OrderID",
            "cardx": "Пришлите card-x",
            "extid": "Пришлите ID",
            "token2": "Добавьте token2 для этой подмены",
            "link": "Пришлите ссылку",
        }
        await query.message.reply_text(prompts.get(field_key, "Пришлите значение"))
        return WAIT_REPLACEMENT_FIELD
    elif data == "replacement_back":
        await admin_show_panel(query.message)
        return ConversationHandler.END
    elif data.startswith("replacement_finish_"):
        info_id = int(data.rsplit("_", 1)[1])
        info = get_order_info(info_id)
        if not info:
            await query.answer("Запись не найдена", show_alert=True)
            return ConversationHandler.END
        deactivate_order_info(info_id)
        await notify_replacement_done(info, context)
        await query.message.reply_text(
            "Заказ для подмены завершён и убран из списка.", reply_markup=admin_panel_keyboard()
        )
    elif data == "admin_orders":
        await query.message.reply_text("Введите Telegram ID пользователя для просмотра его заказов:")
        return WAIT_ADMIN_ORDERS
    elif data == "admin_refresh":
        await refresh_all_users(query.message, context)
        return ConversationHandler.END
    elif data == "admin_all_bots":
        await query.message.reply_text(
            "📡 Подключённые боты по владельцам:", reply_markup=admins_bots_keyboard()
        )
        return ConversationHandler.END
    elif data == "admin_franchise_db":
        bots = list_all_bots()
        connected_bots = [b for b in bots if b.get("token") and b.get("token") != PRIMARY_BOT_TOKEN]
        if not connected_bots:
            await query.message.reply_text("Подключённых ботов нет.", reply_markup=admin_panel_keyboard())
            return ConversationHandler.END
        ensure_all_franchise_tables()
        total_users = 0
        lines = ["🗂️ Статус БД франшизы:"]
        for bot in connected_bots:
            bot_id = bot.get("id")
            title = bot.get("title") or "Без названия"
            if not bot_id:
                lines.append(f"🤖 {title}: не удалось определить ID")
                continue
            try:
                count = count_franchise_users(bot_id)
            except Exception as e:
                logger.error("Не удалось подсчитать пользователей для бота %s: %s", bot_id, e)
                lines.append(f"🤖 {title}: ошибка подсчёта пользователей")
                continue
            total_users += count
            lines.append(f"🤖 {title}: {count} пользователей в отдельной таблице {franchise_table_name(bot_id)}")
        lines.append(f"🧾 Итого пользователей во франшизе: {total_users}")
        await query.message.reply_text("\n".join(lines), reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    elif data == "admin_users_count":
        bots = list_all_bots()
        lines = []
        seen_tokens = set()
        total_users = 0
        primary_count = count_bot_users(PRIMARY_BOT_TOKEN)
        lines.append(f"👑 Основной бот: {primary_count} пользователей")
        total_users += primary_count
        for bot in bots:
            token = bot.get("token")
            if not token or token in seen_tokens or token == PRIMARY_BOT_TOKEN:
                continue
            seen_tokens.add(token)
            count = count_bot_users(token)
            total_users += count
            title = bot.get("title") or "Без названия"
            lines.append(f"🤖 {title}: {count} пользователей")
        lines.append(f"Итого по всем: {total_users}")
        await query.message.reply_text("\n".join(lines), reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    elif data == "admin_dump_db":
        db_file = Path(DB_PATH)
        if not db_file.exists():
            await query.message.reply_text("База данных не найдена", reply_markup=admin_panel_keyboard())
            return ConversationHandler.END
        try:
            await query.message.reply_document(
                document=InputFile(db_file.open("rb"), filename=db_file.name),
                caption="Актуальная база данных",
            )
        except Exception as e:
            logger.error("Не удалось отправить БД: %s", e)
            await query.message.reply_text("Не удалось отправить БД", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    elif data == "admin_restart_bots":
        await query.message.reply_text("Перезапускаю всех ботов...", reply_markup=admin_panel_keyboard())
        await restart_all_bots()
        await query.message.reply_text("Перезапуск завершён", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    elif data.startswith("admin_owner_"):
        owner_id = int(data.rsplit("_", 1)[1])
        bots = list_user_bots(owner_id)
        if not bots:
            await query.message.reply_text(
                "У пользователя нет подключённых ботов", reply_markup=admin_panel_keyboard()
            )
            return ConversationHandler.END
        summary = build_owner_summary(owner_id, bots)
        await query.message.reply_text(summary, reply_markup=admin_owner_keyboard(owner_id, bots))
        return ConversationHandler.END
    elif data.startswith("botreset_"):
        bot_id = int(data.rsplit("_", 1)[1])
        bot = get_bot_by_id(bot_id)
        if not bot:
            await query.answer("Бот не найден", show_alert=True)
            return ConversationHandler.END
        reset_bot_reward(bot_id)
        owner_id = bot.get("owner_id")
        bot_title = bot.get("title") or "бот"
        try:
            await query.answer("Начисления обнулены")
        except Exception:
            pass
        if owner_id:
            try:
                await primary_bot.send_message(
                    owner_id,
                    f"Начисления по боту {bot_title} обнулены администратором.",
                )
            except Exception:
                logger.warning("Не удалось уведомить владельца о сбросе начислений")
        bots = list_user_bots(owner_id) if owner_id else []
        summary_lines = [f"❄️ Начисления для бота {bot_title} сброшены до 0 ₽"]
        if bots:
            summary_lines.append(build_owner_summary(owner_id, bots))
        reply_markup = admin_owner_keyboard(owner_id, bots) if bots else admin_panel_keyboard()
        await query.message.reply_text("\n\n".join(summary_lines), reply_markup=reply_markup)
        return ConversationHandler.END
    elif data.startswith("botadd_") or data.startswith("botsub_"):
        bot_id = int(data.rsplit("_", 1)[1])
        bot = get_bot_by_id(bot_id)
        if not bot:
            await query.answer("Бот не найден", show_alert=True)
            return ConversationHandler.END
        action = "add" if data.startswith("botadd_") else "sub"
        context.user_data["bot_balance_action"] = action
        context.user_data["bot_balance_bot_id"] = bot_id
        context.user_data["bot_balance_owner_id"] = bot.get("owner_id")
        action_text = "добавления" if action == "add" else "списания"
        await query.message.reply_text(
            f"Введите сумму для {action_text} с баланса бота «{bot.get('title') or 'Без названия'}»:"
        )
        return WAIT_BOT_BALANCE
    elif data == "admin_broadcast":
        await query.message.reply_text(
            "📣 Пришлите текст или фото для рассылки по базе (Такси от Майка)",
            reply_markup=taxi_force_reply_markup(),
        )
        return WAIT_ADMIN_BROADCAST
    elif data == "admin_podmena_clear":
        clear_podmena_entries()
        await query.message.reply_text(
            "🧹 База подмен очищена.", reply_markup=admin_panel_keyboard()
        )
        return ConversationHandler.END
    elif data == "admin_toggle":
        new_value = "0" if is_ordering_enabled() else "1"
        set_setting("ordering_enabled", new_value)
        status = "🧊 Приём заказов остановлен" if new_value == "0" else "🎉 Приём заказов возобновлён"
        await query.message.reply_text(status, reply_markup=admin_panel_keyboard())
    elif data == "admin_status":
        status = "🎉 Приём заказов включён" if is_ordering_enabled() else "🧊 Приём заказов выключен"
        await query.message.reply_text(status, reply_markup=admin_panel_keyboard())
    elif data.startswith("payapprove_"):
        payment_id = int(data.rsplit("_", 1)[1])
        payment = get_payment(payment_id)
        if not payment:
            await query.message.reply_text("Платёж не найден")
            return ConversationHandler.END
        user_id = payment.get("tg_id")
        order_id = payment.get("order_id")
        order = get_order(order_id) if order_id else None
        order_bot = get_order_bot(order)
        if order_id:
            update_order_status(order_id, "paid")
        update_payment(payment_id, status="success")
        await order_bot.send_message(user_id, "🎉 Оплата за поездку подтверждена! Спасибо!")
        await query.message.reply_text("Оплата отмечена как успешная")
        return ConversationHandler.END
    elif data.startswith("paydecline_"):
        payment_id = int(data.rsplit("_", 1)[1])
        payment = get_payment(payment_id)
        update_payment(payment_id, status="declined")
        await query.message.reply_text("Отмечено как не найдено")
        if payment:
            order = get_order(payment.get("order_id")) if payment.get("order_id") else None
            order_bot = get_order_bot(order)
            method = payment.get("method")
            crypto_methods = {"ltc", "usdt_trc20", "usdt_trx"}
            is_crypto = method in crypto_methods
            request_text = (
                "❄️⚠️ Оплата не найдена. Пришлите, пожалуйста, ссылку на транзакцию или свяжитесь с оператором."
                if is_crypto
                else "❄️⚠️ Оплата не найдена. Пришлите, пожалуйста, чек в ответном сообщении или свяжитесь с оператором."
            )
            button_label = "✨ Ссылка" if is_crypto else "🧾🎄 Чек"
            await order_bot.send_message(
                payment.get("tg_id"),
                request_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(button_label, callback_data=f"payment_receipt_{payment_id}")]]),
            )


# ==========================
# Отправка сообщений пользователю
# ==========================
async def admin_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    order_id = context.user_data.get('order_id')
    order = get_order(order_id)
    if not order:
        await update.message.reply_text("Заказ не найден.", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    order_bot = get_order_bot(order)
    tg_id = order.get("tg_id")
    await order_bot.send_message(tg_id, f"🔔 Сообщение от администратора:\n{text}")
    await update.message.reply_text("Сообщение отправлено. Теперь введите сумму заказа (₽):")
    return WAIT_ADMIN_SUM


async def admin_replacement_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_id = context.user_data.get('replacement_info_id')
    field_key = context.user_data.get('replacement_field')
    if not info_id or not field_key:
        await update.message.reply_text("Запись не выбрана", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END

    value = update.message.text.strip()
    mapping = {
        "orderid": "order_number",
        "cardx": "card_x",
        "extid": "external_id",
        "token2": "token2",
        "link": "link",
    }
    column = mapping.get(field_key)
    if not column:
        await update.message.reply_text("Неизвестное поле", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END

    update_order_info_field(info_id, **{column: value})
    context.user_data.pop('replacement_info_id', None)
    context.user_data.pop('replacement_field', None)

    info = get_order_info(info_id)
    upsert_podmena_entry(info)
    saved = save_replacement_to_secondary_db(info)
    if not saved:
        fallback = f"{info.get('external_id', '-')}/{info.get('order_number', '-')}/{info.get('card_x', '-')}/{info.get('token2', '-')}"
        await update.message.reply_text(
            "❄️⚠️ Не удалось сохранить подмену во вторую БД. Данные: " + fallback,
            reply_markup=replacement_fields_keyboard(info),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Сохранено", reply_markup=replacement_fields_keyboard(info)
    )
    return ConversationHandler.END


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("payment_paid_"):
        payment_id = int(data.rsplit("_", 1)[1])
        update_payment(payment_id, status="waiting_admin")
        await query.message.reply_text("🎉 Заявка на оплату отправлена администратору")
        await notify_admins_payment(context, payment_id)
    elif data.startswith("payment_check_"):
        payment_id = int(data.rsplit("_", 1)[1])
        update_payment(payment_id, status="waiting_admin")
        await query.message.reply_text("✨ Отправили данные администратору, ждём подтверждения")
        await notify_admins_payment(context, payment_id)
    elif data.startswith("payment_cancel_"):
        payment_id = int(data.rsplit("_", 1)[1])
        update_payment(payment_id, status="cancelled")
        await query.message.reply_text(
            "Отмена операции", reply_markup=main_menu_keyboard(query.from_user.id)
        )
    elif data.startswith("payment_receipt_"):
        payment_id = int(data.rsplit("_", 1)[1])
        payment = get_payment(payment_id)
        context.user_data['waiting_receipt'] = payment_id
        receipt_kind = "link" if payment and payment.get("method") in {"ltc", "usdt_trc20", "usdt_trx"} else "proof"
        context.user_data['waiting_receipt_kind'] = receipt_kind
        prompt = "Пришлите ссылку на транзакцию" if receipt_kind == "link" else "Пришлите чек (фото или файл)"
        await query.message.reply_text(prompt)
        return WAIT_PAYMENT_PROOF
    return ConversationHandler.END


async def payment_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment_id = context.user_data.get('waiting_receipt')
    if not payment_id:
        await update.message.reply_text("Чек не ожидается")
        return ConversationHandler.END
    payment = get_payment(payment_id)
    if not payment:
        await update.message.reply_text("Платёж не найден")
        return ConversationHandler.END
    receipt_kind = context.user_data.pop('waiting_receipt_kind', 'proof')
    caption_lines = [
        f"Данные по оплате #{payment_id}",
        f"Метод: {payment.get('method')}",
    ]
    amount_value = payment.get('amount')
    if amount_value is not None:
        caption_lines.append(
            f"Сумма: {amount_value:.4f} {payment.get('currency') or 'RUB'}"
            if (payment.get("currency") or "RUB") != "RUB"
            else f"Сумма: {amount_value:.2f} {payment.get('currency') or 'RUB'}"
        )
    if payment.get("original_amount") and (payment.get("currency") or "RUB") != (payment.get("original_currency") or "RUB"):
        caption_lines.append(
            f"Эквивалент: {payment.get('original_amount', 0):.2f} {payment.get('original_currency') or 'RUB'}"
        )
    if payment.get("requisites"):
        caption_lines.append(f"Реквизиты: {payment.get('requisites')}")
    caption = "\n".join(caption_lines)
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Зачислить 🎉", callback_data=f"payapprove_{payment_id}")],
        [InlineKeyboardButton("Нет 🎄🚫", callback_data=f"paydecline_{payment_id}")],
    ])
    forwarded = False
    for admin_id in ADMIN_IDS:
        try:
            if receipt_kind == "link" and update.message.text:
                await context.bot.send_message(
                    admin_id,
                    caption + f"\n✨ Ссылка на транзакцию: {update.message.text}",
                    reply_markup=admin_keyboard,
                )
                forwarded = True
            elif update.message.photo:
                photo = update.message.photo[-1]
                await context.bot.send_photo(admin_id, photo=photo.file_id, caption=caption, reply_markup=admin_keyboard)
                forwarded = True
            elif update.message.document:
                doc = update.message.document
                await context.bot.send_document(admin_id, document=doc.file_id, caption=caption, reply_markup=admin_keyboard)
                forwarded = True
            elif update.message.text:
                await context.bot.send_message(admin_id, caption + f"\n🕯️ Комментарий: {update.message.text}", reply_markup=admin_keyboard)
                forwarded = True
        except Exception as e:
            logger.error(f"Не удалось переслать чек админу {admin_id}: {e}")
    if forwarded:
        await update.message.reply_text("Данные отправлены администратору")
    else:
        await update.message.reply_text("Не удалось отправить данные администратору, попробуйте ещё раз")
    context.user_data.pop('waiting_receipt', None)
    context.user_data.pop('waiting_receipt_kind', None)
    return ConversationHandler.END


async def admin_orders_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("🎄🚫 Введите числовой Telegram ID")
        return WAIT_ADMIN_ORDERS

    orders = get_user_orders(target_id, limit=5)
    if not orders:
        await update.message.reply_text("Заказы не найдены", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END

    lines = ["🎁 Последние заказы:"]
    for order in orders:
        lines.append(
            f"№{order['id']} — {order['status']} — {order['amount'] or 0:.2f} ₽ (база {order['base_amount'] or 0:.2f} ₽) — {order['created_at']}"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=admin_panel_keyboard())
    return ConversationHandler.END


async def refresh_all_users(target, context: ContextTypes.DEFAULT_TYPE):
    user_ids = get_all_user_ids()
    if not user_ids:
        await target.reply_text("ℹ️ В базе пока нет пользователей", reply_markup=admin_panel_keyboard())
        return

    updated = 0
    checked = 0
    failed: list[int] = []

    for uid in user_ids:
        try:
            chat = await context.bot.get_chat(uid)
            db_user = get_user(uid)
            old_username = db_user.get("username") if db_user else None
            add_user(uid, chat.username)
            if chat.username and chat.username != old_username:
                updated += 1
            checked += 1
        except Exception as e:
            failed.append(uid)
            logger.error(f"Не удалось обновить пользователя {uid}: {e}")

    lines = [
        "🔔 Проверка завершена:",
        f"🧑‍🎄‍🎄 Проверено пользователей: {checked}",
        f"🖊️❄️ Обновлено username: {updated}",
    ]
    if failed:
        lines.append("❄️⚠️ Не удалось обновить: " + ", ".join(map(str, failed)))

    await target.reply_text("\n".join(lines), reply_markup=admin_panel_keyboard())


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if sender_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Только администраторы могут рассылать сообщения.")
        return ConversationHandler.END

    msg = update.message
    content_text = msg.caption or msg.text
    photo = msg.photo[-1] if msg.photo else None

    if not (content_text or photo):
        await msg.reply_text(
            "⚠️ Пришлите текст или фото для рассылки (Такси от Майка)",
            reply_markup=taxi_force_reply_markup(),
        )
        return WAIT_ADMIN_BROADCAST

    status_message = await msg.reply_text("⏳ Обрабатываю рассылку...")

    sent = 0
    failed = 0
    blocked = 0
    photo_bytes = None

    if photo:
        try:
            file = await photo.get_file()
            photo_bytes = await file.download_as_bytearray()
        except Exception as exc:
            logger.error("Не удалось скачать фото для рассылки: %s", exc)
            await status_message.edit_text(
                "⚠️ Не удалось скачать фото для рассылки.",
                reply_markup=admin_panel_keyboard(),
            )
            return ConversationHandler.END

    bots = [{"token": PRIMARY_BOT_TOKEN, "db_path": DB_PATH, "title": "Основной"}]
    bots.extend(list_all_bots())

    seen_tokens = set()
    for bot_record in bots:
        token = bot_record.get("token")
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        db_path = bot_record.get("db_path") or DB_PATH
        try:
            bot_instance = get_bot_client(token)
        except InvalidToken as e:
            await notify_admins_invalid_bot(token, str(e), bot_record.get("owner_id"))
            delete_bot_by_token(token)
            continue
        user_ids = get_all_user_ids(db_path)
        for idx, uid in enumerate(user_ids, start=1):
            try:
                action = ChatAction.UPLOAD_PHOTO if photo else ChatAction.TYPING
                await bot_instance.send_chat_action(uid, action)
                if photo:
                    image = InputFile(photo_bytes, filename="broadcast.jpg")
                    await bot_instance.send_photo(uid, photo=image, caption=content_text)
                else:
                    await bot_instance.send_message(uid, f"🎺 Такси от Майка:\n{content_text}")
                sent += 1
            except Forbidden:
                blocked += 1
                logger.warning("Пользователь %s заблокировал бота %s", uid, token)
            except InvalidToken as e:
                logger.error("Токен %s устарел при рассылке: %s", token, e)
                await notify_admins_invalid_bot(token, str(e), bot_record.get("owner_id"))
                delete_bot_by_token(token)
                break
            except Exception as e:
                failed += 1
                logger.error(f"Не удалось отправить сообщение {uid} через {token}: {e}")

            if idx % 20 == 0:
                await asyncio.sleep(0.5)

    summary_lines = [
        "📣 Рассылка завершена",
        f"✅ Доставлено: {sent}",
        f"🚫 Блок: {blocked}",
        f"⚠️ Ошибок: {failed}",
    ]

    await status_message.edit_text(
        "\n".join(summary_lines), reply_markup=admin_panel_keyboard()
    )
    return ConversationHandler.END



# Подтверждение суммы и списание баланса
async def admin_sum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(" ", "").replace(",", ".")
    order_id = context.user_data.get('order_id')
    if not order_id:
        await update.message.reply_text("Ошибка: заказ не найден")
        return ConversationHandler.END
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("🎄🚫 Некорректная сумма, введите число >0")
        return WAIT_ADMIN_SUM

    order = get_order(order_id)
    tg_id = order.get("tg_id")
    user = get_user(tg_id)
    coefficient = user["coefficient"] if user else 1
    total = round(amount * coefficient, 2)

    update_order_fields(order_id, status="car_found", amount=total, base_amount=amount)

    updated_order = dict(order or {})
    updated_order.update({"id": order_id, "amount": total, "base_amount": amount})
    order_bot = get_order_bot(order)
    await send_payment_menu(updated_order, order_bot)

    referral_reward = 0
    referrer_id = (user or {}).get("referred_by")
    if referrer_id:
        referral_reward = add_referral_reward(referrer_id, tg_id, amount, order_id)
        if referral_reward:
            try:
                await primary_bot.send_message(
                    referrer_id,
                    f"🎁 Вам начислено {referral_reward:.2f} ₽ за заказ друга №{order_id}. Спасибо, что приглашаете друзей!",
                )
            except Exception as e:
                logger.warning("Не удалось уведомить реферера %s: %s", referrer_id, e)

    bot_token = order.get("bot_token") or PRIMARY_BOT_TOKEN
    bot_record = get_bot_by_token(bot_token)
    if bot_record and bot_record.get("owner_id"):
        reward = round(amount * 0.15, 2)
        add_bot_reward(bot_token, reward)
        bot_link = get_bot_link(bot_token, bot_record.get("title"))
        customer_username = (user or {}).get("username")
        customer_label = f"@{customer_username}" if customer_username else "username не указан"
        customer_text = f"{customer_label} (ID: {tg_id})"
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={
                    "chat_id": bot_record.get("owner_id"),
                    "text": (
                        f"Через вашего бота {bot_link} оформлен заказ №{order_id} на сумму {amount:.2f} ₽.\n"
                        f"Ваша комиссия: {reward:.2f} ₽ (15%).\n\n"
                        f"Заказчик - {customer_text}"
                    ),
                },
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить владельца бота о заказе {order_id}: {e}")

    await update.message.reply_text(
        f"🎉 Сумма заказа сохранена. Итог для клиента: {total:.2f} ₽. Меню оплаты отправлено клиенту",
        reply_markup=payment_choice_keyboard(order_id),
    )

    await update.message.reply_text(
        "Добавить заказ для подмены?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить", callback_data=f"replacement_offer_add_{order_id}")],
            [InlineKeyboardButton("Нет", callback_data=f"replacement_offer_skip_{order_id}")],
        ]),
    )

    return ConversationHandler.END


async def admin_bot_balance_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_value = update.message.text.replace(" ", "").replace(",", ".")
    try:
        value = float(raw_value)
        if value <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("🎄🚫 Некорректная сумма, введите число больше 0")
        return WAIT_BOT_BALANCE

    bot_id = context.user_data.pop("bot_balance_bot_id", None)
    action = context.user_data.pop("bot_balance_action", None)
    owner_id = context.user_data.pop("bot_balance_owner_id", None)

    if not bot_id or action not in {"add", "sub"}:
        await update.message.reply_text("Бот не выбран", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END

    bot = get_bot_by_id(bot_id)
    if not bot:
        await update.message.reply_text("Бот не найден", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END

    current = float(bot.get("pending_reward") or 0)
    delta = value if action == "add" else -value
    new_value = round(max(0, current + delta), 2)
    set_bot_reward(bot_id, new_value)

    action_text = "добавлено" if action == "add" else "списано"
    title = bot.get("title") or "бот"
    await update.message.reply_text(
        f"🎁 {action_text.capitalize()} {value:.2f} ₽. Новый баланс «{title}»: {new_value:.2f} ₽."
    )

    if owner_id:
        bots = list_user_bots(owner_id)
        if bots:
            summary = build_owner_summary(owner_id, bots)
            await update.message.reply_text(summary, reply_markup=admin_owner_keyboard(owner_id, bots))
            return ConversationHandler.END

    await update.message.reply_text("Возврат в админ-панель", reply_markup=admin_panel_keyboard())
    return ConversationHandler.END


@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    now = datetime.now()
    day_ago = now - timedelta(days=1)
    day_ago_str = day_ago.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(ORDERS_DB) as conn:
        c = conn.cursor()
        # Заказы за сутки
        c.execute("SELECT SUM(amount), COUNT(*) FROM orders WHERE created_at >= ?", (day_ago_str,))
        day_sum, day_count = c.fetchone()
        # Заказы за всё время
        c.execute("SELECT SUM(amount), COUNT(*) FROM orders")
        total_sum, total_count = c.fetchone()

    day_sum = day_sum or 0
    total_sum = total_sum or 0
    day_count = day_count or 0
    total_count = total_count or 0

    text = (
        f"✨ <b>Статистика заказов</b>\n\n"
        f"🎆️ Кол-во заказов за сутки: {day_count}\n"
        f"🎆 Кол-во заказов за всё время: {total_count}\n\n"
        f"🎁 Сумма заказов за сутки: {day_sum:.2f} ₽\n"
        f"🎁 Сумма заказов за всё время: {total_sum:.2f} ₽\n\n"
        f"🎉 Заработок за сутки: {day_sum:.2f} ₽\n"
        f"🎁 Заработок за всё время: {total_sum:.2f} ₽"
    )
    await update.message.reply_text(text, parse_mode="HTML")

@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /ban <tg_id>")
        return
    try:
        tg_id = int(context.args[0])
        with sqlite3.connect(BANNED_DB) as conn:
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO banned (tg_id) VALUES (?)", (tg_id,))
            conn.commit()
        await update.message.reply_text(f"🎉 Пользователь {tg_id} заблокирован")
    except ValueError:
        await update.message.reply_text("🎄🚫 Некорректный tg_id")


# ==========================
# Запуск нескольких ботов
# ==========================
RUNNING_BOTS: dict[str, asyncio.Task] = {}
STOPPED_BOTS: set[str] = set()
BOT_LOCKS: dict[str, Path] = {}


def _lock_file_for_token(token: str) -> Path:
    safe_token = safe_token_slug(token)
    return DB_DIR / f"bot_{safe_token}.lock"


def acquire_bot_lock(token: str) -> bool:
    lock_path = _lock_file_for_token(token)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("x", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
        BOT_LOCKS[token] = lock_path
        return True
    except FileExistsError:
        try:
            existing_pid = lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            existing_pid = ""

        if existing_pid.isdigit():
            try:
                os.kill(int(existing_pid), 0)
            except Exception:
                try:
                    lock_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return acquire_bot_lock(token)

        logger.warning(
            "Запуск бота %s пропущен: обнаружен локальный lock (%s). "
            "Возможен другой запущенный экземпляр.",
            token,
            existing_pid or "неизвестен",
        )
        return False


def release_bot_lock(token: str) -> None:
    lock_path = BOT_LOCKS.pop(token, None)
    if not lock_path:
        return
    try:
        lock_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug("Не удалось удалить lock-файл %s: %s", lock_path, exc)


def configure_application(app):
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_type_callback, pattern="^order_"),
            MessageHandler(filters.Regex(f"^{re.escape(PRICE_BTN)}$"), price_check_start),
        ],
        states={
            WAIT_SCREENSHOT: [MessageHandler(filters.PHOTO, screenshot_receive)],
            WAIT_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_city)],
            WAIT_ADDRESS_FROM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_address_from),
                CallbackQueryHandler(favorite_address_callback, pattern="^fav_from_"),
            ],
            WAIT_ADDRESS_TO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_address_to),
                CallbackQueryHandler(favorite_address_callback, pattern="^fav_to_"),
            ],
            WAIT_ADDRESS_THIRD_DECISION: [CallbackQueryHandler(address_third_decision, pattern="^address_")],
            WAIT_ADDRESS_THIRD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_address_third),
                CallbackQueryHandler(favorite_address_callback, pattern="^fav_third_"),
            ],
            WAIT_TARIFF: [CallbackQueryHandler(tariff_selected, pattern="^tariff_")],
            WAIT_ADDITIONAL: [CallbackQueryHandler(additional_selected, pattern="^additional_")],
            WAIT_CHILD_SEAT_TYPE: [CallbackQueryHandler(child_seat_type_selected, pattern="^seat_type_")],
            WAIT_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_comment)],
            WAIT_ORDER_CONFIRM: [CallbackQueryHandler(order_confirmation, pattern="^order_confirm_")],
            WAIT_PRICE_CITY_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_city_from)],
            WAIT_PRICE_ADDRESS_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_address_from)],
            WAIT_PRICE_CITY_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_city_to)],
            WAIT_PRICE_ADDRESS_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_address_to)],
            WAIT_PRICE_TARIFF: [CallbackQueryHandler(price_tariff_selected, pattern="^price_tariff_")],
            WAIT_PRICE_DECISION: [CallbackQueryHandler(price_order_decision, pattern="^price_")],
        },
        fallbacks=[CommandHandler("start", start_over)],
        per_user=True,
        per_message=False,
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^(chat_|found_|admin_orders|admin_refresh|admin_all_bots|admin_franchise_db|admin_owner_|admin_broadcast|admin_users_count|admin_dump_db|admin_restart_bots|admin_toggle|admin_status|admin_replacements|admin_podmena_clear|replacement_|take_|reject_|search_|cancelsearch_|cancel_|payapprove_|paydecline_|botreset_|botadd_|botsub_)")],
        states={
            WAIT_ADMIN_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_message)],
            WAIT_ADMIN_SUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_sum)],
            WAIT_ADMIN_ORDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_orders_lookup)],
            WAIT_ADMIN_BROADCAST: [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
                    admin_broadcast,
                )
            ],
            WAIT_REPLACEMENT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_replacement_save)],
            WAIT_BOT_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bot_balance_update)],
        },
        fallbacks=[CommandHandler("start", start_over)],
        per_user=True,
        per_message=False,
    )

    payment_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_payment_method, pattern="^orderpay_"),
            CallbackQueryHandler(payment_callback, pattern="^payment_")
        ],
        states={
            WAIT_PAYMENT_PROOF: [MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, payment_receipt)],
        },
        fallbacks=[CommandHandler("start", start_over)],
        per_user=True,
        per_message=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(admin_conv_handler)
    app.add_handler(payment_conv)
    app.add_handler(CallbackQueryHandler(order_confirmation, pattern="^order_confirm_"))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern="^profile_"))
    app.add_handler(CallbackQueryHandler(favorite_address_callback, pattern="^fav_(from|to|third)_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(take_|reject_|search_|cancel_|cancelsearch_|pay_card_|replacement_|admin_replacements|admin_refresh|admin_all_bots|admin_franchise_db|admin_owner_|admin_broadcast|admin_users_count|admin_dump_db|admin_restart_bots|admin_podmena_clear|payapprove_|paydecline_|botreset_|botadd_|botsub_)"))
    app.add_handler(CommandHandler("start", start_over))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban_user))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

    app.add_error_handler(error_handler)

    async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        user_id = update.effective_user.id

        if context.user_data.get("awaiting_city"):
            city = text.strip()
            update_user_city(user_id, city)
            context.user_data.pop("awaiting_city", None)
            await update.message.reply_text(f"🌟 Город сохранён: {city}")
            await send_profile_info(update.message, user_id, context)
            return

        if context.user_data.get("awaiting_bot_token"):
            token = text.strip()
            context.user_data.pop("awaiting_bot_token", None)
            info = None
            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getMe", timeout=10
                )
                if resp.status_code == 200:
                    info = resp.json().get("result", {})
                else:
                    raise ValueError("bad response")
            except Exception:
                await update.message.reply_text("Не удалось проверить токен. Убедитесь, что он корректен.")
                return
            title = info.get("username") or info.get("first_name")
            create_bot_storage(token, user_id, title)
            await ensure_bot_running(token)
            await update.message.reply_text("🤖 Бот успешно подключён! ✨")
            await send_profile_info(update.message, user_id, context)
            return

        if user_id in ADMIN_IDS and text == ADMIN_BTN:
            await admin_show_panel(update.message)
            return

        if context.user_data.get("awaiting_fav_action"):
            action = context.user_data.get("awaiting_fav_action")
            if action == "add":
                favorites = get_favorite_addresses(user_id)
                if len(favorites) >= 3:
                    await update.message.reply_text("Можно сохранить не более 3 адресов")
                else:
                    add_favorite_address(user_id, text.strip())
                    await update.message.reply_text("❄️ Адрес добавлен")
                context.user_data.pop("awaiting_fav_action", None)
                await send_profile_info(update.message, user_id, context)
                return
            elif action == "edit":
                fav_id = context.user_data.get("fav_edit_id")
                if fav_id:
                    update_favorite_address(fav_id, user_id, text.strip())
                    await update.message.reply_text("🖊️❄️ Адрес обновлён")
                context.user_data.pop("awaiting_fav_action", None)
                context.user_data.pop("fav_edit_id", None)
                await send_profile_info(update.message, user_id, context)
                return

        if text == PROFILE_BTN:
            await profile(update, context)
        elif text == HELP_BTN:
            await help_menu(update, context)
        elif text == ORDER_BTN:
            await order_menu(update, context)
        elif text == FAQ_BTN:
            await update.message.reply_text(
                "Откройте ответы на частые вопросы:", reply_markup=faq_keyboard()
            )
        elif text == BACK_BTN:
            await update.message.reply_text(
                "Возврат в главное меню",
                reply_markup=main_menu_keyboard(update.effective_user.id),
            )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))


async def launch_bot(token: str):
    if not acquire_bot_lock(token):
        STOPPED_BOTS.add(token)
        return
    try:
        app = ApplicationBuilder().token(token).request(HTTPXRequest(**REQUEST_TIMEOUTS)).build()
    except InvalidToken as e:
        bot_record = delete_bot_by_token(token)
        owner_id = bot_record.get("owner_id") if bot_record else None
        await notify_admins_invalid_bot(token, str(e), owner_id)
        release_bot_lock(token)
        return

    configure_application(app)
    started = False
    try:
        logger.info("🤖 Бот запущен")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        started = True

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("🛑 Остановка бота")
            raise
    except InvalidToken as e:
        bot_record = delete_bot_by_token(token)
        owner_id = bot_record.get("owner_id") if bot_record else None
        await notify_admins_invalid_bot(token, str(e), owner_id)
    except Conflict as e:
        STOPPED_BOTS.add(token)
        logger.warning(
            "Бот %s остановлен из-за конфликта getUpdates (другой экземпляр уже запущен): %s",
            token,
            e,
        )
    except Exception as e:
        bot_record = get_bot_by_token(token)
        owner_id = bot_record.get("owner_id") if bot_record else None
        logger.exception("Ошибка запуска бота %s: %s", token, e)
        await notify_admins_invalid_bot(token, str(e), owner_id)
    finally:
        if started:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        RUNNING_BOTS.pop(token, None)
        release_bot_lock(token)


async def ensure_bot_running(token: str):
    if not token:
        return
    if token in STOPPED_BOTS:
        logger.warning(
            "Запуск бота %s пропущен: обнаружен конфликт getUpdates. "
            "Остановите другой экземпляр или выполните ручной перезапуск.",
            token,
        )
        return
    if token in RUNNING_BOTS:
        return
    loop = asyncio.get_running_loop()
    task = loop.create_task(launch_bot(token))

    async def _restart_after_delay():
        await asyncio.sleep(5)
        await ensure_bot_running(token)

    def _on_done(done_task: asyncio.Task):
        RUNNING_BOTS.pop(token, None)
        if done_task.cancelled():
            return
        if token in STOPPED_BOTS:
            logger.warning("Бот %s остановлен из-за конфликта getUpdates, автоперезапуск отключён.", token)
            return
        if done_task.exception():
            logger.error("Бот %s завершился с ошибкой: %s", token, done_task.exception())
        else:
            logger.warning("Бот %s остановился. Перезапускаем.", token)
        loop.create_task(_restart_after_delay())

    task.add_done_callback(_on_done)
    RUNNING_BOTS[token] = task


async def stop_bot(token: str):
    task = RUNNING_BOTS.get(token)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info(f"Бот {token} остановлен и удалён из списка")


async def restart_all_bots():
    tokens = {PRIMARY_BOT_TOKEN}
    if TOKEN:
        tokens.add(TOKEN)
    for bot in list_all_bots():
        if bot.get("token"):
            tokens.add(bot.get("token"))

    for token in list(RUNNING_BOTS.keys()):
        await stop_bot(token)

    STOPPED_BOTS.clear()
    await asyncio.sleep(1)

    for token in tokens:
        await ensure_bot_running(token)


async def main_async():
    init_db()
    init_podmena_db()
    add_user_bot(0, PRIMARY_BOT_TOKEN, DB_PATH, "Основной бот")
    tokens = {PRIMARY_BOT_TOKEN}
    if TOKEN:
        tokens.add(TOKEN)
    for bot in list_all_bots():
        if bot.get("token"):
            tokens.add(bot.get("token"))

    for token in tokens:
        await ensure_bot_running(token)

    if RUNNING_BOTS:
        await asyncio.gather(*RUNNING_BOTS.values(), return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main_async())