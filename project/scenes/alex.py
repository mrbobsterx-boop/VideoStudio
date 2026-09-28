"""Главный герой: вырезанная фигура, имя, профессия и цитата."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.48, 0.45)
WIND = (0.5, 0.1)


def render(fr, t, dur):
    u = t / dur
    bg = image('street', sat=0.2, con=1.0, bright=0.25, tint=(1.1, 0.95, 0.85), blur=9)
    kb(fr, bg, lerp(900, 1000, u), 420, 1500)
    glow_circle(fr, 640, 560, 420, (190, 110, 60), sigma=120)
    embers(fr, t, 0.6)
    sc = lerp(0.74, 0.82, u)
    hero = sprite('alexei_cut')
    place(fr, hero, 640 + lerp(-20, 10, u), VY + hero.shape[0] * sc / 2 - 40, sc)
    text(fr, t, 0.4, dur - 0.1, tx('name_1', 'ALEX'), 1120, VY + 300, align='l',
         w=700, size=170, track=0.12)
    text(fr, t, 0.8, dur - 0.1, tx('alex_role', 'Mechanic.  34.'), 1120, VY + 420, align='l',
         w=300, size=46, color=EMBER, track=0.15)
    text(fr, t, 1.3, dur - 0.1, tx('alex_quote', '“As long as I breathe, nothing is lost.”'), 1120, VY + 520,
         align='l', fam='corm_i', w=500, size=48)


def sound(a, dur):
    a.braam(0, 0.6)
