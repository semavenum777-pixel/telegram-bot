"""Дневной лимит генераций на пользователя.

Счётчики хранятся в Upstash Redis (бесплатно подключается в Vercel:
Storage → Upstash Redis). Если база не подключена, лимит не действует.
"""

import datetime
import os

import requests

REDIS_URL = (
    os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL") or ""
).strip().rstrip("/")
REDIS_TOKEN = (
    os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN") or ""
).strip()
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "20"))


def enabled():
    return bool(REDIS_URL and REDIS_TOKEN) and DAILY_LIMIT > 0


def take(user_id):
    """Засчитывает одну генерацию. Возвращает False, если лимит на сегодня исчерпан."""
    if not enabled():
        return True

    key = f"limit:{user_id}:{datetime.date.today().isoformat()}"
    try:
        response = requests.post(
            f"{REDIS_URL}/pipeline",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            json=[["INCR", key], ["EXPIRE", key, 2 * 24 * 3600]],
            timeout=10,
        )
        response.raise_for_status()
        count = response.json()[0]["result"]
    except Exception as error:
        # Если база недоступна, не мешаем пользоваться ботом.
        print("Limit error:", repr(error))
        return True
    return count <= DAILY_LIMIT
