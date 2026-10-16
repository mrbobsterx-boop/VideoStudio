"""Красивая 2D-графика для сцен: Skia (движок отрисовки Chrome), подсветка кода (Pygments), постобработка кадра.

Всё доступно в сцене через `from studio.kit import *`.

    def render(fr, t, dur):
        darkbg(fr)
        with canvas(fr) as c:                                   # рисуем Skia прямо в кадр
            sk_rrect(c, 200, 200, 900, 420, 28, (24, 28, 38), shadow=(18, 40, 0.5))
            sk_text(c, 'Заголовок', 260, 330, font('title', 72, 800), WHITE, glow=((120, 170, 255), 18))
        bloom(fr, 0.5)                                          # после блока — снова обычный numpy/cv2

Если skia-python или pygments не установлены, сцена не падает: вместо кадра — понятная заглушка с подсказкой.
"""
import contextlib
import hashlib
import io
import math
import os

import cv2
import numpy as np

from . import kit

try:
    import skia
    HAS_SKIA = True
except Exception:              # нет колеса под эту систему или нет libEGL (Linux) — редактор работает дальше
    HAS_SKIA = False
    skia = None

HERE = os.path.dirname(os.path.abspath(__file__))
BUILTIN_FONTS = os.path.join(HERE, 'fonts')

__all__ = ['skia', 'canvas', 'flush', 'font', 'sk_color', 'sk_paint', 'sk_text', 'sk_text_width', 'sk_rrect',
           'sk_rect', 'sk_circle', 'sk_line', 'sk_path', 'sk_image', 'sk_glow', 'lin_grad', 'rad_grad', 'sk_clip',
           'sk_mask', 'code_block', 'bloom', 'vignette', 'film_grain', 'scanlines', 'motion_blur']

HINTS = {
    'skia': 'skia-python',
    'pygments': 'pygments',
    'fontTools': 'fonttools',
    'pyvista': 'pyvista',
    'trimesh': 'trimesh',
    'manim': 'manim (requirements-manim.txt)',
}


class Missing(RuntimeError):
    """Нет нужной библиотеки: движок покажет заглушку вместо падения сцены."""

    def __init__(self, lib, what=''):
        self.lib = lib
        pkg = HINTS.get(lib, lib)
        super().__init__('Нет %s%s — запусти установку: закрой редактор и запусти start_… снова '
                         '(или: pip install -r requirements.txt)' % (pkg, (' (нужно для %s)' % what) if what else ''))


def _need_skia(what=''):
    if not HAS_SKIA:
        raise Missing('skia', what)


class _Absent:
    """Вместо модуля skia, если его нет: `skia.Paint(...)` в сцене → понятная заглушка, а не AttributeError."""

    def __init__(self, lib):
        self._lib = lib

    def __getattr__(self, k):
        raise Missing(self._lib, 'skia.' + k)

    def __bool__(self):
        return False


if not HAS_SKIA:
    skia = _Absent('skia')


# ================================================================ кадр <-> Skia
_BUFS = kit._LRU(max_items=6)       # буферы RGBA по размеру кадра — переиспользуются, не создаются каждый кадр
_OPEN = []                          # открытые холсты: [кадр, буфер, поверхность]


class Canvas:
    """Холст Skia поверх кадра. Все методы skia.Canvas доступны напрямую: c.drawCircle(...), c.save() …
    Используйте `with canvas(fr) as c:` — после блока кадр обновится сам."""

    def __init__(self, fr, buf, surf):
        self.fr, self.buf, self.surf = fr, buf, surf
        self.sk = surf.getCanvas()
        self.depth = 0
        self.flushed = False

    def __getattr__(self, k):
        return getattr(self.sk, k)

    def __enter__(self):
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        if self.depth <= 0:
            flush(self.fr)
        return False


def _load(fr, buf):
    if buf is fr:
        return
    if fr.shape[2] == 3 and fr.flags['C_CONTIGUOUS']:
        cv2.cvtColor(fr, cv2.COLOR_RGB2RGBA, dst=buf)
    else:
        buf[..., :fr.shape[2]] = fr
        if fr.shape[2] == 3:
            buf[..., 3] = 255


