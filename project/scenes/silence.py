"""Секунда тишины перед финалом."""
from studio.kit import *

HITS = []
AMBIENCE = (0.3, 0.0)
WIND = (0.05, 0.0)


def render(fr, t, dur):
    fr[:] = 0


def sound(a, dur):
    a.heart(0.3, 0.7)
