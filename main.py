import collections
import datetime
import hashlib
import json
import os
import random
import time
import urllib.parse

import requests
from flask import Flask, abort, request

import ai
import animate
import limits
import pages
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
    "👋 Привет! Я превращаю твои фото в стикеры, аватарки, фотосессии и GIF с помощью нейросетей.\n\n"
    "📸 <b>Пришли селфи</b> — и выбери кнопкой:\n"
    "• 😊 набор из 6 стикеров с твоими эмоциями прямо в твой стикерпак;\n"
    "• 🎌 аниме, 🧸 Pixar, 🧱 LEGO и ещё десяток стилей;\n"
    "• 📸 фотосессию в Париже или на пляже, ✨ живые стикеры и 🎞 GIF.\n\n"
    "✍️ Или напиши, что нарисовать: «кот в очках, надпись \"Йо\"».\n"
    "😂 Мем: фото с подписью /mem верх | низ."
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
    "Можно прислать и готовый стикер — переделаю его в другом стиле.\n\n"
    "📸 Фотосессия — реалистичное фото с твоим лицом: пляж, Париж, деловой портрет… "
    "Или фото с подписью /photo что сделать.\n"
    "🖼 Аватарка — кнопка под фото: картинка для профиля в выбранном стиле.\n"
    "😂 Мем — пришли фото с подписью /mem Верх | Низ (работает и с гифками).\n"
    "✨ Оживить — под стикером: сделаю живой стикер, а кнопкой 🎞 GIF — гифку.\n"
    "🎞 Пришли гифку — сделаю из неё живой стикер для пака.\n"
    "👥 В группе — добавь меня в чат и ответь на фото командой /sticker (или /sticker аниме).\n"
    "/mypack — ссылка на твой стикерпак.\n"
    "/invite — пригласи друзей и получай больше генераций."
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

# Новогодние стили: показываются в кнопках с 1 ноября по 14 января.
NEW_YEAR_STYLES = {
    "santa": ("🎅 Дед Мороз", "turn the main subject into Ded Moroz (Russian Father Frost) with a red fur coat, white beard and festive hat, cute cartoon style, keep it recognizable"),
    "snow": ("❄️ Снегурочка", "turn the main subject into a winter fairy-tale character in a light blue fur coat with snowflakes, cute cartoon style, keep it recognizable"),
    "sweater": ("🦌 Свитер с оленями", "the main subject wearing a cozy knitted Christmas sweater with deer, holding a cup of hot cocoa, cute cartoon style, keep it recognizable"),
    "elf": ("🧝 Эльф", "turn the main subject into a cheerful Christmas elf in a green outfit with pointy ears, cute cartoon style, keep it recognizable"),
}
ALL_STYLES = {**STYLES, **NEW_YEAR_STYLES}

PLAIN = "plain"
NO_AGAIN = "-"
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

NEW_YEAR_EMOTIONS = [
    ("ny", "🎄", "С Новым годом!", "joyful, wearing a Santa hat, celebrating with confetti"),
    ("gift", "🎁", "Подарки!", "excited, holding a big wrapped gift box"),
    ("cheers", "🥂", "Ура!", "cheering and raising a glass of sparkling juice, fireworks"),
    ("mandarin", "🍊", "Мандаринки", "happily eating tangerines"),
    ("tired", "😴", "1 января", "sleepy and tired, wrapped in a blanket on January 1st"),
    ("wish", "🌟", "Загадал", "making a wish with eyes closed, sparkles around"),
]
EMOTION_SETS = {
    "emo": ("😊 Делаю набор из 6 эмоций", EMOTIONS),
    "emony": ("🎄 Делаю новогодний набор из 6 стикеров", NEW_YEAR_EMOTIONS),
}

AVATAR_SUFFIX = (
    "Square profile picture: head and shoulders portrait centered, vibrant colorful background."
)
CARD_PROMPT = (
    "Festive New Year greeting card illustration of the main subject: cozy winter scene with a decorated "
    "Christmas tree, garlands, snow and gifts, warm magical lighting, cute cartoon style, keep it recognizable. "
    "Leave the bottom quarter of the image calm for a greeting text."
)


def new_year_season():
    mode = os.environ.get("NEW_YEAR_MODE", "auto").strip().lower()
    if mode in ("on", "1", "true", "yes"):
        return True
    if mode in ("off", "0", "false", "no"):
        return False
    today = datetime.date.today()
    return today.month in (11, 12) or (today.month == 1 and today.day <= 14)


def new_year_greeting():
    today = datetime.date.today()
    year = today.year + 1 if today.month >= 11 else today.year
    return f"С Новым {year} годом!"


# Живое видео из фото: ключ → (кнопка, что должно происходить в видео).
VIDEO_MOTIONS = {
    "alive": ("✨ Ожить", "the person comes alive: natural blinking, a gentle smile, slight head movement, breathing"),
    "smile": ("😊 Улыбка", "the person slowly breaks into a warm genuine smile and looks at the camera"),
    "wave": ("👋 Привет", "the person smiles and waves hello at the camera with one hand"),
    "wink": ("😉 Подмигнуть", "the person playfully winks at the camera and smiles"),
    "laugh": ("😂 Смех", "the person bursts out laughing joyfully"),
    "dance": ("💃 Танец", "the person dances happily to music, moving shoulders and head"),
    "kiss": ("😘 Воздушный поцелуй", "the person sends an air kiss to the camera"),
    "wow": ("😮 Удивление", "the person looks surprised with wide eyes and an open mouth, then smiles"),
}
VIDEO_STYLE = (
    "{motion}. Realistic, the same person with exactly the same face, hair and clothes as in the photo, "
    "smooth natural motion, static camera."
)


