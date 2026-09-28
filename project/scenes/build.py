"""BUILD: дом-убежище в разрезе."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.66, 0.64)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    u = t / dur
    img = image('house', sat=0.75, con=1.1, bright=0.95)
    kb(fr, img, lerp(930, 950, u), lerp(470, 450, u), lerp(1180, 1320, oexp(u)))
    bold(fr, t, 0, dur, tx('build', 'BUILD'), size=230, track=0.35, blur=False, fin=0.2, fout=0.2)


def sound(a, dur):
    a.braam(0, 0.8)
    a.war_drums(0, dur)
