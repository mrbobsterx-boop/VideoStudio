"""Финальная карточка: название, «скоро» и дата, мягкое свечение."""
from studio.kit import *

HITS = [0.2]
AMBIENCE = (0.45, 0.2)
WIND = (0.2, 0.1)


def render(fr, t, dur):
    u = t / dur
    darkbg(fr, (7, 8, 11))
    glow_ellipse(fr, W / 2, H / 2 - 20, 820, 260, (44, 56, 92), sigma=180, amount=0.35 + 0.35 * ioc(prog(t, 0.2, 1.5)))
    effect(fr, t, dur, 'snow', amount=0.35)
    sc = lerp(1.06, 1.0, oc(prog(t, 0.2, 2.0)))
    bold(fr, t, 0.2, dur, tx('end_title', 'НАЗВАНИЕ'), cy=H / 2 - 40, size=int(200 * sc), track=0.18,
         color=(240, 243, 250), fin=0.9)
    text(fr, t, 1.1, dur, tx('end_soon', 'СКОРО'), W / 2, H / 2 + 110, fam='text', w=400, size=44, track=0.6,
         color=(170, 180, 205))
    text(fr, t, 1.6, dur, tx('end_date', '2026'), W / 2, H / 2 + 175, fam='serif', w=500, size=40,
         color=(120, 130, 155))
    effect(fr, t, dur, 'fade_out', dur=1.0)


def sound(a, dur):
    a.braam(0.2, 1.0)
    a.pad(0.2, ['D3', 'A3', 'D4', 'F4'], dur, 0.08)
