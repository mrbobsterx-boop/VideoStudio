"""Слова по одному: каждое слово появляется с ударом (кинетическая типографика)."""
from studio.kit import *

AMBIENCE = (0.5, 0.6)
WIND = None
STEP = 0.55     # секунд на слово
HITS = [i * STEP for i in range(5)]


def render(fr, t, dur):
    darkbg(fr, (6, 6, 9))
    words = tx('kinetic_words', 'ВЫЖИТЬ. ПОСТРОИТЬ. ВЫСТОЯТЬ.').split()
    i = min(len(words) - 1, int(t / STEP))
    lt = t - i * STEP
    last = i == len(words) - 1
    e = oexp(prog(lt, 0, 0.25))
    size = int(lerp(260, 200, e))
    end = dur if last else (i + 1) * STEP
    text(fr, t, i * STEP, end, words[i], W / 2, H / 2, fam='title', w=700, size=size, color=(240, 242, 248),
         blur=False, fin=0.04, fout=0.05 if not last else 0.4, rise=0, track=0.06)
    effect(fr, t, dur, 'bloom', amount=0.35, threshold=200)


def sound(a, dur):
    for k in range(5):
        a.taiko(k * STEP, 0.8)
