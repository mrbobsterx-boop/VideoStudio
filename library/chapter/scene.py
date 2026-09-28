"""Глава: крупный номер, растущие линии и название главы."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.5, 0.5)
WIND = None


def render(fr, t, dur):
    darkbg(fr, (11, 12, 15))
    num = tx('chapter_num', '01')
    e = oexp(prog(t, 0.0, 0.9))
    text(fr, t, 0.0, dur - 0.1, num, W / 2, H / 2 - 40, fam='title', w=200, size=int(lerp(360, 300, e)),
         color=(52, 58, 72), track=0.05, shadow=False, rise=0, fin=0.5)
    ln = ioc(prog(t, 0.35, 1.2)) * 520
    y = int(H / 2 + 105)
    cv2.line(fr, (int(W / 2 - ln), y), (int(W / 2 - 60), y), (120, 132, 160), 2, cv2.LINE_AA) if ln > 60 else None
    cv2.line(fr, (int(W / 2 + 60), y), (int(W / 2 + ln), y), (120, 132, 160), 2, cv2.LINE_AA) if ln > 60 else None
    diamond(fr, W / 2, y, 7, (200, 210, 235), op=prog(t, 0.5, 0.9))
    bold(fr, t, 0.55, dur - 0.1, tx('chapter_title', 'ГЛАВА ПЕРВАЯ'), cy=H / 2 - 20, size=110, track=0.22,
         color=(236, 239, 245))
    serif(fr, t, 1.0, dur - 0.1, tx('chapter_sub', 'где всё началось'), cy=y + 70, size=46, color=(160, 168, 186))
    effect(fr, t, dur, 'fade_out', dur=0.4)


def sound(a, dur):
    a.taiko(0, 0.7)
    a.whoosh(0.3, 0.7, 0.3)
