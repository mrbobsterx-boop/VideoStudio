"""Цитата: слова проявляются по одному, внизу подпись автора."""
from studio.kit import *

HITS = []
AMBIENCE = (0.35, 0.35)
WIND = (0.2, 0.2)


def render(fr, t, dur):
    darkbg(fr, (13, 13, 16))
    glow_circle(fr, W / 2, H / 2, 380, (40, 46, 64), sigma=200, amount=0.6)
    q = tx('quote_text', 'Пока я дышу — ничего не потеряно.')
    words = q.split()
    size = 76
    # разбить на две строки примерно пополам
    half = max(1, (len(words) + 1) // 2)
    lines = [words[:half], words[half:]] if len(words) > 5 else [words]
    text(fr, t, 0.1, dur - 0.2, '“', W / 2 - min(560, W * 0.38), H / 2 - 150, fam='serif', size=260, color=(90, 100, 130),
         shadow=False)
    k = 0
    for li, ws in enumerate(lines):
        full = ' '.join(ws)
        wtot, _ = text_size(full, 'serif', 500, size, 0.01)
        x = W / 2 - wtot / 2
        cy = H / 2 - 50 + li * 100 - (50 if len(lines) == 1 else 0) + 50 * (len(lines) == 1)
        for wd in ws:
            ww, _ = text_size(wd + ' ', 'serif', 500, size, 0.01)
            text(fr, t, 0.3 + k * 0.16, dur - 0.2, wd, x, cy, align='l', fam='serif', w=500, size=size,
                 color=(232, 235, 242), rise=14, fin=0.5)
            x += ww
            k += 1
    text(fr, t, 0.6 + k * 0.16, dur - 0.2, tx('quote_author', '— АЛЕКС, МЕХАНИК'), W / 2, H / 2 + 170, fam='text',
         w=400, size=34, track=0.3, color=(140, 150, 175))


def sound(a, dur):
    a.piano(0.3, 'A4', 0.16)
    a.piano(1.3, 'F4', 0.14)
