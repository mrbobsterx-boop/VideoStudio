"""Готовые эффекты: добавляются к сцене во вкладке «Эффекты» или из кода через effect(fr, t, dur, 'имя', ...).

Каждый эффект описан в REGISTRY: подпись, группа, параметры (для интерфейса) и функция.
Функция получает кадр fr (RGB uint8, меняется на месте), lt — время от начала действия эффекта,
ld — длительность действия эффекта, p — параметры и ctx (t сцены, dur сцены, номер кадра).
"""
import math

import cv2
import numpy as np

from . import kit

REGISTRY = {}
ORDER = []


def _reg(name, label, group, params, desc=''):
    def deco(fn):
        REGISTRY[name] = dict(name=name, label=label, group=group, params=params, desc=desc, fn=fn)
        ORDER.append(name)
        return fn
    return deco


def num(k, label, lo, hi, step, d):
    return dict(k=k, label=label, type='num', min=lo, max=hi, step=step, default=d)


def sel(k, label, options, d):
    return dict(k=k, label=label, type='select', options=options, default=d)


def _ease(x):
    return x * x * (3 - 2 * x)


def _scale_frame(fr, s, dx=0.0, dy=0.0, ang=0.0):
    H, W = fr.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, s)
    M[0, 2] += dx
    M[1, 2] += dy
    cv2.warpAffine(fr, M, (W, H), dst=fr, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _mix_color(fr, color, k):
    if k <= 0.001:
        return
    ov = np.empty_like(fr)
    ov[:] = color
    cv2.addWeighted(fr, 1 - k, ov, k, 0, dst=fr)


# ================================================================ переходы
@_reg('fade_in', 'Появление из чёрного', 'Переходы', [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.5)])
def _fade_in(fr, lt, ld, p, ctx):
    k = kit.prog(lt, 0, p['dur'])
    if k < 1:
        kit.dim(fr, _ease(k))


@_reg('fade_out', 'Уход в чёрное', 'Переходы', [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.5)])
def _fade_out(fr, lt, ld, p, ctx):
    k = 1 - kit.prog(lt, ld - p['dur'], ld)
    if k < 1:
        kit.dim(fr, _ease(k))


@_reg('white_in', 'Из белого', 'Переходы', [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.4)])
def _white_in(fr, lt, ld, p, ctx):
    _mix_color(fr, (255, 255, 255), 1 - _ease(kit.prog(lt, 0, p['dur'])))


@_reg('white_out', 'В белое', 'Переходы', [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.4)])
def _white_out(fr, lt, ld, p, ctx):
    _mix_color(fr, (255, 255, 255), _ease(kit.prog(lt, ld - p['dur'], ld)))


@_reg('flash_in', 'Вспышка на входе', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 1.5, 0.05, 0.25), num('amount', 'Сила', 0, 1, 0.05, 0.8)])
def _flash_in(fr, lt, ld, p, ctx):
    k = (1 - kit.prog(lt, 0, p['dur'])) ** 2 * p['amount']
    _mix_color(fr, (255, 244, 230), k)


@_reg('blur_in', 'Из размытия', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.6), num('amount', 'Сила', 1, 40, 1, 14)])
def _blur_in(fr, lt, ld, p, ctx):
    kit.blur(fr, p['amount'] * (1 - kit.oc(kit.prog(lt, 0, p['dur']))))


@_reg('blur_out', 'В размытие', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 3, 0.05, 0.6), num('amount', 'Сила', 1, 40, 1, 14)])
def _blur_out(fr, lt, ld, p, ctx):
    kit.blur(fr, p['amount'] * kit.ic(kit.prog(lt, ld - p['dur'], ld)))


@_reg('punch_in', 'Удар-наезд на входе', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 1.5, 0.05, 0.35), num('amount', 'Сила', 0.02, 0.6, 0.01, 0.18)])
def _punch_in(fr, lt, ld, p, ctx):
    k = kit.prog(lt, 0, p['dur'])
    if k < 1:
        _scale_frame(fr, 1 + p['amount'] * (1 - kit.oexp(k)))