def canvas(fr):
    """Холст Skia для кадра fr (H×W×3 RGB или H×W×4 RGBA).
    RGBA-картинку Skia рисует прямо в её память; RGB-кадр копируется в постоянный RGBA-буфер (без новых
    массивов, ~2 мс на 1920×1080) и возвращается в кадр в конце `with` (или flush(fr), или сам в конце кадра).
    Внутри `with canvas(fr)` не рисуйте в тот же кадр через numpy/cv2 — после блока снова можно."""
    _need_skia('canvas()')
    for o in _OPEN:
        if o.fr is fr:
            if o.flushed:               # после flush кадр могли менять numpy/cv2 — взять свежий
                _load(fr, o.buf)
                o.flushed = False
            return o
    if fr.dtype != np.uint8 or fr.ndim != 3 or fr.shape[2] not in (3, 4):
        raise ValueError('canvas(fr): нужен массив H×W×3 или H×W×4 uint8')
    h, w = fr.shape[:2]
    if fr.shape[2] == 4 and fr.flags['C_CONTIGUOUS']:
        buf = fr
    else:
        busy = {id(o.buf) for o in _OPEN}
        buf = _BUFS.get((h, w))
        if buf is None or id(buf) in busy:
            buf = np.empty((h, w, 4), np.uint8)
            if (h, w) not in _BUFS:
                _BUFS.put((h, w), buf)
        _load(fr, buf)
    o = Canvas(fr, buf, skia.Surface(buf))
    _OPEN.append(o)
    while len(_OPEN) > 16:              # холсты на временных картинках — не копить
        old = _OPEN.pop(0)
        if not old.flushed:
            _store(old)
    return o


def _store(o):
    if o.buf is o.fr:
        return
    if o.fr.shape[2] == 3 and o.fr.flags['C_CONTIGUOUS']:
        cv2.cvtColor(o.buf, cv2.COLOR_RGBA2RGB, dst=o.fr)
    else:
        o.fr[...] = o.buf[..., :o.fr.shape[2]]


def flush(fr=None):
    """Перенести нарисованное Skia в кадр (для холста без `with`). Без аргумента — все открытые холсты."""
    for o in _OPEN:
        if (fr is None or o.fr is fr) and not o.flushed:
            _store(o)
            o.flushed = True


def _reset():
    """Конец/начало кадра (движок): дописать незакрытые холсты и забыть их."""
    try:
        flush()
    finally:
        del _OPEN[:]


def _raw(c):
    return c.sk if isinstance(c, Canvas) else c


# ================================================================ шрифты
_TF = kit._LRU(max_items=48)        # гарнитуры (с нужной толщиной)
_SKF = kit._LRU(max_items=256)      # skia.Font по размеру


def _font_file(name):
    """Файл шрифта: роль ('title'/'serif'/'text'/'code') или имя файла из fonts/ проекта; затем встроенные."""
    if name == 'code':
        name = kit.FONT_ROLES.get('code') or 'jbmono'
    p = kit._font_path(kit.font_role(name))
    if p:
        return p
    low = name.lower().replace(' ', '').replace('-', '')
    dirs = list(kit.FONT_DIRS or [os.path.join(kit.PROJECT, 'fonts')]) + [BUILTIN_FONTS]
    for d in dirs:
        try:
            files = sorted(os.listdir(d))
        except OSError:
            continue
        for f in files:
            if f.lower().endswith(('.ttf', '.otf')) and f.lower().replace('-', '').startswith(low):
                return os.path.join(d, f)
    if low in ('jbmono', 'jetbrainsmono', 'mono', 'code'):
        return os.path.join(BUILTIN_FONTS, 'JetBrainsMono.ttf')
    raise FileNotFoundError("Шрифт '%s' не найден в папке fonts/" % name)


