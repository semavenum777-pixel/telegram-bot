"""Нейросети: разбор запроса пользователя и генерация картинок.

Сервисы перебираются по очереди: если один не ответил или исчерпал
бесплатный лимит, бот пробует следующий.
"""

import base64
import json
import os
import re

import requests

CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_IMAGE_MODEL = os.environ.get("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")
CF_TEXT_MODEL = os.environ.get("CF_TEXT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

POLLINATIONS_KEY = os.environ.get("POLLINATIONS_KEY")
POLLINATIONS_MODEL = os.environ.get("POLLINATIONS_MODEL", "black-forest-labs/flux.2-klein-4b")
POLLINATIONS_API = "https://gen.pollinations.ai/v1"

IMAGE_SIZE = 512
# Cloudflare принимает входные картинки только меньше 512×512.
CF_INPUT_MAX_SIDE = 504

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


def ai_configured():
    return bool((CF_ACCOUNT_ID and CF_API_TOKEN) or POLLINATIONS_KEY)


# ---------- разбор запроса ----------

def _cloudflare_text(prompt):
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_TEXT_MODEL}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 400},
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()["result"]
    answer = result.get("response")
    if answer is None and result.get("choices"):
        answer = result["choices"][0]["message"]["content"]
    return answer


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
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        try:
            prompt = PARSE_PROMPT.replace("{has_photo}", "yes" if has_photo else "no")
            data = _extract_json(_cloudflare_text(prompt.replace("{text}", text)))
            return {
                "edit": str(data.get("edit") or "").strip(),
                "caption": str(data.get("caption") or "").strip(),
                "remove_background": bool(data.get("remove_background")),
            }
        except Exception as error:
            print("Parse error:", repr(error))
    return _simple_parse(text)


# ---------- генерация картинок ----------

def _cloudflare_image(prompt, photo_png):
    files = {
        "prompt": (None, prompt),
        "width": (None, str(IMAGE_SIZE)),
        "height": (None, str(IMAGE_SIZE)),
    }
    if photo_png:
        files["input_image_0"] = ("photo.png", photo_png, "image/png")

    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_IMAGE_MODEL}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        files=files,
        timeout=120,
    )
    response.raise_for_status()
    return base64.b64decode(response.json()["result"]["image"])


def _pollinations_image(prompt, photo_png):
    headers = {"Authorization": f"Bearer {POLLINATIONS_KEY}"}
    size = f"{IMAGE_SIZE}x{IMAGE_SIZE}"
    if photo_png:
        response = requests.post(
            f"{POLLINATIONS_API}/images/edits",
            headers=headers,
            data={"prompt": prompt, "model": POLLINATIONS_MODEL, "size": size},
            files={"image": ("photo.png", photo_png, "image/png")},
            timeout=180,
        )
    else:
        response = requests.post(
            f"{POLLINATIONS_API}/images/generations",
            headers=headers,
            json={"prompt": prompt, "model": POLLINATIONS_MODEL, "size": size},
            timeout=180,
        )
    response.raise_for_status()
    item = response.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    image = requests.get(item["url"], timeout=60)
    image.raise_for_status()
    return image.content


def generate_image(prompt, photo_png=None, photo_png_small=None):
    """Возвращает картинку (bytes) от первого сработавшего сервиса."""
    providers = []
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        providers.append(("Cloudflare", lambda: _cloudflare_image(prompt, photo_png_small)))
    if POLLINATIONS_KEY:
        providers.append(("Pollinations", lambda: _pollinations_image(prompt, photo_png)))

    for name, call in providers:
        try:
            return call()
        except Exception as error:
            print(f"{name} failed:", repr(error))

    raise AIUnavailable("All image providers failed")
