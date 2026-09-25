import os
import requests
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=10
    )


@app.route("/", methods=["GET"])
def home():
    return "Telegram bot is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True)

    if not update:
        return "OK"

    message = update.get("message")

    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        send_message(
            chat_id,
            "🤖 Привет! Бот запущен.\n\nНапиши мне что-нибудь."
        )
    else:
        send_message(
            chat_id,
            f"Ты написал:\n{text}"
        )

    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
