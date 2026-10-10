import hashlib
import json
import os
import random

import requests
from flask import Flask, abort, request

import ai
import limits
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
    "• фото — предложу стили: аниме, Pixar, комикс, пиксель-арт…;\n"
    "• фото с подписью, что изменить — "
    "«сделай аниме, фон космос, надпись \"Привет\"»;\n"
    "• только текст — нарисую стикер с нуля: "
    "«кот в очках, без фона, надпись \"Йо\"».\n\n"
    "Понравился стикер — жми «➕ В мой пак», и я соберу твой личный стикерпак.\n\n"
    "/help — подробнее"
)

HELP_TEXT = (
    "Как пользоваться:\n\n"
    "1. Отправь фото без подписи — выбери стиль кнопкой.\n\n"
    "2. Или отправь фото и в подписи напиши, что нужно:\n"
    "   — стиль или персонаж: аниме, мультфильм, супергерой, пиксель-арт…\n"
    "   — фон: «фон море», «без фона»\n"
    "   — надпись: надпись \"Текст\"\n\n"
    "3. Или напиши только текст — я нарисую стикер с нуля.\n\n"
    "Под каждым стикером есть кнопки:\n"
    "🔄 Ещё вариант — перерисовать по тому же запросу;\n"
    "➕ В мой пак — добавить в твой личный стикерпак."
) + (f"\n\nВ день можно сделать до {limits.DAILY_LIMIT} стикеров через нейросеть." if limits.enabled() else "")

# Готовые стили для кнопок: ключ → (подпись на кнопке, задание для нейросети).
STYLES = {
    "anime": ("🎌 Аниме", "turn the person into an anime character, Japanese anime style, cel shading, keep the face recognizable"),
    "pixar": ("🧸 Pixar", "turn the person into a cute 3D Pixar-style cartoon character, soft lighting, keep the face recognizable"),
    "comic": ("💥 Комикс", "comic book style illustration of the person, bold ink outlines, vivid colors, halftone shading"),
    "pixel": ("👾 Пиксель-арт", "turn the person into a pixel art character, 16-bit retro video game style"),
    "hero": ("🦸 Супергерой", "turn the person into a superhero in a colorful costume with a cape, comic style, keep the face recognizable"),
    "chibi": ("🍡 Чиби", "turn the person into a cute chibi character with a big head and small body, kawaii style"),
    "cyber": ("🌆 Киберпанк", "turn the person into a cyberpunk character, neon glow, futuristic outfit, keep the face recognizable"),
    "cartoon": ("✏️ Мультик", "turn the person into a flat 2D cartoon character, simple shapes, bright colors, keep the face recognizable"),
}

PLAIN = "plain"

_bot_username = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")


def telegram(method, **kwargs):
    response = requests.post(f"{TELEGRAM_API}/{method}", timeout=30, **kwargs)
    return response.json()


