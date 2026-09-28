"""Шесть выживших: портреты с именами (имена — во вкладке «Тексты»)."""
from studio.kit import *

HITS = []
AMBIENCE = (0.63, 0.6)
WIND = (0.1, 0.1)

NAMES = [('name_1', 'ALEX'), ('name_2', 'MARIA'), ('name_3', 'IGOR'),
         ('name_4', 'SVETLANA'), ('name_5', 'DENIS'), ('name_6', 'OLGA')]


def render(fr, t, dur):
    u = t / dur
    img = image('bunker3', sat=0.8, con=1.1)
    kb(fr, img, lerp(800, 860, u), 440, 1300)
    blur(fr, 6)
    dim(fr, 0.28)
    serif(fr, t, 0.1, dur - 0.1, tx('survivors_line', 'Six survivors. One shelter.'), cy=VY + 120, size=56)
    cw = 270
    x0 = W / 2 - cw * 3 + cw / 2
    for i, (key, default) in enumerate(NAMES):
        e = oc(prog(t, 0.25 + i * 0.18, 0.85 + i * 0.18))
        if e <= 0:
            continue
        x = x0 + i * cw
        y = VY + 400 + (1 - e) * 60
        c = card(portrait('face%d' % (i + 1), 240, 225), border=10, color=(60, 52, 42))
        blit(fr, c, x - c.shape[1] / 2, y - c.shape[0] / 2, e)
        text(fr, t, 0.25 + i * 0.18, dur - 0.1, tx(key, default), x, y + 175,
             w=500, size=34, track=0.25, rise=10, fout=0.3)


def sound(a, dur):
    a.war_drums(0, dur)
    a.melody(0, ['D5', 'C5', 'A4', 'G4', 'A4', 'F4'], step=0.535, g=0.18)
