"""Фото или видео на весь кадр с подписью (всё настраивается во вкладке «Слои»)."""
from studio.kit import *

HITS = []
AMBIENCE = None
WIND = None


def render(fr, t, dur):
    # подсказка видна, пока в слое не выбрана картинка/видео — слой ляжет поверх неё
    darkbg(fr, (18, 20, 26))
    y0, h = safe_area()
    glow_ellipse(fr, W / 2, y0 + h / 2, 700, 260, (40, 50, 80), sigma=150, amount=0.5)
    text(fr, 0.5, 0, 1, 'Выберите фото или видео во вкладке «Слои»', W / 2, y0 + h / 2 - 60, fam='text', w=400,
         size=40, color=(150, 160, 185), fin=0, fout=0, blur=False)


def sound(a, dur):
    pass
