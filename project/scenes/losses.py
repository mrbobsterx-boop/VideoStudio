"""Потери: ранена, голодает, не вернулся."""
from studio.kit import *

HITS = []
AMBIENCE = (0.5, 0.6)
WIND = (0.1, 0.1)

# (номер портрета, ключ имени, имя по умолчанию, ключ статуса, статус, цвет, когда появляется)
WHO = [(2, 'name_2', 'MARIA', 'status_wounded', 'WOUNDED', RED, 0.0),
       (3, 'name_3', 'IGOR', 'status_starving', 'STARVING', EMBER, 0.7),
       (5, 'name_5', 'DENIS', None, '', CREAM, 1.4)]
LOST = 2          # кто из списка WHO не вернулся (индекс: 0, 1, 2)


def render(fr, t, dur):
    fr[:] = 0
    fr[VY:VY + VH] = (10, 9, 9)
    for k, (face, nkey, nname, skey, status, col, d0) in enumerate(WHO):
        e = oc(prog(t, d0, d0 + 0.6))
        if e <= 0:
            continue
        x = W / 2 + (k - 1) * 460
        y = VY + 330
        f = portrait('face%d' % face, 320, 300).copy()
        if k == LOST:
            g = prog(t, 2.0, 2.8)
            grayscale(f, g)
            dim(f, 1 - 0.55 * g)
        c = card(f, border=8)
        blit(fr, c, x - c.shape[1] / 2, y - c.shape[0] / 2 + (1 - e) * 40, e)
        text(fr, t, d0 + 0.1, dur, tx(nkey, nname), x, y + 215, w=600, size=44, track=0.25, rise=8, fout=0.3)
        if skey:
            text(fr, t, d0 + 0.35, dur, tx(skey, status), x, y + 270, w=400, size=30, color=col, track=0.35, rise=8, fout=0.3)
        if k == LOST and t > 2.4:
            p = oc(prog(t, 2.4, 2.9))
            cv2.line(fr, (int(x - 110), int(y + 215)), (int(x - 110 + 220 * p), int(y + 215)), RED, 4, cv2.LINE_AA)
    serif(fr, t, 2.3, dur, tx('loss_line', '{name_5|title} didn’t come back.'), cy=VY + VH - 60, size=60, fout=0.3)


def sound(a, dur):
    for x, n in [(0, 'D4'), (0.7, 'F4'), (1.4, 'A4'), (2.1, 'G4'), (2.7, 'F4'), (3.3, 'E4'), (3.8, 'D4')]:
        a.piano(x, n, 0.3)
    a.pad(0, ['D3', 'F3', 'A3'], 4.0, 0.07)
