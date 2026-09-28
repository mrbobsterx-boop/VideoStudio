"""Разрушенная улица и удар: «IT DIDN'T.»"""
from studio.kit import *

HITS = [1.6]
AMBIENCE = (0.36, 0.5)
WIND = (0.6, 0.57)


def render(fr, t, dur):
    u = t / dur
    img = image('street', sat=0.35, con=1.15, bright=0.72, tint=(0.9, 1.0, 1.08))
    kb(fr, img, lerp(980, 1060, u), lerp(400, 370, u), lerp(1560, 1320, ioc(u)))
    dust(fr, t, amt=0.35)
    if t >= 1.6:
        dim(fr, lerp(0.55, 0.7, prog(t, 1.6, dur)))
    bold(fr, t, 1.6, dur - 0.1, tx('it_didnt', 'IT DIDN’T.'), size=170, fin=0.25, blur=False, track=0.2)
    if t < 0.4:
        dim(fr, prog(t, 0, 0.4))


def sound(a, dur):
    a.braam(1.6, 1.0)
