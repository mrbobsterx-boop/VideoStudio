"""Финал: фигура с собакой на крыше на закате, две строки."""
from studio.kit import *

HITS = []
AMBIENCE = (0.0, 0.8)
WIND = (0.3, 0.4)


def render(fr, t, dur):
    e = ioc(t / dur)
    img = image('menu', sat=0.9, con=1.08, bright=1.05)
    kb(fr, img, lerp(1080, 1015, e), lerp(470, 390, e), lerp(1180, 900, e))
    dust(fr, t, col=(230, 180, 150), amt=0.35)
    if t < 0.8:
        dim(fr, prog(t, 0, 0.8))
    shade_bottom(fr, 260, 0.35)
    half = dur / 2
    serif(fr, t, 0.8, half + 0.2, tx('finale_1', 'People don’t survive because the world is kind.'), size=56)
    serif(fr, t, half + 0.4, dur - 0.1, tx('finale_2', 'They survive because they refuse to give up.'), size=56)


def sound(a, dur):
    a.pad(0.0, ['D3', 'F3', 'A3'], 2.0, 0.10, att=1.5)
    a.pad(2.0, ['Bb2', 'D3', 'F3'], 2.0, 0.11)
    a.pad(4.0, ['F3', 'A3', 'C4'], 1.8, 0.12)
    a.pad(5.8, ['C3', 'E3', 'G3'], 1.6, 0.13)
    for x, n in [(0.2, 'D5'), (1.2, 'C5'), (2.2, 'Bb4'), (3.2, 'A4'), (4.2, 'C5'), (5.2, 'D5'), (6.2, 'E5'), (6.9, 'F5')]:
        a.piano(x, n, 0.26)
    a.riser(dur - 1.8, 1.8, 0.7)