def _static_bytes(path, weight):
    """Вариативный шрифт → статичная копия нужной толщины (fontTools), кэш на диске в <проект>/cache/fonts/.
    Нужна, если Skia не умеет задать ось толщины сам (старые skia-python) — иначе все надписи одной толщины."""
    with open(path, 'rb') as f:
        data = f.read()
    try:
        from fontTools.ttLib import TTFont
    except Exception:
        return data, False
    tt = TTFont(io.BytesIO(data), lazy=True)
    if 'fvar' not in tt:
        return data, False
    axes = {a.axisTag: a for a in tt['fvar'].axes}
    if 'wght' not in axes:
        return data, True
    a = axes['wght']
    w = int(round(max(a.minValue, min(a.maxValue, float(weight)))))
    key = hashlib.sha1(data[:4096] + str(len(data)).encode()).hexdigest()[:10]
    cdir = os.path.join(kit.PROJECT, 'cache', 'fonts')
    cpath = os.path.join(cdir, '%s-%s-%d.ttf' % (os.path.splitext(os.path.basename(path))[0][:40], key, w))
    if os.path.isfile(cpath):
        with open(cpath, 'rb') as f:
            return f.read(), True
    from fontTools.varLib import instancer
    tt = TTFont(io.BytesIO(data))
    loc = {t: (w if t == 'wght' else ax.defaultValue) for t, ax in axes.items()}
    instancer.instantiateVariableFont(tt, loc, inplace=True)
    out = io.BytesIO()
    tt.save(out)
    b = out.getvalue()
    try:
        os.makedirs(cdir, exist_ok=True)
        tmp = cpath + '.%d.tmp' % os.getpid()
        with open(tmp, 'wb') as f:
            f.write(b)
        os.replace(tmp, cpath)
    except OSError:
        pass                          # папка только для чтения — держим в памяти
    return b, True


def _clone_weight(tf, weight):
    """Толщина вариативного шрифта средствами Skia (skia-python ≥ 88: мгновенно). None — не получилось."""
    try:
        axes = tf.getVariationDesignParameters() or []
        ax = [a for a in axes if a.tag == _WGHT]
        if not ax:
            return tf if not axes else None
        w = max(ax[0].min, min(ax[0].max, float(weight)))
        VP = skia.FontArguments.VariationPosition
        coord = [VP.Coordinate(_WGHT, w)]       # держать ссылки до makeClone: Skia хранит указатели на них
        coords = VP.Coordinates(coord)
        pos = VP(coords)
        fa = skia.FontArguments()
        fa.setVariationDesignPosition(pos)
        out = tf.makeClone(fa)
        del coord, coords, pos, fa
        return out
    except Exception:
        return None


_WGHT = (ord('w') << 24) | (ord('g') << 16) | (ord('h') << 8) | ord('t')


def _typeface(name, weight):
    path = _font_file(name)
    k = (path, os.path.getmtime(path), int(weight))
    tf = _TF.get(k)
    if tf is None:
        with open(path, 'rb') as f:        # из байтов — работает и с русскими путями на Windows
            data = f.read()
        base = skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(data))
        if base is None:
            raise ValueError("Skia не смог прочитать шрифт '%s'" % os.path.basename(path))
        tf = _clone_weight(base, weight)
        if tf is None:                    # старый Skia: статичная копия нужной толщины через fontTools
            data, _ = _static_bytes(path, weight)
            tf = skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(data)) or base
        _TF.put(k, tf)
    return tf


def font(name='text', size=60, weight=400):
    """Шрифт Skia: name — роль ('title', 'serif', 'text', 'code') или имя файла из fonts/ проекта
    ('montserrat', 'jbmono' …); weight — толщина 100..900 (у вариативных шрифтов делается статичная копия).
    Кэшируется: вызывать в каждом кадре можно."""
    _need_skia('font()')
    k = (name, kit.font_role(name), round(float(size), 1), int(weight), tuple(kit.FONT_DIRS))
    f = _SKF.get(k)
    if f is None:
        f = skia.Font(_typeface(name, weight), float(size))
        f.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        f.setSubpixel(True)
        f.setHinting(skia.FontHinting.kNone)
        _SKF.put(k, f)
    return f


# ================================================================ цвета и кисти
def sk_color(c, op=1.0):
    """Цвет Skia из (r, g, b), (r, g, b, a), '#rrggbb' или '#rrggbbaa'; op — множитель прозрачности."""
    if isinstance(c, str):
        h = c.lstrip('#')
        c = tuple(int(h[i:i + 2], 16) for i in range(0, len(h), 2))
    if isinstance(c, (int, np.integer)) and not isinstance(c, bool):
        return int(c)
    r, g, b = int(c[0]), int(c[1]), int(c[2])
    a = int(c[3]) if len(c) > 3 else 255
    return skia.ColorSetARGB(max(0, min(255, int(round(a * op)))), r, g, b)


