"""Обратный отсчёт 3-2-1: цифры с ударом и расходящимся кольцом."""
from studio.kit import *

HITS = [0.0, 1.0, 2.0]
AMBIENCE = (0.5, 0.7)
WIND = None


def render(fr, t, dur):
    darkbg(fr, (8, 9, 12))
    step = dur / 3
    i = min(2, int(t / step))
    lt = t - i * step
    n = ['3', '2', '1'][i]
    e = oexp(prog(lt, 0, 0.35))
    ring = oc(prog(lt, 0, step))
    r = int(120 + 380 * ring)
    col = tuple(int(c * (1 - ring)) for c in (150, 170, 220))
    if r > 0:
        cv2.circle(fr, (W // 2, H // 2), r, col, 3, cv2.LINE_AA)
    glow_circle(fr, W / 2, H / 2, 220, (50, 60, 95), sigma=140, amount=1 - 0.6 * ring)
    text(fr, t, i * step, i * step + step, n, W / 2, H / 2, fam='title', w=700, size=int(lerp(420, 300, e)),
         color=(240, 242, 248), blur=False, fin=0.05, fout=0.12, rise=0)


def sound(a, dur):
    for k in range(3):
        a.taiko(k * dur / 3, 0.9)
        a.tick(k * dur / 3 + 0.5, 0.3)
