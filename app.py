import hashlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone

import requests
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import cfg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "data", "site.db"))
YANDEX_TAXI_TOKEN = (os.getenv("YANDEX_TAXI_TOKEN") or cfg.YANDEX_TAXI_TOKEN).strip()
YANDEX_PRICE_CLASS = "comfortplus"
PRICE_TARIFFS = [
    ("econom", "Эконом"),
    ("business", "Комфорт"),
    ("comfortplus", "Комфорт+"),
    ("minivan", "Минивэн"),
    ("vip", "Бизнес"),
    ("ultimate", "Премьер"),
    ("maybach", "Элит"),
]

STATUS_LABELS = {
    "new": "Новый",
    "in_progress": "Взял в работу",
    "searching": "Поиск машины",
    "found": "Машина найдена",
    "link_sent": "Ссылка отправлена",
    "payment_sent": "Реквизиты отправлены",
    "completed": "Завершен",
}

app = Flask(__name__)
app.secret_key = cfg.SECRET_KEY


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            telegram_handle TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    ensure_columns("users", {"telegram_handle": "TEXT"})
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            city TEXT NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            details TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            tariff TEXT,
            price_app REAL,
            price_our REAL,
            contact_handle TEXT,
            link TEXT,
            payment_details TEXT,
            total_price REAL,
            paid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    ensure_columns(
        "orders",
        {
            "city": "TEXT",
            "tariff": "TEXT",
            "price_app": "REAL",
            "price_our": "REAL",
            "contact_handle": "TEXT",
            "link": "TEXT",
            "payment_details": "TEXT",
            "total_price": "REAL",
            "paid": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    db.commit()
    ensure_admin_user()


@app.before_request
def before_request():
    init_db()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == digest


def ensure_admin_user():
    db = get_db()
    admin = db.execute(
        "SELECT id FROM users WHERE is_admin = 1 LIMIT 1"
    ).fetchone()
    if admin:
        return
    if not cfg.ADMIN_USERNAME or not cfg.ADMIN_PASSWORD:
        return
    db.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, is_admin, created_at)
        VALUES (?, ?, 1, ?)
        """,
        (
            cfg.ADMIN_USERNAME,
            hash_password(cfg.ADMIN_PASSWORD),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()


def ensure_columns(table: str, columns: dict[str, str]) -> None:
    db = get_db()
    existing = {
        row[1]
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for column, definition in columns.items():
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    db.commit()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Пожалуйста, войдите в аккаунт.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def admin_required(view):
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            flash("Доступ только для администратора.")
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@app.route("/")
def index():
    user = current_user()
    return render_template("index.html", user=user)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Заполните логин и пароль.")
            return render_template("register.html")
        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO users (username, password_hash, is_admin, created_at)
                VALUES (?, ?, 0, ?)
                """,
                (username, hash_password(password), datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Такой логин уже существует.")
            return render_template("register.html")
        flash("Регистрация успешна! Теперь войдите.")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            flash("Неверный логин или пароль.")
            return render_template("login.html")
        session["user_id"] = user["id"]
        flash("Вы вошли в аккаунт.")
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.")
    return redirect(url_for("index"))


@app.route("/orders")
@login_required
def orders():
    user = current_user()
    db = get_db()
    items = db.execute(
        """
        SELECT * FROM orders
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user["id"],),
    ).fetchall()
    return render_template(
        "orders.html", user=user, orders=items, status_labels=STATUS_LABELS
    )


@app.route("/orders/new", methods=["GET", "POST"])
@login_required
def new_order():
    user = current_user()
    if request.method == "POST":
        city = request.form.get("city", "").strip()
        pickup = request.form.get("pickup", "").strip()
        destination = request.form.get("destination", "").strip()
        details = request.form.get("details", "").strip()
        tariff = request.form.get("tariff", "").strip()
        contact_handle = request.form.get("contact_handle", "").strip()
        if not city or not pickup or not destination:
            flash("Укажите город, откуда и куда едет такси.")
            return render_template("new_order.html", user=user)
        now = datetime.now(timezone.utc).isoformat()
        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO orders (
                user_id, city, pickup, destination, details, status, tariff, contact_handle, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
            """,
            (
                user["id"],
                city,
                pickup,
                destination,
                details,
                tariff or None,
                contact_handle or user["telegram_handle"] or None,
                now,
                now,
            ),
        )
        db.commit()
        send_telegram_order(
            order_id=cursor.lastrowid,
            username=user["username"],
            city=city,
            pickup=pickup,
            destination=destination,
            details=details,
            tariff=tariff,
            contact_handle=contact_handle,
        )
        flash("Заказ создан! Админ получил уведомление в Telegram.")
        return redirect(url_for("orders"))
    return render_template("new_order.html", user=user)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        telegram_handle = request.form.get("telegram_handle", "").strip()
        db = get_db()
        db.execute(
            "UPDATE users SET telegram_handle = ? WHERE id = ?",
            (telegram_handle or None, user["id"]),
        )
        db.commit()
        flash("Telegram-аккаунт обновлён.")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)


@app.route("/price-check", methods=["GET", "POST"])
def price_check():
    result = None
    if request.method == "POST":
        city = request.form.get("city", "").strip()
        pickup = request.form.get("pickup", "").strip()
        destination = request.form.get("destination", "").strip()
        tariff = request.form.get("tariff", YANDEX_PRICE_CLASS).strip() or YANDEX_PRICE_CLASS
        if not city or not pickup or not destination:
            flash("Заполните город, откуда и куда.")
        else:
            try:
                full_from = f"{city}, {pickup}"
                full_to = f"{city}, {destination}"
                price, price_class = fetch_yandex_price(
                    full_from, full_to, price_class=tariff
                )
                price_value = _parse_price_value(price)
                if price_value is None:
                    flash("Не удалось получить цену. Попробуйте ещё раз.")
                else:
                    our_price = round(price_value * 0.55, 2)
                    result = {
                        "app_price": price_value,
                        "our_price": our_price,
                        "tariff_label": get_tariff_label(price_class or tariff),
                    }
            except Exception:
                flash("Не удалось связаться с сервисом цены. Попробуйте позже.")
    return render_template(
        "price_check.html",
        user=current_user(),
        tariffs=PRICE_TARIFFS,
        result=result,
    )


@app.route("/admin/orders")
@admin_required
def admin_orders():
    db = get_db()
    items = db.execute(
        """
        SELECT orders.*, users.username
        FROM orders
        JOIN users ON users.id = orders.user_id
        ORDER BY created_at DESC
        """
    ).fetchall()
    return render_template(
        "admin_orders.html",
        orders=items,
        user=current_user(),
        status_labels=STATUS_LABELS,
        payment_default=cfg.PAYMENT_DETAILS,
    )


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def update_order_status(order_id):
    status = request.form.get("status", "new")
    if status not in STATUS_LABELS:
        flash("Неизвестный статус.")
        return redirect(url_for("admin_orders"))
    set_order_status(order_id, status)
    flash("Статус обновлён.")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/<int:order_id>/update", methods=["POST"])
@admin_required
def update_order_details(order_id):
    link = request.form.get("link", "").strip()
    total_price = request.form.get("total_price", "").strip()
    payment_details = request.form.get("payment_details", "").strip()
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    price_value = None
    if total_price:
        try:
            price_value = float(total_price.replace(",", "."))
        except ValueError:
            flash("Цена должна быть числом.")
            return redirect(url_for("admin_orders"))
    status = "link_sent" if link else None
    db.execute(
        """
        UPDATE orders
        SET link = ?,
            total_price = ?,
            payment_details = ?,
            status = COALESCE(?, status),
            updated_at = ?
        WHERE id = ?
        """,
        (
            link or None,
            price_value,
            payment_details or cfg.PAYMENT_DETAILS,
            status,
            now,
            order_id,
        ),
    )
    db.commit()
    flash("Данные заказа обновлены.")
    return redirect(url_for("admin_orders"))


@app.route("/orders/<int:order_id>/pay", methods=["POST"])
@login_required
def mark_paid(order_id):
    user = current_user()
    db = get_db()
    order = db.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user["id"]),
    ).fetchone()
    if not order:
        flash("Заказ не найден.")
        return redirect(url_for("orders"))
    if not order["total_price"]:
        flash("Сумма оплаты ещё не задана.")
        return redirect(url_for("orders"))
    if order["paid"]:
        flash("Оплата уже отмечена.")
        return redirect(url_for("orders"))
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE orders SET paid = 1, updated_at = ? WHERE id = ?",
        (now, order_id),
    )
    db.commit()
    notify_payment(user["username"], order_id, order["total_price"])
    flash("Спасибо! Оплата отмечена и отправлена администратору.")
    return redirect(url_for("orders"))