# Фотосессии: реалистичные фото с тем же лицом (как Nano Banana). Ключ → (кнопка, сцена).
PHOTO_SCENES = {
    "beach": ("🏖 На пляже", "the person relaxing on a beautiful tropical beach at sunset, summer outfit"),
    "paris": ("🗼 В Париже", "the person standing in Paris with the Eiffel Tower in the background, stylish outfit"),
    "business": ("💼 Деловой портрет", "a professional business headshot of the person in a sharp suit, studio lighting, neutral background"),
    "fashion": ("👗 Модная фотосессия", "a high-fashion magazine photoshoot of the person, designer outfit, dramatic studio light"),
    "retro": ("🎩 Ретро 1920-х", "the person as a 1920s style portrait, vintage clothes and hairstyle, sepia film photo"),
    "car": ("🏎 Со спорткаром", "the person posing next to a luxury sports car on a city street at night"),
    "space": ("🚀 Космонавт", "the person as an astronaut in a spacesuit on a space station with Earth in the window"),
    "winter": ("❄️ Зимняя сказка", "the person in a cozy winter outfit in a snowy forest with soft falling snow"),
    "newyear": ("🎄 Новогодняя фотосессия", "the person in a festive New Year photoshoot next to a decorated Christmas tree with lights and gifts"),
    "superhero": ("🦸 Супергерой в кино", "the person as a movie superhero in a cinematic action scene"),
}
PHOTO_STYLE = (
    "Photorealistic photo edit: {scene}. Keep the person's face and identity exactly the same as in the photo: "
    "same facial features, eyes, nose, mouth, skin tone, hairstyle and hair color. "
    "High quality, natural lighting, realistic skin, sharp focus."
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
    "🎨 Нейросеть для твоих фото — бесплатно.\n\n"
    "• Стикеры из селфи: набор из 6 эмоций с твоим лицом сразу в твой стикерпак\n"
    "• Аниме, Pixar, LEGO, комикс и ещё 10+ стилей\n"
    "• Фотосессии: Париж, пляж, деловой портрет\n"
    "• Живые стикеры и GIF из фото, мемы, аватарки\n"
    "• Новогодние стикеры и открытки 🎄\n\n"
    "Нажми «Старт» и пришли селфи 👇"
)
BOT_SHORT_DESCRIPTION = "Стикеры, аватарки, фотосессии и GIF из твоих фото с помощью нейросетей. Бесплатно 🎨"
BOT_COMMANDS = [
    {"command": "start", "description": "Начать"},
    {"command": "sticker", "description": "Стикер из фото (в группе — ответом на фото)"},
    {"command": "mem", "description": "Мем: /mem текст сверху | текст снизу"},
    {"command": "photo", "description": "Фото с подписью: /photo я на пляже в Майами"},
    {"command": "mypack", "description": "Мой стикерпак"},
    {"command": "invite", "description": "Пригласить друга — больше генераций"},
    {"command": "connect", "description": "Лучшее качество фотосессий (по желанию)"},
    {"command": "balance", "description": "Мой баланс для фотосессий"},
    {"command": "models", "description": "Какие нейросети мне доступны бесплатно"},
    {"command": "help", "description": "Как пользоваться"},
]

GROUP_HELP = (
    "👋 Привет! Я делаю стикеры прямо в чате.\n\n"
    "• Ответь на фото командой /sticker — выберешь стиль кнопками;\n"
    "• /sticker аниме (ответом на фото) — сразу в нужном стиле;\n"
    "• /sticker кот в очках — нарисую с нуля;\n"
    "• /mem Верх | Низ (ответом на фото) — сделаю мем."
)


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


def send_sticker(chat_id, sticker_file, reply_to=None, keyboard=None, video=False):
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
        files={"sticker": ("sticker.webm", sticker_file, "video/webm") if video
               else ("sticker.webp", sticker_file, "image/webp")},
    )


def send_photo(chat_id, photo_file, reply_to=None, keyboard=None, caption=None):
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    if reply_to:
        data["reply_parameters"] = json.dumps(
            {"message_id": reply_to, "allow_sending_without_reply": True}
        )
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return telegram(
        "sendPhoto",
        data=data,
        files={"photo": ("image.jpg", photo_file, "image/jpeg")},
    )


def send_animation(chat_id, gif_bytes, reply_to=None, caption=None, keyboard=None):
    data = {"chat_id": chat_id}
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    if caption:
        data["caption"] = caption
    if reply_to:
        data["reply_parameters"] = json.dumps(
            {"message_id": reply_to, "allow_sending_without_reply": True}
        )
    return telegram(
        "sendAnimation",
        data=data,
        files={"animation": ("animation.gif", gif_bytes, "image/gif")},
    )


def get_animation_file_id(message):
    """GIF или короткое видео в сообщении (Telegram присылает GIF как mp4 в поле animation)."""
    for key in ("animation", "video", "video_note"):
        if message.get(key):
            return message[key]["file_id"]
    document = message.get("document") or {}
    if document.get("mime_type") in ("image/gif", "video/mp4", "video/webm"):
        return document["file_id"]
    return None


def split_command(text):
    """'/sticker@my_bot аниме' → ('/sticker', 'аниме', 'my_bot')."""
    if not text.startswith("/"):
        return "", text, ""
    head, _, args = text.partition(" ")
    command, _, mention = head.partition("@")
    return command.lower(), args.strip(), mention


def get_image_file_id(message):
    photos = message.get("photo")
    if photos:
        return photos[-1]["file_id"]  # самое большое разрешение

    document = message.get("document")
    if document and document.get("mime_type", "").startswith("image/") and document["mime_type"] != "image/gif":
        return document["file_id"]

    sticker = message.get("sticker")
    if sticker and not sticker.get("is_animated") and not sticker.get("is_video"):
        return sticker["file_id"]

    return None