def sk_paint(color=(255, 255, 255), op=1.0, stroke=0, blur=0, shader=None, cap='round', blend=None):
    """Кисть: stroke>0 — контур такой толщины, blur — мягкий край (px), shader — градиент (lin_grad/rad_grad)."""
    _need_skia('sk_paint()')
    p = skia.Paint(AntiAlias=True, Color=sk_color(color, op))
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(float(stroke))
        p.setStrokeCap({'round': skia.Paint.kRound_Cap, 'butt': skia.Paint.kButt_Cap,
                        'square': skia.Paint.kSquare_Cap}.get(cap, skia.Paint.kRound_Cap))
        p.setStrokeJoin(skia.Paint.kRound_Join)
    if blur:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, float(blur)))
    if shader is not None:
        p.setShader(shader)
        p.setAlphaf(max(0.0, min(1.0, op)))
    if blend:
        p.setBlendMode(getattr(skia.BlendMode, 'k' + blend[:1].upper() + blend[1:]))
    return p


def lin_grad(x0, y0, x1, y1, colors, stops=None):
    """Линейный градиент от (x0, y0) к (x1, y1): colors — список цветов, stops — их места 0..1."""
    _need_skia('lin_grad()')
    return skia.GradientShader.MakeLinear([skia.Point(x0, y0), skia.Point(x1, y1)],
                                          [sk_color(c) for c in colors], stops)


def rad_grad(cx, cy, r, colors, stops=None):
    """Радиальный градиент с центром (cx, cy) и радиусом r."""
    _need_skia('rad_grad()')
    return skia.GradientShader.MakeRadial(skia.Point(cx, cy), max(1e-3, float(r)), [sk_color(c) for c in colors], stops)


# ================================================================ фигуры
def _rr(x, y, w, h, r):
    r = max(0.0, min(float(r), w / 2, h / 2))
    return skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r)


def sk_rrect(c, x, y, w, h, r=24, color=(255, 255, 255), op=1.0, shadow=None, stroke=None, shader=None, blur=0):
    """Скруглённый блок: (x, y) — левый верхний угол, r — радиус углов.
    shadow=(сдвиг_вниз, размытие, прозрачность) — мягкая тень; stroke=(цвет, толщина[, прозрачность]) — обводка;
    shader — заливка градиентом; color=None — без заливки."""
    _need_skia('sk_rrect()')
    c = _raw(c)
    if op <= 0:
        return
    if shadow:
        dy, br = shadow[0], shadow[1]
        sa = shadow[2] if len(shadow) > 2 else 0.5
        sc = shadow[3] if len(shadow) > 3 else (0, 0, 0)
        c.drawRRect(_rr(x, y + dy, w, h, r), sk_paint(sc, sa * op, blur=br / 2))
    if color is not None or shader is not None:
        c.drawRRect(_rr(x, y, w, h, r), sk_paint(color or (0, 0, 0), op, shader=shader, blur=blur))
    if stroke:
        sw = stroke[1] if len(stroke) > 1 else 2
        c.drawRRect(_rr(x + sw / 2, y + sw / 2, w - sw, h - sw, max(0, r - sw / 2)),
                    sk_paint(stroke[0], (stroke[2] if len(stroke) > 2 else 1.0) * op, stroke=sw))


def sk_rect(c, x, y, w, h, color=(255, 255, 255), op=1.0, shader=None):
    """Прямоугольник (или заливка градиентом всего кадра: sk_rect(c, 0, 0, W, H, shader=lin_grad(...)))."""
    _need_skia('sk_rect()')
    _raw(c).drawRect(skia.Rect.MakeXYWH(x, y, w, h), sk_paint(color, op, shader=shader))


def sk_circle(c, x, y, r, color=(255, 255, 255), op=1.0, stroke=0, blur=0, shader=None):
    """Круг (stroke>0 — кольцо)."""
    _need_skia('sk_circle()')
    _raw(c).drawCircle(x, y, r, sk_paint(color, op, stroke=stroke, blur=blur, shader=shader))


def sk_glow(c, x, y, r, color, op=0.6):
    """Мягкое световое пятно радиуса r."""
    _need_skia('sk_glow()')
    _raw(c).drawCircle(x, y, r, sk_paint(color, op, blur=r * 0.5))


