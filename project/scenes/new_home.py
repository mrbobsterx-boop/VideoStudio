"""Уютная комната: «And built a home from what was left.»"""
from studio.kit import *

HITS = []
AMBIENCE = (0.57, 0.7)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    u = t / dur
    img = image('cozy_room', sat=0.75, con=1.1, bright=0.88, tint=(1.04, 1, 0.93))
    kb(fr, img, lerp(900, 960, u), lerp(450, 430, u), lerp(1500, 1280, ioc(u)))
    dust(fr, t, col=(230, 190, 140), amt=0.4)
    serif(fr, t, 0.4, dur - 0.1, tx('home_line', 'And built a home from what was left.'))


def sound(a, dur):
    a.ticks(0, dur)
    a.riser(dur - 1.6, 1.6, 0.5)
