"""
Стиль ролика 01 «Игра про выживание вместе с Claude» (Seit Montag) — общие компоненты для всех сцен.

В сцене:
    from studio.kit import *
    from studio.looks.shelter01 import *

Всё по разделу «Стиль ролика» в omnipost-content/youtube-scripts/01-shelter-game-with-claude/scenes.md:
палитра «Ночь» (Midnight + Sky + Gold) из BRAND-COLORS.md, шрифты Montserrat / Manrope / JetBrains Mono,
компоненты (окна, пузыри чата, бейджи, код-карточка, терминал, lower third, мем-рамка…), переходы
(cut, whip, push, zoom-through, wipe, glitch + фирменные hatch и lamp-flicker) и звуки SFX-….

Все функции рисуют прямо в кадр `fr` и зависят только от времени `t` — кадры независимы.
Если файла (видео, картинки, мема, звука) нет — рисуется серая заглушка с именем файла / синтезируется звук.
"""
import math
import os
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image, ImageDraw

from studio import kit
from studio.kit import (clamp, prog, lerp, oc, ic, ioc, oexp, iexp, oback, tx)


def blit(fr, a, x, y, op=1.0):
    """Наложить RGB/RGBA-слой `a` левым верхним углом в (x, y) с прозрачностью op.
    Быстро (cv2.blendLinear вместо float-арифметики numpy); умеет рисовать и в RGBA-слой."""
    h, w = a.shape[:2]
    x = int(round(x)); y = int(round(y))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fr.shape[1], x + w), min(fr.shape[0], y + h)
    if x1 <= x0 or y1 <= y0 or op <= 0.003:
        return
    s = a[y0 - y:y1 - y, x0 - x:x1 - x]
    reg = fr[y0:y1, x0:x1]
    if s.shape[2] == 4:
        al = s[..., 3].astype(np.float32) * (op / 255.0)
    else:
        al = np.full(s.shape[:2], float(op), np.float32)
    if fr.shape[2] == 3:
        src = np.ascontiguousarray(s[..., :3])
        out = cv2.blendLinear(src, np.ascontiguousarray(reg), al, 1.0 - al)
        reg[:] = out
        return
    da = reg[..., 3].astype(np.float32) / 255
    oa = al + da * (1 - al)
    w1 = al / np.maximum(oa, 1e-4)
    rgb = cv2.blendLinear(np.ascontiguousarray(s[..., :3]), np.ascontiguousarray(reg[..., :3]), w1, 1.0 - w1)
    reg[..., :3] = rgb
    reg[..., 3] = (oa * 255).clip(0, 255).astype(np.uint8)


__all__ = [
    'BRAND', 'C', 'FT', 'FX', 'FM',
    'blit', 'P', 'E', 'seg', 'pulse', 'wobble',
    'tlayer', 'text_at', 'text_w', 'rich_line', 'wrap', 'para',
    'rrect', 'panel', 'shadow', 'dim_rect', 'spot', 'line_draw', 'dashed_line', 'arrow', 'ring', 'marker_band',
    'asset_exists', 'vclip', 'full', 'asset_img', 'asset_vid', 'asset_text', 'placeholder', 'fit_into', 'put', 'layer_of', 'meme',
    'bg', 'grain',
    'window', 'browser', 'game_frame', 'phone_frame', 'author_card',
    'chat_bubble', 'caption', 'lower_third', 'chapter_badge', 'stage_badge', 'bug_counter', 'callout', 'chip',
    'check', 'cross', 'checklist', 'counter', 'code_card', 'terminal', 'node', 'stamp', 'big_num', 'lesson_card',
    'cursor', 'icon', 'progress_dots', 'reconstruction_tag',
    'trans_in', 'trans_out', 'scene_fx',
    'sfx', 'sfx_hits',
]

# ================================================================ палитра (BRAND-COLORS.md)
BRAND = dict(red=(212, 60, 32), red_hover=(185, 50, 26), ink=(16, 15, 12), white=(255, 255, 255), paper=(242, 242, 242),
             night=(8, 8, 8), amber=(191, 120, 48), muted=(110, 106, 99), faint=(196, 191, 175),
             midnight=(11, 30, 51), blue=(18, 53, 91), ocean=(43, 92, 143), sky=(157, 188, 223), ice=(234, 240, 247),
             gold=(226, 166, 75), bone=(244, 238, 228), growth=(47, 158, 110))
# цвета темы игры — только внутри интерфейса игры (scenes.md: «Лампа» #E9C27F, «Копоть» #1A1917)
C = dict(BRAND, lamp=(233, 194, 127), soot=(26, 25, 23))

# ================================================================ шрифты
FT, FX, FM = 'montserrat', 'manrope', 'jbmono'      # файлы в project/fonts/: заголовки, текст, код
_FALLBACK = {FT: 'title', FX: 'text', FM: 'text'}


def _fam(f):
    """Файл шрифта или запасная роль из Настроек, если файла нет (чтобы сцена не падала)."""
    return f if kit._font_path(f) else _FALLBACK.get(f, 'text')


# ================================================================ время
def P(t, a, b):
    """Прогресс 0..1 между a и b (линейно)."""
    return prog(t, a, b)


def E(t, a, d=0.4, ease=oexp):
    """Плавный прогресс появления: начинается в a, длится d."""
    return ease(prog(t, a, a + d))


def seg(t, a, b):
    """True, если a <= t < b."""
    return a <= t < b


def pulse(t, t0, d=0.3, amp=0.15):
    """Короткий «пульс» масштаба 1 → 1+amp → 1 начиная с t0."""
    k = prog(t, t0, t0 + d)
    return 1 + amp * math.sin(math.pi * k) if 0 < k < 1 else 1.0


def wobble(t, seed=0, amp=1.0):
    """Небольшое «ручное» дрожание (для штрихов от руки)."""
    return amp * (math.sin(t * 17 + seed * 3.1) * 0.6 + math.sin(t * 29 + seed) * 0.4)


# ================================================================ кэш
class _LRU(OrderedDict):
    def __init__(self, n):
        super().__init__()
        self.n = n

    def get2(self, k, make):
        if k in self:
            self.move_to_end(k)
            return self[k]
        v = make()
        self[k] = v
        while len(self) > self.n:
            self.popitem(last=False)
        return v


_CACHE = _LRU(600)

# ================================================================ текст
PAD = 40   # поле вокруг текста в kit._tlayer


def tlayer(s, fam=FX, w=500, size=36, color=None, track=0.0):
    """RGBA-слой строки (кэш), с полем PAD со всех сторон."""
    color = tuple(int(c) for c in (color or C['white']))
    return kit._tlayer(str(s), _fam(fam), int(w), int(size), color, float(track), False)


_TW = {}


def text_w(s, fam=FX, w=500, size=36, track=0.0):
    """Ширина строки в пикселях (кэш)."""
    k = (str(s), fam, int(w), int(size), track)
    v = _TW.get(k)
    if v is None:
        if len(_TW) > 20000:
            _TW.clear()
        v = _TW[k] = kit.text_size(str(s), _fam(fam), int(w), int(size), track)[0]
    return v


def text_at(fr, s, x, y, fam=FX, w=500, size=36, color=None, op=1.0, align='l', track=0.0, vcenter=False):
    """Строка: (x, y) — левый верхний угол текста (align 'l'), центр ('c') или правый край ('r').
    vcenter=True — y это вертикальный центр строки. Возвращает (x0, y0, ширина, высота)."""
    if not s or op <= 0.01:
        return None
    a = tlayer(s, fam, w, size, color, track)
    tw, th = a.shape[1] - 2 * PAD, a.shape[0] - 2 * PAD
    x0 = x if align == 'l' else (x - tw / 2 if align == 'c' else x - tw)
    y0 = y - th / 2 if vcenter else y
    blit(fr, a, x0 - PAD, y0 - PAD, op)
    return (x0, y0, tw, th)


def rich_line(fr, parts, x, y, fam=FT, w=800, size=56, op=1.0, align='l', vcenter=False):
    """Строка из кусков разного цвета: parts = [('Код пишет ', C['white']), ('Claude', C['gold'])]."""
    ws = [text_w(p[0], fam, w, size) for p in parts]
    total = sum(ws)
    x0 = x if align == 'l' else (x - total / 2 if align == 'c' else x - total)
    th = kit.text_size('Ag', _fam(fam), w, size)[1]
    y0 = y - th / 2 if vcenter else y
    cx = x0
    for (s, col), wd in zip(parts, ws):
        text_at(fr, s, cx, y0, fam, w, size, col, op)
        cx += wd
    return (x0, y0, total, th)


_WRAP = {}


def wrap(s, maxw, fam=FX, w=500, size=36):
    """Разбить текст на строки шириной не больше maxw пикселей (кэш)."""
    k = (str(s), int(maxw), fam, int(w), int(size))
    if k not in _WRAP:
        if len(_WRAP) > 2000:
            _WRAP.clear()
        _WRAP[k] = _wrap(s, maxw, fam, w, size)
    return _WRAP[k]


def _wrap(s, maxw, fam, w, size):
    out = []
    for para_ in str(s).split('\n'):
        line = ''
        for word in para_.split(' '):
            cand = (line + ' ' + word).strip()
            if line and text_w(cand, fam, w, size) > maxw:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