def _glow_stroke(c, draw, w, glow, op):
    if glow:
        gc, gr = glow[0], glow[1]
        ga = glow[2] if len(glow) > 2 else 0.8
        draw(sk_paint(gc, ga * op, stroke=w * 3, blur=gr))


def sk_line(c, x0, y0, x1, y1, color=(255, 255, 255), w=2, op=1.0, dash=None, glow=None, k=1.0):
    """Линия; dash=(штрих, пробел) — пунктир; glow=(цвет, размытие[, прозрачность]) — свечение;
    k 0..1 — какая часть линии нарисована (для анимации «прорисовки»)."""
    _need_skia('sk_line()')
    c = _raw(c)
    if op <= 0 or k <= 0:
        return
    x1, y1 = x0 + (x1 - x0) * min(1.0, k), y0 + (y1 - y0) * min(1.0, k)
    _glow_stroke(c, lambda p: c.drawLine(x0, y0, x1, y1, p), w, glow, op)
    p = sk_paint(color, op, stroke=w)
    if dash:
        p.setPathEffect(skia.DashPathEffect.Make(list(dash), 0))
    c.drawLine(x0, y0, x1, y1, p)


def _path(pts, smooth, closed=False):
    path = skia.Path()
    path.moveTo(*pts[0])
    if smooth and len(pts) > 2:
        for i in range(1, len(pts) - 1):
            mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
            path.quadTo(pts[i][0], pts[i][1], mx, my)
        path.lineTo(*pts[-1])
    else:
        for q in pts[1:]:
            path.lineTo(*q)
    if closed:
        path.close()
    return path


def sk_path(c, pts, color=(255, 255, 255), w=3, op=1.0, smooth=True, glow=None, k=1.0, fill=None, dash=None,
            area=None):
    """Кривая через точки pts [(x, y), …]: smooth — сглаженная, k 0..1 — какая часть нарисована
    (анимация графика), glow — свечение; fill — залить фигуру цветом или градиентом (lin_grad);
    area=y — залить область под кривой до высоты y (график), w=0 — без линии."""
    _need_skia('sk_path()')
    c = _raw(c)
    if op <= 0 or k <= 0 or len(pts) < 2:
        return
    path = _path(pts, smooth, closed=fill is not None and area is None)
    if fill is not None:
        fp = sk_paint(fill, op) if not isinstance(fill, skia.Shader) else sk_paint((255, 255, 255), op, shader=fill)
        if area is not None:
            ap = _path(pts, smooth)
            ap.lineTo(pts[-1][0], area)
            ap.lineTo(pts[0][0], area)
            ap.close()
            c.drawPath(ap, fp)
        else:
            c.drawPath(path, fp)
    if k < 1:
        meas = skia.PathMeasure(path, False)
        seg = skia.Path()
        meas.getSegment(0, meas.getLength() * k, seg, True)
        path = seg
    if w:
        _glow_stroke(c, lambda p: c.drawPath(path, p), w, glow, op)
        p = sk_paint(color, op, stroke=w)
        if dash:
            p.setPathEffect(skia.DashPathEffect.Make(list(dash), 0))
        c.drawPath(path, p)


def sk_image(c, img, x, y, w=None, h=None, op=1.0, r=0, shadow=None):
    """Картинка/кадр видео (numpy RGB или RGBA) в прямоугольник x, y, w, h со скруглением r и тенью —
    например, запись экрана из assets/desk/ в «окне»."""
    _need_skia('sk_image()')
    c = _raw(c)
    ih, iw = img.shape[:2]
    w = iw if w is None else w
    h = ih * w / iw if h is None else h
    if shadow:
        sk_rrect(c, x, y, w, h, r, None, op, shadow=shadow)
    a = img if img.shape[2] == 4 else cv2.cvtColor(img, cv2.COLOR_RGB2RGBA)
    im = skia.Image.fromarray(np.ascontiguousarray(a), colorType=skia.kRGBA_8888_ColorType)
    c.save()
    if r:
        c.clipRRect(_rr(x, y, w, h, r), doAntiAlias=True)
    p = skia.Paint(AntiAlias=True)
    p.setAlphaf(max(0.0, min(1.0, op)))
    c.drawImageRect(im, skia.Rect.MakeXYWH(x, y, w, h), skia.SamplingOptions(skia.FilterMode.kLinear), p)
    c.restore()


