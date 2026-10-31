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
            json=[["INCR", key], ["EXPIRE", key, 2 * 24 * 3600], ["GET", f"bonus:{user_id}"], ["INCR", "stats:gens"]],
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()
        count = results[0]["result"]
        bonus = int(results[2]["result"] or 0)
    except Exception as error:
        # Если база недоступна, не мешаем пользоваться ботом.
        print("Limit error:", repr(error))
        return True
    return count <= daily_limit(bonus)


# За каждого приглашённого друга — столько генераций в день сверху (но не больше BONUS_CAP).
BONUS_PER_FRIEND = int(os.environ.get("BONUS_PER_FRIEND", "5"))
BONUS_CAP = int(os.environ.get("BONUS_CAP", "50"))


def daily_limit(bonus=0):
    return DAILY_LIMIT + min(int(bonus or 0), BONUS_CAP)


def user_limit(user_id):
    return daily_limit(load(f"bonus:{user_id}") or 0)


def first_time(key, ttl=3600):
    """True, если ключ встречается впервые (общий для всех копий бота, если база подключена)."""
    if not (REDIS_URL and REDIS_TOKEN):
        return True
    try:
        response = requests.post(
            f"{REDIS_URL}/pipeline",
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            json=[["SET", f"seen:{key}", "1", "NX", "EX", ttl]],
            timeout=10,
        )
        response.raise_for_status()
        return response.json()[0]["result"] == "OK"
    except Exception as error:
        print("Dedupe error:", repr(error))
        return True


# ---------- хранилище личных ключей пользователей ----------

def store_enabled():
    """Есть ли база, где можно хранить данные пользователей (Upstash Redis)."""
    return bool(REDIS_URL and REDIS_TOKEN)


def _redis(*commands):
    response = requests.post(
        f"{REDIS_URL}/pipeline",
        headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
        json=list(commands),
        timeout=10,
    )
    response.raise_for_status()
    return [item.get("result") for item in response.json()]


def save(key, value, ttl):
    if store_enabled():
        _redis(["SET", key, value, "EX", int(ttl)])


def load(key):
    if not store_enabled():
        return None
    try:
        return _redis(["GET", key])[0]
    except Exception as error:
        print("Store read error:", repr(error))
        return None


def remove(key):
    if store_enabled():
        _redis(["DEL", key])


# ---------- пользователи, статистика, приглашения ----------

def track_user(user_id):
    """Запоминает пользователя. True, если он пишет боту впервые."""
    if not store_enabled():
        return False
    try:
        return _redis(["SADD", "users", str(user_id)])[0] == 1
    except Exception as error:
        print("Track error:", repr(error))
        return False


def stats():
    """(сколько людей пользовались ботом, сколько сделано генераций) или None без базы."""
    if not store_enabled():
        return None
    try:
        users, gens = _redis(["SCARD", "users"], ["GET", "stats:gens"])
        return int(users or 0), int(gens or 0)
    except Exception as error:
        print("Stats error:", repr(error))
        return None


def reward_referrer(referrer_id, new_user_id):
    """Новый пользователь пришёл по приглашению — пригласившему бонус. True, если начислено."""
    if not store_enabled() or str(referrer_id) == str(new_user_id):
        return False
    try:
        added, _ = _redis(
            ["SET", f"invited:{new_user_id}", str(referrer_id), "NX"],
            ["SADD", f"friends:{referrer_id}", str(new_user_id)],
        )
        if added != "OK":
            return False
        _redis(["INCRBY", f"bonus:{referrer_id}", BONUS_PER_FRIEND])
        return True
    except Exception as error:
        print("Referral error:", repr(error))
        return False


def friends_count(user_id):
    if not store_enabled():
        return 0
    try:
        return int(_redis(["SCARD", f"friends:{user_id}"])[0] or 0)
    except Exception:
        return 0
