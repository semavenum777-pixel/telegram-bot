import collections
import hashlib
import json
import os
import random
import time
import urllib.parse

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
    "• селфи — сделаю целый «😊 Набор эмоций» (6 стикеров сразу в твой пак) "
    "или стикер в стиле аниме, Pixar, LEGO, комикс…;\n"
    "• фото с подписью, что изменить — "
    "«сделай аниме, фон космос, надпись \"Привет\"»;\n"
    "• только текст — нарисую стикер с нуля: "
    "«кот в очках, без фона, надпись \"Йо\"».\n\n"
    "Понравился стикер — жми «➕ В мой пак», и я соберу твой личный стикерпак.\n\n"
    "/mypack — мой стикерпак, /help — подробнее"
)

HELP_TEXT = (
    "Как пользоваться:\n\n"
    "1. Отправь фото без подписи — выбери стиль кнопкой. "
    "«😊 Набор эмоций» сделает сразу 6 стикеров с разными эмоциями и сложит их в твой пак.\n\n"
    "2. Или отправь фото и в подписи напиши, что нужно:\n"
    "   — стиль или персонаж: аниме, мультфильм, супергерой, пиксель-арт…\n"
    "   — фон: «фон море», «без фона»\n"
    "   — надпись: надпись \"Текст\"\n\n"
    "3. Или напиши только текст — я нарисую стикер с нуля. "
    "Нет идей — нажми «🎲 Удиви меня» в /start.\n\n"
    "Под каждым стикером есть кнопки:\n"
    "🔄 Ещё вариант — перерисовать по тому же запросу;\n"
    "✍️ Надпись — ответь на стикер текстом, и я допишу его на стикер;\n"
    "➕ В мой пак — добавить в твой личный стикерпак.\n\n"
    "Можно прислать и готовый стикер — переделаю его в другом стиле.\n"
    "/mypack — ссылка на твой стикерпак."
) + (f"\n\nВ день можно сделать до {limits.DAILY_LIMIT} стикеров через нейросеть." if limits.enabled() else "")

# Готовые стили для кнопок: ключ → (подпись на кнопке, задание для нейросети).
STYLES = {
    "anime": ("🎌 Аниме", "turn the main subject (person, pet or object) into an anime character, Japanese anime style, cel shading, keep it recognizable"),
    "pixar": ("🧸 Pixar", "turn the main subject (person, pet or object) into a cute 3D Pixar-style cartoon character, soft lighting, keep it recognizable"),
    "comic": ("💥 Комикс", "comic book style illustration of the main subject, bold ink outlines, vivid colors, halftone shading"),
    "pixel": ("👾 Пиксель-арт", "turn the main subject (person, pet or object) into a pixel art character, 16-bit retro video game style"),
    "hero": ("🦸 Супергерой", "turn the main subject (person, pet or object) into a superhero in a colorful costume with a cape, comic style, keep it recognizable"),
    "chibi": ("🍡 Чиби", "turn the main subject (person, pet or object) into a cute chibi character with a big head and small body, kawaii style"),
    "cyber": ("🌆 Киберпанк", "turn the main subject (person, pet or object) into a cyberpunk character, neon glow, futuristic outfit, keep it recognizable"),
    "lego": ("🧱 LEGO", "turn the main subject (person, pet or object) into a plastic toy brick minifigure, glossy plastic, keep it recognizable"),
    "plush": ("🐻 Плюшевый", "turn the main subject (person, pet or object) into a soft cute plush toy, fluffy fabric texture, keep it recognizable"),
    "vangogh": ("🌻 Ван Гог", "portrait of the main subject painted in the style of Vincent van Gogh, thick swirling brush strokes, keep it recognizable"),
    "zombie": ("🧟 Зомби", "turn the main subject (person, pet or object) into a funny cartoon zombie, green skin, not scary, keep it recognizable"),
    "cartoon": ("✏️ Мультик", "turn the main subject (person, pet or object) into a flat 2D cartoon character, simple shapes, bright colors, keep it recognizable"),
}

PLAIN = "plain"
RANDOM = "random"

