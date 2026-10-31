"""Нейросети: разбор запроса пользователя и генерация картинок.

Бот перебирает все подключённые бесплатные нейросети по очереди: если одна
не ответила или у неё закончился лимит, сразу пробует следующую. Нейросеть,
которая сообщила об исчерпанном лимите, какое-то время пропускается.
Нейросеть подключена, если в настройках хостинга заданы её ключи.
"""

import base64
import json
import os
import re
import time

import requests


def _env(name, default=""):
    return os.environ.get(name, default).strip()


CF_ACCOUNT_ID = _env("CF_ACCOUNT_ID")
CF_API_TOKEN = _env("CF_API_TOKEN")
CF_IMAGE_MODEL = _env("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")
# Запасные модели Cloudflare: пробуются, если основная сломалась (лимит у них общий).
CF_BACKUP_PHOTO_MODEL = _env("CF_BACKUP_PHOTO_MODEL", "@cf/black-forest-labs/flux-2-klein-9b")
CF_TEXT_ONLY_MODEL = _env("CF_TEXT_ONLY_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CF_TEXT_MODEL = _env("CF_TEXT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

GEMINI_API_KEY = _env("GEMINI_API_KEY")
GEMINI_IMAGE_MODEL = _env("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_TEXT_MODEL = _env("GEMINI_TEXT_MODEL", "gemini-2.5-flash-lite")
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"

POLLINATIONS_KEY = _env("POLLINATIONS_KEY")
POLLINATIONS_MODEL = _env("POLLINATIONS_MODEL", "black-forest-labs/flux.2-klein-4b")
# Модель картинок от OpenAI (как в ChatGPT), доступная через баланс Pollinations.
POLLINATIONS_GPT_MODEL = _env("POLLINATIONS_GPT_MODEL", "gptimage")

# Универсальное подключение любых сервисов со стандартом OpenAI Images API
# (OpenAI, Together AI, шлюзы с бонусом при регистрации и т.п.). До 5 штук:
# EXTRA1_URL, EXTRA1_KEY, EXTRA1_MODEL (+ необязательный EXTRA1_SIZE), EXTRA2_..., и т.д.
EXTRA_SERVICES = []
for _n in range(1, 6):
    _url, _key, _model = _env(f"EXTRA{_n}_URL"), _env(f"EXTRA{_n}_KEY"), _env(f"EXTRA{_n}_MODEL")
    if _url and _key and _model:
        EXTRA_SERVICES.append({
            "name": f"Extra{_n} ({_model})",
            "url": _url.rstrip("/"),
            "key": _key,
            "model": _model,
            "size": _env(f"EXTRA{_n}_SIZE"),
        })

BFL_API_KEY = _env("BFL_API_KEY")
BFL_MODEL = _env("BFL_MODEL", "flux-kontext-dev")
BFL_API = "https://api.bfl.ai/v1"
POLLINATIONS_API = "https://gen.pollinations.ai/v1"

FUSIONBRAIN_KEY = _env("FUSIONBRAIN_KEY")
FUSIONBRAIN_SECRET = _env("FUSIONBRAIN_SECRET")
FUSIONBRAIN_API = "https://api-key.fusionbrain.ai/key/api/v1"

IMAGE_SIZE = 512
# Cloudflare принимает входные картинки только меньше 512×512.
CF_INPUT_MAX_SIDE = 504

# Сколько всего можно потратить на одну картинку (Vercel обрывает запрос через 300 с).
TOTAL_BUDGET_SECONDS = 240
# На сколько отложить нейросеть, у которой закончился лимит.
EXHAUSTED_COOLDOWN_SECONDS = 30 * 60
# Если закончились деньги/бонус (HTTP 402), сами по себе они не вернутся — проверяем реже.
NO_CREDITS_COOLDOWN_SECONDS = 6 * 60 * 60

PARSE_PROMPT = """You turn a user's request for a Telegram sticker into JSON.
The user writes in Russian (or another language). Reply with JSON only:
{"edit": string, "caption": string, "remove_background": boolean}

- "edit": an English instruction for an image model describing what to draw
  or how to change the user's photo (style, character, background, clothes...).
  Empty string if the user does not ask to change or draw anything.
- "caption": exact text the user wants written on the sticker, in the original
  language. Empty string if none.
- "remove_background": true if the user wants no background / transparent background.

User has attached a photo: {has_photo}
User request: {text}"""


class AIUnavailable(Exception):
    pass


class LimitReached(Exception):
    """Нейросеть ответила, что бесплатный лимит исчерпан."""

    def __init__(self, message, no_credits=False):
        super().__init__(message)
        self.no_credits = no_credits


def _check(response):
    if response.status_code in (402, 429):
        raise LimitReached(
            f"HTTP {response.status_code}: {response.text[:200]}",
            no_credits=response.status_code == 402,
        )
    response.raise_for_status()


# ---------- нейросети для картинок ----------

def _cloudflare_image(prompt, photo, timeout, seed, size=IMAGE_SIZE, model=None):
    files = {
        "prompt": (None, prompt),
        "width": (None, str(size)),
        "height": (None, str(size)),
    }
    if seed is not None:
        files["seed"] = (None, str(seed))
    if photo:
        files["input_image_0"] = ("photo.png", photo["small"], "image/png")
        if photo.get("ref_small"):
            files["input_image_1"] = ("reference.png", photo["ref_small"], "image/png")

    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model or CF_IMAGE_MODEL}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        files=files,
        timeout=timeout,
    )
    _check(response)
    return base64.b64decode(response.json()["result"]["image"])


