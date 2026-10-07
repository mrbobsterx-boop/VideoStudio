"""Финальные титры: список «роль — имя» плавно едет вверх."""
from studio.kit import *

HITS = []
AMBIENCE = (0.3, 0.2)
WIND = (0.1, 0.1)


def render(fr, t, dur):
    darkbg(fr, (9, 9, 11))
    rows = [r.split('|') for r in tx('credits_rows', 'Режиссёр|Имя Фамилия;Сценарий|Имя Фамилия;Музыка|Имя Фамилия;'
                                                      'Художник|Имя Фамилия;Монтаж|Shelter Studio').split(';') if r]
    total = len(rows) * 130 + 300
    y0 = lerp(H + 40, -total + H * 0.55, t / dur)
    bold(fr, 0.5, 0, 1, tx('credits_head', 'В РОЛЯХ'), cy=y0, size=70, track=0.35, color=(220, 225, 236), blur=False,
         fin=0, fout=0)
    for i, r in enumerate(rows):
        y = y0 + 160 + i * 130
        if -60 < y < H + 60:
            text(fr, 0.5, 0, 1, r[0].strip().upper(), W / 2, y, fam='text', w=300, size=30, track=0.35,
                 color=(130, 140, 165), fin=0, fout=0, blur=False)
            if len(r) > 1:
                text(fr, 0.5, 0, 1, r[1].strip(), W / 2, y + 48, fam='serif', w=500, size=54,
                     color=(236, 238, 244), fin=0, fout=0, blur=False)
    effect(fr, t, dur, 'fade_in', dur=0.6)
    effect(fr, t, dur, 'fade_out', dur=0.8)


def sound(a, dur):
    a.pad(0, ['D3', 'F3', 'A3', 'C4'], dur, 0.07)
