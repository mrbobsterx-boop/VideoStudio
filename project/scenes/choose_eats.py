"""CHOOSE WHO EATS."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.6, 0.6)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    kb(fr, image('bunker3', sat=0.8, con=1.1), 1225, 340, 640)
    dim(fr, lerp(0.75, 0.45, prog(t, 0, dur)))
    bold(fr, t, 0, dur, tx('choose_1', 'CHOOSE WHO EATS.'), size=120, track=0.2, blur=False, fin=0.12, fout=0.15)


def sound(a, dur):
    a.braam(0, 0.95)
    a.taiko(0, 0.9)