def _cloudflare_schnell(prompt, photo, timeout, seed, size=IMAGE_SIZE):
    """Старая быстрая модель Cloudflare: только рисование по тексту, принимает JSON."""
    payload = {"prompt": prompt, "steps": 8}
    if seed is not None:
        payload["seed"] = seed
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_TEXT_ONLY_MODEL}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json=payload,
        timeout=timeout,
    )
    _check(response)
    return base64.b64decode(response.json()["result"]["image"])


def _gemini_image(prompt, photo, timeout, seed, size=IMAGE_SIZE):
    parts = [{"text": f"{prompt}. Square image."}]
    if photo:
        for key in ("large", "ref_large"):
            if photo.get(key):
                parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(photo[key]).decode()}})

    config = {"responseModalities": ["TEXT", "IMAGE"]}
    if seed is not None:
        config["seed"] = seed

    response = requests.post(
        f"{GEMINI_API}/{GEMINI_IMAGE_MODEL}:generateContent",
        headers={"x-goog-api-key": GEMINI_API_KEY},
        json={"contents": [{"parts": parts}], "generationConfig": config},
        timeout=timeout,
    )
    _check(response)
    for candidate in response.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise ValueError("Gemini returned no image")


def _pollinations_image(prompt, photo, timeout, seed, size=IMAGE_SIZE, model=None):
    model = model or POLLINATIONS_MODEL
    headers = {"Authorization": f"Bearer {POLLINATIONS_KEY}"}
    size = f"{size}x{size}"
    if photo:
        response = requests.post(
            f"{POLLINATIONS_API}/images/edits",
            headers=headers,
            data={"prompt": prompt, "model": model, "size": size},
            files=[("image", ("photo.png", photo["large"], "image/png"))]
            + ([("image", ("reference.png", photo["ref_large"], "image/png"))] if photo.get("ref_large") else []),
            timeout=timeout,
        )
    else:
        response = requests.post(
            f"{POLLINATIONS_API}/images/generations",
            headers=headers,
            json={"prompt": prompt, "model": model, "size": size},
            timeout=timeout,
        )
    _check(response)
    item = response.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    image = requests.get(item["url"], timeout=60)
    image.raise_for_status()
    return image.content


