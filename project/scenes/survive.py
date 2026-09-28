"""SURVIVE: панорама по жизни в убежище."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.64, 0.63)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    u = t / dur
    img = image('bunker3', sat=0.8, con=1.1)
    kb(fr, img, lerp(560, 1120, ioc(u)), 440, 1080)
    bold(fr, t, 0, dur, tx('survive', 'SURVIVE'), size=230, track=0.35, blur=False, fin=0.2, fout=0.2)


def sound(a, dur):
    a.braam(0, 0.8)
    a.war_drums(0, dur)
