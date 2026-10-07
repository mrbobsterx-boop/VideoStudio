"""Глитч-заставка: надпись со сбоями изображения и RGB-расслоением."""
from studio.kit import *

HITS = [0.0, 1.6]
AMBIENCE = (0.3, 0.3)
WIND = None


def render(fr, t, dur):
    darkbg(fr, (5, 7, 12))
    for i in range(0, H, 4):           # тонкие строки экрана
        fr[i] = (fr[i].astype(np.uint16) * 7 // 10).astype(np.uint8)
    bold(fr, t, 0.0, dur, tx('glitch_title', 'SYSTEM ONLINE'), size=160, track=0.12, blur=False, fin=0.05,
         fout=0.2, color=(225, 240, 255))
    text(fr, t, 0.5, dur, tx('glitch_sub', 'ПОДКЛЮЧЕНИЕ УСТАНОВЛЕНО'), W / 2, H / 2 + 120, fam='text', w=300, size=36,
         track=0.4, color=(90, 200, 255), blur=False)
    effect(fr, t, dur, 'glitch', amount=0.8, rate=2.5)
    effect(fr, t, dur, 'rgb_split', amount=4)
    effect(fr, t, dur, 'bloom', amount=0.5, threshold=170)


def sound(a, dur):
    a.bass(0, 'D2', 0.3)
    a.tick(0.05, 0.5)
    a.tick(1.6, 0.5)
    a.whoosh(dur - 0.5, 0.5, 0.3)
