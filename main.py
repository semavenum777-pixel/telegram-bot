import hashlib
import os

import requests
from flask import Flask, abort, request

import ai
import stickers

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip("'\"")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Telegram отправляет этот секрет в заголовке каждого запроса на вебхук,
# чтобы чужие запросы на /webhook отбрасывались.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET") or hashlib.sha256(
    BOT_TOKEN.encode()
).hexdigest()

START_TEXT = (
    "🤖 Привет! Я делаю стикеры.\n\n"
    "Что можно прислать:\n"
    "• просто картинку — сделаю из неё стикер;\n"
    "• картинку с подписью, что изменить — "
    "«сделай аниме, фон космос, надпись \"Привет\"»;\n"
    "• только текст — нарисую стикер с нуля: "
    "«кот в очках, без фона, надпись \"Йо\"».\n\n"
    "/help — подробнее"
)

HELP_TEXT = (
    "Как пользоваться:\n\n"
    "1. Отправь фото и в подписи напиши, что нужно:\n"
    "   — стиль или персонаж: аниме, мультфильм, супергерой, пиксель-арт…\n"
    "   — фон: «фон море», «без фона»\n"
    "   — надпись: надпись \"Текст\"\n\n"
    "2. Или напиши только текст — я нарисую стикер с нуля.\n\n"
    "3. Картинка без подписи станет стикером как есть.\n\n"
    "Совет: PNG с прозрачным фоном лучше отправлять файлом."
)


def telegram(method, **kwargs):
    response = requests.post(f"{TELEGRAM_API}/{method}", timeout=30, **kwargs)
    return response.json()


def send_message(chat_id, text):
    return telegram("sendMessage", json={"chat_id": chat_id, "text": text})


def delete_message(chat_id, message_id):
    telegram("deleteMessage", json={"chat_id": chat_id, "message_id": message_id})


def download_file(file_id):
    result = telegram("getFile", json={"file_id": file_id})
    file_path = result["result"]["file_path"]
    response = requests.get(f"{TELEGRAM_FILE_API}/{file_path}", timeout=30)
    response.raise_for_status()
    return response.content


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


def build_prompt(params, has_photo):
    prompt = params["edit"]
    if not has_photo:
        prompt = f"{prompt}, sticker style illustration, bold clean outlines"
    if params["remove_background"]:
        prompt = f"{prompt}, isolated on a plain pure white background"
    return prompt


def create_sticker(chat_id, text, file_id):
    photo = stickers.open_image(download_file(file_id)) if file_id else None

    # Картинка без подписи — просто делаем из неё стикер.
    if photo and not text:
        send_sticker(chat_id, stickers.make_sticker(photo))
        return

    params = ai.parse_request(text, has_photo=bool(photo))
    image = photo

    # У обычного фото фон неоднородный: сначала просим нейросеть заменить его на белый.
    if photo and params["remove_background"] and not params["edit"]:
        params["edit"] = "keep the main subject exactly as it is"

    needs_ai = bool(params["edit"]) or not photo
    if needs_ai:
        if not ai.ai_configured():
            send_message(chat_id, "😔 Нейросеть пока не подключена — могу только сделать стикер из картинки.")
            return

        if not params["edit"]:
            params["edit"] = text

        status = send_message(chat_id, "🎨 Рисую, подожди немного…")
        try:
            result = ai.generate_image(
                build_prompt(params, has_photo=bool(photo)),
                photo_png=stickers.to_png_bytes(photo, max_side=1024) if photo else None,
                photo_png_small=stickers.to_png_bytes(photo, max_side=ai.CF_INPUT_MAX_SIDE) if photo else None,
            )
        except ai.AIUnavailable:
            send_message(chat_id, "😔 Все нейросети сейчас заняты или закончился дневной лимит. Попробуй позже.")
            return
        finally:
            if status.get("ok"):
                delete_message(chat_id, status["result"]["message_id"])
        image = stickers.open_image(result)

    if params["remove_background"]:
        image = stickers.remove_plain_background(image)

    send_sticker(chat_id, stickers.make_sticker(image, params["caption"]))


def handle_message(message):
    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/start"):
        send_message(chat_id, START_TEXT)
        return

    if text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return

    file_id = get_image_file_id(message)
    if not file_id and not text:
        send_message(chat_id, "Пришли картинку или напиши, какой стикер нарисовать. /help")
        return

    try:
        create_sticker(chat_id, text, file_id)
    except Exception as error:
        print("Sticker error:", repr(error))
        send_message(chat_id, "😔 Что-то пошло не так. Попробуй ещё раз или другую картинку.")


@app.route("/", methods=["GET"])
def home():
    return "Telegram sticker bot is running!"


@app.route("/setup", methods=["GET"])
def setup():
    """Открой эту страницу один раз после запуска, чтобы подключить бота к Telegram."""
    if not BOT_TOKEN:
        return "Не задан BOT_TOKEN в настройках хостинга.", 500

    base_url = os.environ.get("WEBHOOK_URL") or f"https://{request.host}"
    result = telegram(
        "setWebhook",
        json={
            "url": f"{base_url.rstrip('/')}/webhook",
            "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ["message"],
        },
    )
    if result.get("ok"):
        return "✅ Бот подключён! Напиши ему в Telegram /start"
    if result.get("error_code") in (401, 404):
        return (
            "❌ Telegram не узнал токен. Проверь BOT_TOKEN в настройках Vercel: "
            "это должна быть строка вида 1234567890:AAH... из @BotFather. "
            "После исправления сделай Redeploy и открой /setup снова."
        ), 500
    return f"❌ Ошибка Telegram: {result.get('description')}", 500


@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)

    update = request.get_json(silent=True) or {}
    message = update.get("message")

    if message and message.get("chat"):
        handle_message(message)

    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
