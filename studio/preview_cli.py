"""
Превью сцен без запуска редактора: кадры в JPEG и (по желанию) время рендера.

    python -m studio.preview_cli СЦЕНА.py ДЛИНА ПАПКА_ВЫХОДА [--project project] [--times 0.1,5,9.9]
                                  [--assets ПАПКА ...] [--fonts ПАПКА] [--width 960] [--sound файл.wav]

По умолчанию — три кадра: начало (0.2 с), середина, конец (длина − 0.2 с). Вид кадра — как в ролике без
кинополос, виньетки и зерна редактора (look: letterbox/vignette/grain выключены), 1920×1080.
--sound — дополнительно посчитать sound(a, dur) сцены и сохранить WAV (проверка, что звук не падает).
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('scene')
    ap.add_argument('dur', type=float)
    ap.add_argument('out')
    ap.add_argument('--project', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'project'))
    ap.add_argument('--times', default='')
    ap.add_argument('--assets', nargs='*', default=[])
    ap.add_argument('--fonts', default='')
    ap.add_argument('--width', type=int, default=960)
    ap.add_argument('--prefix', default='')
    ap.add_argument('--sound', default='')
    a = ap.parse_args(argv)

    from . import engine, kit
    kit.PROJECT = a.project
    code = open(a.scene, encoding='utf-8').read()
    times = [float(x) for x in a.times.split(',') if x.strip()] or [0.2, a.dur / 2, max(0.0, a.dur - 0.2)]
    os.makedirs(a.out, exist_ok=True)
    task_base = dict(path=os.path.abspath(a.scene), code=code, dur=a.dur, lfi=0, size=(1920, 1080),
                     look=dict(letterbox=False, vignette=False, grain=0.0, hits=True), texts={}, layers=[], fx=[],
                     fonts={}, asset_dirs=[os.path.join(a.project, 'assets')] + list(a.assets),
                     font_dirs=[a.fonts or os.path.join(a.project, 'fonts')])
    base = a.prefix or os.path.splitext(os.path.basename(a.scene))[0]
    worst = 0.0
    for i, t in enumerate(times):
        task = dict(task_base, t=t, lfi=int(t * 30))
        t0 = time.time()
        fr, used, newd, err, assets = engine.render_one(task)
        ms = (time.time() - t0) * 1000
        worst = max(worst, ms)
        if err:
            print('ОШИБКА t=%.2f:\n%s' % (t, err))
            return 1
        s = a.width / fr.shape[1]
        sm = cv2.resize(fr, (a.width, int(fr.shape[0] * s)), interpolation=cv2.INTER_AREA)
        name = os.path.join(a.out, '%s_%d.jpg' % (base, i + 1))
        cv2.imwrite(name, cv2.cvtColor(sm, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
        print('%s t=%.2f %.0f мс' % (name, t, ms))
    if a.sound:
        from .sound import SceneAudio, SR
        m = engine.load_module(os.path.abspath(a.scene), code)
        au = SceneAudio(a.dur)
        if hasattr(m, 'sound'):
            m.sound(au, a.dur)
        st = np.stack([au.L, au.R], 1)
        pk = float(np.abs(st).max() or 1)
        import wave
        with wave.open(a.sound, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((st / max(1.0, pk) * 32000).astype(np.int16).tobytes())
        print('звук: %s, пик %.2f' % (a.sound, pk))
    print('максимум: %.0f мс на кадр' % worst)
    return 0


if __name__ == '__main__':
    sys.exit(main())