def para(fr, s, x, y, maxw, fam=FX, w=500, size=36, color=None, op=1.0, lh=1.3, chars=None, align='l'):
    """Абзац с переносом. chars — сколько символов уже «напечатано» (None — все). Возвращает высоту."""
    lines = wrap(s, maxw, fam, w, size)
    n = 10 ** 9 if chars is None else int(chars)
    yy = y
    for ln in lines:
        if n <= 0:
            break
        part = ln[:n]
        n -= len(ln) + 1
        if len(part) < len(ln) and part and align == 'l':
            # «печать»: слой всей строки (кэш) обрезается по ширине напечатанной части — без нового рендера текста
            a = tlayer(ln, fam, w, size, color)
            pw = int(PAD + text_w(part, fam, w, size))
            blit(fr, a[:, :pw], x - PAD, yy - PAD, op)
        else:
            text_at(fr, part, x, yy, fam, w, size, color, op, align)
        yy += size * lh
    return len(lines) * size * lh


# ================================================================ фигуры
def rrect(w, h, r, fill, border=None, bw=0, alpha=255):
    """RGBA-слой скруглённого прямоугольника (кэш)."""
    w, h, r = int(max(2, w)), int(max(2, h)), int(max(0, r))
    key = ('rr', w, h, r, tuple(fill) if fill else None, tuple(border) if border else None, int(bw), int(alpha))

    def make():
        q = 2   # сглаживание: рисуем вдвое крупнее
        im = Image.new('RGBA', (w * q, h * q), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f = tuple(fill) + (alpha,) if fill else None
        o = tuple(border) + (255,) if border and bw else None
        d.rounded_rectangle([0, 0, w * q - 1, h * q - 1], radius=r * q, fill=f, outline=o, width=int(bw * q))
        return np.array(im.resize((w, h), Image.LANCZOS))
    return _CACHE.get2(key, make)


def shadow(fr, x, y, w, h, r=12, blur=30, dy=20, op=0.5):
    """Мягкая тень под панелью (кэш; затемнение умножением — быстро)."""
    w, h = int(w), int(h)
    if op <= 0.01 or w < 2 or h < 2:
        return
    opq = round(op * 20) / 20
    key = ('sh', w, h, int(r), int(blur), opq)

    def make():
        m = blur * 2
        al = np.zeros((h + 2 * m, w + 2 * m), np.float32)
        cv2.rectangle(al, (m, m), (m + w, m + h), 1.0, -1)
        al = cv2.GaussianBlur(al, (0, 0), blur / 2)
        f = (255 * (1 - opq * al)).clip(0, 255).astype(np.uint8)
        return cv2.merge([f, f, f])
    f = _CACHE.get2(key, make)
    m = blur * 2
    x0, y0 = int(x - m), int(y - m + dy)
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(fr.shape[1], x0 + f.shape[1]), min(fr.shape[0], y0 + f.shape[0])
    if xb > xa and yb > ya and fr.shape[2] == 3:
        reg = fr[ya:yb, xa:xb]
        cv2.multiply(reg, f[ya - y0:yb - y0, xa - x0:xb - x0], dst=reg, scale=1 / 255)


def panel(fr, x, y, w, h, fill=None, border=None, bw=1, r=12, op=1.0, alpha=255, sh=True):
    """Панель: тень + скруглённый прямоугольник."""
    if op <= 0.01:
        return
    if sh:
        shadow(fr, x, y, w, h, r, op=0.45 * op)
    blit(fr, rrect(w, h, r, fill or C['midnight'], border, bw, alpha), x, y, op)


def dim_rect(fr, x0, y0, x1, y1, k=0.5):
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(fr.shape[1], int(x1)), min(fr.shape[0], int(y1))
    if x1 > x0 and y1 > y0:
        reg = fr[y0:y1, x0:x1]
        cv2.convertScaleAbs(reg, dst=reg, alpha=k)


def spot(fr, rect, k=0.5, r=8, border=C['sky'], bw=2):
    """Затемнить всё, кроме прямоугольника rect=(x, y, w, h), и обвести его."""
    x, y, w, h = [int(v) for v in rect]
    keep = fr[max(0, y):y + h, max(0, x):x + w].copy()
    cv2.convertScaleAbs(fr, dst=fr, alpha=k)
    fr[max(0, y):y + h, max(0, x):x + w] = keep
    blit(fr, rrect(w, h, r, None, border, bw), x, y)


def line_draw(fr, p0, p1, k, color=None, th=3):
    """Линия, которая «рисуется» от p0 к p1 (k = 0..1)."""
    if k <= 0:
        return
    x = p0[0] + (p1[0] - p0[0]) * k
    y = p0[1] + (p1[1] - p0[1]) * k
    cv2.line(fr, (int(p0[0]), int(p0[1])), (int(x), int(y)), tuple(color or C['sky']), th, cv2.LINE_AA)


def dashed_line(fr, p0, p1, k=1.0, color=None, th=3, dash=16, gap=12, phase=0.0):
    """Пунктир (рисуется на долю k; phase — «бегущий» сдвиг штрихов)."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 1 or k <= 0:
        return
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    s = -(phase % (dash + gap))
    while s < L * k:
        a, b = max(0, s), min(L * k, s + dash)
        if b > a:
            cv2.line(fr, (int(p0[0] + ux * a), int(p0[1] + uy * a)), (int(p0[0] + ux * b), int(p0[1] + uy * b)),
                     tuple(color or C['sky']), th, cv2.LINE_AA)
        s += dash + gap


def arrow(fr, p0, p1, k=1.0, color=None, th=3, head=16, dashed=False, phase=0.0):
    """Стрелка, которая рисуется за k (0..1). Наконечник — когда k > 0.9."""
    color = tuple(color or C['sky'])
    if dashed:
        dashed_line(fr, p0, p1, k, color, th, phase=phase)
    else:
        line_draw(fr, p0, p1, k, color, th)
    if k > 0.9:
        a = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        pts = np.array([p1, (p1[0] - head * math.cos(a - 0.45), p1[1] - head * math.sin(a - 0.45)),
                        (p1[0] - head * math.cos(a + 0.45), p1[1] - head * math.sin(a + 0.45))], np.int32)
        cv2.fillPoly(fr, [pts], color, cv2.LINE_AA)


def ring(fr, t, t0, cx, cy, rx, ry, color=None, th=4, d=0.35, seed=0):
    """Обводка «от руки»: эллипс рисуется за d секунд с лёгким дрожанием."""
    k = oc(prog(t, t0, t0 + d))
    if k <= 0:
        return
    n = 90
    pts = []
    for i in range(int(n * k * 1.08) + 1):
        a = -2.2 + i / n * 2 * math.pi
        j = 1 + 0.03 * math.sin(i * 0.7 + seed) + 0.01 * wobble(t, seed + i * 0.1)
        pts.append((cx + rx * j * math.cos(a), cy + ry * j * math.sin(a)))
    if len(pts) > 1:
        cv2.polylines(fr, [np.array(pts, np.int32)], False, tuple(color or C['gold']), th, cv2.LINE_AA)


def marker_band(fr, x, y, w, h, k=1.0, color=None, alpha=0.3):
    """Маркер-подсветка (как текстовыделителем): полоса растёт слева направо за k."""
    if k <= 0:
        return
    w2 = int(w * k)
    x, y = int(x), int(y)
    reg = fr[max(0, y):y + int(h), max(0, x):x + w2]
    if reg.size:
        col = np.full_like(reg, tuple(color or C['gold']))
        cv2.addWeighted(reg, 1 - alpha, col, alpha, 0, dst=reg)


# ================================================================ медиа
_EXT_ALT = ('', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.HEIC', '.JPG', '.heif')


def placeholder(name, w=1920, h=1080, note=''):
    """Серая заглушка с именем файла (если файла нет)."""
    key = ('ph', name, w, h, note)

    def make():
        a = np.zeros((h, w, 3), np.uint8)
        a[:] = C['muted']
        # диагональная штриховка, чтобы заглушку было видно
        for i in range(-h, w, 60):
            cv2.line(a, (i, 0), (i + h, h), (104, 100, 93), 14)
        s = max(18, int(w / 34))
        text_at(a, 'НЕТ ФАЙЛА', w / 2, h / 2 - s * 1.6, FT, 800, int(s * 1.3), C['ice'], align='c')
        text_at(a, 'assets/' + name, w / 2, h / 2 + s * 0.2, FM, 500, s, C['ice'], align='c')
        if note:
            text_at(a, note, w / 2, h / 2 + s * 1.8, FX, 500, int(s * 0.8), C['faint'], align='c')
        return a
    return _CACHE.get2(key, make)


def asset_img(name):
    """Картинка из assets/ (RGB). Пробует другие расширения (.jpg/.png/.heic…). Нет файла — заглушка."""
    base, ext = os.path.splitext(name)
    for cand in [name] + [base + e for e in _EXT_ALT if e and e != ext]:
        try:
            return kit.image(cand)
        except Exception:
            continue
    return placeholder(name)


def asset_vid(name, t, start=0.0, speed=1.0):
    """Кадр видео из assets/ для момента t (секунды внутри бита) с отступом start в файле. Нет файла — заглушка."""
    try:
        return kit.video(name, t, start=start, speed=speed, loop=True)
    except Exception:
        return placeholder(name, note='видео · %.1f с' % (start + max(0.0, t) * speed))


def asset_exists(name):
    """Есть ли файл в assets/ (для запасных вариантов сцены)."""
    try:
        kit._path(name, ('',), 'Файл')
        return True
    except Exception:
        return False


def vclip(name, t, b0, start=0.0, speed=1.0):
    """Кадр видео для бита, начавшегося в момент b0 сцены: файл с секунды start (тайм-коды из scenes.md)."""
    return asset_vid(name, t - b0, start, speed)


def full(fr, img, cx=0.5, cy=0.5, zoom=1.0):
    """Картинка/кадр видео на весь кадр (cover) с точкой интереса (cx, cy) и увеличением zoom."""
    return fit_into(fr, img, (0, 0, fr.shape[1], fr.shape[0]), cx, cy, zoom)


def asset_text(name, default=''):
    """Текстовый файл из assets/ (.md, .json, .gd…). Нет файла — default."""
    try:
        p = kit._path(name, ('',), 'Файл')
        with open(p, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return default


def fit_into(fr, src, rect, cx=0.5, cy=0.5, zoom=1.0, mode='cover', op=1.0, r=0, bg=None):
    """Вписать картинку src в прямоугольник rect=(x, y, w, h) кадра.
    cover — заполнить (лишнее обрезать), contain — целиком. (cx, cy) — какая точка картинки (доли) в центре,
    zoom — увеличение (1.1 = наезд на 10 %), r — скругление углов."""
    x, y, w, h = [float(v) for v in rect]
    sh_, sw_ = src.shape[:2]
    s = (max(w / sw_, h / sh_) if mode == 'cover' else min(w / sw_, h / sh_)) * zoom
    px, py = cx * sw_, cy * sh_
    if mode == 'cover':
        hw, hh = w / 2 / s, h / 2 / s
        px = min(max(px, hw), sw_ - hw) if sw_ > 2 * hw else sw_ / 2
        py = min(max(py, hh), sh_ - hh) if sh_ > 2 * hh else sh_ / 2
    iw, ih = int(round(w)), int(round(h))
    M = np.float32([[s, 0, w / 2 - px * s], [0, s, h / 2 - py * s]])
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    out = cv2.warpAffine(src[..., :3], M, (iw, ih), flags=interp, borderMode=cv2.BORDER_CONSTANT,
                         borderValue=tuple(bg or C['midnight']))
    if r > 0 or op < 1:
        a = np.dstack([out, (rrect(iw, ih, r, (255, 255, 255))[..., 3] if r > 0 else np.full((ih, iw), 255, np.uint8))])
        blit(fr, a, x, y, op)
    else:
        x0, y0 = int(round(x)), int(round(y))
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(fr.shape[1], x0 + iw), min(fr.shape[0], y0 + ih)
        if xb > xa and yb > ya:
            fr[ya:yb, xa:xb] = out[ya - y0:yb - y0, xa - x0:xb - x0]
    return out


def layer_of(img, op_mask=None):
    """RGB → RGBA (непрозрачный)."""
    if img.shape[2] == 4:
        return img
    return np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])


def put(fr, a, cx, cy, sc=1.0, op=1.0, rot=0.0, rot_y=0.0, rot_x=0.0):
    """Поставить RGBA-слой центром в (cx, cy): масштаб, поворот (градусы),
    rot_y / rot_x — «3D»-наклон окна (градусы, перспектива)."""
    if op <= 0.01 or sc <= 0.01:
        return
    a = layer_of(a)
    h, w = a.shape[:2]
    if abs(rot_y) < 0.05 and abs(rot_x) < 0.05:
        if abs(rot) < 0.01 and abs(sc - 1) < 1e-3:
            blit(fr, a, cx - w / 2, cy - h / 2, op)
            return
        M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, sc)
        c = np.abs(M[:, :2]) @ np.array([w, h])
        bw, bh = int(c[0]) + 4, int(c[1]) + 4
        M[0, 2] += bw / 2 - w / 2
        M[1, 2] += bh / 2 - h / 2
        wa = cv2.warpAffine(a, M, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        blit(fr, wa, cx - bw / 2, cy - bh / 2, op)
        return
    # перспектива: дальний край уже/ниже
    ky = math.sin(math.radians(rot_y)) * 0.5
    kx = math.sin(math.radians(rot_x)) * 0.5
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    l = 1 - max(0, -ky)
    rr = 1 - max(0, ky)
    tp = 1 - max(0, kx)
    bt = 1 - max(0, -kx)
    dw, dh = w * sc, h * sc
    cxw = math.cos(math.radians(rot_y))
    xl, xr = -dw / 2 * cxw, dw / 2 * cxw
    yt, yb = -dh / 2 * math.cos(math.radians(rot_x)), dh / 2 * math.cos(math.radians(rot_x))
    dst = np.float32([[xl * tp, yt * l], [xr * tp, yt * rr], [xr * bt, yb * rr], [xl * bt, yb * l]])
    bw, bh = int(dw + 8), int(dh + 8)
    dst += np.float32([bw / 2, bh / 2])
    M = cv2.getPerspectiveTransform(src, dst)
    wa = cv2.warpPerspective(a, M, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=(0, 0, 0, 0))
    blit(fr, wa, cx - bw / 2, cy - bh / 2, op)


# ================================================================ фон
def bg(fr, t=0.0):
    """Фон всех сцен: градиент Deep Blue → Midnight сверху вниз + зерно 3 %."""
    h, w = fr.shape[:2]

    def make():
        g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
        top, bot = np.array(C['blue'], np.float32), np.array(C['midnight'], np.float32)
        return np.broadcast_to(top * (1 - g) + bot * g, (h, w, 3)).astype(np.uint8).copy()
    fr[:] = _CACHE.get2(('bg', w, h), make)
    grain(fr, t, 0.03)


def grain(fr, t, amt=0.03):
    h, w = fr.shape[:2]
    i = int(t * 12) % 4
    g = _CACHE.get2(('gr', w, h, i), lambda: np.clip(128 + np.random.default_rng(100 + i).normal(0, 40, (h, w, 1)), 0, 255)
                    .astype(np.uint8).repeat(3, 2))
    cv2.addWeighted(fr, 1, g, amt, -128 * amt, dst=fr)


# ================================================================ окна
def _chrome(w, h, kind, addr, r):
    """Рамка окна (RGBA, кэш): панель браузера, точки, плашка адреса, обводка."""
    def make():
        top = 44 if kind == 'browser' else 0
        a = np.zeros((h, w, 4), np.uint8)
        if kind == 'browser':
            a[:top, :, :3] = C['midnight']
            a[:top, :, 3] = 255
            for i, col in enumerate((C['muted'], C['faint'], C['sky'])):
                cv2.circle(a, (22 + i * 22, top // 2), 6, tuple(col) + (255,), -1, cv2.LINE_AA)
            if addr:
                pw = min(w * 0.42, text_w(addr, FX, 500, 20) + 40)
                blit(a, rrect(pw, 28, 14, C['blue']), w / 2 - pw / 2, 8)
                text_at(a, addr, w / 2, 22, FX, 500, 20, C['sky'], align='c', vcenter=True)
            a[top, :, :3] = C['sky']
            a[top, :, 3] = 255
        blit(a, rrect(w, h, r, None, C['sky'], 2 if kind == 'game' else 1), 0, 0)
        return a
    return _CACHE.get2(('chrome', w, h, kind, addr, r), make)


def window(content, w, h, kind='browser', addr=None, r=12):
    """RGBA-слой окна w×h с содержимым content (RGB-кадр).
    kind: 'browser' — панель 44 px с тремя точками и закрытой плашкой адреса; 'game' — рамка Sky 2 px; 'plain'."""
    w, h = int(w), int(h)
    top = 44 if kind == 'browser' else 0
    rgb = np.empty((h, w, 3), np.uint8)
    rgb[:] = C['midnight']
    fit_into(rgb, content, (0, top, w, h - top))
    blit(rgb, _chrome(w, h, kind, addr, r), 0, 0)
    return np.dstack([rgb, rrect(w, h, r, (255, 255, 255))[..., 3]])


def _enter(t, t_in, d=0.5):
    if t_in is None:
        return 1.0
    return oexp(prog(t, t_in, t_in + d))


def browser(fr, t, content, t_in=None, cx=960, cy=540, w=1632, h=918, addr='локально', zoom=1.0, op=1.0, rot_y=0.0):
    """Окно браузера (85 % ширины) с записью экрана/картинкой. Появление: масштаб 0.94→1 + прозрачность, oexp 0.5 с.
    Адресная строка всегда закрыта плашкой (addr)."""
    k = _enter(t, t_in)
    sh_w, sh_h = w * (0.94 + 0.06 * k) * zoom, h * (0.94 + 0.06 * k) * zoom
    shadow(fr, cx - sh_w / 2, cy - sh_h / 2, sh_w, sh_h, 12, op=0.5 * k * op)
    put(fr, window(content, w, h, 'browser', addr), cx, cy, (0.94 + 0.06 * k) * zoom, k * op, rot_y=rot_y)


def game_frame(fr, t, content, t_in=None, cx=960, cy=540, w=1536, h=864, zoom=1.0, op=1.0, tilt=True, r=10):
    """Окно игры/Godot: рамка Sky 2 px, тень; появление — наклон rotateY 8°→0 + масштаб 0.94→1 за 0.6 с."""
    k = oexp(prog(t, t_in, t_in + 0.6)) if t_in is not None else 1.0
    sc = (0.94 + 0.06 * k) * zoom
    shadow(fr, cx - w * sc / 2, cy - h * sc / 2, w * sc, h * sc, r, op=0.5 * k * op)
    put(fr, window(content, w, h, 'game', r=r), cx, cy, sc, k * op, rot_y=(8 * (1 - k) if tilt else 0))


def phone_frame(fr, content, cx, cy, h=700, op=1.0, rot_y=0.0):
    """Рамка телефона 9:19.5, радиус 56, рамка 10 px Sky."""
    w = int(h * 9 / 19.5)
    a = np.zeros((h, w, 4), np.uint8)
    inner = fit_into(np.zeros((h - 20, w - 20, 3), np.uint8), content, (0, 0, w - 20, h - 20))
    a[10:h - 10, 10:w - 10, :3] = inner
    a[..., 3] = rrect(w, h, 56, (255, 255, 255))[..., 3]
    blit(a, rrect(w, h, 56, None, C['sky'], 10), 0, 0)
    a[..., 3] = np.minimum(a[..., 3], rrect(w, h, 56, (255, 255, 255))[..., 3])
    put(fr, a, cx, cy, 1.0, op, rot_y=rot_y)


def author_card(fr, t, img, x, y, w, h, t_in=0.0, side='l', zoom0=1.0, zoom1=1.08, dur=4.0, focus=(0.5, 0.4), op=1.0):
    """Фото автора 3:4 в карточке: радиус 18, тень; въезд сбоку 60–80 px + поворот −3°→0 (back-out 0.5 с),
    внутри — медленный наезд zoom0→zoom1 за dur."""
    k = oback(prog(t, t_in, t_in + 0.5))
    ke = prog(t, t_in, t_in + 0.3)
    z = lerp(zoom0, zoom1, prog(t, t_in, t_in + dur))
    tile = np.zeros((int(h), int(w), 3), np.uint8)
    fit_into(tile, img, (0, 0, w, h), focus[0], focus[1], z)
    a = np.dstack([tile, rrect(w, h, 18, (255, 255, 255))[..., 3]])
    dx = (1 - k) * (-70 if side == 'l' else 70)
    shadow(fr, x + dx, y, w, h, 18, op=0.45 * ke * op)
    put(fr, a, x + w / 2 + dx, y + h / 2, 1.0, ke * op, rot=-3 * (1 - k))


# ================================================================ компоненты
def chat_bubble(fr, t, t0, s, side='me', x=None, y=600, maxw=900, size=38, cps=30, op=1.0, typing=True, t1=None):
    """Пузырь чата. Мой — справа, Ocean, текст White; Claude — слева, Midnight, рамка Sky 1 px, подпись «Claude».
    Выезд снизу 40 px oexp 0.4 с, печать cps символов в секунду. Возвращает (x, y, w, h)."""
    if t < t0:
        return None
    k = oexp(prog(t, t0, t0 + 0.4))
    if t1 is not None:
        k *= 1 - prog(t, t1 - 0.3, t1)
    if k <= 0.01:
        return None
    lines = wrap(s, maxw, FX, 500, size)
    bw = max(text_w(l, FX, 500, size) for l in lines) + 56
    bh = len(lines) * size * 1.3 + 40
    if x is None:
        x = 1920 - 120 - bw if side == 'me' else 120
    yy = y + (1 - k) * 40
    if side == 'me':
        panel(fr, x, yy, bw, bh, C['ocean'], None, 0, 14, op * k)
    else:
        text_at(fr, tx('look_claude', 'Claude'), x + 4, yy - 34, FX, 600, 22, C['sky'], op * k)
        panel(fr, x, yy, bw, bh, C['midnight'], C['sky'], 1, 14, op * k)
    chars = (t - t0) * cps if typing else None
    para(fr, s, x + 28, yy + 18, maxw + 4, FX, 500, size, C['white'], op * k, 1.3, chars)
    return (x, yy, bw, bh)


def caption(fr, t, t0, t1, s, cx=960, cy=900, gold=None, size=56, fill=None, red=False, op=1.0):
    """Плашка-надпись до 6 слов: Deep Blue, радиус 10, Montserrat 800 White; одно слово (gold) — Gold.
    red=True — плашка Signal Red (только как плашка с белым текстом). Снизу 30 px + прозрачность, oexp 0.35 с."""
    if t < t0 or (t1 is not None and t > t1):
        return
    k = oexp(prog(t, t0, t0 + 0.35))
    if t1 is not None:
        k *= 1 - prog(t, t1 - 0.25, t1)
    if k <= 0.01:
        return
    parts = [(s, C['white'])]
    if gold and gold in s:
        i = s.index(gold)
        parts = [(s[:i], C['white']), (gold, C['gold']), (s[i + len(gold):], C['white'])]
        parts = [p for p in parts if p[0]]
    tw = sum(text_w(p[0], FT, 800, size) for p in parts)
    th = size * 1.25
    bw, bh = tw + 56, th + 28
    y = cy - bh / 2 + (1 - k) * 30 - prog(t, (t1 or 1e9) - 0.25, t1 or 1e9) * 20
    panel(fr, cx - bw / 2, y, bw, bh, fill or (C['red'] if red else C['blue']), None, 0, 10, op * k)
    rich_line(fr, parts, cx, y + bh / 2, FT, 800, size, op * k, 'c', vcenter=True)


def lower_third(fr, t, t0, t1, s, x=80, y=940, size=44):
    """Подпись слева внизу: полоса 4×56 Gold + Montserrat 600 44 px White на Midnight 80 %.
    Выезд слева 0.4 с, уход 0.3 с."""
    if t < t0 or t > t1:
        return
    k = oexp(prog(t, t0, t0 + 0.4)) * (1 - ic(prog(t, t1 - 0.3, t1)))
    if k <= 0.01:
        return
    tw = text_w(s, FT, 600, size)
    dx = (1 - k) * -120
    blit(fr, rrect(tw + 60, 72, 8, C['midnight'], alpha=204), x + dx, y - 8, k)
    blit(fr, rrect(4, 56, 1, C['gold']), x + dx + 14, y, k)
    text_at(fr, s, x + dx + 34, y + 28, FT, 600, size, C['white'], k, vcenter=True)


def chapter_badge(fr, t, t0, num, title, x=80, y=60, hold=3.0):
    """Бейдж главы: «0N» Gold + название White на Deep Blue 85 %. Выезд слева 0.4 с, держится hold,
    потом сворачивается до номера."""
    if t < t0:
        return
    k = oexp(prog(t, t0, t0 + 0.4))
    c = ioc(prog(t, t0 + hold, t0 + hold + 0.4))
    nw = text_w(num, FT, 800, 30) + 40
    tw = text_w(title, FT, 700, 30)
    bw = nw + (tw + 28) * (1 - c)
    dx = (1 - k) * -100
    blit(fr, rrect(bw, 56, 10, C['blue'], alpha=217), x + dx, y, k)
    text_at(fr, num, x + dx + 20, y + 28, FT, 800, 30, C['gold'], k, vcenter=True)
    if c < 0.98:
        text_at(fr, title, x + dx + nw, y + 28, FT, 700, 30, C['white'], k * (1 - c), vcenter=True)


def stage_badge(fr, t, n, t_change=-9.0, total=9, x=80, y=140, op=1.0):
    """«Этап N/9» + полоса из 9 сегментов (пройденные — Gold); новый сегмент заполняется 0.4 с."""
    blit(fr, rrect(300, 92, 10, C['blue']), x, y, op)
    text_at(fr, tx('look_stage', 'Этап') + ' %d/%d' % (n, total), x + 20, y + 30, FT, 800, 34, C['white'], op, vcenter=True)
    sw = (300 - 40 - (total - 1) * 4) / total
    fillk = oc(prog(t, t_change, t_change + 0.4))
    for i in range(total):
        sx = x + 20 + i * (sw + 4)
        col = C['midnight']
        if i < n - 1 or (i == n - 1 and fillk >= 1):
            col = C['gold']
        blit(fr, rrect(sw, 10, 3, col), sx, y + 64, op)
        if i == n - 1 and fillk < 1:
            blit(fr, rrect(max(2, sw * fillk), 10, 3, C['gold']), sx, y + 64, op)


def bug_counter(fr, t, n, t_change=-9.0, t_in=None, t_out=None):
    """Фирменный счётчик «косяки: N» (правый верх): число прокатывается вверх 0.3 с + пульс, на росте — Gold 0.5 с."""
    k = 1.0
    if t_in is not None:
        k = oexp(prog(t, t_in, t_in + 0.4))
    if t_out is not None:
        k *= 1 - ic(prog(t, t_out - 0.4, t_out))
    if k <= 0.01:
        return
    x, y, w, h = 1640 + (1 - k) * 320, 60, 220, 64
    blit(fr, rrect(w, h, 10, C['midnight'], C['sky'], 1), x, y, k)
    icon(fr, 'bug', x + 34, y + h / 2, 30, C['sky'], 2)
    lab = tx('look_bugs', 'косяки:')
    text_at(fr, lab, x + 60, y + h / 2, FT, 700, 28, C['white'], k, vcenter=True)
    roll = prog(t, t_change, t_change + 0.3)
    col = C['gold'] if 0 <= t - t_change < 0.5 else C['white']
    sc = pulse(t, t_change, 0.3, 0.15)
    nx = x + 66 + text_w(lab + ' ', FT, 700, 28)
    if roll < 1:
        text_at(fr, str(max(0, n - 1)), nx, y + h / 2 - roll * 30, FT, 700, 30, C['white'], k * (1 - roll), vcenter=True)
        text_at(fr, str(n), nx, y + h / 2 + (1 - roll) * 30, FT, 700, int(30 * sc), col, k * roll, vcenter=True)
    else:
        text_at(fr, str(n), nx, y + h / 2, FT, 700, int(30 * sc), col, k, vcenter=True)


def callout(fr, t, t0, pt, lab, s, t1=None, size=34):
    """Выноска: точка 10 px Gold + линия 2 px Sky + подпись Manrope 600 на Midnight 80 %.
    Линия рисуется 0.25 с, подпись проявляется 0.2 с."""
    if t < t0 or (t1 is not None and t > t1):
        return
    out = 1 - prog(t, t1 - 0.25, t1) if t1 is not None else 1
    k = oc(prog(t, t0, t0 + 0.25))
    cv2.circle(fr, (int(pt[0]), int(pt[1])), 6, C['gold'], -1, cv2.LINE_AA)
    line_draw(fr, pt, lab, k * out, C['sky'], 2)
    kk = prog(t, t0 + 0.25, t0 + 0.45) * out
    if kk > 0:
        tw = text_w(s, FX, 600, size)
        right = lab[0] < pt[0]
        bx = lab[0] - tw - 36 if right else lab[0]
        blit(fr, rrect(tw + 36, size + 24, 8, C['midnight'], alpha=204), bx, lab[1] - (size + 24) / 2, kk)
        text_at(fr, s, bx + 18, lab[1], FX, 600, size, C['white'], kk, vcenter=True)


def chip(fr, t, t0, s, x, y, style='dark', size=30, align='l', t1=None, op=1.0):
    """Чип: dark — Midnight + рамка Sky, blue — Deep Blue, ice — Ice с текстом Deep Blue, gold — рамка Gold.
    Появление back-out 0.3 с. Возвращает ширину."""
    if t < t0 or (t1 is not None and t > t1):
        return 0
    k = oback(prog(t, t0, t0 + 0.3))
    if t1 is not None:
        k *= 1 - prog(t, t1 - 0.2, t1)
    fill, border, col = {'dark': (C['midnight'], C['sky'], C['white']), 'blue': (C['blue'], None, C['white']),
                         'ice': (C['ice'], None, C['blue']), 'gold': (C['midnight'], C['gold'], C['white']),
                         'growth': (C['growth'], None, C['white'])}[style]
    tw = text_w(s, FX, 600, size)
    w, h = tw + 40, size + 26
    x0 = x if align == 'l' else (x - w / 2 if align == 'c' else x - w)
    a = rrect(w, h, h / 2 - 2, fill, border, 2 if border else 0).copy()
    text_at(a, s, w / 2, h / 2, FX, 600, size, col, align='c', vcenter=True)
    put(fr, a, x0 + w / 2, y + h / 2, max(0.01, k), clamp(k * 2) * op)
    return w


def check(fr, t, t0, cx, cy, s=40, color=None, th=6, d=0.2):
    """Галочка ✓ (Growth), рисуется за d, с отскоком."""
    k = prog(t, t0, t0 + d)
    if k <= 0:
        return
    sc = oback(prog(t, t0, t0 + 0.35))
    p0, p1, p2 = (cx - s * 0.45 * sc, cy), (cx - s * 0.1 * sc, cy + s * 0.35 * sc), (cx + s * 0.5 * sc, cy - s * 0.4 * sc)
    col = color or C['growth']
    line_draw(fr, p0, p1, clamp(k * 2), col, th)
    if k > 0.5:
        line_draw(fr, p1, p2, (k - 0.5) * 2, col, th)


def cross(fr, t, t0, cx, cy, s=36, color=None, th=6):
    k = oback(prog(t, t0, t0 + 0.3))
    if k <= 0:
        return
    col = color or C['faint']
    d = s / 2 * k
    cv2.line(fr, (int(cx - d), int(cy - d)), (int(cx + d), int(cy + d)), col, th, cv2.LINE_AA)
    cv2.line(fr, (int(cx - d), int(cy + d)), (int(cx + d), int(cy - d)), col, th, cv2.LINE_AA)


def checklist(fr, t, items, x=1270, y=200, w=580, size=32, gap=62, op=1.0, panel_bg=True):
    """Чек-лист справа (30 % ширины): items = [(текст, время отметки)]; пункт появляется за 0.25 с до галочки."""
    vis = [(s, ti) for s, ti in items if t >= ti - 0.25]
    if not vis:
        return
    if panel_bg:
        panel(fr, x - 30, y - 30, w + 60, len(items) * gap + 40, C['midnight'], C['sky'], 1, 14, op, alpha=225)
    for i, (s, ti) in enumerate(items):
        if t < ti - 0.25:
            continue
        k = oexp(prog(t, ti - 0.25, ti + 0.1))
        yy = y + i * gap + (1 - k) * 16
        blit(fr, rrect(36, 36, 8, None, C['sky'], 2), x, yy, k * op)
        check(fr, t, ti, x + 18, yy + 18, 30, th=5)
        text_at(fr, s, x + 56, yy + 18, FX, 600, size, C['white'], k * op, vcenter=True)


def counter(fr, t, t0, t1, v0, v1, cx, cy, size=180, color=None, fmt='{:d}', suffix='', prefix='', op=1.0, align='c'):
    """Счётчик Montserrat 900: число катится от v0 к v1 (ioc), последняя цифра прокатывается как одометр."""
    if t < t0:
        return
    k = ioc(prog(t, t0, t1))
    v = lerp(v0, v1, k)
    iv = int(math.floor(v + 1e-6))
    frac = v - iv if k < 1 else 0
    col = color or C['white']
    s0 = prefix + fmt.format(iv) + suffix
    a = oexp(prog(t, t0, t0 + 0.3)) * op
    if frac > 0.02:
        s1 = prefix + fmt.format(iv + 1) + suffix
        text_at(fr, s0, cx, cy - frac * size * 0.35, FT, 900, size, col, a * (1 - frac), align, vcenter=True)
        text_at(fr, s1, cx, cy + (1 - frac) * size * 0.35, FT, 900, size, col, a * frac, align, vcenter=True)
    else:
        text_at(fr, s0, cx, cy, FT, 900, size, col, a, align, vcenter=True)


def _code_color(tok):
    if tok.startswith('"') or tok.startswith("'"):
        return C['white']
    if tok.replace('.', '', 1).replace('-', '', 1).isdigit():
        return C['gold']
    return C['sky']


def code_card(fr, t, rect, title, lines, hl=(), scroll=0.0, chars=None, size=26, op=1.0, hl_k=1.0, first_line=1):
    """Код-карточка: Midnight, рамка Sky 1 px, шапка с именем файла, номера строк Muted, JetBrains Mono;
    подсветка строк hl — Deep Blue 60 % + метка Gold 4 px. scroll — сдвиг в строках, chars — печать."""
    x, y, w, h = [int(v) for v in rect]
    panel(fr, x, y, w, h, C['midnight'], C['sky'], 1, 12, op)
    blit(fr, rrect(w - 2, 48, 11, C['blue']), x + 1, y + 1, op)
    text_at(fr, title, x + 24, y + 25, FX, 600, 22, C['sky'], op, vcenter=True)
    lh = size * 1.45
    top = y + 64
    n_vis = int((h - 80) / lh)
    i0 = int(scroll)
    off = (scroll - i0) * lh
    left = chars if chars is not None else 10 ** 9
    sub = fr[top:y + h - 12, x + 1:x + w - 1]
    for j in range(i0, min(len(lines), i0 + n_vis + 2)):
        ln = lines[j]
        yy = (j - i0) * lh - off
        if yy < -lh or yy > sub.shape[0]:
            continue
        if j + first_line in hl:
            marker_band(sub, 0, yy - 4, int((w - 2) * hl_k), lh, 1, C['blue'], 0.6 * op)
            if hl_k > 0.05:
                sub[max(0, int(yy - 4)):max(0, int(yy - 4 + lh)), 0:4] = C['gold']
        text_at(sub, str(j + first_line), 52, yy, FM, 400, size - 4, C['muted'], op, 'r')
        if left <= 0:
            continue
        nshow = max(0, int(left))
        left -= len(ln) + 1
        cx = 72
        pos = 0
        for tok in _tokens(ln):
            if pos >= nshow:
                break
            vis = tok[:nshow - pos]
            pos += len(tok)
            tw_ = text_w(tok, FM, 500, size) if tok.strip() else text_w('a', FM, 500, size) * len(tok)
            if tok.strip():
                col = _code_color(tok)
                if len(vis) < len(tok):
                    a = tlayer(tok, FM, 500, size, col)
                    blit(sub, a[:, :int(PAD + text_w(vis, FM, 500, size))], cx - PAD, yy - PAD, op)
                else:
                    text_at(sub, tok, cx, yy, FM, 500, size, col, op)
            cx += tw_
            if cx > w - 20:
                break


def _tokens(s):
    out, cur, q = [], '', None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                out.append(cur); cur, q = '', None
            continue
        if ch in '"\'':
            if cur:
                out.append(cur)
            cur, q = ch, ch
        elif ch == ' ':
            if cur and not cur.isspace():
                out.append(cur); cur = ''
            cur += ch
        else:
            if cur.isspace() and cur:
                out.append(cur); cur = ''
            cur += ch
    if cur:
        out.append(cur)
    return out


def terminal(fr, t, rect, lines, size=26, op=1.0, title=''):
    """Терминал: Night #080808, промпт $ Growth, текст Ice, повторы Muted. lines = [(время, текст, цвет|None)]."""
    x, y, w, h = [int(v) for v in rect]
    panel(fr, x, y, w, h, C['night'], C['sky'], 1, 12, op)
    for i, col in enumerate((C['muted'], C['faint'], C['sky'])):
        cv2.circle(fr, (x + 24 + i * 22, y + 24), 6, col, -1, cv2.LINE_AA)
    if title:
        text_at(fr, title, x + w / 2, y + 24, FX, 500, 20, C['muted'], op, 'c', vcenter=True)
    lh = size * 1.5
    vis = [l for l in lines if t >= l[0]]
    n_fit = int((h - 70) / lh)
    vis = vis[-n_fit:]
    for i, (ti, s, col) in enumerate(vis):
        k = prog(t, ti, ti + 0.15)
        yy = y + 56 + i * lh
        if s.startswith('$ '):
            text_at(fr, '$', x + 24, yy, FM, 600, size, C['growth'], k * op)
            text_at(fr, s[2:], x + 24 + text_w('$ ', FM, 600, size), yy, FM, 500, size, col or C['ice'], k * op)
        else:
            text_at(fr, s, x + 24, yy, FM, 500, size, col or C['ice'], k * op)
    if int(t * 2) % 2 == 0 and vis:
        yy = y + 56 + len(vis) * lh
        if yy < y + h - lh:
            cv2.rectangle(fr, (x + 24, int(yy + 4)), (x + 24 + int(size * 0.55), int(yy + size)), C['ice'], -1)


def node(fr, t, t0, s, cx, cy, w=240, h=80, border=None, fill=None, size=30, color=None, op=1.0, gray=False):
    """Узел схемы: Deep Blue, текст White Manrope 600; выбранное — рамка Gold. Появление: прозрачность + сдвиг 20 px 0.3 с."""
    if t < t0:
        return
    k = oc(prog(t, t0, t0 + 0.3))
    lines = wrap(s, w - 30, FX, 600, size)
    hh = max(h, len(lines) * size * 1.25 + 30)
    y = cy - hh / 2 + (1 - k) * 20
    f = fill or (C['muted'] if gray else C['blue'])
    panel(fr, cx - w / 2, y, w, hh, f, border, 3 if border else 0, 12, k * op)
    for i, ln in enumerate(lines):
        text_at(fr, ln, cx, y + 15 + i * size * 1.25, FX, 600, size, color or C['white'], k * op, 'c')


def stamp(fr, t, t0, s, cx, cy, size=72, t1=None, ang=-6):
    """Штамп: плашка Signal Red, рамка 6 px White, Montserrat 900 White, поворот −6°.
    Масштаб 1.6→1 за 0.18 с + тряска 0.2 с."""
    if t < t0 or (t1 is not None and t > t1):
        return
    k = prog(t, t0, t0 + 0.18)
    sc = lerp(1.6, 1.0, oc(k))
    sh = (1 - prog(t, t0 + 0.18, t0 + 0.38)) * (k >= 1)
    tw = text_w(s, FT, 900, size)
    w, h = int(tw + 70), int(size * 1.35 + 30)
    a = rrect(w, h, 8, C['red'], C['white'], 6).copy()
    text_at(a, s, w / 2, h / 2, FT, 900, size, C['white'], align='c', vcenter=True)
    # «стёртая краска»
    rng = np.random.default_rng(len(s))
    for _ in range(40):
        px, py = int(rng.random() * w), int(rng.random() * h)
        cv2.circle(a, (px, py), int(1 + rng.random() * 3), (0, 0, 0, 0), -1)
    put(fr, a, cx + math.sin(t * 90) * 8 * sh, cy + math.cos(t * 70) * 6 * sh, sc, clamp(k * 3), ang)


def big_num(fr, t, t0, s, x, y, size=220, color=None, op=1.0):
    """Крупный номер (идеи/вывода): Montserrat 900 Gold."""
    k = oback(prog(t, t0, t0 + 0.4))
    if k <= 0:
        return
    text_at(fr, s, x, y + (1 - k) * 40, FT, 900, size, color or C['gold'], clamp(k) * op)


def lesson_card(fr, t, t0, num, s, op=1.0, y_off=0.0):
    """Карточка вывода: Deep Blue на весь кадр, номер Gold 160 px, текст Montserrat 800 56 px White (≤ 70 % ширины).
    Вход — push снизу 0.4 с."""
    k = oc(prog(t, t0, t0 + 0.4))
    if k <= 0:
        return
    dy = (1 - k) * 1080 + y_off
    fr[max(0, int(dy)):] = C['blue']
    grain(fr, t, 0.03)
    text_at(fr, num, 160, 260 + dy, FT, 900, 160, C['gold'], op)
    para(fr, s, 160, 480 + dy, 1340, FT, 800, 64, C['white'], op, 1.2)


def cursor(fr, x, y, click=0.0, op=1.0):
    """Курсор-стрелка 48 px; click (0..1) — сжатие 0.9 и кольцо клика Sky."""
    s = 1 - 0.1 * math.sin(math.pi * clamp(click))
    pts = np.array([[0, 0], [0, 34], [9, 26], [16, 42], [22, 39], [15, 24], [27, 24]], np.float32) * 1.15 * s
    pts += np.float32([x, y])
    if 0 < click < 1:
        cv2.circle(fr, (int(x), int(y)), int(10 + 40 * click), C['sky'], 3, cv2.LINE_AA)
    cv2.fillPoly(fr, [pts.astype(np.int32)], C['white'], cv2.LINE_AA)
    cv2.polylines(fr, [pts.astype(np.int32)], True, C['ink'], 2, cv2.LINE_AA)


def progress_dots(fr, n, total, x, y, r=12, gap=40):
    """Кружки прогресса (выводы): рамка Sky, заполненный — Gold."""
    for i in range(total):
        c = (int(x + i * gap), int(y))
        if i < n:
            cv2.circle(fr, c, r, C['gold'], -1, cv2.LINE_AA)
        cv2.circle(fr, c, r, C['sky'], 2, cv2.LINE_AA)


def reconstruction_tag(fr, s=None):
    """Плашка в углу «реконструкция» (Manrope 22 px Sky)."""
    s = s or tx('look_recon', 'реконструкция')
    w = text_w(s, FX, 500, 22) + 30
    blit(fr, rrect(w, 38, 8, C['midnight'], C['sky'], 1, 220), 1920 - 80 - w, 1080 - 80 - 38)
    text_at(fr, s, 1920 - 80 - w / 2, 1080 - 80 - 19, FX, 500, 22, C['sky'], align='c', vcenter=True)


# ---------------------------------------------------------------- иконки (свои линии, без брендов)
def icon(fr, name, cx, cy, s=60, color=None, th=3):
    """Простые линейные иконки: bunker, backpack, people, hand, bolt, drop, can, fridge, clock, chat, folder, file,
    phone, laptop, cloud, lock, eye, shop, bug, step, apple, shovel, moon, plane, heart, thumb, warn, house, car,
    paw, bed, wrench, crowbar, plus, doc, globe."""
    col = tuple(color or C['sky'])
    s2 = s / 2
    L = lambda *p: cv2.polylines(fr, [np.array([(cx + a * s2, cy + b * s2) for a, b in p], np.int32)], False, col, th, cv2.LINE_AA)
    Cl = lambda *p: cv2.polylines(fr, [np.array([(cx + a * s2, cy + b * s2) for a, b in p], np.int32)], True, col, th, cv2.LINE_AA)
    O = lambda a, b, r: cv2.circle(fr, (int(cx + a * s2), int(cy + b * s2)), max(1, int(r * s2)), col, th, cv2.LINE_AA)
    if name == 'bunker':
        L((-1, -0.1), (1, -0.1)); Cl((-0.8, -0.1), (0.8, -0.1), (0.8, 0.9), (-0.8, 0.9)); L((-0.8, 0.4), (0.8, 0.4))
        L((0, -0.1), (0, -0.7)); L((-0.25, -0.7), (0.25, -0.7))
    elif name == 'house':
        Cl((-0.8, -0.1), (0, -0.8), (0.8, -0.1), (0.8, 0.85), (-0.8, 0.85)); Cl((-0.2, 0.85), (-0.2, 0.3), (0.2, 0.3), (0.2, 0.85))
    elif name == 'backpack':
        Cl((-0.6, -0.4), (0.6, -0.4), (0.7, 0.9), (-0.7, 0.9)); L((-0.3, -0.4), (-0.3, -0.75), (0.3, -0.75), (0.3, -0.4))
        Cl((-0.35, 0.25), (0.35, 0.25), (0.35, 0.65), (-0.35, 0.65))
    elif name == 'people':
        for dx in (-0.45, 0.45):
            O(dx, -0.4, 0.25); L((dx - 0.4, 0.8), (dx - 0.4, 0.25), (dx + 0.4, 0.25), (dx + 0.4, 0.8))
    elif name == 'hand':
        L((-0.5, 0.9), (-0.5, -0.1)); L((-0.25, 0.3), (-0.25, -0.8)); L((0.0, 0.3), (0.0, -0.9)); L((0.25, 0.3), (0.25, -0.7))
        L((0.5, 0.4), (0.5, -0.4)); L((-0.5, 0.9), (0.5, 0.9), (0.5, 0.4))
    elif name == 'bolt':
        Cl((0.1, -0.9), (-0.5, 0.15), (0.0, 0.15), (-0.15, 0.9), (0.5, -0.2), (0.0, -0.2))
    elif name == 'drop':
        pts = [(math.sin(a) * 0.6 * (1 - 0.0), 0.3 - math.cos(a) * 0.6) for a in np.linspace(-2.3, 2.3, 30)]
        L((0, -0.9), *[(x, -y + 0.6) for x, y in pts], (0, -0.9))
    elif name == 'can':
        Cl((-0.5, -0.7), (0.5, -0.7), (0.5, 0.8), (-0.5, 0.8)); L((-0.5, -0.2), (0.5, -0.2)); L((-0.5, 0.3), (0.5, 0.3))
    elif name == 'fridge':
        Cl((-0.55, -0.9), (0.55, -0.9), (0.55, 0.9), (-0.55, 0.9)); L((-0.55, -0.2), (0.55, -0.2)); L((0.35, -0.6), (0.35, -0.4))
        L((0.35, 0.1), (0.35, 0.4))
    elif name == 'clock':
        O(0, 0, 0.85); L((0, 0), (0, -0.55)); L((0, 0), (0.4, 0.2))
    elif name == 'chat':
        Cl((-0.85, -0.7), (0.85, -0.7), (0.85, 0.4), (-0.1, 0.4), (-0.5, 0.85), (-0.45, 0.4), (-0.85, 0.4))
        for dx in (-0.4, 0, 0.4):
            O(dx, -0.15, 0.05)
    elif name == 'folder':
        Cl((-0.9, -0.6), (-0.3, -0.6), (-0.15, -0.4), (0.9, -0.4), (0.9, 0.75), (-0.9, 0.75))
    elif name in ('file', 'doc'):
        Cl((-0.6, -0.9), (0.25, -0.9), (0.6, -0.55), (0.6, 0.9), (-0.6, 0.9)); L((0.25, -0.9), (0.25, -0.55), (0.6, -0.55))
        for yy in (-0.2, 0.15, 0.5):
            L((-0.35, yy), (0.35, yy))
    elif name == 'phone':
        Cl((-0.45, -0.9), (0.45, -0.9), (0.45, 0.9), (-0.45, 0.9)); L((-0.12, 0.7), (0.12, 0.7))
    elif name == 'laptop':
        Cl((-0.7, -0.6), (0.7, -0.6), (0.7, 0.35), (-0.7, 0.35)); L((-0.95, 0.6), (0.95, 0.6), (0.7, 0.35))
        L((-0.95, 0.6), (-0.7, 0.35))
    elif name == 'cloud':
        O(-0.35, 0.1, 0.38); O(0.15, -0.15, 0.48); O(0.55, 0.15, 0.32)
    elif name == 'lock':
        Cl((-0.55, -0.1), (0.55, -0.1), (0.55, 0.85), (-0.55, 0.85))
        L((-0.35, -0.1), (-0.35, -0.5), (-0.2, -0.75), (0.2, -0.75), (0.35, -0.5), (0.35, -0.1))
    elif name == 'eye':
        L(*[(math.cos(a) * 0.9, math.sin(a) * 0.45) for a in np.linspace(0, 2 * math.pi, 40)]); O(0, 0, 0.25)
    elif name == 'shop':
        Cl((-0.85, -0.2), (0.85, -0.2), (0.85, 0.85), (-0.85, 0.85)); L((-0.95, -0.2), (-0.7, -0.75), (0.7, -0.75), (0.95, -0.2))
        L((-0.6, 0.15), (0.6, 0.55)); L((-0.6, 0.55), (0.6, 0.15))
    elif name == 'bug':
        cv2.ellipse(fr, (int(cx), int(cy + s2 * 0.15)), (int(s2 * 0.4), int(s2 * 0.6)), 0, 0, 360, col, th, cv2.LINE_AA)
        O(0, -0.6, 0.22)
        for yy in (-0.1, 0.2, 0.5):
            L((-0.4, yy), (-0.85, yy - 0.15)); L((0.4, yy), (0.85, yy - 0.15))
    elif name == 'step':
        cv2.ellipse(fr, (int(cx - s2 * 0.3), int(cy - s2 * 0.2)), (int(s2 * 0.25), int(s2 * 0.45)), 0, 0, 360, col, th, cv2.LINE_AA)
        cv2.ellipse(fr, (int(cx + s2 * 0.3), int(cy + s2 * 0.3)), (int(s2 * 0.25), int(s2 * 0.45)), 0, 0, 360, col, th, cv2.LINE_AA)
    elif name == 'apple':
        O(0, 0.15, 0.65); L((0, -0.5), (0.15, -0.85))
    elif name == 'shovel':
        L((0.6, -0.9), (-0.1, 0.2)); Cl((-0.1, 0.2), (-0.55, 0.0), (-0.85, 0.6), (-0.3, 0.75))
    elif name == 'moon':
        cv2.ellipse(fr, (int(cx), int(cy)), (int(s2 * 0.8), int(s2 * 0.8)), 0, 60, 300, col, th, cv2.LINE_AA)
    elif name == 'plane':
        Cl((-0.9, 0.0), (0.9, -0.7), (0.35, 0.8), (0.05, 0.2)); L((0.05, 0.2), (0.9, -0.7))
    elif name == 'heart':
        L(*[(0.8 * (16 * math.sin(a) ** 3) / 16, -0.8 * (13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)) / 16)
            for a in np.linspace(0, 2 * math.pi, 50)])
    elif name == 'thumb':
        Cl((-0.8, -0.1), (-0.45, -0.1), (-0.45, 0.85), (-0.8, 0.85)); L((-0.45, -0.1), (-0.1, -0.85), (0.1, -0.7), (0.0, -0.2),
                                                                          (0.75, -0.2), (0.65, 0.85), (-0.45, 0.85))
    elif name == 'warn':
        Cl((0, -0.9), (0.9, 0.8), (-0.9, 0.8)); L((0, -0.3), (0, 0.3)); O(0, 0.55, 0.05)
    elif name == 'car':
        Cl((-0.9, 0.1), (-0.6, -0.4), (0.4, -0.4), (0.7, 0.1), (0.9, 0.1), (0.9, 0.5), (-0.9, 0.5)); O(-0.5, 0.55, 0.18); O(0.5, 0.55, 0.18)
    elif name == 'paw':
        O(0, 0.35, 0.35)
        for a, b in ((-0.55, -0.15), (-0.2, -0.55), (0.2, -0.55), (0.55, -0.15)):
            O(a, b, 0.15)
    elif name == 'bed':
        L((-0.9, -0.5), (-0.9, 0.7)); L((-0.9, 0.3), (0.9, 0.3), (0.9, 0.7)); Cl((-0.6, 0.0), (-0.2, 0.0), (-0.2, 0.3), (-0.6, 0.3))
    elif name == 'wrench':
        L((-0.6, 0.75), (0.25, -0.1)); O(0.45, -0.35, 0.35); L((0.35, -0.75), (0.55, -0.45))
    elif name == 'crowbar':
        L((-0.7, 0.8), (0.45, -0.6)); L((0.45, -0.6), (0.65, -0.75), (0.85, -0.6)); L((-0.7, 0.8), (-0.85, 0.7))
    elif name == 'plus':
        L((0, -0.7), (0, 0.7)); L((-0.7, 0), (0.7, 0))
    elif name == 'globe':
        O(0, 0, 0.85); L((-0.85, 0), (0.85, 0)); cv2.ellipse(fr, (int(cx), int(cy)), (int(s2 * 0.4), int(s2 * 0.85)), 0, 0, 360, col, th, cv2.LINE_AA)
    else:
        O(0, 0, 0.7)