def _openai_compatible_image(service, prompt, photo, timeout, seed, size=IMAGE_SIZE):
    """Любой сервис со стандартом OpenAI Images API: /images/edits и /images/generations."""
    headers = {"Authorization": f"Bearer {service['key']}"}
    image_size = service["size"] or f"{max(size, 1024)}x{max(size, 1024)}"
    if photo:
        response = requests.post(
            f"{service['url']}/images/edits",
            headers=headers,
            data={"prompt": prompt, "model": service["model"], "size": image_size, "n": "1"},
            files=[("image", ("photo.png", photo["large"], "image/png"))]
            + ([("image", ("reference.png", photo["ref_large"], "image/png"))] if photo.get("ref_large") else []),
            timeout=timeout,
        )
    else:
        response = requests.post(
            f"{service['url']}/images/generations",
            headers=headers,
            json={"prompt": prompt, "model": service["model"], "size": image_size, "n": 1},
            timeout=timeout,
        )
    _check(response)
    item = response.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    image = requests.get(item["url"], timeout=60)
    image.raise_for_status()
    return image.content


def _bfl_image(prompt, photo, timeout, seed, size=IMAGE_SIZE):
    """Black Forest Labs — создатели FLUX. Kontext умеет менять фото."""
    deadline = time.monotonic() + timeout
    headers = {"x-key": BFL_API_KEY, "accept": "application/json"}
    payload = {"prompt": prompt, "aspect_ratio": "1:1", "output_format": "png"}
    if photo:
        payload["input_image"] = base64.b64encode(photo["large"]).decode()
    if seed is not None:
        payload["seed"] = seed

    response = requests.post(f"{BFL_API}/{BFL_MODEL}", headers=headers, json=payload, timeout=30)
    _check(response)
    task = response.json()
    polling_url = task.get("polling_url") or f"{BFL_API}/get_result?id={task['id']}"

    while time.monotonic() < deadline:
        time.sleep(2)
        status = requests.get(polling_url, headers=headers, timeout=20)
        _check(status)
        result = status.json()
        if result.get("status") == "Ready":
            image = requests.get(result["result"]["sample"], timeout=60)
            image.raise_for_status()
            return image.content
        if result.get("status") not in ("Pending", "Processing", "Queued", None):
            raise ValueError(f"BFL: {result.get('status')}")
    raise TimeoutError("BFL did not finish in time")


_fusionbrain_pipeline = None


def _fusionbrain_image(prompt, photo, timeout, seed, size=IMAGE_SIZE):
    """Kandinsky (Сбер). Умеет только рисовать по тексту, фото не принимает."""
    global _fusionbrain_pipeline
    deadline = time.monotonic() + timeout
    headers = {"X-Key": f"Key {FUSIONBRAIN_KEY}", "X-Secret": f"Secret {FUSIONBRAIN_SECRET}"}

    if not _fusionbrain_pipeline:
        response = requests.get(f"{FUSIONBRAIN_API}/pipelines", headers=headers, timeout=20)
        _check(response)
        pipelines = [p for p in response.json() if p.get("status", "ACTIVE") == "ACTIVE"]
        _fusionbrain_pipeline = pipelines[0]["id"]

    params = {
        "type": "GENERATE",
        "numImages": 1,
        "width": 1024,
        "height": 1024,
        "generateParams": {"query": prompt},
    }
    response = requests.post(
        f"{FUSIONBRAIN_API}/pipeline/run",
        headers=headers,
        files={
            "pipeline_id": (None, _fusionbrain_pipeline),
            "params": (None, json.dumps(params), "application/json"),
        },
        timeout=30,
    )
    _check(response)
    run = response.json()
    if run.get("model_status"):
        raise LimitReached(f"Kandinsky is busy: {run['model_status']}")

    while time.monotonic() < deadline:
        time.sleep(3)
        status = requests.get(
            f"{FUSIONBRAIN_API}/pipeline/status/{run['uuid']}", headers=headers, timeout=20
        )
        _check(status)
        result = status.json()
        if result["status"] == "DONE":
            if result["result"].get("censored"):
                raise ValueError("Kandinsky censored the image")
            return base64.b64decode(result["result"]["files"][0])
        if result["status"] == "FAIL":
            raise ValueError(f"Kandinsky failed: {result}")
    raise TimeoutError("Kandinsky did not finish in time")


