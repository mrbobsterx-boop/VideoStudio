"""Кинотитр: разреженный заголовок, по которому проходит блик света."""
from studio.kit import *

HITS = [0.15]
AMBIENCE = (0.4, 0.5)
WIND = (0.15, 0.2)


def render(fr, t, dur):
    u = t / dur
    darkbg(fr, (9, 10, 13))
    glow_ellipse(fr, W / 2, H / 2, 760, 220, (60, 72, 104), sigma=170, amount=0.45 + 0.2 * u)
    dust(fr, t, amt=0.25, col=(180, 190, 210))
    title = tx('cine_title', 'НАЗВАНИЕ')
    box = bold(fr, t, 0.1, dur - 0.1, title, size=170, track=0.32, fin=1.0, fout=0.5, color=(236, 239, 245))
    if box:
        # блик: светлая полоса проходит по надписи
        x, y, w, h = box
        k = prog(t, 0.6, 1.8)
        if 0 < k < 1:
            sx = int(x - 200 + (w + 400) * ioc(k))
            y0, y1 = int(max(0, y)), int(min(H, y + h))
            x0, x1 = max(0, sx - 90), min(W, sx + 90)
            if x1 > x0:
                band = fr[y0:y1, x0:x1].astype(np.float32)
                ramp = np.clip(1 - np.abs(np.arange(x1 - x0) - (sx - x0)) / 90, 0, 1)[None, :, None]
                fr[y0:y1, x0:x1] = np.clip(band + band * ramp * 0.9, 0, 255).astype(np.uint8)
    serif(fr, t, 0.9, dur - 0.1, tx('cine_sub', 'история, которая начинается сейчас'), cy=H / 2 + 140, size=50,
          color=(170, 178, 196))
    effect(fr, t, dur, 'fade_in', dur=0.6)
    effect(fr, t, dur, 'fade_out', dur=0.5)


def sound(a, dur):
    a.braam(0.15, 0.8)
    a.pad(0, ['D3', 'A3', 'F4'], dur, 0.06)
