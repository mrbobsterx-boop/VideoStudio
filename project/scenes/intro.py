"""Интро: чёрный экран и первая фраза под стук сердца."""
from studio.kit import *

HITS = []                 # удары (тряска + вспышка): секунды от начала сцены
AMBIENCE = (0.15, 0.36)   # фоновый гул: громкость в начале и в конце сцены
WIND = (0.3, 0.6)         # ветер: громкость в начале и в конце


def render(fr, t, dur):
    fr[:] = 0
    serif(fr, t, 0.5, dur - 0.2, tx('intro_line', 'At first, they said it would pass.'), cy=H / 2, size=62)


def sound(a, dur):
    for x in [0.35, 1.25, 2.15]:
        a.heart(x, 0.9)
