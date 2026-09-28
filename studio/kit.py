"""
Набор инструментов для сцен.  В каждой сцене пишется:

    from studio.kit import *

Кадр `fr` — это массив numpy размером H x W x 3 (RGB, 0..255).
Все координаты — в пикселях кадра 1920 x 1080.
Полезная (видимая) область между чёрными полосами: от VY до VY+VH по вертикали.
"""
import math
import os
import re
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

__all__ = [
    # размеры и цвета
    'W', 'H', 'VY', 'VH', 'CREAM', 'EMBER', 'RED', 'WHITE', 'BLACK',
    # математика и плавности
    'math', 'np', 'cv2', 'clamp', 'prog', 'lerp', 'oc', 'ic', 'ioc', 'oexp', 'iexp', 'oback', 'obounce',
    # тексты
    'tx', 'text', 'serif', 'bold', 'text_size',
    # картинки и видео
    'image', 'sprite', 'portrait', 'kb', 'place', 'blit', 'video', 'video_info', 'cover', 'contain', 'safe_area',
    # готовые эффекты (см. вкладку «Эффекты»)
    'effect',
    # эффекты кадра
    'fill', 'darkbg', 'dim', 'blur', 'grayscale', 'shade_bottom', 'glow_circle', 'glow_ellipse',
    'dust', 'embers', 'card', 'diamond',
]

W, H = 1920, 1080
VY, VH = 138, 804            # кинополосы 2.39:1

CREAM = (236, 228, 214)
EMBER = (235, 125, 45)
RED = (215, 55, 40)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# ---- заполняется движком ----
PROJECT = '.'
TEXTS = {}
USED = set()
NEW_DEFAULTS = {}
ASSETS_USED = set()
ASSET_DIRS = []           # где искать картинки/видео (по умолчанию PROJECT/assets)
FONT_DIRS = []            # где искать шрифты (по умолчанию PROJECT/fonts)
FONT_ROLES = {}           # роль -> файл шрифта: {'title': 'oswald', 'serif': 'corm_i', 'text': 'oswald'}
DEFAULT_ROLES = {'title': 'oswald', 'serif': 'corm_i', 'text': 'oswald'}
LETTERBOX = True          # включены ли кинополосы (из Настроек) — от этого зависит «видимая область»


def safe_area():
    """(y0, высота) области кадра, которую видно: между кинополосами или весь кадр, если полос нет."""
    return (VY, VH) if LETTERBOX else (0, H)


class _LRU(OrderedDict):
    """Кэш с ограничением по объёму (байты numpy-массивов) или по числу элементов."""

    def __init__(self, max_bytes=None, max_items=None):
        super().__init__()
        self.max_bytes, self.max_items, self.bytes = max_bytes, max_items, 0

    def get(self, k, d=None):
        if k in self:
            self.move_to_end(k)
            return self[k]
        return d

    def put(self, k, v):
        if k in self:
            self.bytes -= getattr(self[k], 'nbytes', 0)
        self[k] = v
        self.move_to_end(k)
        self.bytes += getattr(v, 'nbytes', 0)
        while len(self) > 1 and ((self.max_bytes and self.bytes > self.max_bytes) or
                                 (self.max_items and len(self) > self.max_items)):
            _, old = self.popitem(last=False)
            self.bytes -= getattr(old, 'nbytes', 0)
        return v


