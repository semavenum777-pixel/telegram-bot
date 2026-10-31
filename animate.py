"""Анимированные (видео) стикеры из обычного стикера — без нейросети.

Telegram принимает видео-стикеры в формате WEBM (VP9) с прозрачностью:
512 px по большей стороне, до 3 секунд, до 30 кадров в секунду, до 256 КБ, без звука.
"""

import io
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


def _effect_frames(image, effect, fps=FPS):
    # Оставляем место по краям, чтобы при движении стикер не обрезался.
    room = 0.78 if effect in ("spin", "wobble") else 0.84
    base = stickers.fit_to_sticker(image)
    base.thumbnail((int(SIZE * room), int(SIZE * room)), Image.LANCZOS)
    count = fps * SECONDS
    return [_frame(base, effect, i / count) for i in range(count)]


def make_video_sticker(image, effect):
    """Возвращает байты WEBM-стикера с анимацией effect."""
    frames = _effect_frames(image, effect)

    for crf in (34, 42, 50, 58):
        video = _encode(frames, crf)
        if len(video) <= MAX_BYTES:
            return video
    return video


# ---------- GIF ----------

GIF_BACKGROUND = (255, 255, 255)
GIF_FPS = 20
MAX_GIF_SECONDS = 6


def _save_gif(frames, fps):
    output = io.BytesIO()
    first, rest = frames[0], frames[1:]
    first.save(
        output, format="GIF", save_all=True, append_images=rest,
        duration=int(1000 / fps), loop=0, optimize=True, disposal=2,
    )
    return output.getvalue()


def make_gif(image, effect):
    """Та же анимация, что у живого стикера, но GIF-файлом на белом фоне — чтобы отправить куда угодно."""
    frames = []
    for frame in _effect_frames(image, effect, fps=GIF_FPS):
        flat = Image.new("RGB", frame.size, GIF_BACKGROUND)
        flat.paste(frame, mask=frame.getchannel("A"))
        frames.append(flat.convert("P", palette=Image.ADAPTIVE, colors=128))
    return _save_gif(frames, GIF_FPS)


def _with_temp_input(data, suffix=".mp4"):
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(data)
    handle.close()
    return handle.name


def video_to_sticker(data):
    """GIF или короткое видео → видео-стикер Telegram (до 3 секунд, 512 px, VP9, до 256 КБ)."""
    source = _with_temp_input(data)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as out:
        path = out.name
    try:
        for fps, crf in ((30, 36), (24, 44), (20, 52), (15, 60)):
            subprocess.run(
                [
                    _ffmpeg(), "-y", "-loglevel", "error", "-i", source, "-t", "3",
                    "-vf", f"scale={SIZE}:{SIZE}:force_original_aspect_ratio=decrease,fps={fps}",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", str(crf),
                    "-deadline", "realtime", "-cpu-used", "8", "-an", path,
                ],
                check=True,
                timeout=90,
            )
            with open(path, "rb") as file:
                video = file.read()
            if len(video) <= MAX_BYTES:
                break
        return video
    finally:
        os.remove(source)
        os.remove(path)


def video_frames(data, fps=12, width=480):
    """Раскладывает GIF / видео на кадры (не больше MAX_GIF_SECONDS секунд)."""
    source = _with_temp_input(data)
    folder = tempfile.mkdtemp()
    try:
        subprocess.run(
            [
                _ffmpeg(), "-y", "-loglevel", "error", "-i", source, "-t", str(MAX_GIF_SECONDS),
                "-vf", f"fps={fps},scale={width}:-2", os.path.join(folder, "%04d.png"),
            ],
            check=True,
            timeout=90,
        )
        names = sorted(os.listdir(folder))
        return [Image.open(os.path.join(folder, name)).convert("RGB") for name in names]
    finally:
        os.remove(source)
        shutil.rmtree(folder, ignore_errors=True)


def make_meme_gif(data, top, bottom, fps=12):
    """Мем-GIF: на каждый кадр гифки пишем текст сверху и снизу."""
    frames = [
        stickers.draw_meme_text(frame, top, bottom).convert("P", palette=Image.ADAPTIVE, colors=128)
        for frame in video_frames(data, fps=fps)
    ]
    return _save_gif(frames, fps)