def message_text(message):
    text = (message.get("text") or message.get("caption") or "").strip()
    command, args, _ = split_command(text)
    if command == "/sticker":
        return args  # «/sticker аниме» → просьба «аниме»
    return text


def _pairs(buttons):
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def style_buttons(styles, prefix):
    return [{"text": label, "callback_data": f"{prefix}:{key}"} for key, (label, _) in styles.items()]


def video_available(user_id):
    """Показывать ли «🎬 Оживить»: если баланс не подключён — да (бот предложит подключить),
    если подключён — только когда хоть одна видео-модель доступна этому пользователю."""
    if not premium_available():
        return False
    key = (premium_key(user_id) if user_id else None) or ai.POLLINATIONS_KEY
    return bool(key) and bool(ai.video_models_for_key(key))


def style_keyboard(user_id=None):
    rows = []
    if new_year_season():
        rows.append([{"text": "🎄 Новогодний набор — 6 стикеров в пак", "callback_data": "emony"}])
        rows.append([{"text": "🎁 Новогодняя открытка", "callback_data": "card"}])
        rows += _pairs(style_buttons(NEW_YEAR_STYLES, "style"))
    rows.append([{"text": "😊 Набор эмоций — 6 стикеров в пак", "callback_data": "emo"}])
    rows += _pairs(style_buttons(STYLES, "style"))
    rows.append([
        {"text": "🎲 Случайный стиль", "callback_data": f"style:{RANDOM}"},
        {"text": "🖼 Просто стикер", "callback_data": f"style:{PLAIN}"},
    ])
    if premium_available():
        if video_available(user_id):
            rows.insert(0, [{"text": "🎬 Оживить фото — живое видео", "callback_data": "video"}])
        rows.insert(0, [{"text": "📸 Фотосессия — реалистичное фото", "callback_data": "photo"}])
    rows.append([
        {"text": "🖼 Аватарка", "callback_data": "ava"},
        {"text": "🎞 GIF", "callback_data": "photogif"},
        {"text": "😂 Мем", "callback_data": "memhint"},
    ])
    return rows


def avatar_keyboard():
    styles = {**(NEW_YEAR_STYLES if new_year_season() else {}), **STYLES}
    return _pairs(style_buttons(styles, "ava"))


def result_keyboard(again_data=None):
    first_row = []
    if again_data:
        first_row.append({"text": "🔄 Ещё вариант", "callback_data": again_data})
    first_row.append({"text": "✍️ Надпись", "callback_data": "caption"})
    return [first_row, quick_caption_row(), [ANIMATE_BUTTON, PACK_BUTTON]]


ANIMATE_BUTTON = {"text": "✨ Оживить", "callback_data": "anim"}
PACK_BUTTON = {"text": "➕ В мой пак", "callback_data": "pack"}


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


def render(chat_id, user_id, origin, style=None, seed=None, params=None, again_data=None, mode="sticker"):
    """Делает стикер (или аватарку / открытку) по сообщению origin и отправляет ответом на него.
    mode: "sticker", "avatar" или "card"."""
    text = message_text(origin)
    file_id = get_image_file_id(origin)
    photo = stickers.open_image(download_file(file_id)) if file_id else None
    reply_to = origin["message_id"]

    if mode == "sticker" and (style == PLAIN or (photo and not text and not style and not params)):
        send_sticker(chat_id, stickers.make_sticker(photo, outline=True), reply_to, result_keyboard())
        return

    if mode == "avatar":
        params = {"edit": f"{ALL_STYLES[style][1]}. {AVATAR_SUFFIX}", "caption": "", "remove_background": False}
    elif mode == "card":
        params = {"edit": CARD_PROMPT, "caption": "", "remove_background": False}
    elif params:
        pass
    elif style:
        params = {"edit": ALL_STYLES[style][1], "caption": "", "remove_background": True}
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
            send_limit_reached(chat_id, user_id)
            return

        if not params["edit"]:
            params["edit"] = text

        action = "choose_sticker" if mode == "sticker" else "upload_photo"
        telegram("sendChatAction", json={"chat_id": chat_id, "action": action})
        status = send_message(chat_id, "🎨 Рисую, подожди немного…")
        # Обрезаем вокруг центра: лицо крупнее — нейросеть лучше сохраняет сходство.
        source = stickers.crop_square(photo) if photo else None
        try:
            result = ai.generate_image(
                build_prompt(params, has_photo=bool(photo)),
                photo_png=stickers.to_png_bytes(source, max_side=1024) if photo else None,
                photo_png_small=stickers.to_png_bytes(source, max_side=ai.CF_INPUT_MAX_SIDE) if photo else None,
                seed=seed,
                size=ai.IMAGE_SIZE if mode == "sticker" else 1024,
            )
        except ai.AIUnavailable:
            send_message(chat_id, "😔 Все нейросети сейчас заняты или закончился дневной лимит. Попробуй позже.")
            return
        finally:
            if status.get("ok"):
                delete_message(chat_id, status["result"]["message_id"])
        image = stickers.open_image(result)

    if mode == "avatar":
        send_photo(
            chat_id, stickers.to_jpeg(image), reply_to,
            [[{"text": "🔄 Ещё вариант", "callback_data": f"ava:{style}"}]],
            caption="🖼 Твоя аватарка — сохрани и поставь в профиль",
        )
        return
    if mode == "card":
        send_photo(
            chat_id, stickers.make_card(image, new_year_greeting()), reply_to,
            [[{"text": "🔄 Ещё вариант", "callback_data": "card"}]],
            caption=f"🎁 Открытка готова — перешли её друзьям! Сделано в @{bot_username()}",
        )
        return

    if params["remove_background"]:
        image = stickers.remove_plain_background(image)

    again = again_data or (f"again:{style}" if style else "again")
    if again == NO_AGAIN:
        again = None
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