def send_message(chat_id, text, reply_to=None, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return telegram("sendMessage", json=payload)


def delete_message(chat_id, message_id):
    telegram("deleteMessage", json={"chat_id": chat_id, "message_id": message_id})


def download_file(file_id):
    result = telegram("getFile", json={"file_id": file_id})
    file_path = result["result"]["file_path"]
    response = requests.get(f"{TELEGRAM_FILE_API}/{file_path}", timeout=30)
    response.raise_for_status()
    return response.content


def send_sticker(chat_id, sticker_file, reply_to=None, keyboard=None):
    data = {"chat_id": chat_id}
    if reply_to:
        data["reply_parameters"] = json.dumps(
            {"message_id": reply_to, "allow_sending_without_reply": True}
        )
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    telegram(
        "sendSticker",
        data=data,
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


def message_text(message):
    return (message.get("text") or message.get("caption") or "").strip()


def style_keyboard():
    buttons = [
        {"text": label, "callback_data": f"style:{key}"}
        for key, (label, _) in STYLES.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([{"text": "🖼 Просто стикер", "callback_data": f"style:{PLAIN}"}])
    return rows


def result_keyboard(again_data=None):
    row = []
    if again_data:
        row.append({"text": "🔄 Ещё вариант", "callback_data": again_data})
    row.append({"text": "➕ В мой пак", "callback_data": "pack"})
    return [row]


def build_prompt(params, has_photo):
    prompt = params["edit"]
    if not has_photo:
        prompt = f"{prompt}, sticker style illustration, bold clean outlines"
    if params["remove_background"]:
        prompt = f"{prompt}, isolated on a plain pure white background"
    return prompt


def render(chat_id, user_id, origin, style=None, seed=None):
    """Делает стикер по сообщению пользователя origin и отправляет его ответом на это сообщение."""
    text = message_text(origin)
    file_id = get_image_file_id(origin)
    photo = stickers.open_image(download_file(file_id)) if file_id else None
    reply_to = origin["message_id"]

    if style == PLAIN or (photo and not text and not style):
        send_sticker(chat_id, stickers.make_sticker(photo), reply_to, result_keyboard())
        return

    if style:
        params = {"edit": STYLES[style][1], "caption": "", "remove_background": True}
    else:
        params = ai.parse_request(text, has_photo=bool(photo))
        # У обычного фото фон неоднородный: сначала просим нейросеть заменить его на белый.
        if photo and params["remove_background"] and not params["edit"]:
            params["edit"] = "keep the main subject exactly as it is"

    image = photo
    if params["edit"] or not photo:
        if not ai.ai_configured():
            send_message(chat_id, "😔 Нейросеть пока не подключена — могу только сделать стикер из картинки.")
            return

        if not limits.take(user_id):
            send_message(
                chat_id,
                f"⏳ Лимит на сегодня исчерпан: можно {limits.DAILY_LIMIT} стикеров в день. Приходи завтра!",
            )
            return

        if not params["edit"]:
            params["edit"] = text

        status = send_message(chat_id, "🎨 Рисую, подожди немного…")
        try:
            result = ai.generate_image(
                build_prompt(params, has_photo=bool(photo)),
                photo_png=stickers.to_png_bytes(photo, max_side=1024) if photo else None,
                photo_png_small=stickers.to_png_bytes(photo, max_side=ai.CF_INPUT_MAX_SIDE) if photo else None,
                seed=seed,
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

    again = f"again:{style}" if style else "again"
    send_sticker(
        chat_id,
        stickers.make_sticker(image, params["caption"]),
        reply_to,
        result_keyboard(again),
    )


def bot_username():
    global _bot_username
    if not _bot_username:
        _bot_username = telegram("getMe")["result"]["username"]
    return _bot_username


def add_to_pack(user, sticker_file_id):
    """Добавляет стикер в личный пак пользователя, при первом разе создаёт пак."""
    name = f"pack{user['id']}_by_{bot_username()}"
    sticker = {"sticker": sticker_file_id, "format": "static", "emoji_list": ["😀"]}

    result = telegram("addStickerToSet", json={"user_id": user["id"], "name": name, "sticker": sticker})
    if not result.get("ok") and "STICKERSET_INVALID" in (result.get("description") or ""):
        title = f"Стикеры {user.get('first_name', '')}".strip()[:64]
        result = telegram(
            "createNewStickerSet",
            json={"user_id": user["id"], "name": name, "title": title, "stickers": [sticker]},
        )

    if result.get("ok"):
        return f"✅ Добавил в твой пак: https://t.me/addstickers/{name}"

    print("Pack error:", result)
    if "TOO_MUCH" in (result.get("description") or ""):
        return "😔 В паке уже максимум стикеров (120)."
    return "😔 Не получилось добавить стикер в пак. Попробуй ещё раз."


def handle_callback(query):
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    user = query["from"]

    telegram("answerCallbackQuery", json={"callback_query_id": query["id"]})
    if not chat_id:
        return

    if data == "pack":
        sticker = message.get("sticker")
        if not sticker:
            return
        send_message(chat_id, add_to_pack(user, sticker["file_id"]), reply_to=message["message_id"])
        # Убираем кнопку «В мой пак», чтобы не добавить стикер дважды.
        keyboard = [
            [button for button in row if button["callback_data"] != "pack"]
            for row in message.get("reply_markup", {}).get("inline_keyboard", [])
        ]
        telegram(
            "editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message["message_id"],
                "reply_markup": {"inline_keyboard": [row for row in keyboard if row]},
            },
        )
        return

    origin = message.get("reply_to_message")
    if not origin:
        send_message(chat_id, "Не нашёл исходное сообщение — пришли фото или запрос заново.")
        return

    action, _, style = data.partition(":")
    if style and style != PLAIN and style not in STYLES:
        return

    if action == "style":
        render(chat_id, user["id"], origin, style=style)
    elif action == "again":
        render(chat_id, user["id"], origin, style=style or None, seed=random.randint(0, 2**31 - 1))


def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message_text(message)

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

    if file_id and not text:
        send_message(
            chat_id,
            "Выбери стиль 👇",
            reply_to=message["message_id"],
            keyboard=style_keyboard(),
        )
        return

    render(chat_id, message["from"]["id"], message)


def safely(handler, update_part, chat_id):
    try:
        handler(update_part)
    except Exception as error:
        print("Sticker error:", repr(error))
        if chat_id:
            send_message(chat_id, "😔 Что-то пошло не так. Попробуй ещё раз или другую картинку.")


ALLOWED_UPDATES = ["message", "callback_query"]
_webhook_checked = False


def register_webhook():
    base_url = os.environ.get("WEBHOOK_URL") or f"https://{request.host}"
    return telegram(
        "setWebhook",
        json={
            "url": f"{base_url.rstrip('/')}/webhook",
            "secret_token": WEBHOOK_SECRET,
            "allowed_updates": ALLOWED_UPDATES,
        },
    )


def ensure_webhook_up_to_date():
    """После обновлений бота сама включает новые типы событий (например, нажатия кнопок),
    чтобы не нужно было заново открывать /setup."""
    global _webhook_checked
    if _webhook_checked:
        return
    _webhook_checked = True
    try:
        info = telegram("getWebhookInfo").get("result", {})
        if set(ALLOWED_UPDATES) - set(info.get("allowed_updates") or ALLOWED_UPDATES):
            print("Webhook update:", register_webhook())
    except Exception as error:
        print("Webhook check error:", repr(error))


@app.route("/", methods=["GET"])
def home():
    return "Telegram sticker bot is running!"


@app.route("/setup", methods=["GET"])
def setup():
    """Открой эту страницу один раз после запуска, чтобы подключить бота к Telegram."""
    if not BOT_TOKEN:
        return "Не задан BOT_TOKEN в настройках хостинга.", 500

    result = register_webhook()
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

    ensure_webhook_up_to_date()

    update = request.get_json(silent=True) or {}
    message = update.get("message")
    query = update.get("callback_query")

    if message and message.get("chat") and message.get("from"):
        safely(handle_message, message, message["chat"]["id"])
    elif query:
        chat_id = (query.get("message") or {}).get("chat", {}).get("id")
        safely(handle_callback, query, chat_id)

    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