def set_order_status(order_id: int, status: str) -> None:
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        UPDATE orders
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, now, order_id),
    )
    db.commit()


def send_telegram_order(
    order_id: int,
    username: str,
    city: str,
    pickup: str,
    destination: str,
    details: str,
    tariff: str | None,
    contact_handle: str | None,
):
    if not cfg.BOT_TOKEN or not cfg.ADMIN_TELEGRAM_ID:
        return
    tariff_text = tariff or "не указан"
    contact_text = contact_handle or "не указан"
    text = (
        "Новый заказ с сайта!\n"
        f"Заказ №{order_id}\n"
        f"Клиент: {username}\n"
        f"Город: {city}\n"
        f"Откуда: {pickup}\n"
        f"Куда: {destination}\n"
        f"Тариф: {tariff_text}\n"
        f"Контакт: {contact_text}\n"
        f"Детали: {details or 'нет'}"
    )
    url = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": cfg.ADMIN_TELEGRAM_ID,
            "text": text,
        },
        timeout=10,
    )


def notify_payment(username: str, order_id: int, total_price: float) -> None:
    if not cfg.BOT_TOKEN or not cfg.ADMIN_TELEGRAM_ID:
        return
    text = (
        "Оплата подтверждена на сайте!\n"
        f"Заказ №{order_id}\n"
        f"Клиент: {username}\n"
        f"Сумма: {total_price:.2f} ₽"
    )
    url = f"https://api.telegram.org/bot{cfg.BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": cfg.ADMIN_TELEGRAM_ID,
            "text": text,
        },
        timeout=10,
    )


def get_tariff_label(code: str | None) -> str:
    for key, label in PRICE_TARIFFS:
        if key == code:
            return label
    return code or "Неизвестный"


def _normalize_point(value) -> list[float] | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) for v in value)
    ):
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
    if not YANDEX_TAXI_TOKEN:
        raise RuntimeError("Не задан YANDEX_TAXI_TOKEN")
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
