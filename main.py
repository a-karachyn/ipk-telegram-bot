import os
import re
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="IPK Telegram Lead Bot v5")

# =========================
# Настройки
# =========================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

# Почта для отправки заявок
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.mail.ru").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465").strip())
SMTP_LOGIN = os.getenv("SMTP_LOGIN", "").strip()          # например: ak.01@bk.ru
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()    # спецпароль для внешнего приложения
LEADS_EMAIL = os.getenv("LEADS_EMAIL", "ak.01@bk.ru").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

if not SMTP_LOGIN:
    raise RuntimeError("Не задан SMTP_LOGIN")

if not SMTP_PASSWORD:
    raise RuntimeError("Не задан SMTP_PASSWORD")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =========================
# In-memory state
# =========================
users: Dict[int, Dict[str, Any]] = {}

services = {
    "1": "Разработка СТУ",
    "2": "Расчет пожарные риски",
    "3": "Проектирование СПС, СОУЭ, Пожаротушение",
    "4": "Проектирование систем КСОБ",
}

STATE_CHOOSE_SERVICE = "choose_service"
STATE_NAME = "name"
STATE_PHONE = "phone"
STATE_COMMENT = "comment"

# =========================
# Клавиатуры
# =========================
def get_main_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [[{"text": "заявка"}]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def get_services_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [
            [{"text": "1"}, {"text": "2"}],
            [{"text": "3"}, {"text": "4"}],
            [{"text": "заявка"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def get_comment_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [
            [{"text": "Пропустить"}],
            [{"text": "заявка"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

# =========================
# Вспомогательные функции
# =========================
def get_services_text() -> str:
    return (
        "Выберите услугу:\n\n"
        "1. Разработка СТУ\n"
        "2. Расчет пожарные риски\n"
        "3. Проектирование СПС, СОУЭ, Пожаротушение\n"
        "4. Проектирование систем КСОБ"
    )


def reset_user(user_id: int) -> None:
    users.pop(user_id, None)


def init_user(user_id: int) -> None:
    users[user_id] = {
        "state": STATE_CHOOSE_SERVICE,
        "service_key": None,
        "service_name": None,
        "name": None,
        "phone": None,
        "comment": None,
    }


def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


def extract_text_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    message = update.get("message")
    if not message:
        return None

    text = message.get("text")
    if not isinstance(text, str):
        return None

    chat = message.get("chat", {})
    from_user = message.get("from", {})

    chat_id = chat.get("id")
    user_id = from_user.get("id")
    username = from_user.get("username")
    first_name = from_user.get("first_name")
    last_name = from_user.get("last_name")

    if chat_id is None or user_id is None:
        return None

    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "text": text.strip(),
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
    }


def get_telegram_user_label(message_data: Dict[str, Any]) -> str:
    first_name = message_data.get("first_name") or ""
    last_name = message_data.get("last_name") or ""
    username = message_data.get("username")

    full_name = f"{first_name} {last_name}".strip()

    if full_name and username:
        return f"{full_name} (@{username})"
    if full_name:
        return full_name
    if username:
        return f"@{username}"

    return f"user_id={message_data['user_id']}"


def normalize_phone(phone: str) -> str:
    return re.sub(r"\s+", "", phone.strip())


def is_valid_phone(phone: str) -> bool:
    cleaned = normalize_phone(phone)

    allowed_pattern = r"^\+?[0-9\-\(\)]+$"
    if not re.match(allowed_pattern, cleaned):
        return False

    digits_only = re.sub(r"\D", "", cleaned)
    return len(digits_only) >= 10


def format_email_subject(user_data: Dict[str, Any]) -> str:
    service_name = user_data.get("service_name", "Заявка")
    return f"Новая заявка — {service_name}"


def format_email_body(user_data: Dict[str, Any], message_data: Dict[str, Any]) -> str:
    comment = user_data.get("comment") or "—"
    client_label = get_telegram_user_label(message_data)

    return (
        "Новая заявка с Telegram-бота\n\n"
        f"Услуга: {user_data.get('service_name', '—')}\n"
        f"Имя: {user_data.get('name', '—')}\n"
        f"Телефон: {user_data.get('phone', '—')}\n"
        f"Комментарий: {comment}\n\n"
        f"Клиент в Telegram: {client_label}\n"
        f"Chat ID: {message_data.get('chat_id')}\n"
        f"User ID: {message_data.get('user_id')}"
    )


def send_email_lead(user_data: Dict[str, Any], message_data: Dict[str, Any]) -> bool:
    subject = format_email_subject(user_data)
    body = format_email_body(user_data, message_data)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = SMTP_LOGIN
    msg["To"] = LEADS_EMAIL

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.login(SMTP_LOGIN, SMTP_PASSWORD)
            server.sendmail(SMTP_LOGIN, [LEADS_EMAIL], msg.as_string())
        return True
    except Exception:
        return False


def start_application(chat_id: int, user_id: int) -> None:
    init_user(user_id)
    send_message(
        chat_id,
        get_services_text(),
        reply_markup=get_services_keyboard(),
    )


def process_user_message(message_data: Dict[str, Any]) -> None:
    chat_id = message_data["chat_id"]
    user_id = message_data["user_id"]
    text = message_data["text"].strip()

    if text.lower() == "заявка":
        start_application(chat_id, user_id)
        return

    if user_id not in users:
        send_message(
            chat_id,
            'Чтобы оставить заявку, нажмите кнопку "заявка".',
            reply_markup=get_main_keyboard(),
        )
        return

    user_data = users[user_id]
    state = user_data["state"]

    if state == STATE_CHOOSE_SERVICE:
        if text not in services:
            send_message(
                chat_id,
                "Пожалуйста, нажмите кнопку с номером услуги.",
                reply_markup=get_services_keyboard(),
            )
            return

        user_data["service_key"] = text
        user_data["service_name"] = services[text]
        user_data["state"] = STATE_NAME

        send_message(chat_id, "Введите имя")
        return

    if state == STATE_NAME:
        if not text:
            send_message(chat_id, "Имя не должно быть пустым. Введите имя")
            return

        user_data["name"] = text
        user_data["state"] = STATE_PHONE

        send_message(chat_id, "Введите телефон")
        return

    if state == STATE_PHONE:
        if not text:
            send_message(chat_id, "Телефон не должен быть пустым. Введите телефон")
            return

        if not is_valid_phone(text):
            send_message(
                chat_id,
                "Телефон введен неверно.\nВведите номер еще раз, например: +79991234567",
            )
            return

        user_data["phone"] = normalize_phone(text)
        user_data["state"] = STATE_COMMENT

        send_message(
            chat_id,
            'Введите комментарий или нажмите кнопку "Пропустить".',
            reply_markup=get_comment_keyboard(),
        )
        return

    if state == STATE_COMMENT:
        if text.lower() == "пропустить":
            user_data["comment"] = None
        else:
            user_data["comment"] = text

        email_sent = send_email_lead(user_data, message_data)

        if email_sent:
            send_message(
                chat_id,
                "Спасибо. Заявка принята. Мы свяжемся с вами.",
                reply_markup=get_main_keyboard(),
            )
        else:
            send_message(
                chat_id,
                "Спасибо. Заявка сохранена. Мы свяжемся с вами.",
                reply_markup=get_main_keyboard(),
            )

        reset_user(user_id)
        return

    reset_user(user_id)
    send_message(
        chat_id,
        'Сценарий был сброшен. Нажмите кнопку "заявка", чтобы начать заново.',
        reply_markup=get_main_keyboard(),
    )

# =========================
# HTTP
# =========================
@app.get("/")
async def healthcheck():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    message_data = extract_text_message(update)
    if not message_data:
        return {"ok": True, "ignored": True}

    try:
        process_user_message(message_data)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}") from exc

    return {"ok": True}


@app.post("/webhook/{secret}")
async def telegram_webhook_secret(secret: str, request: Request):
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=404, detail="Secret webhook route is disabled")

    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    message_data = extract_text_message(update)
    if not message_data:
        return {"ok": True, "ignored": True}

    try:
        process_user_message(message_data)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}") from exc

    return {"ok": True}