@_reg('whip_in', 'Смазанный вход', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 1.5, 0.05, 0.3), sel('dir', 'Откуда', [['left', 'слева'], ['right', 'справа']], 'right')])
def _whip_in(fr, lt, ld, p, ctx):
    k = kit.prog(lt, 0, p['dur'])
    if k >= 1:
        return
    e = 1 - kit.oexp(k)
    W = fr.shape[1]
    sgn = 1 if p['dir'] == 'right' else -1
    _scale_frame(fr, 1.0, dx=sgn * W * 0.35 * e)
    n = int(2 + 120 * e)
    kern = np.zeros((1, n), np.float32)
    kern[0, :] = 1.0 / n
    fr[:] = cv2.filter2D(fr, -1, kern, borderType=cv2.BORDER_REFLECT)


@_reg('whip_out', 'Смазанный уход', 'Переходы',
      [num('dur', 'Длительность, с', 0.05, 1.5, 0.05, 0.3), sel('dir', 'Куда', [['left', 'влево'], ['right', 'вправо']], 'left')])
def _whip_out(fr, lt, ld, p, ctx):
    k = kit.prog(lt, ld - p['dur'], ld)
    if k <= 0:
        return
    e = kit.iexp(k)
    W = fr.shape[1]
    sgn = 1 if p['dir'] == 'right' else -1
    _scale_frame(fr, 1.0, dx=sgn * W * 0.35 * e)
    n = int(2 + 120 * e)
    kern = np.full((1, n), 1.0 / n, np.float32)
    fr[:] = cv2.filter2D(fr, -1, kern, borderType=cv2.BORDER_REFLECT)


# ================================================================ камера
@_reg('zoom', 'Наезд / отъезд камеры', 'Камера',
      [num('amount', 'Сила (минус — отъезд)', -0.4, 0.4, 0.01, 0.08),
       sel('ease', 'Плавность', [['linear', 'ровно'], ['inout', 'мягко'], ['out', 'тормозит']], 'linear')])
def _zoom(fr, lt, ld, p, ctx):
    u = kit.prog(lt, 0, ld)
    u = {'inout': kit.ioc, 'out': kit.oc}.get(p['ease'], lambda x: x)(u)
    a = p['amount']
    s = 1 + a * u if a >= 0 else 1 + (-a) * (1 - u)
    if abs(s - 1) > 1e-4:
        _scale_frame(fr, s)


@_reg('pan', 'Панорама', 'Камера',
      [num('amount', 'Сдвиг, px (минус — влево)', -400, 400, 10, 120),
       sel('axis', 'Направление', [['x', 'по горизонтали'], ['y', 'по вертикали']], 'x')])
def _pan(fr, lt, ld, p, ctx):
    u = kit.ioc(kit.prog(lt, 0, ld))
    a = p['amount']
    H, W = fr.shape[:2]
    s = 1 + 2 * abs(a) / (W if p['axis'] == 'x' else H)
    d = a * (u - 0.5)
    _scale_frame(fr, s, dx=d if p['axis'] == 'x' else 0, dy=d if p['axis'] == 'y' else 0)


@_reg('shake', 'Тряска камеры', 'Камера',
      [num('amount', 'Сила, px', 1, 60, 1, 10), num('speed', 'Скорость', 0.2, 5, 0.1, 1.0)])
def _shake(fr, lt, ld, p, ctx):
    a, sp = p['amount'], p['speed']
    t = ctx['t'] * sp
    dx = (math.sin(t * 13.1) + 0.6 * math.sin(t * 29.7 + 1)) * a * 0.6
    dy = (math.cos(t * 11.3) + 0.6 * math.sin(t * 23.9 + 2)) * a * 0.5
    ang = math.sin(t * 7.7) * a * 0.012
    _scale_frame(fr, 1 + a / 700, dx, dy, ang)


@_reg('handheld', 'Ручная камера', 'Камера', [num('amount', 'Сила', 0.1, 3, 0.1, 1.0)])
def _handheld(fr, lt, ld, p, ctx):
    a, t = p['amount'], ctx['t']
    dx = (math.sin(t * 0.9) * 6 + math.sin(t * 2.3 + 1) * 3) * a
    dy = (math.sin(t * 0.7 + 2) * 4 + math.sin(t * 1.9) * 2) * a
    ang = math.sin(t * 0.5 + 1) * 0.35 * a
    _scale_frame(fr, 1 + 0.02 * a, dx, dy, ang)


