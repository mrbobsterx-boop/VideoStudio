"""Вылазка: герой бежит к радиовышке."""
from studio.kit import *

HITS = []
AMBIENCE = (0.53, 0.5)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    e = ioc(t / dur)
    img = image('run', sat=0.8, con=1.1)
    kb(fr, img, lerp(955, 1062, e), lerp(330, 300, e), lerp(800, 850, e))
    dust(fr, t, col=(200, 170, 160), amt=0.3)
    box = text(fr, t, 0.4, dur - 0.1, tx('run_objective', 'Reach the radio tower'), W - 120, VY + 70, align='r',
               w=400, size=34, track=0.06, rise=0)
    if box:
        diamond(fr, box[0] - 26, VY + 72, 9, EMBER, op=oc(prog(t, 0.4, 1.0)) * (1 - prog(t, dur - 0.6, dur - 0.1)))
    serif(fr, t, 1.2, dur - 0.1, tx('run_line', 'Out there, every mistake is final.'))


def sound(a, dur):
    a.pulse(0, dur, 0.3)
    x, k = 0.0, 0
    while x < dur:
        a.taiko(x, 0.45 if k % 2 == 0 else 0.25)
        x += 0.25; k += 1
    a.riser(dur - 1.4, 1.4, 0.35)
