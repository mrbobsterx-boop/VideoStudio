"""Логотип SHELTER и «COMING SOON»."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.2, 0.0)
WIND = (0.2, 0.1)


def render(fr, t, dur):
    darkbg(fr, (8, 7, 8))
    glow_ellipse(fr, W // 2, VY + 420, 700, 260, (90, 45, 18), sigma=120)
    embers(fr, t, 0.9)
    e = oc(prog(t, 0, 1.2))
    sc = 2.05 * lerp(1.12, 1.0, e) * lerp(1, 1.03, prog(t, 0, dur))
    place(fr, sprite('logo'), W / 2, VY + 370, sc, op=e)
    text(fr, t, 1.8, dur, tx('coming_soon', 'COMING SOON'), W / 2, VY + 700, w=400, size=40, track=0.6, fout=0.8)
    if t > dur - 0.8:
        dim(fr, 1 - prog(t, dur - 0.8, dur))


def sound(a, dur):
    a.braam(0, 1.3)
    a.taiko(0, 1.2)
    a.piano(1.8, 'D4', 0.25, 5)
    a.piano(1.8, 'D3', 0.20, 5)
