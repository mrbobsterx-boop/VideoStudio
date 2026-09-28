"""SCAVENGE: детали слетаются к разбитой машине, и она становится целой."""
from studio.kit import *

HITS = [0.0]
AMBIENCE = (0.7, 0.68)
WIND = (0.1, 0.1)

# (картинка, смещение x, смещение y, масштаб)
PARTS = [('p_engine', -780, -260, 2.3), ('p_wheel', -820, 230, 2.2), ('p_battery', 800, -230, 2.2),
         ('p_radiator', -700, 10, 2.1), ('p_gearbox', 760, 110, 2.1), ('p_steer', 620, -330, 2.0),
         ('p_jerry', -560, -340, 2.0), ('p_plugs', 560, 330, 2.0), ('p_drum', 860, 300, 1.9)]


def render(fr, t, dur):
    darkbg(fr, (18, 14, 12))
    embers(fr, t, 0.5)
    bold(fr, t, 0, dur, tx('scavenge', 'SCAVENGE'), cy=VY + 150, size=120, track=0.35, blur=False, fin=0.2, fout=0.2)
    cx, cy = W / 2, VY + 470
    swap = prog(t, 1.15, 1.35)
    if swap < 1:
        place(fr, sprite('p_car_bad'), cx, cy, 2.3, op=1 - swap)
    if swap > 0:
        place(fr, sprite('p_car_ok'), cx, cy, 2.3 * lerp(1.04, 1, swap), op=swap)
    for i, (n, dx, dy, s) in enumerate(PARTS):
        p = prog(t, 0.05 + i * 0.07, 0.55 + i * 0.07)
        if p <= 0:
            continue
        e = oc(p)
        fly = prog(t, 1.0, 1.25)
        x = cx + dx * (1.8 - 0.8 * e) * (1 - fly * 0.9)
        y = cy + dy * (1.8 - 0.8 * e) * (1 - fly * 0.9)
        ang = (1 - e) * (90 if i % 2 else -90) + math.sin(t * 2 + i) * 4
        place(fr, sprite(n), x, y, s * (1 - fly * 0.6), ang=ang, op=min(1, p * 3) * (1 - fly))


def sound(a, dur):
    a.braam(0, 0.8)
    a.war_drums(0, dur)
