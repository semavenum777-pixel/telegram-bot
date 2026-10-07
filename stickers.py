import io
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

STICKER_SIZE = 512
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")


def open_image(image_bytes):
    return Image.open(io.BytesIO(image_bytes)).convert("RGBA")


def to_png_bytes(image, max_side=None):
    if max_side and max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def fit_to_sticker(image):
    # Одна сторона должна быть ровно 512, другая — не больше 512.
    scale = STICKER_SIZE / max(image.size)
    new_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    return image.resize(new_size, Image.LANCZOS)


def remove_plain_background(image, threshold=40):
    """Делает прозрачным однотонный фон, заливая его от углов картинки."""
    rgb = image.convert("RGB")
    filled = rgb.copy()
    sentinel = (255, 0, 255)
    w, h = rgb.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if filled.getpixel(corner) != sentinel:
            ImageDraw.floodfill(filled, corner, sentinel, thresh=threshold)

    changed = ImageChops.difference(rgb, filled).convert("L").point(
        lambda value: 255 if value else 0
    )
    alpha = ImageChops.subtract(image.getchannel("A"), changed)

    result = image.copy()
    result.putalpha(alpha)

    bbox = alpha.getbbox()
    if bbox:
        result = result.crop(bbox)
    return result


def _load_font(size):
    return ImageFont.truetype(FONT_PATH, size)


def _wrap_text(draw, text, font, max_width):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def add_caption(image, text):
    """Пишет текст белыми буквами с чёрной обводкой внизу стикера."""
    image = fit_to_sticker(image)
    max_width = image.width - 24
    draw = ImageDraw.Draw(image)

    size = 72
    while True:
        font = _load_font(size)
        lines = _wrap_text(draw, text, font, max_width)
        widest = max(draw.textlength(line, font=font) for line in lines)
        line_height = size + 8
        if (widest <= max_width and len(lines) * line_height <= image.height / 3) or size <= 20:
            break
        size -= 4

    stroke = max(2, size // 12)
    y = image.height - len(lines) * line_height - 12
    for line in lines:
        x = (image.width - draw.textlength(line, font=font)) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )
        y += line_height
    return image


def make_sticker(image, caption=""):
    image = fit_to_sticker(image)
    if caption:
        image = add_caption(image, caption)

    output = io.BytesIO()
    image.save(output, format="WEBP")
    output.seek(0)
    return output