# ================================================================ мем
def meme(fr, t, name, dur=2.0, start=0.0):
    """Мем на весь кадр: лёгкий наезд 100→106 % (вход и выход — жёсткий cut)."""
    src = asset_vid(name, t, start)
    fit_into(fr, src, (0, 0, fr.shape[1], fr.shape[0]), 0.5, 0.5, lerp(1.0, 1.06, prog(t, 0, dur)))


# ================================================================ переходы
TRANS_IN = {'cut': 0.0, 'whip': 0.125, 'push': 0.25, 'zoom-through': 0.2, 'wipe': 0.2, 'glitch': 0.13,
            'hatch': 0.3, 'lamp-flicker': 0.2}
TRANS_OUT = {'cut': 0.0, 'whip': 0.125, 'push': 0.25, 'zoom-through': 0.2, 'wipe': 0.2, 'glitch': 0.12,
             'hatch': 0.3, 'lamp-flicker': 0.4}


def _shift(fr, dx, dy, fillc=None):
    h, w = fr.shape[:2]
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    out = cv2.warpAffine(fr, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(fillc or C['midnight']))
    fr[:] = out


def _mblur(fr, n):
    n = int(n)
    if n >= 3:
        k = np.zeros((1, n), np.float32)
        k[:] = 1 / n
        fr[:] = cv2.filter2D(fr, -1, k)