def put_in_pack(user, sticker_file_id, emoji="😀", video=False):
    """Добавляет стикер в личный пак пользователя, при первом разе создаёт пак.
    Возвращает ответ Telegram. В одном паке могут быть и обычные, и анимированные стикеры."""
    name = pack_name(user["id"])
    sticker = {"sticker": sticker_file_id, "format": "video" if video else "static", "emoji_list": [emoji]}

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


def add_to_pack(chat_id, user, sticker_file_id, reply_to=None, video=False):
    result = put_in_pack(user, sticker_file_id, video=video)
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


def make_emotion_pack(chat_id, user, origin, kind="emo"):
    """Делает из одного фото 6 стикеров с разными эмоциями и складывает их в пак."""
    intro, emotions = EMOTION_SETS[kind]
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
    status = send_message(chat_id, f"{intro} — это займёт около минуты…")
    started = time.monotonic()
    done = 0
    # Одинаковый seed и первый стикер как образец — чтобы все 6 были одним персонажем.
    seed = random.randint(0, 2**31 - 1)
    reference = None

    for _, emoji, caption, mood in emotions:
        if time.monotonic() - started > 200:
            break
        if not limits.take(user["id"]):
            send_limit_reached(chat_id, user["id"])
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
            [[{"text": "✍️ Надпись", "callback_data": "caption"}, ANIMATE_BUTTON]],
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


def make_meme_from(chat_id, source, args, reply_to):
    """/mem Верх | Низ — мем без нейросети, мгновенно."""
    top, sep, bottom = args.partition("|")
    if not sep:
        top, bottom = "", top  # одна строка — пишем снизу
    if not (top.strip() or bottom.strip()):
        send_message(chat_id, "Напиши текст мема: /mem Текст сверху | Текст снизу", reply_to=reply_to)
        return
    image = stickers.open_image(download_file(get_image_file_id(source)))
    send_photo(
        chat_id,
        stickers.make_meme(image, top.strip(), bottom.strip()),
        source["message_id"],
        caption=f"😂 Мемы и стикеры — @{bot_username()}",
    )


def invite_link(user_id):
    return f"https://t.me/{bot_username()}?start=ref_{user_id}"


def invite_keyboard(user_id):
    text = "Смотри, этот бот делает стикеры, аватарки и фотосессии из твоих фото — бесплатно 🔥"
    url = "https://t.me/share/url?" + urllib.parse.urlencode({"url": invite_link(user_id), "text": text})
    return [[{"text": "📤 Отправить приглашение", "url": url}]]


def send_invite(chat_id, user_id):
    if not limits.enabled():
        send_message(chat_id, f"📤 Поделись ботом с друзьями: {invite_link(user_id)}", keyboard=invite_keyboard(user_id))
        return
    friends = limits.friends_count(user_id)
    send_message(
        chat_id,
        f"🎁 За каждого друга, который откроет бота по твоей ссылке, — "
        f"+{limits.BONUS_PER_FRIEND} генераций в день навсегда (до +{limits.BONUS_CAP}).\n\n"
        f"👥 Уже пришло друзей: {friends}\n"
        f"⚡ Твой лимит: {plural_stickers(limits.user_limit(user_id))} в день\n\n"
        f"Твоя ссылка: {invite_link(user_id)}",
        keyboard=invite_keyboard(user_id),
    )


def send_limit_reached(chat_id, user_id):
    text = f"⏳ На сегодня всё: можно {plural_stickers(limits.user_limit(user_id))} в день. Приходи завтра!"
    if limits.enabled():
        text += f"\n\n🎁 Хочешь больше? Пригласи друга — +{limits.BONUS_PER_FRIEND} генераций в день за каждого."
    send_message(chat_id, text, keyboard=invite_keyboard(user_id))


def format_count(n):
    return f"{n:,}".replace(",", " ")


def send_start(chat_id, user_id):
    text = START_TEXT
    numbers = limits.stats()
    if numbers and numbers[0] >= 10:
        users, gens = numbers
        text += f"\n\n🔥 Уже {format_count(users)} человек сделали {format_count(gens)} картинок."
    telegram("sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [
            [{"text": "🎲 Удиви меня — нарисуй что-нибудь", "callback_data": "surprise"}],
            [{"text": "👥 Добавить в группу", "url": f"https://t.me/{bot_username()}?startgroup=start"},
             {"text": "🎁 Пригласить друга", "callback_data": "invite"}],
        ]},
    })


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


def animate_sticker(chat_id, message, effect=None):
    """✨ Оживить: делает из обычного стикера бота анимированный (видео-стикер)."""
    source = message
    if not (source.get("sticker") and not source["sticker"].get("is_video")):
        source = message.get("reply_to_message") or {}  # нажали под уже анимированным стикером
    sticker = source.get("sticker")
    if not sticker or sticker.get("is_video") or sticker.get("is_animated"):
        send_message(chat_id, "Не нашёл исходный стикер — нажми «✨ Оживить» под обычным стикером.")
        return

    effect = effect or random.choice(list(animate.EFFECTS))
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "choose_sticker"})
    image = stickers.open_image(download_file(sticker["file_id"]))
    video = animate.make_video_sticker(image, effect)
    send_sticker(
        chat_id,
        video,
        source["message_id"],
        [
            [{"text": "🔄 Другая анимация", "callback_data": "anim"}, {"text": "🎞 GIF", "callback_data": f"gif:{effect}"}],
            [PACK_BUTTON],
        ],
        video=True,
    )


