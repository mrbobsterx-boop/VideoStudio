"""DAY 23: запасы и число выживших падают."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.6, 0.57)
WIND = (0.1, 0.1)

# (ключ текста, подпись, было, стало)
STATS = [('stat_1', 'SURVIVORS', 6, 4), ('stat_2', 'FOOD', 42, 27), ('stat_3', 'WATER', 28, 18),
         ('stat_4', 'POWER', 36, 12), ('stat_5', 'MEDICINE', 8, 3)]


def render(fr, t, dur):
    u = t / dur
    img = image('bunker2', sat=0.5, con=1.1, bright=0.55, tint=(1, 0.97, 0.95))
    kb(fr, img, lerp(780, 820, u), 420, 1400)
    blur(fr, 3)
    dim(fr, 0.6)
    bold(fr, t, 0, dur - 0.1, tx('day_title', 'DAY 23'), cy=VY + 260, size=170, track=0.3, blur=False, fin=0.15)
    cw = 330
    x0 = W / 2 - cw * 2
    for i, (key, label, a, b) in enumerate(STATS):
        p = prog(t, 0.5 + i * 0.12, 1.8 + i * 0.12)
        val = int(round(lerp(a, b, ioc(p))))
        x = x0 + i * cw
        text(fr, t, 0.3, dur - 0.1, tx(key, label), x, VY + 470, w=400, size=28, color=(170, 160, 145), track=0.3, rise=0)
        text(fr, t, 0.3, dur - 0.1, str(val), x, VY + 550, w=600, size=84, color=RED if p > 0 else CREAM, rise=0, blur=False)
        if p >= 1:
            text(fr, t, 2.1 + i * 0.12, dur - 0.1, '▼ %d' % (a - b), x, VY + 630, w=400, size=28, color=RED,
                 track=0.1, rise=0)


def sound(a, dur):
    a.braam(0, 1.0, root=34.65)
    for x in [0.5, 0.8, 1.1, 1.4, 1.7, 2.0]:
        a.tick(x, 0.35)
    a.pulse(0, dur, 0.22)
