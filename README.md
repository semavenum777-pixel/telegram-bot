# Telegram Sticker Bot

Бот превращает присланную картинку (фото или файл PNG/JPG/WEBP) в стикер 512×512 в формате WEBP.

## Запуск на Render

1. Создайте бота у [@BotFather](https://t.me/BotFather) и скопируйте токен.
2. На Render создайте **Web Service** из этого репозитория:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn main:app`
3. В Environment добавьте переменную `BOT_TOKEN` с токеном.
4. Задеплойте. Вебхук настроится автоматически (Render сам передаёт `RENDER_EXTERNAL_URL`).

## Переменные окружения

| Переменная | Обязательна | Описание |
|---|---|---|
| `BOT_TOKEN` | да | Токен от @BotFather |
| `WEBHOOK_URL` | нет | Публичный адрес сервиса, если хостинг не Render |
| `WEBHOOK_SECRET` | нет | Секрет для проверки запросов от Telegram (по умолчанию выводится из токена) |