def _zoom(fr, z, cx=None, cy=None):
    h, w = fr.shape[:2]
    cx = w / 2 if cx is None else cx
    cy = h / 2 if cy is None else cy
    M = np.float32([[z, 0, cx - cx * z], [0, z, cy - cy * z]])
    fr[:] = cv2.warpAffine(fr, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def _glitch(fr, k, seed):
    if k <= 0:
        return
    h, w = fr.shape[:2]
    d = int(18 * k)
    if d > 0:
        r = fr[:, :, 0].copy()
        b = fr[:, :, 2].copy()
        fr[:, d:, 0] = r[:, :-d]
        fr[:, :-d, 2] = b[:, d:]
    rng = np.random.default_rng(seed)
    for _ in range(int(8 * k) + 1):
        y0 = int(rng.random() * h)
        hh = int(10 + rng.random() * 60)
        sh = int((rng.random() - 0.5) * 120 * k)
        fr[y0:y0 + hh] = np.roll(fr[y0:y0 + hh], sh, axis=1)


def _hatch(fr, closed):
    """Створки люка Midnight с заклёпками: closed=0 — открыты, 1 — сомкнуты в центре."""
    if closed <= 0:
        return
    h, w = fr.shape[:2]
    pw = int(w / 2 * closed)
    for side in (0, 1):
        x0 = 0 if side == 0 else w - pw
        fr[:, x0:x0 + pw] = C['midnight']
        edge = pw if side == 0 else w - pw
        cv2.rectangle(fr, (edge - 14 if side == 0 else edge, 0), (edge if side == 0 else edge + 14, h), C['blue'], -1)
        for yy in range(60, h, 120):
            for ex in (36, 90):
                xr = edge - ex if side == 0 else edge + ex
                if 0 <= xr < w:
                    cv2.circle(fr, (int(xr), yy), 7, C['ocean'], -1, cv2.LINE_AA)
                    cv2.circle(fr, (int(xr), yy), 7, C['sky'], 1, cv2.LINE_AA)


def _flicker(fr, k):
    """Мерцание лампы: k 0..1 по времени эффекта."""
    if k <= 0:
        return
    lv = 1.0
    for a, b in ((0.1, 0.3), (0.45, 0.65)):
        if a <= k < b:
            lv = 0.15
    if k >= 0.8:
        lv = 0.0 if k >= 0.95 else 1 - (k - 0.8) / 0.15
    dim_ = max(0.0, lv)
    cv2.convertScaleAbs(fr, dst=fr, alpha=dim_)


def _wipe(fr, k, reveal):
    """Шторка: полоса Sky 6 px идёт слева направо. reveal=True — новый кадр открывается слева."""
    h, w = fr.shape[:2]
    x = int(w * k)
    if reveal:
        fr[:, x:] = C['midnight']
    else:
        fr[:, :x] = C['midnight']
    cv2.rectangle(fr, (x - 3, 0), (x + 3, h), C['sky'], -1)


def trans_in(fr, t, kind, seed=1):
    """Вход сцены (первые доли секунды). Половина фирменного/стандартного перехода — вторая в trans_out
    предыдущей сцены, поэтому склейка в проекте выглядит цельной."""
    d = TRANS_IN.get(kind, 0)
    if d <= 0 or t >= d:
        return
    k = prog(t, 0, d)
    if kind == 'hatch':
        _hatch(fr, 1 - oc(k))
    elif kind == 'lamp-flicker':
        cv2.convertScaleAbs(fr, dst=fr, alpha=(0.15 if 0.3 < k < 0.55 else oc(k)))
    elif kind == 'push':
        _shift(fr, 0, (1 - oc(k)) * fr.shape[0] * 0.5)
    elif kind == 'whip':
        _shift(fr, (1 - oc(k)) * fr.shape[1] * 0.35, 0)
        _mblur(fr, 60 * (1 - k))
    elif kind == 'zoom-through':
        _zoom(fr, lerp(1.35, 1.0, oc(k)))
        if k < 0.7:
            fr[:] = cv2.GaussianBlur(fr, (0, 0), 6 * (1 - k))
    elif kind == 'glitch':
        _glitch(fr, 1 - k, seed + int(t * 30))
    elif kind == 'wipe':
        _wipe(fr, oc(k), True)


def trans_out(fr, t, dur, kind, seed=2):
    """Выход сцены (последние доли секунды)."""
    d = TRANS_OUT.get(kind, 0)
    if d <= 0 or t < dur - d:
        return
    k = prog(t, dur - d, dur)
    if kind == 'hatch':
        _hatch(fr, ic(k))
    elif kind == 'lamp-flicker':
        _flicker(fr, k)
    elif kind == 'push':
        _shift(fr, 0, -ic(k) * fr.shape[0] * 0.5)
    elif kind == 'whip':
        _shift(fr, -ic(k) * fr.shape[1] * 0.35, 0)
        _mblur(fr, 60 * k)
    elif kind == 'zoom-through':
        _zoom(fr, lerp(1.0, 1.6, ic(k)))
        fr[:] = cv2.GaussianBlur(fr, (0, 0), 0.1 + 6 * k)
    elif kind == 'glitch':
        _glitch(fr, k, seed + int(t * 30))
    elif kind == 'wipe':
        _wipe(fr, ic(k), False)


def scene_fx(fr, t, dur, tin, tout):
    """Вход + выход сцены одним вызовом (в конце render)."""
    trans_in(fr, t, tin)
    trans_out(fr, t, dur, tout)


# ================================================================ звук
_SFX_FALLBACK = {}


def _syn(a, name, t0, g):
    """Запасной синтез, если файла assets/sfx/<name>.wav нет."""
    from studio.sound import tt, bp, hp, lp, SR
    n = name.replace('SFX-', '')
    r = a.rng
    if n == 'whoosh':
        a.whoosh(t0, 0.35, 0.35 * g)
    elif n in ('click', 'keyboard-tap'):
        a.tick(t0, 0.35 * g)
    elif n == 'tick':
        a.tick(t0, 0.18 * g)
    elif n == 'pop':
        x = tt(0.12)
        a.add(np.sin(2 * np.pi * np.cumsum(900 - 500 * x / 0.12) / SR) * np.exp(-x / 0.03), t0, 0.35 * g)
    elif n == 'keyboard-typing':
        for i in range(24):
            a.tick(t0 + i * 0.13 + r.random() * 0.05, 0.12 * g)
    elif n == 'message-send':
        x = tt(0.25)
        a.add(np.sin(2 * np.pi * np.cumsum(500 + 900 * x / 0.25) / SR) * np.exp(-x / 0.08), t0, 0.25 * g)
    elif n == 'record-scratch':
        x = tt(0.45)
        f = 300 + 1200 * np.abs(np.sin(x * 14))
        s = bp(r.standard_normal(len(x)), 300, 3000) * 0.6 + np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.4
        a.add(s * np.exp(-x / 0.25), t0, 0.45 * g)
    elif n == 'stamp':
        a.taiko(t0, 0.7 * g)
    elif n == 'error-buzz':
        x = tt(0.3)
        a.add(lp(np.sign(np.sin(2 * np.pi * 110 * x)), 1200) * np.exp(-x / 0.15), t0, 0.25 * g)
    elif n == 'success-soft':
        a.piano(t0, 'E5', 0.18 * g, 1.5)
        a.piano(t0 + 0.09, 'B5', 0.14 * g, 1.5)
    elif n == 'bell-ding':
        a.piano(t0, 'A6', 0.2 * g, 2.0)
    elif n == 'hit-soft':
        a.taiko(t0, 0.45 * g)
    elif n == 'tire-screech-short':
        x = tt(0.4)
        a.add(bp(r.standard_normal(len(x)), 1800, 3500) * np.sin(np.pi * x / 0.4), t0, 0.12 * g)
    elif n == 'card-flip':
        x = tt(0.15)
        a.add(hp(r.standard_normal(len(x)), 2000) * np.exp(-x / 0.03), t0, 0.25 * g)
    elif n == 'fast-forward':
        x = tt(0.8)
        a.add(np.sin(2 * np.pi * np.cumsum(200 + 1600 * x / 0.8) / SR) * 0.3 * np.sin(np.pi * x / 0.8), t0, 0.25 * g)
    elif n == 'hatch-clang':
        x = tt(0.9)
        s = sum(np.sin(2 * np.pi * f * x) * np.exp(-x / d) for f, d in ((180, 0.4), (431, 0.25), (797, 0.18), (1250, 0.1)))
        s += lp(r.standard_normal(len(x)), 1500) * np.exp(-x / 0.03)
        a.add(s * 0.4, t0, 0.5 * g, wet=0.4)
    elif n == 'lamp-buzz':
        x = tt(1.2)
        s = lp(np.sign(np.sin(2 * np.pi * 100 * x)), 600) * 0.15 * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * x))
        a.add(s, t0, 0.3 * g)
    elif n == 'dig-shovel':
        a.taiko(t0, 0.25 * g)
        x = tt(0.25)
        a.add(bp(r.standard_normal(len(x)), 300, 2000) * np.exp(-x / 0.08), t0 + 0.02, 0.25 * g)
    elif n == 'wind-cold':
        x = tt(3.0)
        s = bp(r.standard_normal(len(x)), 300, 1200) * np.sin(np.pi * x / 3.0) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.7 * x))
        a.add(s, t0, 0.18 * g, wet=0.3)
    else:
        a.tick(t0, 0.2 * g)


def sfx(a, name, t0, g=1.0):
    """Звук SFX-… из assets/sfx/ (имя без расширения, например 'SFX-whoosh'); нет файла — синтез."""
    if t0 < 0 or t0 > a.dur + 0.5:
        return
    try:
        a.clip('sfx/' + name, t0, g, dur=4.0)
    except Exception:
        _syn(a, name, t0, g)


def sfx_hits(a, name, times, g=1.0):
    for ti in times:
        sfx(a, name, ti, g)