# Порядок = приоритет.
# photo: умеет ли нейросеть менять присланное фото.
# group: у моделей одной группы общий лимит — если он кончился, пропускаем всю группу.
PROVIDERS = [
    {"name": "Cloudflare FLUX.2 klein 4B", "group": "Cloudflare", "photo": True, "timeout": 60,
     "call": _cloudflare_image, "enabled": lambda: bool(CF_ACCOUNT_ID and CF_API_TOKEN)},
    {"name": "Cloudflare FLUX.2 klein 9B", "group": "Cloudflare", "photo": True, "timeout": 60,
     "call": lambda *a: _cloudflare_image(*a, model=CF_BACKUP_PHOTO_MODEL),
     "enabled": lambda: bool(CF_ACCOUNT_ID and CF_API_TOKEN and CF_BACKUP_PHOTO_MODEL)},
    {"name": "Gemini", "group": "Gemini", "photo": True, "timeout": 90,
     "call": _gemini_image, "enabled": lambda: bool(GEMINI_API_KEY)},
    {"name": "Black Forest Labs", "group": "BFL", "photo": True, "timeout": 90,
     "call": _bfl_image, "enabled": lambda: bool(BFL_API_KEY)},
    *[
        {"name": service["name"], "group": service["name"], "photo": True, "timeout": 120,
         "call": (lambda service: lambda *a: _openai_compatible_image(service, *a))(service),
         "enabled": lambda: True}
        for service in EXTRA_SERVICES
    ],
    {"name": "Pollinations FLUX", "group": "Pollinations", "photo": True, "timeout": 90,
     "call": _pollinations_image, "enabled": lambda: bool(POLLINATIONS_KEY)},
    {"name": "Pollinations GPT Image", "group": "Pollinations", "photo": True, "timeout": 120,
     "call": lambda *a: _pollinations_image(*a, model=POLLINATIONS_GPT_MODEL),
     "enabled": lambda: bool(POLLINATIONS_KEY and POLLINATIONS_GPT_MODEL)},
    {"name": "Cloudflare FLUX.1 schnell", "group": "Cloudflare", "photo": False, "timeout": 60,
     "call": _cloudflare_schnell, "enabled": lambda: bool(CF_ACCOUNT_ID and CF_API_TOKEN and CF_TEXT_ONLY_MODEL)},
    {"name": "Kandinsky", "group": "Kandinsky", "photo": False, "timeout": 90,
     "call": _fusionbrain_image, "enabled": lambda: bool(FUSIONBRAIN_KEY and FUSIONBRAIN_SECRET)},
]

# Группа нейросетей → время, до которого её не трогаем (закончился лимит).
_exhausted_until = {}


# Для фото первыми идут нейросети, которые лучше сохраняют сходство с человеком
# (если их ключи подключены). Для рисования по тексту порядок обычный.
PHOTO_PRIORITY = {"Gemini": 0, "BFL": 1, **{service["name"]: 2 for service in EXTRA_SERVICES}}


def _available(has_photo):
    now = time.time()
    providers = [
        p for p in PROVIDERS
        if p["enabled"]() and (p["photo"] or not has_photo) and _exhausted_until.get(p["group"], 0) <= now
    ]
    if has_photo:
        providers.sort(key=lambda p: PHOTO_PRIORITY.get(p["group"], len(PHOTO_PRIORITY)))
    return providers


def ai_configured(has_photo=False):
    return any(p["enabled"]() and (p["photo"] or not has_photo) for p in PROVIDERS)


