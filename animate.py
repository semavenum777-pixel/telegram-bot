"""Анимированные (видео) стикеры из обычного стикера — без нейросети.

Telegram принимает видео-стикеры в формате WEBM (VP9) с прозрачностью:
512 px по большей стороне, до 3 секунд, до 30 кадров в секунду, до 256 КБ, без звука.
"""

import math
import os
import shutil
import stat
import subprocess
import tempfile

from PIL import Image

import stickers

SIZE = 512
FPS = 30
SECONDS = 2
MAX_BYTES = 256 * 1024

# Ключ → подпись на кнопке.
EFFECTS = {
    "wobble": "🫨 Покачивание",
    "bounce": "🦘 Прыжки",
    "pulse": "💓 Пульс",
    "spin": "🌀 Вертушка",
    "shake": "😤 Тряска",
}


def _ffmpeg():
    import imageio_ffmpeg

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    if os.access(exe, os.X_OK):
        return exe
    # На хостинге файл может оказаться без права на запуск — копируем во временную папку.
    copy = os.path.join(tempfile.gettempdir(), "ffmpeg")
    if not os.path.exists(copy):
        shutil.copy(exe, copy)
        os.chmod(copy, os.stat(copy).st_mode | stat.S_IEXEC)
    return copy


def _frame(base, effect, t):
    """Один кадр: t от 0 до 1 — доля пройденной анимации (зациклена)."""
    angle, scale_x, scale_y, dx, dy = 0.0, 1.0, 1.0, 0.0, 0.0
    wave = math.sin(2 * math.pi * t)

    if effect == "wobble":
        angle = 10 * wave
    elif effect == "bounce":
        jump = abs(math.sin(2 * math.pi * t))  # два прыжка за цикл
        dy = -60 * jump
        squash = 1 - jump  # у «земли» сплющиваемся
        scale_x, scale_y = 1 + 0.08 * squash, 1 - 0.08 * squash
    elif effect == "pulse":
        beat = max(0.0, math.sin(4 * math.pi * t)) ** 3  # два удара сердца
        scale_x = scale_y = 1 + 0.12 * beat
    elif effect == "spin":
        angle = -360 * t
    elif effect == "shake":
        dx = 10 * math.sin(2 * math.pi * 8 * t)
        angle = 3 * math.sin(2 * math.pi * 6 * t)

    image = base
    if scale_x != 1 or scale_y != 1:
        image = image.resize((max(1, int(base.width * scale_x)), max(1, int(base.height * scale_y))), Image.BICUBIC)
    if angle:
        image = image.rotate(angle, resample=Image.BICUBIC, expand=True)

    frame = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    x = int((SIZE - image.width) / 2 + dx)
    y = int((SIZE - image.height) / 2 + dy + (30 if effect == "bounce" else 0))
    # alpha_composite не принимает отрицательные координаты — обрезаем вылезающую часть.
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(image.width, SIZE - x), min(image.height, SIZE - y)
    if right > left and bottom > top:
        frame.alpha_composite(image.crop((left, top, right, bottom)), (x + left, y + top))
    return frame


def _encode(frames, crf):
    raw = b"".join(frame.tobytes() for frame in frames)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as out:
        path = out.name
    try:
        subprocess.run(
            [
                _ffmpeg(), "-y", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{SIZE}x{SIZE}", "-r", str(FPS), "-i", "-",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", str(crf),
                "-deadline", "realtime", "-cpu-used", "8", "-an", "-t", str(SECONDS), path,
            ],
            input=raw,
            check=True,
            timeout=60,
        )
        with open(path, "rb") as file:
            return file.read()
    finally:
        os.remove(path)


def make_video_sticker(image, effect):
    """Возвращает байты WEBM-стикера с анимацией effect."""
    # Оставляем место по краям, чтобы при движении стикер не обрезался.
    room = 0.78 if effect in ("spin", "wobble") else 0.84
    base = stickers.fit_to_sticker(image)
    base.thumbnail((int(SIZE * room), int(SIZE * room)), Image.LANCZOS)

    count = FPS * SECONDS
    frames = [_frame(base, effect, i / count) for i in range(count)]

    for crf in (34, 42, 50, 58):
        video = _encode(frames, crf)
        if len(video) <= MAX_BYTES:
            return video
    return video
