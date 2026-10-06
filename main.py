import hashlib
import io
import os

import requests
from flask import Flask, abort, request
from PIL import Image

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Telegram отправляет этот секрет в заголовке каждого запроса на вебхук,
# чтобы чужие запросы на /webhook отбрасывались.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET") or hashlib.sha256(
    BOT_TOKEN.encode()
).hexdigest()

STICKER_SIZE = 512

START_TEXT = (
    "🤖 Привет! Я бот для создания Telegram-стикеров.\n\n"
    "Пришли мне картинку (фото или файлом) — "
    "и я превращу её в стикер 512×512.\n\n"
    "Совет: отправляй PNG с прозрачным фоном файлом, "
    "тогда прозрачность сохранится."
)

HELP_TEXT = (
    "Команды:\n"
    "/start — приветствие\n"
    "/help — эта справка\n\n"
    "Просто отправь изображение, и я верну его в виде стикера."
)


def telegram(method, **kwargs):
    response = requests.post(f"{TELEGRAM_API}/{method}", timeout=30, **kwargs)
    return response.json()


def send_message(chat_id, text):
    telegram("sendMessage", json={"chat_id": chat_id, "text": text})


def download_file(file_id):
    result = telegram("getFile", json={"file_id": file_id})
    file_path = result["result"]["file_path"]
    response = requests.get(f"{TELEGRAM_FILE_API}/{file_path}", timeout=30)
    response.raise_for_status()
    return response.content


def make_sticker(image_bytes):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    # Одна сторона должна быть ровно 512, другая — не больше 512.
    scale = STICKER_SIZE / max(image.size)
    new_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    image = image.resize(new_size, Image.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="WEBP")
    output.seek(0)
    return output


def send_sticker(chat_id, sticker_file):
    telegram(
        "sendSticker",
        data={"chat_id": chat_id},
        files={"sticker": ("sticker.webp", sticker_file, "image/webp")},
    )


def get_image_file_id(message):
    photos = message.get("photo")
    if photos:
        return photos[-1]["file_id"]  # самое большое разрешение

    document = message.get("document")
    if document and document.get("mime_type", "").startswith("image/"):
        return document["file_id"]

    return None


def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text.startswith("/start"):
        send_message(chat_id, START_TEXT)
        return

    if text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return

    file_id = get_image_file_id(message)
    if file_id:
        try:
            sticker = make_sticker(download_file(file_id))
        except Exception as error:
            print("Sticker error:", repr(error))
            send_message(chat_id, "😔 Не получилось обработать картинку.")
            return
        send_sticker(chat_id, sticker)
        return

    send_message(chat_id, "Пришли мне картинку, и я сделаю из неё стикер. /help")


def set_webhook():
    base_url = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")

    if not base_url:
        print("WEBHOOK_URL / RENDER_EXTERNAL_URL not set, webhook not configured")
        return

    try:
        result = telegram(
            "setWebhook",
            json={
                "url": f"{base_url.rstrip('/')}/webhook",
                "secret_token": WEBHOOK_SECRET,
                "allowed_updates": ["message"],
            },
        )
        print("Webhook:", result)
    except requests.RequestException as error:
        print("Webhook error:", repr(error))


@app.route("/", methods=["GET"])
def home():
    return "Telegram sticker bot is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)

    update = request.get_json(silent=True) or {}
    message = update.get("message")

    if message and message.get("chat"):
        handle_message(message)

    return "OK"


# Вызывается при импорте, чтобы вебхук ставился и под gunicorn
# (там блок __main__ не выполняется).
set_webhook()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
