"""CRAFT: три верстака выпрыгивают снизу."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.68, 0.66)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    darkbg(fr, (14, 12, 14))
    glow_circle(fr, W // 2, VY + 500, 500, (120, 60, 20), sigma=150)
    for i, (n, x) in enumerate([('b_chem', 400), ('b_forge', 960), ('b_radio', 1520)]):
        e = oback(prog(t, i * 0.12, 0.5 + i * 0.12))
        place(fr, sprite(n), x, VY + 510 + (1 - e) * 500, 1.12 * lerp(1, 1.04, prog(t, 0, dur)))
    embers(fr, t, 1.0)
    bold(fr, t, 0, dur, tx('craft', 'CRAFT'), cy=VY + 120, size=120, track=0.35, blur=False, fin=0.2, fout=0.2)


def sound(a, dur):
    a.braam(0, 0.8)
    a.war_drums(0, dur)
