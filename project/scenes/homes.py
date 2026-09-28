"""Брошенная кухня: «We left our homes behind.»"""
from studio.kit import *

HITS = []
AMBIENCE = (0.5, 0.48)
WIND = (0.57, 0.5)


def render(fr, t, dur):
    u = t / dur
    img = image('kitchen', sat=0.55, con=1.1, bright=0.8, tint=(1.05, 1.0, 0.92))
    kb(fr, img, lerp(820, 1260, ioc(u)), 400, 1320)
    dust(fr, t, col=(210, 190, 150), amt=0.45)
    serif(fr, t, 0.5, dur - 0.2, tx('homes_line', 'We left our homes behind.'))


def sound(a, dur):
    a.piano(0.1, 'D4', 0.22)
    a.piano(1.4, 'F4', 0.20)
    a.piano(2.6, 'A4', 0.18)