def send_gif_version(chat_id, message, effect):
    """🎞 GIF: та же анимация обычным GIF-файлом — его можно сохранить и отправить куда угодно."""
    source = message.get("reply_to_message") or {}
    sticker = source.get("sticker")
    if effect not in animate.EFFECTS or not sticker or sticker.get("is_video"):
        send_message(chat_id, "Не нашёл исходный стикер — оживи его ещё раз.")
        return
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "upload_video"})
    image = stickers.open_image(download_file(sticker["file_id"]))
    send_animation(chat_id, animate.make_gif(image, effect), message["message_id"], f"🎞 Сделано в @{bot_username()}")


def video_keyboard():
    buttons = [{"text": label, "callback_data": f"vid:{key}"} for key, (label, _) in VIDEO_MOTIONS.items()]
    return _pairs(buttons)


def photo_keyboard():
    buttons = [{"text": label, "callback_data": f"ph:{key}"} for key, (label, _) in PHOTO_SCENES.items()]
    rows = _pairs(buttons)
    rows.append([{"text": "✍️ Свой запрос", "callback_data": "phhint"}])
    return rows


# ---------- личный баланс Pollinations у каждого пользователя ----------

USER_KEY_TTL = 30 * 24 * 3600


def premium_available():
    """Фотосессия и живое видео: либо каждый подключает свой аккаунт (нужна база), либо общий ключ владельца."""
    return limits.store_enabled() or bool(ai.POLLINATIONS_KEY)


def premium_key(user_id):
    """Ключ, с которым делать фото/видео для этого пользователя (None — нужно подключиться)."""
    if limits.store_enabled():
        return limits.load(f"pkey:{user_id}")
    return ai.POLLINATIONS_KEY or None


CONNECT_TEXT = (
    "🔗 По желанию можно подключить свой бесплатный баланс Pollinations — тогда фотосессии "
    "делает более точная нейросеть (лучше сохраняет лицо), и ты пользуешься своим собственным лимитом.\n\n"
    "Подключение — 1 минута: нужен вход через GitHub."
)


def send_connect_prompt(chat_id):
    send_message(
        chat_id,
        CONNECT_TEXT,
        keyboard=[[{"text": "🔗 Подключить бесплатный баланс", "callback_data": "connect"}]],
    )


def start_connect(chat_id, user):
    if not limits.store_enabled():
        send_message(chat_id, "Подключение личного баланса пока не настроено владельцем бота.")
        return
    data = ai.start_connect()
    limits.save(f"device:{user['id']}", data["device_code"], data.get("expires_in", 1800))
    send_message(
        chat_id,
        "1️⃣ Открой ссылку и войди через GitHub.\n"
        "2️⃣ Нажми «Allow» (Разрешить). Там же можно задать, сколько Pollen боту можно тратить.\n"
        "3️⃣ Вернись сюда и нажми «✅ Я подтвердил».\n\n"
        f"Код, если спросят: {data['user_code']}",
        keyboard=[
            [{"text": "🔗 Открыть Pollinations", "url": data["verification_uri_complete"]}],
            [{"text": "✅ Я подтвердил", "callback_data": "connect:check"}],
        ],
    )


def check_connect(chat_id, user):
    device_code = limits.load(f"device:{user['id']}")
    if not device_code:
        send_message(chat_id, "Ссылка устарела — начнём заново.", keyboard=[[{"text": "🔗 Подключить", "callback_data": "connect"}]])
        return
    key, error = ai.finish_connect(device_code)
    if key:
        limits.save(f"pkey:{user['id']}", key, USER_KEY_TTL)
        limits.remove(f"device:{user['id']}")
        balance = ai.pollen_balance(key)
        extra = f" На балансе: {balance:.2f} Pollen." if isinstance(balance, (int, float)) else ""
        send_message(chat_id, f"✅ Подключено!{extra} Теперь пришли фото и выбери «📸 Фотосессия» или «🎬 Оживить фото».")
    elif error in ("authorization_pending", "slow_down"):
        send_message(chat_id, "⏳ Ещё не подтверждено. Открой ссылку, нажми «Allow», потом снова «✅ Я подтвердил».",
                     keyboard=[[{"text": "✅ Я подтвердил", "callback_data": "connect:check"}]])
    else:
        print("Connect error:", error)
        send_message(chat_id, "😔 Не получилось подключить. Попробуем ещё раз?",
                     keyboard=[[{"text": "🔗 Подключить заново", "callback_data": "connect"}]])


def send_balance(chat_id, user_id):
    key = limits.load(f"pkey:{user_id}") if limits.store_enabled() else None
    if not key:
        send_connect_prompt(chat_id)
        return
    balance = ai.pollen_balance(key)
    text = f"💰 На твоём балансе Pollinations: {balance:.2f} Pollen." if isinstance(balance, (int, float)) \
        else "💰 Баланс узнать не удалось, но аккаунт подключён."
    models = ai.photo_models_for_key(key)
    if models:
        names = ", ".join(ai.PHOTO_MODEL_NAMES.get(m, m) for m in models[:4])
        text += f"\n📸 Для фотосессий тебе доступны: {names}."
    else:
        text += "\n📸 Сильные модели для фото на бесплатном балансе сейчас недоступны — фото делает простая нейросеть."
    send_message(chat_id, text + "\nПополнить или поменять лимит можно на enter.pollinations.ai. /disconnect — отключить.")


def out_of_credits_text():
    return (
        "\n\n⚠️ Твой бесплатный баланс Pollinations для сильных моделей закончился — "
        "это фото сделала простая бесплатная нейросеть, поэтому лицо может отличаться. /balance — проверить баланс."
    )


