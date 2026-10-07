"""Большое число: счётчик быстро растёт до значения, под ним подпись."""
from studio.kit import *

HITS = [2.0]
AMBIENCE = (0.4, 0.55)
WIND = None


def render(fr, t, dur):
    darkbg(fr, (10, 11, 14))
    raw = tx('bignum_value', '1000000')
    digits = ''.join(c for c in raw if c.isdigit()) or '0'
    target = int(digits)
    k = oexp(prog(t, 0.2, 2.0))
    v = int(round(target * k))
    s = '{:,}'.format(v).replace(',', ' ') + tx('bignum_suffix', '+')
    glow_ellipse(fr, W / 2, H / 2 - 20, 620, 160, (40, 60, 110), sigma=150, amount=0.4 + 0.5 * prog(t, 1.8, 2.3))
    text(fr, t, 0.1, dur - 0.1, s, W / 2, H / 2 - 30, fam='title', w=700, size=200, color=(240, 243, 250),
         track=0.02, blur=False, fin=0.3)
    text(fr, t, 0.7, dur - 0.1, tx('bignum_label', 'ИГРОКОВ УЖЕ ВНУТРИ'), W / 2, H / 2 + 110, fam='text', w=400,
         size=42, track=0.35, color=(140, 152, 180))


def sound(a, dur):
    a.ticks(0.2, 2.0, start=0.12, accel=0.0, g=0.2)
    a.braam(2.0, 0.7)
