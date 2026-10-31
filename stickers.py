import io
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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


def crop_square(image):
    """Квадрат по центру; у вертикальных фото чуть выше центра — там обычно лицо."""
    w, h = image.size
    if w / h > 1.6:
        return image  # широкий снимок (например, групповое фото) не режем
    side = min(w, h)
    left = (w - side) // 2
    top = int((h - side) * 0.3)
    return image.crop((left, top, left + side, top + side))


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


def has_transparency(image):
    alpha = image.getchannel("A")
    return alpha.getextrema()[0] < 250


def add_outline(image, width=10):
    """Белая обводка по контуру, как у стикеров Telegram."""
    image = fit_to_sticker(image)
    pad = width + 2
    canvas = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(image, (pad, pad))

    alpha = canvas.getchannel("A").point(lambda value: 255 if value > 40 else 0)
    outline = alpha.filter(ImageFilter.MaxFilter(2 * width + 1)).filter(ImageFilter.GaussianBlur(1))

    result = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    result.putalpha(outline)
    result.alpha_composite(canvas)
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


def make_sticker(image, caption="", outline=False):
    if outline and has_transparency(image):
        image = add_outline(image)
    image = fit_to_sticker(image)
    if caption:
        image = add_caption(image, caption)

    output = io.BytesIO()
    image.save(output, format="WEBP")
    output.seek(0)
    return output


def to_jpeg(image, quality=92):
    output = io.BytesIO()
    background = Image.new("RGB", image.size, "white")
    background.paste(image, mask=image.getchannel("A"))
    background.save(output, format="JPEG", quality=quality)
    output.seek(0)
    return output


def _draw_block(draw, text, width, top, max_height, fill, stroke_fill, from_bottom=False):
    """Текст по центру, автоматически уменьшается, чтобы влезть в ширину и высоту блока."""
    size = max(24, width // 9)
    while True:
        font = _load_font(size)
        lines = _wrap_text(draw, text, font, width * 0.92)
        line_height = int(size * 1.15)
        widest = max(draw.textlength(line, font=font) for line in lines)
        if (widest <= width * 0.92 and len(lines) * line_height <= max_height) or size <= 18:
            break
        size -= 4

    stroke = max(2, size // 12)
    y = top - len(lines) * line_height if from_bottom else top
    for line in lines:
        x = (width - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        y += line_height


def make_meme(image, top="", bottom=""):
    """Классический мем: белые заглавные буквы с чёрной обводкой сверху и снизу. Без нейросети."""
    image = image.copy()
    image.thumbnail((1080, 1080), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    margin = image.height // 30
    if top:
        _draw_block(draw, top.upper(), image.width, margin, image.height // 3, "white", "black")
    if bottom:
        _draw_block(draw, bottom.upper(), image.width, image.height - margin, image.height // 3, "white", "black", from_bottom=True)
    return to_jpeg(image)


def make_card(image, greeting):
    """Открытка: картинка и поздравление золотыми буквами внизу."""
    image = image.copy()
    image.thumbnail((1080, 1080), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    _draw_block(
        draw, greeting, image.width, image.height - image.height // 25, image.height // 4,
        (255, 215, 90), (90, 20, 20), from_bottom=True,
    )
    return to_jpeg(image)