@contextlib.contextmanager
def sk_clip(c, x, y, w, h, r=0):
    """Маска-окно: всё, что нарисовано внутри блока `with sk_clip(c, …):`, видно только в этом прямоугольнике."""
    _need_skia('sk_clip()')
    c = _raw(c)
    c.save()
    c.clipRRect(_rr(x, y, w, h, r), doAntiAlias=True)
    try:
        yield c
    finally:
        c.restore()


@contextlib.contextmanager
def sk_mask(c, shader, rect=None):
    """Мягкая маска: содержимое блока проявляется по альфе шейдера (градиента).
    Например, нижний край тает: `with sk_mask(c, lin_grad(0, 600, 0, 900, [(0,0,0,255), (0,0,0,0)])):`"""
    _need_skia('sk_mask()')
    c = _raw(c)
    bounds = skia.Rect.MakeXYWH(*rect) if rect else None
    c.saveLayer(bounds)
    try:
        yield c
    finally:
        p = skia.Paint(Shader=shader)
        p.setBlendMode(skia.BlendMode.kDstIn)
        c.drawPaint(p)
        c.restore()


# ================================================================ текст
def sk_text_width(s, f, track=0.0):
    """Ширина строки в пикселях для шрифта f (font(...)); track — разрядка в долях кегля."""
    if not s:
        return 0.0
    return f.measureText(s) + track * f.getSize() * max(0, len(s) - 1)


def sk_text(c, s, x, y, f=None, color=(255, 255, 255), op=1.0, align='l', track=0.0, shadow=None, glow=None,
            shader=None):
    """Строка текста Skia. (x, y) — точка на базовой линии; align 'l' / 'c' / 'r'.
    f — font(...), по умолчанию роль 'text' 60 px; track — разрядка; shadow=(сдвиг, размытие[, прозрачность]);
    glow=(цвет, размытие[, прозрачность]) — свечение; shader — заливка градиентом. Возвращает ширину."""
    _need_skia('sk_text()')
    c = _raw(c)
    if not s or op <= 0:
        return 0.0
    f = f or font('text', 60)
    wd = sk_text_width(s, f, track)
    x0 = x - (wd if align == 'r' else wd / 2 if align == 'c' else 0)
    if track:
        xs, cx = [], 0.0
        for ch in s:
            xs.append(cx)
            cx += f.measureText(ch) + track * f.getSize()
        blob = skia.TextBlob.MakeFromPosTextH(s, xs, 0, f)
    else:
        blob = skia.TextBlob.MakeFromString(s, f)
    if blob is None:
        return wd
    if glow:
        ga = glow[2] if len(glow) > 2 else 0.9
        c.drawTextBlob(blob, x0, y, sk_paint(glow[0], ga * op, blur=glow[1]))
    if shadow:
        sa = shadow[2] if len(shadow) > 2 else 0.5
        c.drawTextBlob(blob, x0, y + shadow[0], sk_paint((0, 0, 0), sa * op, blur=shadow[1] / 2))
    c.drawTextBlob(blob, x0, y, sk_paint(color, op, shader=shader))
    return wd


# ================================================================ код с подсветкой
_TOK = kit._LRU(max_items=64)


def _style(theme):
    try:
        from pygments.styles import get_style_by_name
    except Exception:
        raise Missing('pygments', 'code_block()')
    try:
        return get_style_by_name(theme)
    except Exception:
        return get_style_by_name('monokai')


def _hex(h, d):
    if not h:
        return d
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _tokens(code, lang, theme):
    """Строки кода → [[(текст, цвет, жирный, курсив), …], …] (кэш)."""
    k = (code, lang, theme)
    v = _TOK.get(k)
    if v is not None:
        return v
    try:
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.util import ClassNotFound
    except Exception:
        raise Missing('pygments', 'code_block()')
    st = _style(theme)
    try:
        lx = get_lexer_by_name(lang or 'text', stripnl=False, ensurenl=False)
    except ClassNotFound:
        lx = guess_lexer(code)
    base = _hex(st.style_for_token(__import__('pygments.token', fromlist=['Text']).Text).get('color'), (220, 223, 228))
    lines, cur = [], []
    for ttype, val in lx.get_tokens(code.expandtabs(4)):
        s = st.style_for_token(ttype)
        colr = _hex(s.get('color'), base)
        parts = val.split('\n')
        for i, part in enumerate(parts):
            if i:
                lines.append(cur)
                cur = []
            if part:
                cur.append((part, colr, bool(s.get('bold')), bool(s.get('italic'))))
    lines.append(cur)
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    _TOK.put(k, lines)
    return lines


