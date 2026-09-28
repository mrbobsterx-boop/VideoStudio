"""Слои сцены без кода: видео, картинка или текст поверх (или под) кадром из render().

Слой — это словарь из project.json. Все времена — секунды от начала сцены.
"""
import math

import cv2
import numpy as np

from . import fx, kit

TYPES = ('video', 'image', 'text')
FITS = ('cover', 'contain', 'free')
BLENDS = ('normal', 'screen', 'add', 'multiply')
MOTIONS = ('none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down')
ANIMS = ('fade', 'rise', 'blur', 'scale', 'type', 'slide', 'none')
POSITIONS = ('center', 'lower', 'upper', 'left', 'right', 'custom')

DEFAULTS = dict(
    common=dict(start=0.0, end=None, z='top', opacity=1.0, fade_in=0.3, fade_out=0.3, hidden=False),
    video=dict(src='', trim=0.0, speed=1.0, loop=True, volume=0.0, fit='cover', area='visible', x=960.0, y=540.0,
               scale=1.0, rotate=0.0, focus_x=0.5, focus_y=0.5, blend='normal', motion='zoom_in', motion_amt=0.08,
               sat=1.0, con=1.0, bright=1.0, blur=0.0, gray=0.0, grade='', radius=0.0),
    text=dict(key='', font='title', weight=700, size=110, color='#ECE4D6', align='c', pos='center', x=960.0, y=540.0,
              track=0.08, anim='rise', shadow=True, plate=0.0, line=1.15),
)
DEFAULTS['image'] = dict(DEFAULTS['video'])
for _k in ('trim', 'speed', 'loop', 'volume'):
    DEFAULTS['image'].pop(_k)


def _num(v, d, lo=None, hi=None):
    try:
        v = float(v)
        if not math.isfinite(v):
            raise ValueError
    except (TypeError, ValueError):
        return d
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v


def clean(L):
    """Проверить слой из интерфейса: только известные поля, числа — в разумных пределах."""
    kind = L.get('type')
    if kind not in TYPES:
        return None
    out = dict(id=str(L.get('id') or '')[:24], type=kind, name=str(L.get('name') or '')[:60])
    spec = dict(DEFAULTS['common'], **DEFAULTS[kind])
    for k, d in spec.items():
        v = L.get(k, d)
        if k == 'end':
            out[k] = None if v in (None, '') else _num(v, None, 0, 3600)
        elif isinstance(d, bool):
            out[k] = bool(v)
        elif isinstance(d, float):
            lim = dict(opacity=(0, 1), fade_in=(0, 30), fade_out=(0, 30), start=(0, 3600), trim=(0, 86400),
                       speed=(0.05, 8), volume=(0, 3), scale=(0.02, 20), sat=(0, 3), con=(0, 3), bright=(0, 3),
                       blur=(0, 60), gray=(0, 1), motion_amt=(0, 1), focus_x=(0, 1), focus_y=(0, 1), track=(-0.2, 2),
                       plate=(0, 1), line=(0.6, 3), rotate=(-360, 360), radius=(0, 400),
                       x=(-4000, 6000), y=(-4000, 6000)).get(k, (None, None))
            out[k] = _num(v, d, *lim)
        elif isinstance(d, int):
            out[k] = int(_num(v, d, 100, 900)) if k == 'weight' else int(_num(v, d, 8, 600))
        else:
            out[k] = str(v if v is not None else d)[:200]
    if kind == 'text':
        out['size'] = int(_num(L.get('size', 110), 110, 8, 600))
    for k, allowed in (('fit', FITS), ('blend', BLENDS), ('motion', MOTIONS), ('anim', ANIMS), ('pos', POSITIONS),
                       ('z', ('top', 'bottom')), ('area', ('visible', 'full')), ('align', ('c', 'l', 'r'))):
        if k in out and out[k] not in allowed:
            out[k] = spec[k]
    if out.get('grade') and out['grade'] not in fx._GRADES:
        out['grade'] = ''
    return out


# ------------------------------------------------------------------ рисование
def _window(L, dur):
    t0 = float(L.get('start') or 0)
    t1 = L.get('end')
    t1 = dur if t1 is None else min(dur, float(t1))
    return t0, t1


def _fade(L, lt, ld):
    k = 1.0
    fi, fo = float(L.get('fade_in') or 0), float(L.get('fade_out') or 0)
    if fi > 0:
        k *= kit.oc(kit.prog(lt, 0, fi))
    if fo > 0:
        k *= 1 - kit.prog(lt, ld - fo, ld)
    return k


def _source(L, lt):
    name = L.get('src') or ''
    if not name:
        return None
    if L['type'] == 'video':
        return kit.video(name, lt, start=float(L.get('trim') or 0), speed=float(L.get('speed') or 1),
                         loop=bool(L.get('loop', True)))
    p = kit._path(name)
    if p.lower().endswith('.png'):
        a = kit.sprite(name)
        if a[..., 3].min() == 255:
            a = a[..., :3]
        return a
    return kit.image(name)