def generate_image(prompt, photo_png=None, photo_png_small=None, seed=None, ref_png=None, ref_png_small=None, size=IMAGE_SIZE):
    """Возвращает картинку (bytes) от первой сработавшей нейросети.
    ref_png — необязательная вторая картинка-образец (например, уже готовый стикер этого персонажа)."""
    photo = None
    if photo_png:
        photo = {"large": photo_png, "small": photo_png_small, "ref_large": ref_png, "ref_small": ref_png_small}
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS

    for provider in _available(has_photo=bool(photo)):
        if _exhausted_until.get(provider["group"], 0) > time.time():
            continue  # лимит группы кончился только что, на другой её модели
        remaining = deadline - time.monotonic()
        if remaining < 15:
            break
        try:
            return provider["call"](prompt, photo, min(provider["timeout"], remaining), seed, size)
        except LimitReached as error:
            print(f"{provider['name']} limit reached:", error)
            cooldown = NO_CREDITS_COOLDOWN_SECONDS if error.no_credits else EXHAUSTED_COOLDOWN_SECONDS
            _exhausted_until[provider["group"]] = time.time() + cooldown
        except Exception as error:
            print(f"{provider['name']} failed:", repr(error))

    raise AIUnavailable("All image providers failed")


# ---------- разбор запроса ----------

def _cloudflare_text(prompt):
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_TEXT_MODEL}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 400},
        timeout=60,
    )
    _check(response)
    result = response.json()["result"]
    answer = result.get("response")
    if answer is None and result.get("choices"):
        answer = result["choices"][0]["message"]["content"]
    return answer