def code_block(fr, code, x, y, lang='python', size=28, theme='one-dark', font_name='code', reveal=None,
               highlight=(), dim=0.45, numbers=True, width=None, line_h=1.5, pad=None, r=18, bg=True, op=1.0,
               title=None, shadow=(16, 36, 0.45), cursor=False, t=0.0, accent=(97, 175, 239)):
    """Блок кода с подсветкой синтаксиса (Pygments + Skia) — как в редакторе.
    (x, y) — левый верхний угол; lang — язык ('python', 'gdscript', 'js', 'bash' …); theme — тема Pygments
    ('one-dark', 'monokai', 'dracula', 'github-dark', 'nord' …); font_name — шрифт (по умолчанию JetBrains Mono).
    reveal — сколько строк видно (дробное — последняя печатается по буквам), None — все;
    highlight — номера строк (с 1), которые подсветить, остальные приглушаются на dim;
    title — заголовок окна (имя файла); cursor — мигающий курсор в конце напечатанного (нужен t);
    accent — цвет выделения строк.
    Возвращает (x, y, ширина, высота) блока."""
    lines = _tokens(code, lang, theme)
    _need_skia('code_block()')
    st = _style(theme)
    bgc = _hex(st.background_color, (24, 26, 33))
    hlc = tuple(int(b + (a - b) * 0.16) for a, b in zip(accent, bgc))     # строка-акцент: фон + немного акцента
    f = font(font_name, size, 400)
    fb = font(font_name, size, 700)
    lh = size * line_h
    pad = size * 0.9 if pad is None else pad
    gutter = (f.measureText('%d' % len(lines)) + size * 1.2) if numbers else 0
    top = pad + (size * 1.6 if title else 0)
    if width is None:
        longest = max((sum(f.measureText(p[0]) for p in ln) for ln in lines), default=0)
        width = longest + gutter + pad * 2
    height = top + lh * len(lines) + pad * 0.7
    n_show = len(lines) if reveal is None else max(0.0, min(float(reveal), len(lines)))
    hl = set(int(i) for i in (highlight or ()))
    with canvas(fr) as c:
        if bg:
            sk_rrect(c, x, y, width, height, r, bgc, op, shadow=shadow)
            if title:
                for i, dc in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
                    sk_circle(c, x + pad + i * size * 0.8, y + pad * 0.55 + size * 0.35, size * 0.22, dc, op * 0.9)
                sk_text(c, title, x + width / 2, y + pad * 0.55 + size * 0.6, font(font_name, size * 0.78),
                        (150, 156, 168), op, align='c')
        with sk_clip(c, x, y, width, height, r):
            base_y = y + top
            last = None
            for i, ln in enumerate(lines):
                if i >= math.ceil(n_show - 1e-9):
                    break
                ly = base_y + i * lh
                part = 1.0 if i + 1 <= n_show else n_show - i
                lo = op * ((1.0 if (not hl or (i + 1) in hl) else dim))
                if (i + 1) in hl:
                    sk_rect(c, x, ly, width, lh, hlc, op)
                    sk_rect(c, x, ly, size * 0.14, lh, accent, op)
                base = ly + lh * 0.5 + size * 0.36
                if numbers:
                    sk_text(c, '%d' % (i + 1), x + pad + gutter - size * 1.2, base, f, (110, 116, 130), lo * 0.8,
                            align='r')
                total = sum(len(p[0]) for p in ln)
                limit = total if part >= 1 else int(total * part)
                cx = x + pad + gutter
                used = 0
                for s, col, b, it in ln:
                    if used >= limit:
                        break
                    s = s[:limit - used]
                    used += len(s)
                    ff = fb if b else f
                    sk_text(c, s, cx, base, ff, col, lo)
                    cx += ff.measureText(s)
                last = (cx, ly)
            if cursor and last is not None and (math.sin(t * 6.0) > -0.2 or n_show < len(lines)):
                sk_rect(c, last[0] + 2, last[1] + lh * 0.18, size * 0.55, lh * 0.64, (220, 223, 228), op * 0.85)
    return (x, y, width, height)


