"""Карта: маршрут от убежища к больнице."""
from studio.kit import *

HITS = [2.6]
AMBIENCE = (0.57, 0.53)
WIND = (0.1, 0.1)

# точки маршрута в пикселях картинки карты
PATH = [(818, 575), (790, 530), (768, 470), (778, 420), (800, 370), (838, 318)]
TARGET = (838, 311)


def render(fr, t, dur):
    e = ioc(t / dur)
    cx, cy, w = lerp(800, 830, e), lerp(480, 462, e), lerp(1150, 820, e)
    kb(fr, image('map', sat=0.8, con=1.15), cx, cy, w)
    h = w * VH / W
    s = W / w

    def P(x, y):                                  # из координат карты в координаты кадра
        return (int((x - (cx - w / 2)) * s), int((y - (cy - h / 2)) * s + VY))

    # рисуем пунктир по пройденной части пути
    d = prog(t, 0.4, 2.2)
    seg = [math.dist(PATH[i], PATH[i + 1]) for i in range(len(PATH) - 1)]
    want, acc, pts = sum(seg) * d, 0, [PATH[0]]
    for i, sl in enumerate(seg):
        if acc + sl <= want:
            pts.append(PATH[i + 1]); acc += sl
        else:
            f = (want - acc) / sl
            pts.append((lerp(PATH[i][0], PATH[i + 1][0], f), lerp(PATH[i][1], PATH[i + 1][1], f)))
            break
    dl = 0
    for i in range(len(pts) - 1):
        a = np.array(P(*pts[i]), float); b = np.array(P(*pts[i + 1]), float)
        L = np.linalg.norm(b - a); n = int(L // 6) + 1
        for j in range(n):
            if int((dl + j * 6) / 18) % 2 == 0:
                p1 = a + (b - a) * j / n; p2 = a + (b - a) * min(1, (j + 1) / n)
                cv2.line(fr, tuple(p1.astype(int)), tuple(p2.astype(int)), RED, 5, cv2.LINE_AA)
        dl += L
    # пульсирующие круги у цели
    if t > 2.0:
        hx, hy = P(*TARGET)
        for k in range(2):
            ph = ((t - 2.0) * 1.2 + k * 0.5) % 1
            ov = fr.copy()
            cv2.circle(ov, (hx, hy), int(30 + ph * 110), RED, 5, cv2.LINE_AA)
            cv2.addWeighted(ov, 1 - ph, fr, ph, 0, dst=fr)
    serif(fr, t, 0.7, 2.5, tx('map_line', 'The hospital. Medicine. High danger.'))
    bold(fr, t, 2.6, dur - 0.1, tx('map_call', 'SOMEONE HAS TO GO.'), cy=VY + VH - 120, size=70, track=0.25, fin=0.2, blur=False)


def sound(a, dur):
    a.pulse(0, dur, 0.22)
    a.braam(2.6, 0.7)