# ================================================================ math
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, a, b):
    """0 до момента a, 1 после момента b, плавно между ними."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def lerp(a, b, k):
    return a + (b - a) * k


def oc(x):   return 1 - (1 - x) ** 3                    # ease-out cubic
def ic(x):   return x ** 3                               # ease-in cubic
def ioc(x):  return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2   # in-out cubic
def oexp(x): return 1 if x >= 1 else 1 - 2 ** (-10 * x)
def iexp(x): return 0 if x <= 0 else 2 ** (10 * x - 10)


def oback(x):
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def obounce(x):
    n, d = 7.5625, 2.75
    if x < 1 / d: return n * x * x
    if x < 2 / d: x -= 1.5 / d; return n * x * x + .75
    if x < 2.5 / d: x -= 2.25 / d; return n * x * x + .9375
    x -= 2.625 / d; return n * x * x + .984375


# ================================================================ texts
def tx(key, default=''):
    """Текст из вкладки «Тексты». Если ключа ещё нет — он появится там со значением default.
    Внутри текста можно ссылаться на другие ключи: '{name_5} didn’t come back.'
    С фильтром: {name_5|title} -> Denis, {name_5|upper} -> DENIS, {name_5|lower} -> denis."""
    USED.add(key)
    if key in TEXTS:
        s = TEXTS[key]
    else:
        s = default
        TEXTS[key] = default
        NEW_DEFAULTS[key] = default

    def sub(m):
        k, f = m.group(1), m.group(2)
        if k in TEXTS and k != key:
            USED.add(k)
            v = str(TEXTS[k])
            if f == 'title': v = v[:1].upper() + v[1:].lower()
            elif f == 'upper': v = v.upper()
            elif f == 'lower': v = v.lower()
            return v
        return m.group(0)
    return re.sub(r'\{(\w+)(?:\|(title|upper|lower))?\}', sub, str(s))


_FONTS = _LRU(max_items=160)


def font_role(fam):
    """'title' / 'serif' / 'text' -> файл шрифта, выбранный в Настройках; иначе — само имя файла."""
    if fam in FONT_ROLES:
        return FONT_ROLES[fam]
    return DEFAULT_ROLES.get(fam, fam)


def _font_path(fam):
    for d in (FONT_DIRS or [os.path.join(PROJECT, 'fonts')]):
        for ext in ('.ttf', '.otf', '.TTF', '.OTF', ''):
            p = os.path.join(d, fam + ext)
            if os.path.isfile(p):
                return p
    return None


def _font(fam, weight, size):
    fam = font_role(fam)
    k = (fam, weight, int(size))
    f = _FONTS.get(k)
    if f is None:
        path = _font_path(fam)
        if path is None:
            raise FileNotFoundError("Шрифт '%s' не найден в папке fonts/" % fam)
        f = ImageFont.truetype(path, int(size))
        try:
            ax = f.get_variation_axes()
            if ax:
                lo, hi = ax[0].get('minimum', weight), ax[0].get('maximum', weight)
                f.set_variation_by_axes([max(lo, min(hi, weight))])
        except Exception:
            pass
        _FONTS.put(k, f)
    return f


_TL = {}


def _tlayer(s, fam, w, size, color, track, shadow):
    k = (s, fam, w, size, color, track, shadow)
    if k in _TL:
        return _TL[k]
    if len(_TL) > 400:
        _TL.clear()
    f = _font(fam, w, size)
    pad = 40
    widths = [f.getlength(c) for c in s]
    tw = sum(widths) + track * size * max(0, len(s) - 1)
    asc, desc = f.getmetrics()
    im = Image.new('RGBA', (int(tw) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = pad
    for c, wd in zip(s, widths):
        d.text((x, pad), c, font=f, fill=tuple(color) + (255,))
        x += wd + track * size
    a = np.array(im)
    if shadow:
        al = a[..., 3].astype(np.float32)
        sh = cv2.GaussianBlur(al, (0, 0), 10) * 0.75
        outa = al / 255 + sh / 255 * (1 - al / 255)
        rgbc = a[..., :3].astype(np.float32) * (al / 255)[..., None] / np.maximum(outa, 1e-4)[..., None]
        a = np.dstack([rgbc, outa * 255]).clip(0, 255).astype(np.uint8)
    _TL[k] = a
    return a


def text_size(s, fam='text', w=400, size=60, track=0.0):
    """Ширина и высота строки в пикселях."""
    f = _font(fam, w, size)
    tw = sum(f.getlength(c) for c in s) + track * size * max(0, len(s) - 1)
    asc, desc = f.getmetrics()
    return tw, asc + desc


def blit(fr, a, x, y, op=1.0):
    """Наложить RGBA-картинку `a` левым верхним углом в точку (x, y) с прозрачностью op."""
    h, w = a.shape[:2]
    x = int(round(x)); y = int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fr.shape[1], x + w), min(fr.shape[0], y + h)
    if x1 <= x0 or y1 <= y0 or op <= 0:
        return
    s = a[y0 - y:y1 - y, x0 - x:x1 - x]
    if s.shape[2] == 3:
        al = np.full(s.shape[:2] + (1,), op, np.float32)
    else:
        al = s[..., 3:4].astype(np.float32) / 255 * op
    reg = fr[y0:y1, x0:x1].astype(np.float32)
    fr[y0:y1, x0:x1] = (reg * (1 - al) + s[..., :3] * al).astype(np.uint8)


def text(fr, t, t0, t1, s, cx, cy, align='c', rise=18, blur=True, fin=0.6, fout=0.5,
         fam='text', w=400, size=60, color=CREAM, track=0.0, shadow=True):
    """Текст, который появляется в момент t0 и исчезает к моменту t1.
    align: 'c' — по центру от cx, 'l' — от левого края cx, 'r' — до правого края cx.
    fam: 'title' / 'serif' / 'text' — шрифты из Настроек, или имя файла из папки fonts/.
    Возвращает (x, y, ширина, высота) надписи или None, если она не видна."""
    if t < t0 or t > t1 or not s:
        return None
    a = _tlayer(s, fam, w, int(size), tuple(color), track, shadow)
    ei = oc(prog(t, t0, t0 + fin)) if fin > 0 else 1.0
    eo = prog(t, t1 - fout, t1) if fout > 0 else 0.0
    op = ei * (1 - eo)
    if op <= 0.01:
        return None
    if blur:
        sg = (1 - ei) * 7 + eo * 5
        if sg > 0.4:
            a = cv2.GaussianBlur(a, (0, 0), sg)
    h, wd = a.shape[:2]
    x = cx - wd / 2 if align == 'c' else (cx - 40 if align == 'l' else cx - wd + 40)
    y = cy - h / 2 + (1 - ei) * rise - eo * rise * 0.5
    blit(fr, a, x, y, op)
    return (x + 40, y + 40, wd - 80, h - 80)


def serif(fr, t, t0, t1, s, cy=VY + VH - 120, size=68, cx=W / 2, **k):
    """Курсивная кинематографичная строка (по умолчанию — внизу кадра, как субтитр)."""
    k.setdefault('color', CREAM)
    k.setdefault('fam', 'serif')
    return text(fr, t, t0, t1, s, cx, cy, w=500, size=size, track=0.01, **k)


def bold(fr, t, t0, t1, s, cy=H / 2, size=150, cx=W / 2, color=CREAM, track=0.08, **k):
    """Крупный жирный заголовок."""
    k.setdefault('fam', 'title')
    return text(fr, t, t0, t1, s, cx, cy, w=700, size=size, color=color, track=track, **k)


# ================================================================ images
_IMG = _LRU(max_bytes=700 << 20)
IMG_EXTS = ('', '.png', '.jpg', '.jpeg', '.webp')
VID_EXTS = ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi')


def _path(name, exts=IMG_EXTS, what='Картинка'):
    for d in (ASSET_DIRS or [os.path.join(PROJECT, 'assets')]):
        for ext in exts:
            p = os.path.join(d, name + ext)
            if os.path.isfile(p):
                ASSETS_USED.add(name)
                return p
    raise FileNotFoundError("%s '%s' не найдена в папке assets/" % (what, name))


def _mt(p):
    return os.path.getmtime(p)


def _lut(fn):
    x = np.arange(256, dtype=np.float32)
    return np.clip(fn(x), 0, 255).astype(np.uint8)


def _saturate(a, sat):
    """Насыщенность: 0 — ч/б, 1 — без изменений, >1 — сочнее (быстро, без float-кадра)."""
    if abs(sat - 1) < 1e-3:
        return a
    g = cv2.cvtColor(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    return cv2.addWeighted(a, sat, g, 1 - sat, 0)


def _grade(a, sat, con, bright, tint):
    a = _saturate(a[..., :3], sat)
    tint = tuple(tint)
    if (con, bright, tint) == (1.0, 1.0, (1, 1, 1)):
        return a if a.flags['C_CONTIGUOUS'] else np.ascontiguousarray(a)
    ch = cv2.split(a)
    out = [cv2.LUT(c, _lut(lambda x, m=m: ((x / 255 - 0.5) * con + 0.5) * bright * m * 255)) for c, m in zip(ch, tint)]
    return cv2.merge(out)


def image(name, sat=1.0, con=1.0, bright=1.0, tint=(1, 1, 1), blur=0):
    """Картинка из assets/ (RGB) с цветокоррекцией:
    sat — насыщенность, con — контраст, bright — яркость, tint — множители (R, G, B)."""
    p = _path(name)
    key = ('img', p, _mt(p), sat, con, bright, tuple(tint), blur)
    a = _IMG.get(key)
    if a is None:
        a = np.array(Image.open(p).convert('RGB'))
        if (sat, con, bright, tuple(tint)) != (1.0, 1.0, 1.0, (1, 1, 1)):
            a = _grade(a, sat, con, bright, tint)
        if blur:
            a = cv2.GaussianBlur(a, (0, 0), blur)
        _IMG.put(key, a)
    return a


def sprite(name):
    """Картинка с прозрачностью (RGBA) из assets/ — для place()."""
    p = _path(name)
    key = ('spr', p, _mt(p))
    a = _IMG.get(key)
    if a is None:
        a = _IMG.put(key, np.array(Image.open(p).convert('RGBA')))
    return a


def portrait(name, w, h, sharpen=0.6):
    """Маленькую картинку увеличить до w x h с повышением резкости."""
    p = _path(name)
    key = ('por', p, _mt(p), int(w), int(h), sharpen)
    f = _IMG.get(key)
    if f is None:
        f = cv2.resize(image(name), (int(w), int(h)), interpolation=cv2.INTER_CUBIC)
        if sharpen:
            bl = cv2.GaussianBlur(f, (0, 0), 2)
            f = cv2.addWeighted(f, 1 + sharpen, bl, -sharpen, 0)
        _IMG.put(key, f)
    return f


def video(name, t, start=0.0, speed=1.0, loop=True, sat=1.0, con=1.0, bright=1.0, tint=(1, 1, 1), blur=0):
    """Кадр видео из assets/ (RGB) для момента сцены t.
    start — с какой секунды файла начать (подрезка), speed — скорость, loop — зациклить.
    Дальше кадр используется как картинка: cover(fr, video('beach', t)) или kb(fr, video(...), ...)."""
    from . import media
    p = _path(name, VID_EXTS, 'Видео')
    a = media.frame_at(p, start + max(0.0, t) * speed, loop)
    if (sat, con, bright, tuple(tint)) != (1.0, 1.0, 1.0, (1, 1, 1)):
        a = _grade(a, sat, con, bright, tint)
    if blur:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    return a


def video_info(name):
    """Длина и размер видео: dict(w, h, fps, frames, dur)."""
    from . import media
    return media.info(_path(name, VID_EXTS, 'Видео'))


def _area(area):
    if area == 'full':
        return (0, 0, W, H)
    y0, h = safe_area()
    return (0, y0, W, h)


def cover(fr, img, zoom=1.0, fx=0.5, fy=0.5, area='visible', dx=0.0, dy=0.0, op=1.0):
    """Заполнить кадр картинкой/кадром видео целиком (лишнее обрезается).
    zoom > 1 — крупнее, fx/fy (0..1) — какую часть картинки держать в центре,
    area='visible' — только между кинополосами, 'full' — весь кадр; dx, dy — сдвиг в пикселях."""
    x0, y0, aw, ah = _area(area)
    h, w = img.shape[:2]
    s = max(aw / w, ah / h) * zoom
    cx = w * fx
    cy = h * fy
    # не показывать края: держать центр так, чтобы картинка покрывала область
    hw, hh = aw / 2 / s, ah / 2 / s
    cx = min(max(cx, hw), w - hw) if w > 2 * hw else w / 2
    cy = min(max(cy, hh), h - hh) if h > 2 * hh else h / 2
    M = np.float32([[s, 0, x0 + aw / 2 - cx * s + dx], [0, s, y0 + ah / 2 - cy * s + dy]])
    _warp_into(fr, img, M, (x0, y0, aw, ah), op)


def contain(fr, img, zoom=1.0, area='visible', dx=0.0, dy=0.0, op=1.0):
    """Вписать картинку целиком (с полями), по центру области."""
    x0, y0, aw, ah = _area(area)
    h, w = img.shape[:2]
    s = min(aw / w, ah / h) * zoom
    M = np.float32([[s, 0, x0 + aw / 2 - w / 2 * s + dx], [0, s, y0 + ah / 2 - h / 2 * s + dy]])
    _warp_into(fr, img, M, (x0, y0, aw, ah), op)


def _warp_into(fr, img, M, rect, op=1.0):
    x0, y0, aw, ah = [int(round(v)) for v in rect]
    M = M.copy()
    M[0, 2] -= x0
    M[1, 2] -= y0
    if img.shape[2] == 3 and op >= 0.999:
        sub = cv2.warpAffine(img, M, (aw, ah), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        # края, куда картинка не попала, оставить как были
        mask = cv2.warpAffine(np.full(img.shape[:2], 255, np.uint8), M, (aw, ah), flags=cv2.INTER_NEAREST)
        reg = fr[y0:y0 + ah, x0:x0 + aw]
        np.copyto(reg, sub, where=mask[..., None] > 0)
        return
    src = img if img.shape[2] == 4 else np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    sub = cv2.warpAffine(src, M, (aw, ah), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    blit(fr[y0:y0 + ah, x0:x0 + aw], sub, 0, 0, op)


def effect(fr, t, dur, name, /, **params):
    """Готовый эффект из вкладки «Эффекты» прямо из кода: effect(fr, t, dur, 'glitch', amount=0.6).
    t0/t1 — когда эффект активен (по умолчанию — вся сцена)."""
    from . import fx
    fx.apply(fr, t, dur, dict(params, name=name))


def kb(fr, src, cx, cy, w, shift=(0, 0)):
    """«Камера» над картинкой src: показать участок шириной w пикселей с центром (cx, cy)
    в координатах самой картинки. Меняйте cx, cy, w во времени — получится наезд/панорама."""
    h = w * VH / W
    s = W / w
    M = np.float32([[s, 0, -(cx - w / 2) * s + shift[0]], [0, s, -(cy - h / 2) * s + VY + shift[1]]])
    cv2.warpAffine(src, M, (fr.shape[1], fr.shape[0]), dst=fr, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def place(fr, spr, cx, cy, sc=1.0, ang=0, op=1.0):
    """Поставить спрайт центром в (cx, cy): sc — масштаб, ang — поворот в градусах, op — прозрачность."""
    if op <= 0:
        return
    h, w = spr.shape[:2]
    if spr.shape[2] == 3:
        spr = np.dstack([spr, np.full((h, w), 255, np.uint8)])
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    c = np.abs(M[:, :2]) @ np.array([w, h])
    bw, bh = int(c[0]) + 4, int(c[1]) + 4
    M[0, 2] += bw / 2 - w / 2
    M[1, 2] += bh / 2 - h / 2
    wa = cv2.warpAffine(spr, M, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    blit(fr, wa, cx - bw / 2, cy - bh / 2, op)


def card(img, border=8, color=(55, 48, 40)):
    """Рамка вокруг картинки (для портретов). Возвращает RGBA для blit/place."""
    h, w = img.shape[:2]
    c = np.zeros((h + border * 2, w + border * 2, 4), np.uint8)
    c[..., :3] = color
    c[..., 3] = 255
    c[border:border + h, border:border + w, :3] = img[..., :3]
    return c


# ================================================================ frame fx
def fill(fr, color):
    fr[:] = color


def darkbg(fr, color=(22, 16, 12)):
    """Чёрный кадр с тёмной заливкой рабочей области."""
    fr[:] = 0
    fr[VY:VY + VH] = color


def dim(fr, k):
    """Умножить яркость кадра на k (0 — чёрный, 1 — без изменений)."""
    cv2.convertScaleAbs(fr, dst=fr, alpha=max(0.0, k))


def blur(fr, sigma):
    if sigma > 0.3:
        fr[:] = cv2.GaussianBlur(fr, (0, 0), sigma)


def grayscale(fr, k=1.0):
    g = cv2.cvtColor(cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
    fr[:] = cv2.addWeighted(fr, 1 - k, g, k, 0)


def shade_bottom(fr, h=260, k=0.35):
    """Затемнить низ кадра (под субтитры)."""
    y1 = VY + VH
    fr[y1 - h:y1] = (fr[y1 - h:y1].astype(np.float32) * np.linspace(1, k, h)[:, None, None]).astype(np.uint8)


_GLOW = {}


def _glow(key, draw, sigma):
    """Мягкое пятно света: рисуется в 1/4 размера и растягивается — в десятки раз быстрее."""
    g = _GLOW.get(key)
    if g is None:
        q = 4
        sm = np.zeros((H // q, W // q, 3), np.uint8)
        draw(sm, q)
        sm = cv2.GaussianBlur(sm, (0, 0), max(0.5, sigma / q))
        g = cv2.resize(sm, (W, H), interpolation=cv2.INTER_LINEAR)
        if len(_GLOW) > 60:
            _GLOW.clear()
        _GLOW[key] = g
    return g


def glow_circle(fr, x, y, r, color, sigma=120, amount=1.0):
    """Мягкое свечение-круг (добавляется к кадру)."""
    c = tuple(int(v) for v in color)
    g = _glow(('c', int(x), int(y), int(r), c, sigma),
              lambda sm, q: cv2.circle(sm, (int(x / q), int(y / q)), max(1, int(r / q)), c, -1, cv2.LINE_AA), sigma)
    _add(fr, g, amount)


def glow_ellipse(fr, x, y, rx, ry, color, sigma=120, amount=1.0):
    """Мягкое свечение-эллипс (добавляется к кадру)."""
    c = tuple(int(v) for v in color)
    g = _glow(('e', int(x), int(y), int(rx), int(ry), c, sigma),
              lambda sm, q: cv2.ellipse(sm, (int(x / q), int(y / q)), (max(1, int(rx / q)), max(1, int(ry / q))), 0, 0,
                                        360, c, -1, cv2.LINE_AA), sigma)
    _add(fr, g, amount)


def _add(fr, g, amount):
    if amount >= 0.999:
        cv2.add(fr, g, dst=fr)
    else:
        cv2.addWeighted(fr, 1, g, amount, 0, dst=fr)


_R = np.random.default_rng(5)
_DUST = _R.random((200, 5))
_EMB = _R.random((160, 5))


def dust(fr, t, n=140, col=(200, 190, 170), amt=0.5):
    """Пылинки, летящие в воздухе."""
    ov = np.zeros_like(fr)
    for i in range(min(n, len(_DUST))):
        x0, y0, sp, sz, ph = _DUST[i]
        x = (x0 * W + t * (12 + sp * 30)) % W
        y = VY + ((y0 * VH - t * (6 + sp * 14) + math.sin(t * 0.7 + ph * 6) * 20) % VH)
        cv2.circle(ov, (int(x), int(y)), 1 + int(sz * 2.2), tuple(col), -1, cv2.LINE_AA)
    cv2.addWeighted(fr, 1, ov, amt, 0, dst=fr)


def embers(fr, t, amt=1.0, n=110):
    """Поднимающиеся искры."""
    ov = np.zeros_like(fr)
    for i in range(min(n, len(_EMB))):
        x0, sp, sz, ph, lf = _EMB[i]
        life = (t * (0.15 + sp * 0.25) + ph) % 1
        x = x0 * W + math.sin(t * 1.3 + ph * 9) * 40 + life * 60
        y = VY + VH * (1.05 - life * 1.1)
        br = math.sin(life * math.pi) * (0.6 + 0.4 * math.sin(t * 9 + ph * 20))
        c = (int(255 * br), int(120 * br), int(40 * br))
        cv2.circle(ov, (int(x), int(y)), 1 + int(sz * 3), c, -1, cv2.LINE_AA)
    sm = cv2.resize(ov, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    ov2 = cv2.resize(cv2.GaussianBlur(sm, (0, 0), 1.5), (W, H))
    cv2.addWeighted(fr, 1, ov, amt, 0, dst=fr)
    cv2.addWeighted(fr, 1, ov2, amt * 1.5, 0, dst=fr)


def diamond(fr, x, y, r, color, op=1.0):
    """Маленький ромб (маркер задачи)."""
    pts = np.array([[x, y - r], [x + r, y], [x, y + r], [x - r, y]], np.int32)
    if op >= 0.999:
        cv2.fillPoly(fr, [pts], tuple(color), cv2.LINE_AA)
    else:
        ov = fr.copy()
        cv2.fillPoly(ov, [pts], tuple(color), cv2.LINE_AA)
        cv2.addWeighted(ov, op, fr, 1 - op, 0, dst=fr)