# ================================================================ цвет
_GRADES = {
    # (множители RGB, насыщенность, контраст, подъём теней RGB, яркость)
    'cold': ((0.9, 1.0, 1.12), 0.85, 1.05, (0, 4, 10), 1.0),
    'warm': ((1.1, 1.0, 0.86), 1.05, 1.05, (8, 4, 0), 1.0),
    'teal_orange': (None, 1.1, 1.1, None, 1.0),
    'bleach': ((1.0, 1.0, 1.0), 0.45, 1.3, (0, 0, 0), 1.02),
    'noir': ((1.0, 1.0, 1.0), 0.0, 1.35, (0, 0, 0), 0.95),
    'sepia': (None, 0.0, 1.05, None, 1.0),
    'vivid': ((1.0, 1.0, 1.0), 1.4, 1.12, (0, 0, 0), 1.03),
    'faded': ((1.02, 1.0, 0.98), 0.75, 0.82, (22, 20, 18), 1.0),
    'night': ((0.75, 0.9, 1.2), 0.6, 1.1, (0, 4, 14), 0.8),
    'matrix': ((0.8, 1.12, 0.8), 0.8, 1.1, (0, 6, 0), 1.0),
}
GRADE_OPTIONS = [['cold', 'холодный'], ['warm', 'тёплый'], ['teal_orange', 'бирюза/оранж (кино)'], ['bleach', 'выбеленный'],
                 ['noir', 'нуар ч/б'], ['sepia', 'сепия'], ['vivid', 'сочный'], ['faded', 'выцветший плёночный'],
                 ['night', 'ночь'], ['matrix', 'зелёный']]


_GLUT = {}


def _grade_luts(preset):
    """Три таблицы (по каналу R, G, B) для пресета — считаются один раз."""
    if preset in _GLUT:
        return _GLUT[preset]
    mul, sat, con, lift, br = _GRADES[preset]
    x = np.arange(256, dtype=np.float32)
    luts = []
    for c in range(3):
        v = x.copy()
        if preset == 'teal_orange':
            l = v / 255
            v = v + [-14, 6, 16][c] * (1 - l) ** 2 + [18, 6, -16][c] * l ** 2
        elif preset == 'sepia':
            v = v * [1.07, 0.95, 0.78][c] + [10, 4, 0][c]
        v = (v - 128) * con + 128
        if mul:
            v = v * mul[c]
        if lift:
            v = v + lift[c] * (1 - v / 255)
        v = v * br
        luts.append(np.clip(v, 0, 255).astype(np.uint8))
    _GLUT[preset] = (sat, luts)
    return _GLUT[preset]


def grade(fr, preset, strength=1.0):
    """Цветокоррекция кадра по пресету (см. GRADE_OPTIONS)."""
    if preset not in _GRADES or strength <= 0:
        return
    sat, luts = _grade_luts(preset)
    src = fr
    if preset == 'sepia':
        src = kit._saturate(fr, 0.0)
        sat = 1.0
    src = kit._saturate(src, sat)
    out = cv2.merge([cv2.LUT(c, l) for c, l in zip(cv2.split(src), luts)])
    if strength >= 0.999:
        fr[:] = out
    else:
        cv2.addWeighted(fr, 1 - strength, out, strength, 0, dst=fr)


@_reg('grade', 'Цветокоррекция (пресет)', 'Цвет',
      [sel('preset', 'Стиль', GRADE_OPTIONS, 'teal_orange'), num('strength', 'Сила', 0, 1, 0.05, 0.8)])
def _grade(fr, lt, ld, p, ctx):
    grade(fr, p['preset'], p['strength'])


@_reg('adjust', 'Яркость / контраст / насыщенность', 'Цвет',
      [num('bright', 'Яркость', 0.2, 2, 0.02, 1.0), num('con', 'Контраст', 0.3, 2, 0.02, 1.0),
       num('sat', 'Насыщенность', 0, 2.5, 0.05, 1.0)])
def _adjust(fr, lt, ld, p, ctx):
    fr[:] = kit._grade(fr, p['sat'], p['con'], p['bright'], (1, 1, 1))


