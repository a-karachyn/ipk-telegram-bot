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
        text = data["message"].get("text", "").lower()

        if text == "заявка":
            msg = (
                "Оставьте заявку.\n\n"
                "Напишите услугу:\n"
                "1. Разработка СТУ\n"
                "2. Расчет пожарных рисков\n"
                "3. Проектирование СПС, СОУЭ, Пожаротушение\n"
                "4. Проектирование систем КСОБ"
            )
        else:
            msg = "Напишите 'заявка' чтобы оставить запрос."

        requests.post(
            URL,
            json={
                "chat_id": chat_id,
                "text": msg
            }
        )

    return {"ok": True}