def make_photo_edit(chat_id, user_id, origin, scene, again_data):
    """📸 Реалистичное фото с тем же лицом (Nano Banana через Pollinations, с запасными нейросетями)."""
    file_id = get_image_file_id(origin)
    if not file_id:
        send_message(chat_id, "Не нашёл фото — пришли его ещё раз.")
        return
    # Подключил свой баланс — его ключ; нет — только бесплатные нейросети (без входа куда-либо).
    key = premium_key(user_id) or ai.NO_KEY
    if not limits.take(user_id):
        send_limit_reached(chat_id, user_id)
        return

    photo = stickers.open_image(download_file(file_id))
    source = stickers.crop_square(photo)
    status = send_message(chat_id, "📸 Делаю фото — до минуты…")
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "upload_photo"})
    try:
        with ai.use_key(key):
            result = ai.edit_photo(
                PHOTO_STYLE.format(scene=scene),
                stickers.to_png_bytes(source, max_side=1024),
                stickers.to_png_bytes(source, max_side=ai.CF_INPUT_MAX_SIDE),
                seed=random.randint(0, 2**31 - 1),
            )
    except ai.AIUnavailable:
        send_message(chat_id, "😔 Нейросети сейчас заняты или закончился баланс. Попробуй позже.")
        return
    finally:
        if status.get("ok"):
            delete_message(chat_id, status["result"]["message_id"])

    row = [] if again_data == NO_AGAIN else [{"text": "🔄 Ещё вариант", "callback_data": again_data}]
    if video_available(user_id):
        row.append({"text": "🎬 Оживить", "callback_data": "video:self"})
    keyboard = [row] if row else None
    send_photo(
        chat_id,
        stickers.to_jpeg(stickers.open_image(result)),
        origin["message_id"],
        keyboard,
        caption=f"📸 Сделано в @{bot_username()} · нейросеть: {ai.last_used['name'] or '—'}"
        + (out_of_credits_text() if ai.last_used.get("no_credits") and limits.store_enabled() else "")
        + ("\n\n💡 Хочешь точнее сходство? /connect — подключи свой бесплатный баланс."
           if key == ai.NO_KEY and limits.store_enabled() else ""),
    )


def make_live_video(chat_id, user_id, origin, motion):
    """🎬 Живое видео из фото через видео-нейросеть."""
    file_id = get_image_file_id(origin)
    if not file_id:
        send_message(chat_id, "Не нашёл фото — пришли его ещё раз.")
        return
    key = premium_key(user_id)
    if not key:
        send_connect_prompt(chat_id)
        return
    if not limits.take(user_id):
        send_limit_reached(chat_id, user_id)
        return

    photo = stickers.open_image(download_file(file_id))
    status = send_message(chat_id, "🎬 Оживляю фото — это займёт 1–3 минуты…")
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "upload_video"})
    try:
        with ai.use_key(key):
            video = ai.animate_photo(
                stickers.to_jpeg(photo).getvalue(),
                VIDEO_STYLE.format(motion=VIDEO_MOTIONS[motion][1]),
                portrait=photo.height >= photo.width,
            )
    except ai.AIUnavailable:
        send_message(
            chat_id,
            "😔 Видео не получилось: нейросеть недоступна или на твоём балансе Pollinations "
            "не хватает Pollen (/balance — проверить). Пока можно сделать 🎞 GIF — он работает всегда.",
        )
        return
    finally:
        if status.get("ok"):
            delete_message(chat_id, status["result"]["message_id"])

    telegram(
        "sendAnimation",
        data={
            "chat_id": chat_id,
            "caption": f"🎬 Сделано в @{bot_username()} · нейросеть: {ai.last_used.get('video') or '—'}",
            "reply_parameters": json.dumps({"message_id": origin["message_id"], "allow_sending_without_reply": True}),
            "reply_markup": json.dumps({"inline_keyboard": [
                [{"text": "🔄 Ещё раз", "callback_data": f"vid:{motion}"},
                 {"text": "🎞 В живой стикер", "callback_data": "vid2sticker"}],
            ]}),
        },
        files={"animation": ("video.mp4", video, "video/mp4")},
    )


def photo_to_gif(chat_id, origin):
    """🎞 GIF прямо из фото: фото оживает с одним из эффектов (без нейросети, без лимитов)."""
    file_id = get_image_file_id(origin)
    if not file_id:
        send_message(chat_id, "Не нашёл фото — пришли его ещё раз.")
        return
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "upload_video"})
    image = stickers.open_image(download_file(file_id))
    effect = random.choice(list(animate.EFFECTS))
    send_animation(
        chat_id,
        animate.make_gif(image, effect),
        origin["message_id"],
        f"🎞 {animate.EFFECTS[effect]} · @{bot_username()}",
        [[{"text": "🔄 Другой эффект", "callback_data": "photogif"}]],
    )


def gif_to_sticker(chat_id, source):
    """Гифка → живой стикер для пака."""
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "choose_sticker"})
    video = animate.video_to_sticker(download_file(get_animation_file_id(source)))
    send_sticker(chat_id, video, source["message_id"], [[PACK_BUTTON]], video=True)


def make_meme_gif_from(chat_id, source, args, reply_to):
    top, sep, bottom = args.partition("|")
    if not sep:
        top, bottom = "", top
    if not (top.strip() or bottom.strip()):
        send_message(chat_id, "Напиши текст мема: /mem Текст сверху | Текст снизу", reply_to=reply_to)
        return
    telegram("sendChatAction", json={"chat_id": chat_id, "action": "upload_video"})
    gif = animate.make_meme_gif(download_file(get_animation_file_id(source)), top.strip(), bottom.strip())
    send_animation(chat_id, gif, source["message_id"], f"😂 Мемы и стикеры — @{bot_username()}")