def _grade(src, L):
    sat, con, br = L.get('sat', 1.0), L.get('con', 1.0), L.get('bright', 1.0)
    rgb = src[..., :3]
    changed = False
    if (sat, con, br) != (1.0, 1.0, 1.0):
        rgb = kit._grade(rgb, sat, con, br, (1, 1, 1))
        changed = True
    if L.get('gray', 0) > 0:
        rgb = rgb.copy() if not changed else rgb
        kit.grayscale(rgb, L['gray'])
        changed = True
    if L.get('grade'):
        rgb = rgb.copy() if not changed else rgb
        fx.grade(rgb, L['grade'], 0.85)
        changed = True
    if L.get('blur', 0) > 0.3:
        rgb = cv2.GaussianBlur(rgb, (0, 0), L['blur'])
        changed = True
    if not changed:
        return src
    return np.dstack([rgb, src[..., 3]]) if src.shape[2] == 4 else rgb


def _motion(L, u):
    """Добавочный масштаб и сдвиг (px) от «движения камеры» слоя."""
    m, a = L.get('motion', 'none'), float(L.get('motion_amt') or 0)
    u = kit.ioc(u)
    s, dx, dy = 1.0, 0.0, 0.0
    if m == 'zoom_in':
        s = 1 + a * u
    elif m == 'zoom_out':
        s = 1 + a * (1 - u)
    elif m.startswith('pan_'):
        s = 1 + a
        d = kit.W * a * 0.45 * (u - 0.5) * 2
        dx = {'pan_left': d, 'pan_right': -d}.get(m, 0.0)
        dy = {'pan_up': d * 0.56, 'pan_down': -d * 0.56}.get(m, 0.0)
    return s, dx, dy