@_reg('bw', 'Чёрно-белое', 'Цвет', [num('amount', 'Сила', 0, 1, 0.05, 1.0)])
def _bw(fr, lt, ld, p, ctx):
    kit.grayscale(fr, p['amount'])


@_reg('tint', 'Тонирование цветом', 'Цвет',
      [sel('color', 'Цвет', [['#3b6cff', 'синий'], ['#1fb5a8', 'бирюзовый'], ['#b83dff', 'фиолетовый'],
                              ['#ff3b5c', 'красный'], ['#ffd27a', 'золотой'], ['#7dff9a', 'зелёный']], '#3b6cff'),
       num('amount', 'Сила', 0, 1, 0.05, 0.25)])
def _tint(fr, lt, ld, p, ctx):
    c = _hex(p['color'])
    g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
    col = cv2.merge([cv2.LUT(g, kit._lut(lambda x, m=m: x * m / 255)) for m in c])
    cv2.addWeighted(fr, 1 - p['amount'], col, p['amount'], 0, dst=fr)


def _hex(s, default=(236, 228, 214)):
    try:
        s = str(s).lstrip('#')
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


# ================================================================ стилизация
@_reg('rgb_split', 'Расслоение цвета (RGB)', 'Стиль', [num('amount', 'Сдвиг, px', 1, 40, 1, 6)])
def _rgb_split(fr, lt, ld, p, ctx):
    d = int(p['amount'])
    if d > 0:
        r = fr[:, :, 0].copy()
        b = fr[:, :, 2].copy()
        fr[:, d:, 0] = r[:, :-d]
        fr[:, :-d, 2] = b[:, d:]


@_reg('glitch', 'Глитч', 'Стиль',
      [num('amount', 'Сила', 0.05, 1, 0.05, 0.5), num('rate', 'Частота сбоев', 0.2, 8, 0.1, 2.0)])
def _glitch(fr, lt, ld, p, ctx):
    t = ctx['t']
    slot = int(t * p['rate'] * 4)
    rng = np.random.default_rng(slot * 7919 + 13)
    if rng.random() > 0.45 + 0.35 * p['amount']:
        return          # между сбоями — чистая картинка
    H, W = fr.shape[:2]
    a = p['amount']
    for _ in range(int(3 + 10 * a)):
        y = int(rng.integers(0, H - 8))
        h = int(rng.integers(4, max(6, int(H * 0.08 * a) + 6)))
        dx = int(rng.normal(0, 60 * a))
        fr[y:y + h] = np.roll(fr[y:y + h], dx, axis=1)
    _rgb_split(fr, lt, ld, dict(amount=int(4 + 18 * a * rng.random())), ctx)