def caption_sticker(chat_id, sticker_message, caption):
    """Дописывает текст на уже готовый стикер бота."""
    if sticker_message["sticker"].get("is_video"):
        send_message(chat_id, "✍️ Надпись можно добавить к обычному стикеру — ответь текстом на него, а потом оживи.")
        return
    image = stickers.open_image(download_file(sticker_message["sticker"]["file_id"]))
    send_sticker(
        chat_id,
        stickers.make_sticker(image, caption),
        sticker_message["message_id"],
        [[{"text": "✍️ Надпись", "callback_data": "caption"}], [ANIMATE_BUTTON, PACK_BUTTON]],
    )


def handle_callback(query):
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    user = query["from"]

    if data == "memhint":
        telegram(
            "answerCallbackQuery",
            json={
                "callback_query_id": query["id"],
                "text": "Пришли это фото ещё раз с подписью:\n/mem Текст сверху | Текст снизу",
                "show_alert": True,
            },
        )
        return

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
        add_to_pack(chat_id, user, sticker["file_id"], reply_to=message["message_id"], video=bool(sticker.get("is_video")))
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

    if data == "connect":
        if message.get("chat", {}).get("type", "private") != "private":
            send_message(chat_id, f"🔗 Подключение — в личке с ботом: https://t.me/{bot_username()}?start=connect")
        else:
            start_connect(chat_id, user)
        return

    if data == "invite":
        send_invite(chat_id, user["id"])
        return

    if data == "connect:check":
        check_connect(chat_id, user)
        return

    if data == "anim":
        animate_sticker(chat_id, message)
        return

    if data.startswith("gif:"):
        send_gif_version(chat_id, message, data.partition(":")[2])
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

    if data in EMOTION_SETS:
        make_emotion_pack(chat_id, user, origin, kind=data)
        return

    if data == "video:self" and message.get("photo"):
        send_message(chat_id, "🎬 Что должно происходить в видео? 👇", reply_to=message["message_id"], keyboard=video_keyboard())
        return

    if data == "vid2sticker":
        if get_animation_file_id(message):
            gif_to_sticker(chat_id, message)
        return

    if data == "video":
        send_message(chat_id, "🎬 Что должно происходить в видео? 👇", reply_to=origin["message_id"], keyboard=video_keyboard())
        return

    if data == "photo":
        send_message(chat_id, "📸 Выбери фотосессию 👇", reply_to=origin["message_id"], keyboard=photo_keyboard())
        return

    if data == "phhint":
        send_message(
            chat_id,
            "✍️ Пришли это фото ещё раз с подписью, например:\n"
            "/photo я в смокинге на красной дорожке\n"
            "/photo поменяй фон на горы, а футболку на красную",
        )
        return

    if data.startswith("ph:") and data[3:] in PHOTO_SCENES:
        make_photo_edit(chat_id, user["id"], origin, PHOTO_SCENES[data[3:]][1], data)
        return

    if data == "phcustom":
        request = message_text(origin).partition(" ")[2] if message_text(origin).startswith("/photo") else ""
        if request:
            make_photo_edit(chat_id, user["id"], origin, ai.translate_request(request), "phcustom")
        return

    if data.startswith("vid:") and data[4:] in VIDEO_MOTIONS:
        make_live_video(chat_id, user["id"], origin, data[4:])
        return

    if data == "photogif":
        photo_to_gif(chat_id, origin)
        return

    if data == "ava":
        send_message(chat_id, "🖼 Выбери стиль аватарки 👇", reply_to=origin["message_id"], keyboard=avatar_keyboard())
        return

    if data == "card":
        render(chat_id, user["id"], origin, mode="card", seed=random.randint(0, 2**31 - 1))
        return

    action, _, style = data.partition(":")
    if style == RANDOM:
        style = random.choice(list(STYLES))
    if style and style != PLAIN and style not in ALL_STYLES:
        return

    if action == "ava" and style in ALL_STYLES:
        render(chat_id, user["id"], origin, style=style, mode="avatar", seed=random.randint(0, 2**31 - 1))
    elif action == "style":
        render(chat_id, user["id"], origin, style=style)
    elif action == "again":
        render(chat_id, user["id"], origin, style=style or None, seed=random.randint(0, 2**31 - 1))


def handle_sticker_command(message, args):
    """/sticker в группе или в личке: ответом на фото, с подписью к фото или с текстом."""
    chat_id = message["chat"]["id"]
    replied = message.get("reply_to_message") or {}
    for candidate in (message, replied):
        if get_animation_file_id(candidate):
            gif_to_sticker(chat_id, candidate)
            return
    if get_image_file_id(message):
        source = message
    elif get_image_file_id(replied):
        source = replied
    else:
        source = None

    if not source and not args:
        send_message(chat_id, GROUP_HELP, reply_to=message["message_id"])
    elif source and not args:
        send_message(chat_id, "Выбери стиль 👇", reply_to=source["message_id"],
                     keyboard=style_keyboard(message["from"]["id"]))
    elif source is message or not source:
        render(chat_id, message["from"]["id"], message)
    else:
        # Ответ на чужое фото: просьбу берём из команды, картинку — из того фото.
        origin = {key: source[key] for key in ("photo", "document", "sticker") if key in source}
        origin.update({"message_id": source["message_id"], "caption": args})
        render(chat_id, message["from"]["id"], origin, again_data=NO_AGAIN)


