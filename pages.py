"""Страница-витрина бота, которая открывается по адресу сайта на Vercel."""

import html

LANDING = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Стикеры из фото — @{username}</title>
<meta name="description" content="Telegram-бот, который делает стикеры из твоих фото: аниме, Pixar, LEGO, набор из 6 эмоций с твоим лицом, аватарки, мемы и новогодние открытки. Бесплатно.">
<meta property="og:title" content="Стикеры из фото — @{username}">
<meta property="og:description" content="Отправь селфи — получи свой стикерпак. Бесплатно, прямо в Telegram.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎨</text></svg>">
<style>
  :root {{
    --bg: #fbf7f2; --card: #ffffff; --text: #1d1b22; --muted: #6b6574;
    --accent: #2aabee; --accent-2: #ff7a59; --border: #ece5dc; --shadow: 0 10px 30px rgba(40, 30, 20, .08);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #141218; --card: #1e1b24; --text: #f3eff7; --muted: #a59fae;
      --border: #2d2834; --shadow: 0 10px 30px rgba(0, 0, 0, .35);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 17px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  }}
  .wrap {{ max-width: 1040px; margin: 0 auto; padding: 0 16px; }}
  header {{ padding: 56px 0 24px; text-align: center; }}
  .badge {{
    display: inline-block; padding: 6px 14px; border-radius: 999px; background: var(--card);
    border: 1px solid var(--border); color: var(--muted); font-size: 14px;
  }}
  h1 {{ font-size: clamp(34px, 6vw, 60px); line-height: 1.08; margin: 18px 0 14px; letter-spacing: -.02em; }}
  h1 span {{ background: linear-gradient(90deg, var(--accent), var(--accent-2)); -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .lead {{ color: var(--muted); font-size: clamp(17px, 2.4vw, 21px); max-width: 640px; margin: 0 auto 28px; }}
  .cta {{
    display: inline-flex; align-items: center; gap: 10px; padding: 16px 28px; border-radius: 16px;
    background: var(--accent); color: #fff; font-weight: 700; font-size: 18px; text-decoration: none;
    box-shadow: 0 8px 24px rgba(42, 171, 238, .35); transition: transform .15s ease;
  }}
  .cta:hover {{ transform: translateY(-2px); }}
  .note {{ color: var(--muted); font-size: 14px; margin-top: 12px; }}
  .stickers {{ display: flex; justify-content: center; flex-wrap: wrap; gap: 14px; margin: 40px 0 8px; }}
  .sticker {{
    width: 112px; height: 112px; border-radius: 28px; background: var(--card); border: 4px solid #fff;
    box-shadow: var(--shadow); display: grid; place-items: center; font-size: 54px; position: relative;
    animation: float 4s ease-in-out infinite;
  }}
  .sticker small {{
    position: absolute; bottom: 8px; font-size: 12px; font-weight: 800; color: #fff;
    -webkit-text-stroke: 3px #111; paint-order: stroke fill;
  }}
  .sticker:nth-child(2n) {{ animation-delay: -1.3s; transform: rotate(-4deg); }}
  .sticker:nth-child(3n) {{ animation-delay: -2.6s; transform: rotate(3deg); }}
  @keyframes float {{ 50% {{ translate: 0 -8px; }} }}
  @media (prefers-reduced-motion: reduce) {{ .sticker {{ animation: none; }} }}
  section {{ padding: 40px 0; }}
  h2 {{ font-size: clamp(26px, 4vw, 36px); text-align: center; margin: 0 0 28px; letter-spacing: -.01em; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 16px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 22px; padding: 22px;
    box-shadow: var(--shadow);
  }}
  .card .icon {{ font-size: 34px; }}
  .card h3 {{ margin: 10px 0 6px; font-size: 19px; }}
  .card p {{ margin: 0; color: var(--muted); font-size: 15.5px; }}
  .steps {{ counter-reset: step; }}
  .steps .card {{ position: relative; padding-top: 52px; }}
  .steps .card::before {{
    counter-increment: step; content: counter(step); position: absolute; top: 18px; left: 22px;
    width: 26px; height: 26px; border-radius: 50%; background: var(--accent-2); color: #fff;
    display: grid; place-items: center; font-weight: 800; font-size: 14px;
  }}
  code {{ background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 1px 6px; font-size: 14px; }}
  footer {{ text-align: center; padding: 40px 0 56px; }}
  footer .note {{ margin-top: 18px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="badge">🎨 Telegram-бот · бесплатно</span>
    <h1>Твоё селфи → <span>твой стикерпак</span></h1>
    <p class="lead">Отправь фото — нейросеть превратит тебя в аниме-героя, LEGO-человечка или мультяшку и сразу соберёт личный стикерпак.</p>
    <a class="cta" href="https://t.me/{username}">✈️ Открыть в Telegram</a>
    <div class="note">@{username} · без регистрации и оплаты</div>
    <div class="stickers" aria-hidden="true">
      <div class="sticker">😊<small>Ура!</small></div>
      <div class="sticker">😂<small>Ахаха</small></div>
      <div class="sticker">😍<small>Люблю</small></div>
      <div class="sticker">😮<small>Ого!</small></div>
      <div class="sticker">😡<small>Злюсь</small></div>
      <div class="sticker">🎄<small>С НГ!</small></div>
    </div>
  </header>

  <section>
    <h2>Что умеет бот</h2>
    <div class="grid">
      <div class="card"><div class="icon">😊</div><h3>Набор эмоций</h3><p>Одно селфи — 6 стикеров с твоим лицом: радость, грусть, злость, любовь, смех и удивление. Сразу в твоём паке.</p></div>
      <div class="card"><div class="icon">🎌</div><h3>12+ стилей</h3><p>Аниме, Pixar, LEGO, комикс, пиксель-арт, супергерой, плюшевая игрушка, Ван Гог и другие — одной кнопкой.</p></div>
      <div class="card"><div class="icon">✍️</div><h3>Надписи</h3><p>«Ок», «Спасибо», «Ахах» в одно касание или любой свой текст прямо на стикере.</p></div>
      <div class="card"><div class="icon">🖼</div><h3>Аватарки</h3><p>Картинка для профиля в любом стиле — скачай и поставь на аватар.</p></div>
      <div class="card"><div class="icon">😂</div><h3>Мемы</h3><p>Фото с подписью <code>/mem верх | низ</code> — и классический мем готов за секунду.</p></div>
      <div class="card"><div class="icon">🎁</div><h3>Новый год</h3><p>Дед Мороз, свитер с оленями, новогодний набор стикеров и открытки, которые хочется переслать всем.</p></div>
      <div class="card"><div class="icon">👥</div><h3>В групповых чатах</h3><p>Добавь бота в чат с друзьями и ответь на любое фото командой <code>/sticker</code>.</p></div>
      <div class="card"><div class="icon">🎲</div><h3>Удиви меня</h3><p>Нет идей? Бот сам нарисует капибару в джакузи или пингвина-диджея.</p></div>
    </div>
  </section>

  <section>
    <h2>Как это работает</h2>
    <div class="grid steps">
      <div class="card"><h3>Открой бота</h3><p>Нажми «Старт» в <a href="https://t.me/{username}">@{username}</a>.</p></div>
      <div class="card"><h3>Пришли фото</h3><p>Лучше селфи крупным планом при хорошем свете.</p></div>
      <div class="card"><h3>Выбери стиль</h3><p>Нажми кнопку — через несколько секунд стикер готов.</p></div>
      <div class="card"><h3>Собери пак</h3><p>«➕ В мой пак» — и стикеры уже у тебя и у друзей.</p></div>
    </div>
  </section>

  <footer>
    <a class="cta" href="https://t.me/{username}">Сделать свои стикеры</a>
    <div class="note">Работает на бесплатных нейросетях · @{username}</div>
  </footer>
</div>
</body>
</html>
"""


def landing_page(username):
    return LANDING.format(username=html.escape(username or "telegram"))