def _gemini_text(prompt):
    response = requests.post(
        f"{GEMINI_API}/{GEMINI_TEXT_MODEL}:generateContent",
        headers={"x-goog-api-key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=60,
    )
    _check(response)
    parts = response.json()["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


TEXT_PROVIDERS = [
    ("Cloudflare", _cloudflare_text, lambda: bool(CF_ACCOUNT_ID and CF_API_TOKEN)),
    ("Gemini", _gemini_text, lambda: bool(GEMINI_API_KEY)),
]


def _extract_json(answer):
    if isinstance(answer, dict):
        return answer
    match = re.search(r"\{.*\}", answer or "", re.S)
    if not match:
        raise ValueError(f"No JSON in answer: {answer!r}")
    return json.loads(match.group(0))


def _simple_parse(text):
    """Запасной разбор без нейросети."""
    caption = ""
    match = re.search(r"надпис\w*\s*:?\s*[\"«“']([^\"»”']+)[\"»”']", text, re.I)
    if match:
        caption = match.group(1).strip()
        text = text.replace(match.group(0), " ")

    remove_background = bool(re.search(r"без\s+фона|прозрачн", text, re.I))
    edit = re.sub(r"(\s*,)+", ",", re.sub(r"\s+", " ", text)).strip(" ,.;")
    return {"edit": edit, "caption": caption, "remove_background": remove_background}


def parse_request(text, has_photo):
    prompt = PARSE_PROMPT.replace("{has_photo}", "yes" if has_photo else "no").replace("{text}", text)
    for name, call, enabled in TEXT_PROVIDERS:
        if not enabled():
            continue
        try:
            data = _extract_json(call(prompt))
            return {
                "edit": str(data.get("edit") or "").strip(),
                "caption": str(data.get("caption") or "").strip(),
                "remove_background": bool(data.get("remove_background")),
            }
        except Exception as error:
            print(f"{name} parse error:", repr(error))
    return _simple_parse(text)


# ---------- живое видео из фото ----------

# Видео-нейросеть Pollinations: оживляет фото (моргание, улыбка, движение). Тратит баланс Pollinations.
POLLINATIONS_VIDEO_MODEL = _env("POLLINATIONS_VIDEO_MODEL", "alibaba/wan-2.2-fast")
VIDEO_SECONDS = int(_env("VIDEO_SECONDS", "4"))
POLLINATIONS_MEDIA = "https://media.pollinations.ai"


def video_configured():
    return bool(POLLINATIONS_KEY)


def _upload_to_pollinations(image_bytes):
    """Видео-нейросети нужна ссылка на фото: загружаем его в хранилище Pollinations.
    Ссылка не публикуется в галереях, но доступна тому, кто её знает; файл удаляется через 30 дней."""
    response = requests.post(
        f"{POLLINATIONS_MEDIA}/upload",
        headers={"Authorization": f"Bearer {POLLINATIONS_KEY}"},
        files={"file": ("photo.jpg", image_bytes, "image/jpeg")},
        timeout=60,
    )
    _check(response)
    return response.json()["url"]


def animate_photo(image_bytes, prompt, portrait=True):
    """Возвращает MP4: фото, превращённое в короткое живое видео."""
    if not video_configured():
        raise AIUnavailable("No video provider configured")
    try:
        url = _upload_to_pollinations(image_bytes)
        response = requests.get(
            f"https://gen.pollinations.ai/video/{requests.utils.quote(prompt, safe='')}",
            headers={"Authorization": f"Bearer {POLLINATIONS_KEY}"},
            params={
                "model": POLLINATIONS_VIDEO_MODEL,
                "image": url,
                "duration": VIDEO_SECONDS,
                "aspectRatio": "9:16" if portrait else "16:9",
                "audio": "false",
            },
            timeout=TOTAL_BUDGET_SECONDS,
        )
        _check(response)
        if not response.headers.get("content-type", "").startswith("video/"):
            raise ValueError(f"Unexpected response: {response.headers.get('content-type')}")
        return response.content
    except LimitReached as error:
        print("Video limit reached:", error)
        raise AIUnavailable("No video credits") from error
    except AIUnavailable:
        raise
    except Exception as error:
        print("Video failed:", repr(error))
        raise AIUnavailable("Video generation failed") from error


# ---------- реалистичный фоторедактор (как Nano Banana) ----------

# Модель Google «Nano Banana» через баланс Pollinations: меняет фото и хорошо сохраняет лицо.
POLLINATIONS_PHOTO_MODEL = _env("POLLINATIONS_PHOTO_MODEL", "google/gemini-2.5-flash-image")
PHOTO_SIZE = 1024


def edit_photo(prompt, photo_png, photo_png_small, seed=None):
    """Реалистичная правка фото. Сначала Nano Banana (Pollinations), потом обычная цепочка нейросетей."""
    if POLLINATIONS_KEY and POLLINATIONS_PHOTO_MODEL and _exhausted_until.get("Nano Banana", 0) <= time.time():
        try:
            return _pollinations_image(
                prompt, {"large": photo_png, "small": photo_png_small}, 150, seed,
                size=PHOTO_SIZE, model=POLLINATIONS_PHOTO_MODEL,
            )
        except LimitReached as error:
            print("Nano Banana limit reached:", error)
            cooldown = NO_CREDITS_COOLDOWN_SECONDS if error.no_credits else EXHAUSTED_COOLDOWN_SECONDS
            _exhausted_until["Nano Banana"] = time.time() + cooldown
        except Exception as error:
            print("Nano Banana failed:", repr(error))
    return generate_image(prompt, photo_png, photo_png_small, seed=seed, size=PHOTO_SIZE)


def translate_request(text):
    """Переводит просьбу пользователя в короткую английскую инструкцию для нейросети."""
    prompt = (
        "Rewrite this photo editing request as one short clear English instruction for an image model. "
        "Reply with the instruction only, no quotes.\n\nRequest: " + text
    )
    for name, call, enabled in TEXT_PROVIDERS:
        if not enabled():
            continue
        try:
            answer = (call(prompt) or "").strip().strip('"')
            if answer:
                return answer
        except Exception as error:
            print(f"{name} translate error:", repr(error))
    return text
