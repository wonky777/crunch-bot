"""Карточка с QR в стиле CRUNCH!: малиновый фон, бабблгам-шрифт, логотип."""
import io
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
PINK = (254, 35, 117)       # фон бренда
CREAM = (255, 232, 241)     # светло-розовый (текст логотипа)
SOFT = (255, 150, 190)      # блики
BERRY = (122, 8, 52)        # модули QR — тёмные, чтобы камера читала без проблем
W, H = 1080, 1560


def _font(size: int, weight: int = 900) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(os.path.join(ASSETS, "font.ttf"), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _center(d, text, y, font, fill, spacing=0):
    if spacing:
        widths = [d.textlength(ch, font=font) for ch in text]
        x = (W - (sum(widths) + spacing * (len(text) - 1))) / 2
        for ch, w in zip(text, widths):
            d.text((x, y), ch, font=font, fill=fill)
            x += w + spacing
    else:
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill=fill)


def _sparkle(d, cx, cy, r, fill):
    k = r * 0.22
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
               (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def make_qr(payload: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=16, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(back_color=(255, 255, 255), front_color=BERRY),
    ).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def render_card(code: str, payload: str) -> bytes:
    img = Image.new("RGB", (W, H), PINK)
    d = ImageDraw.Draw(img)

    # логотип (вырезан из фирменной картинки на том же фоне — швов не видно)
    logo = Image.open(os.path.join(ASSETS, "logo.png")).convert("RGB")
    lw = 820
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    img.paste(logo, ((W - lw) // 2, 50))

    _center(d, "Бесплатный CRUNCH", 520, _font(72), CREAM)

    # белая плашка с QR
    px0, py0, pw = 190, 625, 700
    d.rounded_rectangle((px0 + 0, py0 + 10, px0 + pw, py0 + pw + 10), 56, fill=(200, 10, 85))  # тень
    d.rounded_rectangle((px0, py0, px0 + pw, py0 + pw), 56, fill=(255, 255, 255))
    qr = make_qr(payload, 600)
    img.paste(qr, (px0 + 50, py0 + 50))

    _center(d, code, 1350, _font(78), CREAM, spacing=14)
    _center(d, "покажи на кассе · @crunch.krd", 1470, _font(36, 800), SOFT)

    for cx, cy, r in [(95, 640, 46), (985, 735, 34), (110, 1010, 30), (975, 1090, 48)]:
        _sparkle(d, cx, cy, r, CREAM)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