# ================================================================ постобработка кадра (без Skia: numpy/cv2)
_VIGN = kit._LRU(max_items=6)
_NOISE = kit._LRU(max_items=2)


def bloom(fr, amount=0.6, threshold=170, radius=None):
    """Свечение ярких мест (как в кино): всё ярче threshold мягко «светится». radius — размер ореола (px)."""
    if amount <= 0:
        return
    h, w = fr.shape[:2]
    q = 4
    sm = cv2.resize(fr, (max(1, w // q), max(1, h // q)), interpolation=cv2.INTER_AREA)
    hi = cv2.subtract(sm, np.full_like(sm, int(threshold)))
    hi = cv2.convertScaleAbs(hi, alpha=255.0 / max(1, 255 - threshold))
    r = (radius or max(w, h) / 100) / q
    b = cv2.addWeighted(cv2.GaussianBlur(hi, (0, 0), max(0.8, r)), 1.0,
                        cv2.GaussianBlur(hi, (0, 0), max(1.5, r * 2.8)), 0.6, 0)
    b = cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)
    cv2.addWeighted(fr, 1.0, b, float(amount), 0, dst=fr)


def vignette(fr, amount=0.4, size=0.35):
    """Затемнение краёв кадра: amount — сила 0..1, size — какая часть центра не темнеет."""
    if amount <= 0:
        return
    h, w = fr.shape[:2]
    k = (w, h, round(amount, 3), round(size, 3))
    m = _VIGN.get(k)
    if m is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        g = (1 - amount * np.clip(d - size, 0, 1) ** 1.6) * 255
        m = _VIGN.put(k, cv2.merge([g.clip(0, 255).astype(np.uint8)] * 3))
    cv2.multiply(fr, m, dst=fr, scale=1 / 255)


def film_grain(fr, t, amount=0.05, fps=24):
    """Плёночное зерно, меняется fps раз в секунду. amount ~0.03..0.12."""
    if amount <= 0:
        return
    h, w = fr.shape[:2]
    n = _NOISE.get((w, h))
    if n is None:
        n = _NOISE.put((w, h), np.stack([np.clip(128 + np.random.default_rng(i).normal(0, 40, (h, w)), 0, 255)
                                         .astype(np.uint8) for i in range(8)]))
    g = cv2.merge([n[int(t * fps) % 8]] * 3)
    cv2.addWeighted(fr, 1, g, float(amount), -128 * float(amount), dst=fr)


def scanlines(fr, amount=0.15, gap=3, t=0.0, speed=0.0):
    """Строки, как на старом мониторе: каждая gap-я строка темнее на amount; speed — бегут вниз (строк/с)."""
    if amount <= 0:
        return
    off = int(t * speed) % max(1, int(gap))
    v = fr[off::max(1, int(gap))]
    np.multiply(v, 1.0 - amount, out=v, casting='unsafe')


def motion_blur(fr, dx, dy=0.0):
    """Смаз движения на вектор (dx, dy) пикселей — для быстрых пролётов и переходов."""
    L = int(round(math.hypot(dx, dy)))
    if L < 2:
        return
    q = 2 if L > 24 else 1
    h, w = fr.shape[:2]
    src = cv2.resize(fr, (w // q, h // q), interpolation=cv2.INTER_AREA) if q > 1 else fr
    n = max(2, L // q)
    if abs(dy) < 1e-6:
        out = cv2.blur(src, (n, 1))
    elif abs(dx) < 1e-6:
        out = cv2.blur(src, (1, n))
    else:
        kern = np.zeros((n, n), np.float32)
        a = math.atan2(dy, dx)
        cx = cy = (n - 1) / 2
        for i in range(n):
            s = i - cx
            kern[int(round(cy + s * math.sin(a))), int(round(cx + s * math.cos(a)))] = 1
        out = cv2.filter2D(src, -1, kern / kern.sum())
    if q > 1:
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
    fr[...] = out