def handle_message(message):
    chat_id = message["chat"]["id"]
    raw_text = (message.get("text") or message.get("caption") or "").strip()
    command, args, mention = split_command(raw_text)
    if mention and mention.lower() != bot_username().lower():
        return  # команда другому боту в группе

    replied = message.get("reply_to_message") or {}
    is_private = message["chat"].get("type", "private") == "private"
    if is_private:
        is_new = limits.track_user(message["from"]["id"])
        if command == "/start" and args.startswith("ref_") and is_new:
            referrer = args[4:]
            if referrer.isdigit() and limits.reward_referrer(referrer, message["from"]["id"]):
                send_message(
                    int(referrer),
                    f"🎉 По твоей ссылке пришёл друг! +{limits.BONUS_PER_FRIEND} генераций в день. /invite — подробнее",
                )
    if command == "/invite":
        send_invite(chat_id, message["from"]["id"])
        return
    if command == "/sticker":
        handle_sticker_command(message, args)
        return
    if command == "/models":
        key = premium_key(message["from"]["id"])
        if key:
            send_message(chat_id, "🤖 Сейчас тебе доступны:\n\n" + ai.free_models_report(key))
        else:
            send_message(
                chat_id,
                "🤖 Без подключения всё работает на бесплатной нейросети Cloudflare FLUX.2 klein: "
                "стикеры, набор эмоций, стили, аватарки и фотосессии. GIF, живые стикеры и мемы — "
                "без нейросети, без лимитов.\n\n" + CONNECT_TEXT,
                keyboard=[[{"text": "🔗 Подключить бесплатный баланс", "callback_data": "connect"}]],
            )
        return

    if command in ("/connect", "/balance", "/disconnect") or raw_text.startswith("/start connect"):
        if message["chat"].get("type", "private") != "private":
            send_message(chat_id, f"🔗 Это в личке с ботом: https://t.me/{bot_username()}?start=connect")
        elif command == "/balance":
            send_balance(chat_id, message["from"]["id"])
        elif command == "/disconnect":
            limits.remove(f"pkey:{message['from']['id']}")
            send_message(chat_id, "🔌 Отключено. Ключ также можно удалить на enter.pollinations.ai.")
        else:
            start_connect(chat_id, message["from"])
        return

    if command == "/photo":
        source = message if get_image_file_id(message) else replied
        if not get_image_file_id(source) or not args:
            send_message(chat_id, "Пришли фото с подписью /photo и что сделать, например: /photo я на пляже в Майами")
            return
        origin = dict(source)
        if source is not message:
            origin = {key: source[key] for key in ("photo", "document") if key in source}
            origin.update({"message_id": source["message_id"]})
        again = "phcustom" if source is message else NO_AGAIN
        make_photo_edit(chat_id, message["from"]["id"], origin, ai.translate_request(args), again)
        return

    if command == "/mem":
        for candidate in (message, replied):
            if get_animation_file_id(candidate):
                make_meme_gif_from(chat_id, candidate, args, message["message_id"])
                return
        source = message if get_image_file_id(message) else replied
        if not get_image_file_id(source):
            send_message(chat_id, "Ответь командой /mem на фото или пришли фото с подписью /mem Верх | Низ")
            return
        make_meme_from(chat_id, source, args, message["message_id"])
        return

    if message["chat"].get("type", "private") != "private":
        # В группе отвечаем только на команды и на ответы к нашим стикерам.
        if command in ("/start", "/help"):
            send_message(chat_id, GROUP_HELP)
        elif command == "/mypack":
            send_my_pack(chat_id, message["from"]["id"])
        elif raw_text and not command and is_our_sticker(replied):
            caption_sticker(chat_id, replied, raw_text)
        return

    text = message_text(message)

    if text.startswith("/start"):
        send_start(chat_id, message["from"]["id"])
        return

    if text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return

    if text.startswith("/mypack"):
        send_my_pack(chat_id, message["from"]["id"])
        return

    if text and is_our_sticker(replied):
        caption_sticker(chat_id, replied, text)
        return

    if get_animation_file_id(message) and not text:
        gif_to_sticker(chat_id, message)
        send_message(chat_id, "💡 Хочешь мем-GIF? Пришли эту гифку с подписью /mem Текст сверху | Текст снизу")
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
            keyboard=style_keyboard(message["from"]["id"]),
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


ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


def handle_added_to_chat(update):
    """Бота добавили в группу — коротко рассказываем, что он умеет."""
    chat = update.get("chat") or {}
    status = (update.get("new_chat_member") or {}).get("status")
    old_status = (update.get("old_chat_member") or {}).get("status")
    if chat.get("type") in ("group", "supergroup") and status in ("member", "administrator") \
            and old_status in ("left", "kicked", None):
        send_message(chat["id"], GROUP_HELP)
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
    if [(c.get("command"), c.get("description")) for c in current] != \
            [(c["command"], c["description"]) for c in BOT_COMMANDS]:
        telegram("setMyCommands", json={"commands": BOT_COMMANDS})
    if (telegram("getMyDescription").get("result") or {}).get("description") != BOT_DESCRIPTION:
        telegram("setMyDescription", json={"description": BOT_DESCRIPTION})
    if (telegram("getMyShortDescription").get("result") or {}).get("short_description") != BOT_SHORT_DESCRIPTION:
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
    try:
        username = bot_username() if BOT_TOKEN else ""
    except Exception as error:
        print("Landing username error:", repr(error))
        username = ""
    return pages.landing_page(username)


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
    membership = update.get("my_chat_member")

    if message and message.get("chat") and message.get("from"):
        safely(handle_message, message, message["chat"]["id"])
    elif query:
        chat_id = (query.get("message") or {}).get("chat", {}).get("id")
        safely(handle_callback, query, chat_id)
    elif membership:
        safely(handle_added_to_chat, membership, None)

    return "OK"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