@_reg('vhs', 'Видеокассета (VHS)', 'Стиль', [num('amount', 'Сила', 0.1, 1, 0.05, 0.6)])
def _vhs(fr, lt, ld, p, ctx):
    a = p['amount']
    H, W = fr.shape[:2]
    sm = cv2.resize(fr, (W // 3, H // 2), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), 0.8)
    soft = cv2.resize(sm, (W, H), interpolation=cv2.INTER_LINEAR)
    cv2.addWeighted(fr, 1 - 0.7 * a, soft, 0.7 * a, 0, dst=fr)
    _rgb_split(fr, lt, ld, dict(amount=int(3 + 5 * a)), ctx)
    lines = np.ones((H, 1, 1), np.float32)
    lines[::3] = 1 - 0.18 * a
    fr[:] = (fr.astype(np.float32) * lines).astype(np.uint8)
    rng = np.random.default_rng(ctx['lfi'])
    y = int((ctx['t'] * 90) % H)
    band = slice(y, min(H, y + int(18 * a) + 4))
    fr[band] = np.roll(fr[band], int(rng.integers(5, 25)), axis=1)
    noise = rng.integers(0, int(30 * a) + 1, (H // 4, W // 4), dtype=np.uint8)
    noise = cv2.resize(noise, (W, H), interpolation=cv2.INTER_NEAREST)
    cv2.add(fr, cv2.merge([noise] * 3), dst=fr)


@_reg('bloom', 'Свечение ярких мест', 'Стиль',
      [num('amount', 'Сила', 0.1, 2, 0.05, 0.6), num('threshold', 'Порог', 100, 250, 5, 180)])
def _bloom(fr, lt, ld, p, ctx):
    H, W = fr.shape[:2]
    sm = cv2.resize(fr, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    br = cv2.subtract(sm, np.full_like(sm, int(p['threshold'])))
    br = cv2.GaussianBlur(br, (0, 0), 12)
    big = cv2.resize(br, (W, H), interpolation=cv2.INTER_LINEAR)
    cv2.addWeighted(fr, 1, big, p['amount'] * 2.2, 0, dst=fr)


@_reg('light_leak', 'Засветка плёнки', 'Стиль',
      [sel('color', 'Цвет', [['warm', 'тёплая'], ['rose', 'розовая'], ['cyan', 'голубая'], ['gold', 'золотая']], 'warm'),
       num('amount', 'Сила', 0.05, 1.5, 0.05, 0.6), num('speed', 'Скорость', 0.1, 3, 0.1, 1.0)])
def _light_leak(fr, lt, ld, p, ctx):
    cols = {'warm': (255, 120, 50), 'rose': (255, 80, 140), 'cyan': (60, 190, 255), 'gold': (255, 200, 90)}
    c = cols.get(p['color'], (255, 120, 50))
    H, W = fr.shape[:2]
    w, h = W // 8, H // 8
    ov = np.zeros((h, w, 3), np.uint8)
    t = ctx['t'] * p['speed']
    for i, (ph, r) in enumerate([(0.0, 0.55), (2.1, 0.4), (4.2, 0.3)]):
        x = w * (0.5 + 0.55 * math.sin(t * 0.45 + ph))
        y = h * (0.5 + 0.45 * math.cos(t * 0.33 + ph * 1.3))
        k = 0.55 + 0.45 * math.sin(t * 0.8 + ph * 2)
        cv2.circle(ov, (int(x), int(y)), int(w * r), tuple(int(v * k) for v in c), -1)
    ov = cv2.GaussianBlur(ov, (0, 0), w * 0.12)
    big = cv2.resize(ov, (W, H), interpolation=cv2.INTER_LINEAR)
    cv2.addWeighted(fr, 1, big, p['amount'], 0, dst=fr)


@_reg('vignette', 'Сильная виньетка', 'Стиль', [num('amount', 'Сила', 0.1, 1, 0.05, 0.5)])
def _vignette(fr, lt, ld, p, ctx):
    H, W = fr.shape[:2]
    key = ('vig', W, H, round(p['amount'], 2))
    m = _CACHE.get(key)
    if m is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        v = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        k = 1 - p['amount'] * (1 - np.clip(1 - v ** 2.2 * 0.8, 0, 1))
        m = _CACHE[key] = cv2.merge([(k * 255).astype(np.uint8)] * 3)
        while len(_CACHE) > 12:
            _CACHE.pop(next(iter(_CACHE)))
    cv2.multiply(fr, m, dst=fr, scale=1 / 255)


@_reg('sharpen', 'Резкость', 'Стиль', [num('amount', 'Сила', 0.1, 2, 0.05, 0.5)])
def _sharpen(fr, lt, ld, p, ctx):
    bl = cv2.GaussianBlur(fr, (0, 0), 2)
    cv2.addWeighted(fr, 1 + p['amount'], bl, -p['amount'], 0, dst=fr)


@_reg('blur_all', 'Размытие', 'Стиль', [num('amount', 'Сила', 0.5, 30, 0.5, 6)])
def _blur_all(fr, lt, ld, p, ctx):
    kit.blur(fr, p['amount'])


@_reg('darken', 'Затемнение', 'Стиль', [num('amount', 'Сила', 0, 1, 0.05, 0.3)])
def _darken(fr, lt, ld, p, ctx):
    kit.dim(fr, 1 - p['amount'])


@_reg('shade_bottom', 'Затемнение снизу (под титры)', 'Стиль', [num('amount', 'Сила', 0, 1, 0.05, 0.6)])
def _shade(fr, lt, ld, p, ctx):
    kit.shade_bottom(fr, h=300, k=1 - p['amount'])


# ================================================================ частицы
@_reg('dust', 'Пыль в воздухе', 'Частицы', [num('amount', 'Сила', 0.05, 1.5, 0.05, 0.4)])
def _dust(fr, lt, ld, p, ctx):
    kit.dust(fr, ctx['t'], amt=p['amount'])


@_reg('embers', 'Искры', 'Частицы', [num('amount', 'Сила', 0.05, 1.5, 0.05, 0.7)])
def _embers(fr, lt, ld, p, ctx):
    kit.embers(fr, ctx['t'], p['amount'])


_R = np.random.default_rng(21)
_SNOW = _R.random((260, 4))
_RAIN = _R.random((300, 3))


@_reg('snow', 'Снег', 'Частицы', [num('amount', 'Сила', 0.1, 1.5, 0.05, 0.7)])
def _snow(fr, lt, ld, p, ctx):
    H, W = fr.shape[:2]
    t = ctx['t']
    ov = np.zeros_like(fr)
    for x0, y0, sz, ph in _SNOW:
        sp = 40 + sz * 90
        x = (x0 * W + math.sin(t * 0.8 + ph * 6) * 30) % W
        y = (y0 * H + t * sp) % H
        cv2.circle(ov, (int(x), int(y)), 1 + int(sz * 3), (240, 244, 250), -1, cv2.LINE_AA)
    cv2.addWeighted(fr, 1, ov, p['amount'], 0, dst=fr)


@_reg('rain', 'Дождь', 'Частицы', [num('amount', 'Сила', 0.1, 1.5, 0.05, 0.5)])
def _rain(fr, lt, ld, p, ctx):
    H, W = fr.shape[:2]
    t = ctx['t']
    ov = np.zeros_like(fr)
    for x0, y0, sp in _RAIN:
        v = 1400 + sp * 900
        x = (x0 * W + t * 180) % W
        y = (y0 * H + t * v) % (H + 80) - 40
        cv2.line(ov, (int(x), int(y)), (int(x - 6), int(y - 38 - sp * 20)), (170, 180, 195), 1, cv2.LINE_AA)
    cv2.addWeighted(fr, 1, ov, p['amount'], 0, dst=fr)
    kit.dim(fr, 1 - 0.08 * p['amount'])


_CACHE = {}


# ================================================================ применение
def defaults(name):
    e = REGISTRY.get(name)
    return {q['k']: q['default'] for q in e['params']} if e else {}


def clean(item):
    """Проверить и дополнить описание эффекта (для project.json)."""
    name = item.get('name')
    if name not in REGISTRY:
        return None
    out = dict(name=name, on=bool(item.get('on', True)))
    for q in REGISTRY[name]['params']:
        v = item.get(q['k'], q['default'])
        if q['type'] == 'num':
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = q['default']
            v = max(q['min'], min(q['max'], v))
        else:
            if v not in [o[0] for o in q['options']]:
                v = q['default']
        out[q['k']] = v
    for k in ('t0', 't1'):
        v = item.get(k)
        if v not in (None, ''):
            try:
                out[k] = max(0.0, float(v))
            except (TypeError, ValueError):
                pass
    return out


def apply(fr, t, dur, item, lfi=0):
    e = REGISTRY.get(item.get('name'))
    if not e or item.get('on') is False:
        return
    t0 = float(item.get('t0') or 0.0)
    t1 = item.get('t1')
    t1 = dur if t1 in (None, '') else min(dur, float(t1))
    if not (t0 <= t <= t1 + 1e-6):
        return
    p = defaults(item['name'])
    p.update({k: v for k, v in item.items() if k in p})
    e['fn'](fr, t - t0, max(1e-3, t1 - t0), p, dict(t=t, dur=dur, lfi=lfi))


def apply_all(fr, t, dur, items, lfi=0):
    for it in items or []:
        apply(fr, t, dur, it, lfi)


def catalog():
    """Описание эффектов для интерфейса и для инструкции ИИ."""
    return [dict(name=n, label=REGISTRY[n]['label'], group=REGISTRY[n]['group'], params=REGISTRY[n]['params'],
                 desc=REGISTRY[n]['desc']) for n in ORDER]