# Набор эмоций: ключ, эмодзи для пака, надпись, описание для нейросети.
EMOTIONS = [
    ("happy", "😊", "Ура!", "very happy with a big joyful smile"),
    ("sad", "😢", "Грущу", "sad with teary eyes"),
    ("angry", "😡", "Злюсь", "angry and furious, frowning"),
    ("love", "😍", "Люблю", "in love, with heart-shaped eyes and little hearts around"),
    ("laugh", "😂", "Ахаха", "laughing hard with tears of joy"),
    ("wow", "😮", "Ого!", "surprised and shocked with an open mouth"),
]
EMOTION_STYLE = (
    "Image 1 is a photo of the subject. Draw this exact same subject as a cute cartoon sticker "
    "character that looks {mood}. Preserve the identity: same face shape, hairstyle, hair color, "
    "eye color, skin tone, glasses, facial hair and clothes. Change only the facial expression and pose. "
    "Expressive face, isolated on a plain pure white background."
)
# Добавляется, когда первый стикер уже готов: остальные рисуются по нему как по образцу.
EMOTION_REFERENCE = (
    " Image 2 is the already drawn sticker of this same character: keep exactly the same character "
    "design, face, art style and colors as in image 2."
)

# Быстрые надписи под стикером (без эмодзи — их нет в шрифте).
QUICK_CAPTIONS = ["Ок", "Спасибо", "Ахах", "Люблю"]

# Идеи для кнопки «Удиви меня»: (как показать пользователю, задание для нейросети).
SURPRISES = [
    ("кот-астронавт", "a cute cat astronaut floating in space"),
    ("капибара с мандарином в джакузи", "a relaxed capybara in a hot tub with a tangerine on its head"),
    ("корги-супергерой", "a corgi superhero with a red cape flying"),
    ("енот ест пиццу", "a happy raccoon eating a huge slice of pizza"),
    ("пингвин-диджей", "a penguin DJ with headphones at a turntable"),
    ("ленивец с кофе", "a sleepy sloth holding a big cup of coffee"),
    ("хомяк-рокер", "a hamster rock star playing an electric guitar"),
    ("панда-самурай", "a panda samurai with a katana, heroic pose"),
    ("утка на пляже", "a cool duck in sunglasses relaxing on a beach"),
    ("дракончик пьёт чай", "a tiny cute dragon drinking tea from a cup"),
    ("лиса в пижаме", "a sleepy fox in pajamas yawning"),
    ("сова-профессор", "a wise owl professor with glasses and a book"),
]

_bot_username = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")

BOT_DESCRIPTION = (
    "Делаю стикеры из твоих фото с помощью нейросетей: аниме, Pixar, комикс, "
    "пиксель-арт и другие стили, надписи, фон. Собираю твой личный стикерпак. Бесплатно."
)
BOT_SHORT_DESCRIPTION = "Стикеры из фото: аниме, Pixar, комикс и другие стили. Бесплатно."
BOT_COMMANDS = [
    {"command": "start", "description": "Начать"},
    {"command": "mypack", "description": "Мой стикерпак"},
    {"command": "help", "description": "Как пользоваться"},
]


