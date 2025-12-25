import hashlib
import os
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
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            details TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
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
    return render_template("orders.html", user=user, orders=items)


@app.route("/orders/new", methods=["GET", "POST"])
@login_required
def new_order():
    user = current_user()
    if request.method == "POST":
        pickup = request.form.get("pickup", "").strip()
        destination = request.form.get("destination", "").strip()
        details = request.form.get("details", "").strip()
        if not pickup or not destination:
            flash("Укажите откуда и куда едет такси.")
            return render_template("new_order.html", user=user)
        now = datetime.now(timezone.utc).isoformat()
        db = get_db()
        db.execute(
            """
            INSERT INTO orders (user_id, pickup, destination, details, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'new', ?, ?)
            """,
            (user["id"], pickup, destination, details, now, now),
        )
        db.commit()
        send_telegram_order(user["username"], pickup, destination, details)
        flash("Заказ создан! Админ получил уведомление в Telegram.")
        return redirect(url_for("orders"))
    return render_template("new_order.html", user=user)


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
    return render_template("admin_orders.html", orders=items, user=current_user())


@app.route("/admin/orders/<int:order_id>/complete", methods=["POST"])
@admin_required
def complete_order(order_id):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        UPDATE orders
        SET status = 'completed', updated_at = ?
        WHERE id = ?
        """,
        (now, order_id),
    )
    db.commit()
    flash("Заказ отмечен как выполненный.")
    return redirect(url_for("admin_orders"))


def send_telegram_order(username: str, pickup: str, destination: str, details: str):
    if not cfg.BOT_TOKEN or not cfg.ADMIN_TELEGRAM_ID:
        return
    text = (
        "Новый заказ с сайта!\n"
        f"Клиент: {username}\n"
        f"Откуда: {pickup}\n"
        f"Куда: {destination}\n"
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