def _rounded(a, r):
    h, w = a.shape[:2]
    r = int(min(r, h / 2, w / 2))
    if r < 2:
        return a
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    if a.shape[2] == 3:
        return np.dstack([a, m])
    out = a.copy()
    out[..., 3] = (out[..., 3].astype(np.uint16) * m // 255).astype(np.uint8)
    return out


def _blend(fr, layer_rgba, op, mode):
    """Смешать полнокадровый RGBA-слой с кадром."""
    al = layer_rgba[..., 3:4].astype(np.float32) / 255 * op
    if al.max() <= 0.002:
        return
    src = layer_rgba[..., :3].astype(np.float32)
    dst = fr.astype(np.float32)
    if mode == 'screen':
        res = 255 - (255 - dst) * (255 - src) / 255
    elif mode == 'add':
        res = np.minimum(255, dst + src)
    elif mode == 'multiply':
        res = dst * src / 255
    else:
        res = src
    fr[:] = (dst * (1 - al) + res * al).astype(np.uint8)


def _draw_media(fr, L, lt, ld, op):
    src = _source(L, lt)
    if src is None:
        return
    src = _grade(src, L)
    h, w = src.shape[:2]
    area = L.get('area', 'visible')
    x0, y0, aw, ah = kit._area(area)
    fit = L.get('fit', 'cover')
    ms, mdx, mdy = _motion(L, kit.prog(lt, 0, ld))
    sc = float(L.get('scale') or 1)
    if fit == 'cover':
        s = max(aw / w, ah / h) * sc * ms
        cx, cy = x0 + aw / 2, y0 + ah / 2
        # точка фокуса: какую часть картинки держать в центре
        fx_, fy_ = float(L.get('focus_x', 0.5)), float(L.get('focus_y', 0.5))
        px = w * fx_
        py = h * fy_
        hw, hh = aw / 2 / s, ah / 2 / s
        px = min(max(px, hw), w - hw) if w > 2 * hw else w / 2
        py = min(max(py, hh), h - hh) if h > 2 * hh else h / 2
    elif fit == 'contain':
        s = min(aw / w, ah / h) * sc * ms
        cx, cy = x0 + aw / 2, y0 + ah / 2
        px, py = w / 2, h / 2
    else:   # free: центр слоя в точке (x, y), масштаб — от размера исходника
        s = sc * ms
        cx, cy = float(L.get('x', 960)), float(L.get('y', 540))
        px, py = w / 2, h / 2
    cx += mdx
    cy += mdy
    ang = float(L.get('rotate') or 0)
    M = cv2.getRotationMatrix2D((px, py), -ang, s)
    M[0, 2] += cx - px
    M[1, 2] += cy - py
    simple = (fit == 'cover' and op >= 0.999 and L.get('blend', 'normal') == 'normal' and src.shape[2] == 3
              and abs(ang) < 1e-3 and not L.get('radius'))
    if simple:
        # быстрый путь: непрозрачный кадр на всю область
        kit._warp_into(fr, src, M, (x0, y0, aw, ah), 1.0)
        return
    if L.get('radius'):
        src = _rounded(src, float(L['radius']) / max(s, 1e-3))
    if src.shape[2] == 3:
        src = np.dstack([src, np.full((h, w), 255, np.uint8)])
    # рисовать только в прямоугольнике, куда попадает слой
    pts = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], np.float32) @ M.T
    clip = fit in ('cover', 'contain') and area == 'visible'
    lo_y = y0 if clip else 0
    hi_y = y0 + ah if clip else kit.H
    bx0, by0 = max(0, int(pts[:, 0].min()) - 1), max(lo_y, int(pts[:, 1].min()) - 1)
    bx1, by1 = min(kit.W, int(pts[:, 0].max()) + 2), min(hi_y, int(pts[:, 1].max()) + 2)
    if bx1 <= bx0 or by1 <= by0:
        return
    M2 = M.copy()
    M2[0, 2] -= bx0
    M2[1, 2] -= by0
    lay = cv2.warpAffine(src, M2, (bx1 - bx0, by1 - by0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                         borderValue=(0, 0, 0, 0))
    _blend(fr[by0:by1, bx0:bx1], lay, op, L.get('blend', 'normal'))


def _text_pos(L):
    pos = L.get('pos', 'center')
    y0, ah = kit.safe_area()
    if pos == 'lower':
        return kit.W / 2, y0 + ah - (120 if kit.LETTERBOX else 150), 'c'
    if pos == 'upper':
        return kit.W / 2, y0 + (120 if kit.LETTERBOX else 150), 'c'
    if pos == 'left':
        return 160, kit.H / 2, 'l'
    if pos == 'right':
        return kit.W - 160, kit.H / 2, 'r'
    if pos == 'custom':
        return float(L.get('x', 960)), float(L.get('y', 540)), L.get('align', 'c')
    return kit.W / 2, kit.H / 2, 'c'


def _draw_text(fr, L, lt, ld, op):
    s = kit.tx(L.get('key') or 'text', L.get('text', ''))
    if not s.strip():
        return
    anim = L.get('anim', 'rise')
    fi = float(L.get('fade_in') or 0)
    ein = kit.oc(kit.prog(lt, 0, fi)) if fi > 0 else 1.0
    if anim == 'type':
        n = len(s)
        dur_type = max(fi, min(ld * 0.6, 0.045 * n))
        s = s[:int(round(n * kit.prog(lt, 0, dur_type)))]
        if not s:
            return
    color = fx._hex(L.get('color', '#ECE4D6'))
    size = int(L.get('size', 110))
    lines = s.split('\n')
    arrs = [kit._tlayer(ln, L.get('font', 'title'), int(L.get('weight', 700)), size, color,
                        float(L.get('track', 0.0)), bool(L.get('shadow', True))) for ln in lines if ln]
    if not arrs:
        return
    cx, cy, align = _text_pos(L)
    lh = size * float(L.get('line', 1.15))
    total_h = lh * (len(arrs) - 1)
    dy_anim, sc, sg, dx_anim = 0.0, 1.0, 0.0, 0.0
    if anim == 'rise':
        dy_anim = (1 - ein) * 30
    elif anim == 'blur':
        sg = (1 - ein) * 10
    elif anim == 'scale':
        sc = 0.85 + 0.15 * ein
    elif anim == 'slide':
        dx_anim = (1 - ein) * -80
    plate = float(L.get('plate') or 0)
    if plate > 0:
        wmax = max(a.shape[1] for a in arrs) - 80
        ph = total_h + size * 1.2
        bx = cx - wmax / 2 if align == 'c' else (cx if align == 'l' else cx - wmax)
        x1, y1 = int(bx - 36 + dx_anim), int(cy - ph / 2 - 10 + dy_anim)
        x2, y2 = int(bx + wmax + 36 + dx_anim), int(cy + ph / 2 + 10 + dy_anim)
        ov = fr.copy()
        cv2.rectangle(ov, (x1, y1), (x2, y2), (8, 9, 12), -1)
        cv2.addWeighted(ov, plate * op, fr, 1 - plate * op, 0, dst=fr)
    for i, a in enumerate(arrs):
        if sg > 0.4:
            a = cv2.GaussianBlur(a, (0, 0), sg)
        h, w = a.shape[:2]
        y = cy - total_h / 2 + i * lh + dy_anim
        if align == 'c':
            x = cx
        elif align == 'l':
            x = cx + (w - 80) / 2 - 0
        else:
            x = cx - (w - 80) / 2
        if sc != 1.0:
            kit.place(fr, a, x + dx_anim, y, sc, 0, op)
        else:
            kit.blit(fr, a, x + dx_anim - w / 2, y - h / 2, op)


def draw(fr, t, dur, layers, z='top'):
    for L in layers or []:
        if L.get('hidden') or L.get('z', 'top') != z:
            continue
        t0, t1 = _window(L, dur)
        if not (t0 <= t < t1 or (t1 >= dur and t0 <= t <= t1)):
            continue
        lt, ld = t - t0, max(1e-3, t1 - t0)
        op = float(L.get('opacity', 1.0)) * _fade(L, lt, ld)
        if op <= 0.003:
            continue
        if L['type'] == 'text':
            _draw_text(fr, L, lt, ld, op)
        else:
            _draw_media(fr, L, lt, ld, op)