def plural_stickers(n):
    if n % 10 == 1 and n % 100 != 11:
        word = "стикер"
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = "стикера"
    else:
        word = "стикеров"
    return f"{n} {word}"


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
    return telegram(
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

    sticker = message.get("sticker")
    if sticker and not sticker.get("is_animated") and not sticker.get("is_video"):
        return sticker["file_id"]

    return None


def message_text(message):
    return (message.get("text") or message.get("caption") or "").strip()


def style_keyboard():
    buttons = [
        {"text": label, "callback_data": f"style:{key}"}
        for key, (label, _) in STYLES.items()
    ]
    rows = [[{"text": "😊 Набор эмоций — 6 стикеров в пак", "callback_data": "emo"}]]
    rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([
        {"text": "🎲 Случайный стиль", "callback_data": f"style:{RANDOM}"},
        {"text": "🖼 Просто стикер", "callback_data": f"style:{PLAIN}"},
    ])
    return rows


def result_keyboard(again_data=None):
    first_row = []
    if again_data:
        first_row.append({"text": "🔄 Ещё вариант", "callback_data": again_data})
    first_row.append({"text": "✍️ Надпись", "callback_data": "caption"})
    return [first_row, quick_caption_row(), [{"text": "➕ В мой пак", "callback_data": "pack"}]]


def quick_caption_row():
    return [{"text": text, "callback_data": f"cap:{i}"} for i, text in enumerate(QUICK_CAPTIONS)]


def share_keyboard(name):
    text = f"Смотри мои стикеры! Сделал в @{bot_username()}"
    url = "https://t.me/share/url?" + urllib.parse.urlencode(
        {"url": f"https://t.me/addstickers/{name}", "text": text}
    )
    return [[{"text": "📤 Поделиться паком", "url": url}]]


# Добавляется ко всем заданиям с фото, чтобы результат был похож на человека на снимке.
IDENTITY = (
    "The result must clearly look like the same person (or pet) from the photo: keep the exact "
    "face shape, facial features, eyes, nose, mouth, skin tone, hairstyle, hair color, glasses "
    "and facial hair. Change only what was asked."
)


def build_prompt(params, has_photo):
    prompt = params["edit"]
    if has_photo:
        prompt = f"{prompt}. {IDENTITY}"
    else:
        prompt = f"{prompt}, sticker style illustration, bold clean outlines"
    if params["remove_background"]:
        prompt = f"{prompt}, isolated on a plain pure white background"
    return prompt


def render(chat_id, user_id, origin, style=None, seed=None, params=None, again_data=None):
    """Делает стикер по сообщению пользователя origin и отправляет его ответом на это сообщение."""
    text = message_text(origin)
    file_id = get_image_file_id(origin)
    photo = stickers.open_image(download_file(file_id)) if file_id else None
    reply_to = origin["message_id"]

    if style == PLAIN or (photo and not text and not style):
        send_sticker(chat_id, stickers.make_sticker(photo, outline=True), reply_to, result_keyboard())
        return

    if params:
        pass
    elif style:
        params = {"edit": STYLES[style][1], "caption": "", "remove_background": True}
    else:
        params = ai.parse_request(text, has_photo=bool(photo))
        # У обычного фото фон неоднородный: сначала просим нейросеть заменить его на белый.
        if photo and params["remove_background"] and not params["edit"]:
            params["edit"] = "keep the main subject exactly as it is"

    image = photo
    if params["edit"] or not photo:
        if not ai.ai_configured(has_photo=bool(photo)):
            send_message(chat_id, "😔 Нейросеть пока не подключена — могу только сделать стикер из картинки.")
            return

        if not limits.take(user_id):
            send_message(
                chat_id,
                f"⏳ Лимит на сегодня исчерпан: можно {plural_stickers(limits.DAILY_LIMIT)} в день. Приходи завтра!",
            )
            return

        if not params["edit"]:
            params["edit"] = text

        telegram("sendChatAction", json={"chat_id": chat_id, "action": "choose_sticker"})
        status = send_message(chat_id, "🎨 Рисую, подожди немного…")
        # Обрезаем вокруг центра: лицо крупнее — нейросеть лучше сохраняет сходство.
        source = stickers.crop_square(photo) if photo else None
        try:
            result = ai.generate_image(
                build_prompt(params, has_photo=bool(photo)),
                photo_png=stickers.to_png_bytes(source, max_side=1024) if photo else None,
                photo_png_small=stickers.to_png_bytes(source, max_side=ai.CF_INPUT_MAX_SIDE) if photo else None,
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

    again = again_data or (f"again:{style}" if style else "again")
    send_sticker(
        chat_id,
        stickers.make_sticker(image, params["caption"], outline=params["remove_background"]),
        reply_to,
        result_keyboard(again),
    )


def bot_username():
    global _bot_username
    if not _bot_username:
        _bot_username = telegram("getMe")["result"]["username"]
    return _bot_username


def put_in_pack(user, sticker_file_id, emoji="😀"):
    """Добавляет стикер в личный пак пользователя, при первом разе создаёт пак.
    Возвращает ответ Telegram."""
    name = pack_name(user["id"])
    sticker = {"sticker": sticker_file_id, "format": "static", "emoji_list": [emoji]}

    result = telegram("addStickerToSet", json={"user_id": user["id"], "name": name, "sticker": sticker})
    if not result.get("ok") and "STICKERSET_INVALID" in (result.get("description") or ""):
        # В названии пака — ссылка на бота: кто получит стикер, сможет найти бота.
        title = f"{user.get('first_name', 'Мои')} стикеры · @{bot_username()}"[:64]
        result = telegram(
            "createNewStickerSet",
            json={"user_id": user["id"], "name": name, "title": title, "stickers": [sticker]},
        )
    if not result.get("ok"):
        print("Pack error:", result)
    return result


def add_to_pack(chat_id, user, sticker_file_id, reply_to=None):
    result = put_in_pack(user, sticker_file_id)
    name = pack_name(user["id"])
    if result.get("ok"):
        send_message(
            chat_id,
            f"✅ Добавил в твой пак: https://t.me/addstickers/{name}",
            reply_to=reply_to,
            keyboard=share_keyboard(name),
        )
    elif "TOO_MUCH" in (result.get("description") or ""):
        send_message(chat_id, "😔 В паке уже максимум стикеров (120).", reply_to=reply_to)
    else:
        send_message(chat_id, "😔 Не получилось добавить стикер в пак. Попробуй ещё раз.", reply_to=reply_to)


def make_emotion_pack(chat_id, user, origin):
    """Делает из одного фото 6 стикеров с разными эмоциями и складывает их в пак."""
    file_id = get_image_file_id(origin)
    if not file_id:
        send_message(chat_id, "Для набора эмоций нужно фото.")
        return
    if not ai.ai_configured(has_photo=True):
        send_message(chat_id, "😔 Нейросеть пока не подключена.")
        return

    # Квадрат по центру: лицо занимает больше кадра, и нейросеть лучше его сохраняет.
    photo = stickers.crop_square(stickers.open_image(download_file(file_id)))
    photo_large = stickers.to_png_bytes(photo, max_side=1024)
    photo_small = stickers.to_png_bytes(photo, max_side=ai.CF_INPUT_MAX_SIDE)
    status = send_message(chat_id, "😊 Делаю набор из 6 эмоций — это займёт около минуты…")
    started = time.monotonic()
    done = 0
    # Одинаковый seed и первый стикер как образец — чтобы все 6 были одним персонажем.
    seed = random.randint(0, 2**31 - 1)
    reference = None

    for _, emoji, caption, mood in EMOTIONS:
        if time.monotonic() - started > 200:
            break
        if not limits.take(user["id"]):
            send_message(chat_id, f"⏳ Дневной лимит закончился ({plural_stickers(limits.DAILY_LIMIT)} в день). Остальное — завтра!")
            break
        telegram("sendChatAction", json={"chat_id": chat_id, "action": "choose_sticker"})
        try:
            prompt = EMOTION_STYLE.format(mood=mood) + (EMOTION_REFERENCE if reference else "")
            result = ai.generate_image(
                prompt,
                photo_png=photo_large,
                photo_png_small=photo_small,
                seed=seed,
                ref_png=reference and stickers.to_png_bytes(reference, max_side=1024),
                ref_png_small=reference and stickers.to_png_bytes(reference, max_side=ai.CF_INPUT_MAX_SIDE),
            )
        except ai.AIUnavailable:
            send_message(chat_id, "😔 Нейросети сейчас заняты — доделаю в другой раз.")
            break
        generated = stickers.open_image(result)
        if reference is None:
            reference = generated
        image = stickers.remove_plain_background(generated)
        sent = send_sticker(
            chat_id,
            stickers.make_sticker(image, caption, outline=True),
            origin["message_id"],
            [[{"text": "✍️ Надпись", "callback_data": "caption"}]],
        )
        if sent.get("ok"):
            put_in_pack(user, sent["result"]["sticker"]["file_id"], emoji)
            done += 1

    if status.get("ok"):
        delete_message(chat_id, status["result"]["message_id"])
    if done:
        name = pack_name(user["id"])
        send_message(
            chat_id,
            f"🎉 Готово! {plural_stickers(done)} уже в твоём паке: https://t.me/addstickers/{name}",
            keyboard=share_keyboard(name),
        )


def surprise(chat_id, user_id, message):
    idea, prompt = random.choice(SURPRISES)
    send_message(chat_id, f"🎲 Рисую: {idea}")
    render(
        chat_id,
        user_id,
        {"message_id": message["message_id"]},  # рисуем с нуля, без исходной картинки
        params={"edit": prompt, "caption": "", "remove_background": True},
        again_data="surprise",
    )


def pack_name(user_id):
    return f"pack{user_id}_by_{bot_username()}"


def send_my_pack(chat_id, user_id):
    name = pack_name(user_id)
    result = telegram("getStickerSet", json={"name": name})
    if result.get("ok"):
        count = len(result.get("result", {}).get("stickers", []))
        send_message(
            chat_id,
            f"📦 В твоём паке {plural_stickers(count)}: https://t.me/addstickers/{name}",
            keyboard=share_keyboard(name),
        )
    else:
        send_message(chat_id, "📦 Пак пока пуст. Нажми «➕ В мой пак» под любым стикером — и я его создам.")


def is_our_sticker(message):
    author = message.get("from") or {}
    return bool(message.get("sticker")) and author.get("is_bot") and author.get("username") == bot_username()


def caption_sticker(chat_id, sticker_message, caption):
    """Дописывает текст на уже готовый стикер бота."""
    image = stickers.open_image(download_file(sticker_message["sticker"]["file_id"]))
    send_sticker(
        chat_id,
        stickers.make_sticker(image, caption),
        sticker_message["message_id"],
        [[{"text": "✍️ Надпись", "callback_data": "caption"}], [{"text": "➕ В мой пак", "callback_data": "pack"}]],
    )


def handle_callback(query):
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    user = query["from"]

    if data == "caption":
        telegram(
            "answerCallbackQuery",
            json={
                "callback_query_id": query["id"],
                "text": "Ответь на этот стикер текстом (свайп влево по стикеру → напиши надпись), и я допишу её.",
                "show_alert": True,
            },
        )
        return

    telegram("answerCallbackQuery", json={"callback_query_id": query["id"]})
    if not chat_id:
        return

    if data == "pack":
        sticker = message.get("sticker")
        if not sticker:
            return
        add_to_pack(chat_id, user, sticker["file_id"], reply_to=message["message_id"])
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

    if data.startswith("cap:"):
        index = data.partition(":")[2]
        if message.get("sticker") and index.isdigit() and int(index) < len(QUICK_CAPTIONS):
            caption_sticker(chat_id, message, QUICK_CAPTIONS[int(index)])
        return

    if data == "surprise":
        surprise(chat_id, user["id"], message)
        return

    origin = message.get("reply_to_message")
    if not origin:
        send_message(chat_id, "Не нашёл исходное сообщение — пришли фото или запрос заново.")
        return

    if data == "emo":
        make_emotion_pack(chat_id, user, origin)
        return

    action, _, style = data.partition(":")
    if style == RANDOM:
        style = random.choice(list(STYLES))
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
        send_message(
            chat_id,
            START_TEXT,
            keyboard=[[{"text": "🎲 Удиви меня — нарисуй что-нибудь", "callback_data": "surprise"}]],
        )
        return

    if text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return

    if text.startswith("/mypack"):
        send_my_pack(chat_id, message["from"]["id"])
        return

    replied = message.get("reply_to_message") or {}
    if text and is_our_sticker(replied):
        caption_sticker(chat_id, replied, text)
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
_recent_updates = collections.OrderedDict()


def is_duplicate(update_id):
    """Telegram повторно присылает событие, если бот долго рисует. Второй раз не обрабатываем."""
    if update_id is None:
        return False
    if update_id in _recent_updates:
        return True
    _recent_updates[update_id] = True
    while len(_recent_updates) > 1000:
        _recent_updates.popitem(last=False)
    return not limits.first_time(f"update:{update_id}")


def ensure_bot_profile():
    """Описание бота, которое видно до нажатия «Старт», и меню команд."""
    current = telegram("getMyCommands").get("result") or []
    if [c.get("command") for c in current] == [c["command"] for c in BOT_COMMANDS]:
        return
    telegram("setMyCommands", json={"commands": BOT_COMMANDS})
    telegram("setMyDescription", json={"description": BOT_DESCRIPTION})
    telegram("setMyShortDescription", json={"short_description": BOT_SHORT_DESCRIPTION})


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
        ensure_bot_profile()
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
    if is_duplicate(update.get("update_id")):
        return "OK"
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
