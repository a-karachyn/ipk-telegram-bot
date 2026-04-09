from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

TOKEN = os.getenv("TELEGRAM_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

@app.post("/")
async def webhook(request: Request):
    data = await request.json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.lower() == "заявка":
            msg = "Оставьте заявку.\nНапишите услугу:\n1. СТУ\n2. Пожарные риски\n3. СПА\n4. КСОБ"
        else:
            msg = "Напишите 'заявка' чтобы оставить запрос."

        requests.post(URL, json={
            "chat_id": chat_id,
            "text": msg
        })

    return {"ok": True}
