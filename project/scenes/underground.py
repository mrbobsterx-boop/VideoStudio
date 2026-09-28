"""Убежище: мигает и загорается свет. «So we went underground.»"""
from studio.kit import *

HITS = []
AMBIENCE = (0.45, 0.57)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    u = t / dur
    img = image('bunker_room', sat=0.8, con=1.1, tint=(1.05, 1, 0.95))
    kb(fr, img, lerp(840, 880, u), 475, lerp(1420, 1250, oc(u)))
    # мигание ламп: (начало, конец) вспышек в секундах
    br = 0.12
    for a, b in [(0.3, 0.38), (0.46, 0.52), (0.6, 0.62), (0.7, 99)]:
        if a <= t < b:
            br = 1.0 if b - a > 0.05 else 0.6
    dim(fr, br)
    dust(fr, t, amt=0.3 * br)
    serif(fr, t, 0.8, dur - 0.1, tx('underground_line', 'So we went underground.'))


def sound(a, dur):
    for x in [0, 0.9, 1.8, 2.7]:
        a.taiko(x, 0.35)
    a.pad(0, ['D2', 'A2', 'D3'], 6.0, 0.08)
