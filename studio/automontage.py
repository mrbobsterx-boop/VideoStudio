"""Автомонтаж: из ваших картинок и видео (и музыки) собрать ролик в выбранном стиле.

Каждая картинка/видео становится сценой из слоёв: медиа на весь кадр с движением камеры,
переходы, цветокоррекция и подписи — всё это потом можно поменять руками во вкладках «Слои» и «Эффекты».
Если загружена музыка — склейки ставятся в такт (по найденным долям).
"""
import os
import random

import numpy as np

from . import engine, versions

STYLES = {
    'cinematic': dict(label='Кино', beats=8, sec=3.6, grade='teal_orange', motions=['zoom_in', 'pan_left', 'zoom_out', 'pan_right'],
                      motion_amt=0.1, title_font='title', look=dict(letterbox=True, vignette=True, grain=0.07),
                      desc='Плавные наезды, затемнения между кадрами, киношный цвет, кинополосы'),
    'dynamic': dict(label='Динамичный', beats=2, sec=1.4, grade='vivid', motions=['zoom_in', 'zoom_out'],
                    motion_amt=0.14, title_font='title', look=dict(letterbox=False, vignette=True, grain=0.04),
                    desc='Быстрые склейки в ритм, удары-наезды, вспышки, смазанные переходы'),
    'soft': dict(label='Тёплые воспоминания', beats=8, sec=3.4, grade='faded', motions=['zoom_in', 'pan_right', 'zoom_out'],
                 motion_amt=0.07, title_font='serif', look=dict(letterbox=False, vignette=True, grain=0.08),
                 desc='Тёплый плёночный цвет, засветки, мягкие появления из размытия'),
    'noir': dict(label='Нуар / драма', beats=8, sec=3.8, grade='noir', motions=['zoom_in', 'pan_left', 'zoom_in'],
                 motion_amt=0.08, title_font='title', look=dict(letterbox=True, vignette=True, grain=0.1),
                 desc='Чёрно-белое, контраст, сильная виньетка, медленный ритм'),
    'glitch': dict(label='Кибер / глитч', beats=4, sec=1.8, grade='night', motions=['zoom_in', 'zoom_out', 'pan_left'],
                   motion_amt=0.12, title_font='title', look=dict(letterbox=False, vignette=True, grain=0.05),
                   desc='Холодный цвет, глитч-сбои и RGB-расслоение на склейках'),
}


# ------------------------------------------------------------------ ритм музыки
def analyze_music(samples, sr):
    """Найти доли (beats) в музыке. Возвращает (tempo_bpm, список секунд долей, громкость по времени)."""
    if samples is None or len(samples) < sr * 2:
        return None, [], None
    mono = samples.mean(1) if samples.ndim == 2 else samples
    hop, win = 512, 2048
    n = (len(mono) - win) // hop
    if n < 50:
        return None, [], None
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    flux = np.zeros(n)
    energy = np.zeros(n)
    w = np.hanning(win).astype(np.float32)
    prev = None
    for a in range(0, n, 2048):                  # по кускам — чтобы не держать весь спектр в памяти
        fr = mono[idx[a:a + 2048]].astype(np.float32) * w
        mag = np.log1p(np.abs(np.fft.rfft(fr, axis=1))[:, :400])
        energy[a:a + 2048] = np.sqrt((fr ** 2).mean(1))
        d = np.diff(mag, axis=0, prepend=mag[:1] if prev is None else prev[None, :])
        flux[a:a + 2048] = np.maximum(d, 0).sum(1)
        prev = mag[-1]
    flux -= np.convolve(flux, np.ones(16) / 16, mode='same')
    flux = np.maximum(flux, 0)
    if flux.max() <= 0:
        return None, [], energy
    flux /= flux.max()
    fps = sr / hop
    # темп: автокорреляция в диапазоне 70..180 уд/мин, с предпочтением ~110
    ac = np.correlate(flux, flux, mode='full')[len(flux) - 1:]
    lags = np.arange(len(ac))
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    if hi >= len(ac):
        return None, [], energy
    bpm_l = 60 * fps / np.maximum(lags[lo:hi], 1)
    score = ac[lo:hi] * np.exp(-0.5 * (np.log2(bpm_l / 110)) ** 2 / 0.5 ** 2)
    period = lo + int(np.argmax(score))
    tempo = 60 * fps / period
    # фаза: сдвиг сетки, на который приходится больше всего всплесков
    best, phase = -1, 0
    for ph in range(period):
        s = flux[ph::period].sum()
        if s > best:
            best, phase = s, ph
    beats = [(phase + k * period) / fps for k in range(int((n - phase) / period) + 1)]
    return round(float(tempo), 1), beats, energy


# ------------------------------------------------------------------ сборка
def media_list(studio):
    from . import media
    d = os.path.join(studio.dir, 'assets')
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        stem, ext = os.path.splitext(f)
        ext = ext.lower()
        p = os.path.join(d, f)
        if ext in engine.VIDEO_EXT:
            try:
                i = media.info(p)
            except Exception:
                continue
            out.append(dict(name=stem, file=f, kind='video', dur=i['dur'], w=i['w'], h=i['h']))
        elif ext in engine.IMG_EXT:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    w, h = im.size
                    alpha = ext == '.png' and im.mode in ('RGBA', 'LA', 'P')
            except Exception:
                continue
            # вырезанные объекты и крошечные иконки на весь кадр не годятся
            if alpha or max(w, h) < 500:
                continue
            out.append(dict(name=stem, file=f, kind='image', dur=0, w=w, h=h))
    return out


def music_info(studio):
    a = studio.p['audio']
    fn = a.get('music_file')
    if not fn:
        return None
    path = os.path.join(studio.dir, 'audio', os.path.basename(fn))
    if not os.path.isfile(path):
        return None
    m = studio.music_samples(path)
    tempo, beats, energy = analyze_music(m, engine.SR)
    return dict(file=fn, dur=round(len(m) / engine.SR, 2), tempo=tempo, beats=beats,
                offset=float(a.get('music_offset', 0)))


def _cut_points(total, style, mus, n_media):
    """Длины сцен: по долям музыки или ровным шагом."""
    st = STYLES[style]
    if mus and mus.get('beats') and mus.get('tempo'):
        beat = 60.0 / mus['tempo']
        pattern = {'dynamic': [2, 2, 4, 2, 1, 1, 2, 4], 'glitch': [4, 2, 2, 4]}.get(style, [st['beats']])
        durs, i = [], 0
        acc = 0.0
        while acc < total - beat * 0.5:
            d = pattern[i % len(pattern)] * beat
            while d < 0.8:
                d *= 2
            d = min(d, total - acc)
            durs.append(d)
            acc += d
            i += 1
        # слишком короткий хвост — приклеить к предыдущей сцене
        if len(durs) > 1 and durs[-1] < max(1.2, beat * 1.5):
            durs[-2] += durs.pop()
        return durs
    step = st['sec']
    k = max(1, int(round(total / step)))
    return [total / k] * k


def _fx_for(style, i, n, dur, first, last):
    fx = []
    g = STYLES[style]['grade']
    if style == 'cinematic':
        fx += [dict(name='grade', preset=g, strength=0.75)]
        fx += [dict(name='fade_in', dur=0.9 if first else 0.25), dict(name='fade_out', dur=1.2 if last else 0.25)]
    elif style == 'dynamic':
        fx += [dict(name='grade', preset=g, strength=0.6)]
        fx += [dict(name='punch_in', dur=0.3, amount=0.14) if i % 3 != 2 else dict(name='whip_in', dur=0.25, dir='right' if i % 2 else 'left')]
        if i % 4 == 0:
            fx += [dict(name='flash_in', dur=0.2, amount=0.7)]
        if last:
            fx += [dict(name='fade_out', dur=0.6)]
    elif style == 'soft':
        fx += [dict(name='grade', preset=g, strength=0.8), dict(name='grade', preset='warm', strength=0.5),
               dict(name='light_leak', color=['warm', 'gold', 'rose'][i % 3], amount=0.45, speed=0.7),
               dict(name='dust', amount=0.3), dict(name='blur_in', dur=0.6, amount=10),
               dict(name='fade_in', dur=0.5 if not first else 1.0)]
        if last:
            fx += [dict(name='fade_out', dur=1.4)]
    elif style == 'noir':
        fx += [dict(name='grade', preset=g, strength=1.0), dict(name='vignette', amount=0.55),
               dict(name='fade_in', dur=0.8 if first else 0.35), dict(name='fade_out', dur=1.4 if last else 0.35)]
    elif style == 'glitch':
        fx += [dict(name='grade', preset=g, strength=0.7), dict(name='glitch', amount=0.55, rate=1.2, t1=0.35),
               dict(name='rgb_split', amount=3)]
        if i % 3 == 1:
            fx += [dict(name='vhs', amount=0.35)]
        if last:
            fx += [dict(name='fade_out', dur=0.6)]
    return fx


_SOUND = {
    'cinematic': "    a.pad(0, ['D3', 'A3', 'F4'], dur, 0.07)\n    if {first}:\n        a.braam(0, 0.7)\n",
    'dynamic': "    a.taiko(0, 0.7)\n    a.whoosh(max(0, dur - 0.35), 0.3, 0.35)\n",
    'soft': "    a.piano(0.05, {note!r}, 0.18)\n",
    'noir': "    a.heart(0.1, 0.6)\n    a.pad(0, ['D2', 'A2'], dur, 0.05)\n",
    'glitch': "    a.tick(0, 0.4)\n    a.bass(0, 'D2', 0.25)\n",
}
_NOTES = ['D4', 'F4', 'A4', 'C5', 'A4', 'F4', 'E4', 'G4']


def _scene_code(title, style, first, idx, with_sound, hits):
    snd = _SOUND[style].format(first=first, note=_NOTES[idx % len(_NOTES)]) if with_sound else '    pass\n'
    return ('"""Автомонтаж: %s."""\nfrom studio.kit import *\n\nHITS = %r\nAMBIENCE = None\nWIND = None\n\n\n'
            'def render(fr, t, dur):\n    # картинка/видео, подписи и эффекты — во вкладках «Слои» и «Эффекты»\n    pass\n\n\n'
            'def sound(a, dur):\n%s') % (title.replace('"', "'"), hits, snd)


def _title_code(key, style, with_sound, end=False):
    bg = {'cinematic': '(8, 9, 12)', 'dynamic': '(6, 6, 8)', 'soft': '(22, 17, 14)', 'noir': '(6, 6, 6)', 'glitch': '(4, 6, 12)'}[style]
    part = 'embers(fr, t, 0.5)' if style in ('cinematic', 'dynamic') else ('dust(fr, t, amt=0.35)' if style != 'glitch' else "effect(fr, t, dur, 'glitch', amount=0.4, rate=1.5)")
    snd = ('    a.braam(0.1, 0.8)\n    a.riser(max(0, dur - 1.6), 1.5, 0.35)\n' if not end else '    a.braam(0.2, 0.9)\n    a.pad(0, [\'D3\', \'A3\', \'D4\'], dur, 0.08)\n') if with_sound else '    pass\n'
    return ('"""Автомонтаж: %s."""\nfrom studio.kit import *\n\nHITS = %s\nAMBIENCE = (0.35, 0.45)\nWIND = (0.2, 0.2)\n\n\n'
            'def render(fr, t, dur):\n    u = t / dur\n    darkbg(fr, %s)\n    glow_ellipse(fr, W / 2, H / 2, 700, 240, (70, 80, 110), sigma=160, amount=0.35 + 0.15 * u)\n'
            '    %s\n\n\ndef sound(a, dur):\n%s') % ('финальный титр' if end else 'вступительный титр',
                                                    '[0.2]' if style in ('cinematic', 'dynamic') else '[]', bg, part, snd)


def build(studio, opts):
    style = opts.get('style', 'cinematic')
    if style not in STYLES:
        style = 'cinematic'
    st = STYLES[style]
    names = opts.get('media') or [m['name'] for m in media_list(studio)]
    allm = {m['name']: m for m in media_list(studio)}
    items = [allm[n] for n in names if n in allm]
    if not items:
        raise ValueError('Нет картинок или видео для автомонтажа. Добавьте их во вкладке «Медиа».')
    if opts.get('order') == 'shuffle':
        random.Random(opts.get('seed', 7)).shuffle(items)
    mus = music_info(studio) if opts.get('use_music', True) else None
    title = str(opts.get('title') or '').strip()
    subtitle = str(opts.get('subtitle') or '').strip()
    end_title = str(opts.get('end_title') or '').strip()
    end_sub = str(opts.get('end_sub') or '').strip()
    captions = [c.strip() for c in str(opts.get('captions') or '').splitlines() if c.strip()]
    title_d = 3.2 if title else 0.0
    end_d = 3.6 if end_title else 0.0
    target = float(opts.get('duration') or 0)
    if target <= 0:
        if mus:
            target = max(6.0, min(mus['dur'] - max(0.0, mus['offset']), 600))
        else:
            target = title_d + end_d + len(items) * st['sec']
    target = max(3.0, min(target, 1200.0))
    body = max(1.0, target - title_d - end_d)
    if mus and mus.get('beats') and mus.get('tempo'):
        beat = 60.0 / mus['tempo']
        # вступление — до ближайшей сильной доли, чтобы первая склейка попала в ритм
        if title_d:
            title_d = max(2.0, round(title_d / (beat * 4)) * beat * 4)
            body = max(1.0, target - title_d - end_d)
    durs = _cut_points(body, style, mus, len(items))
    with_sound = not (mus and studio.p['audio'].get('music_file'))
    ver = versions.create(studio, 'Перед автомонтажом', auto=True)
    if opts.get('replace'):
        for s in list(studio.p['scenes']):
            studio.delete_scene(s['id'])
    after = None
    if not opts.get('replace') and studio.p['scenes']:
        after = studio.p['scenes'][-1]['id']
    font = st['title_font']
    added = []
    if title:
        layers = [dict(type='text', text=title, font=font, weight=700, size=150 if font == 'title' else 120,
                       track=0.25 if font == 'title' else 0.02, pos='center', anim='blur', fade_in=0.9, fade_out=0.5,
                       color='#EEF0F4')]
        if subtitle:
            layers.append(dict(type='text', text=subtitle, font='serif', weight=500, size=54, pos='custom', x=960, y=660,
                               align='c', anim='rise', start=0.7, fade_in=0.8, fade_out=0.5, track=0.02, color='#C9CED8'))
        fxl = [dict(name='fade_in', dur=0.6), dict(name='fade_out', dur=0.4)]
        sid = studio.add_scene(after=after, name='Титр', code=_title_code('am_title', style, with_sound), dur=title_d,
                               layers=layers, fx=fxl)
        added.append(sid)
        after = sid
    n = len(durs)
    use = {}
    for i, d in enumerate(durs):
        m = items[i % len(items)]
        k = use.get(m['name'], 0)
        use[m['name']] = k + 1
        motion = st['motions'][i % len(st['motions'])]
        L = dict(type=m['kind'], src=m['name'], fit='cover', motion=motion, motion_amt=st['motion_amt'],
                 fade_in=0, fade_out=0, z='bottom')
        if m['kind'] == 'video':
            # разные куски одного видео для повторов; видео длиннее сцены — берём середину
            vd = max(0.0, m['dur'])
            if vd > d + 0.5:
                slots = max(1, int(vd // (d + 0.2)))
                start = (vd - d) * (0.35 if slots == 1 else ((k % slots) + 0.5) / slots)
                L['trim'] = round(max(0.0, min(vd - d, start)), 2)
            L['loop'] = True
            L['volume'] = float(opts.get('video_volume', 0.0))
        layers = [L]
        if i < len(captions):
            layers.append(dict(type='text', text=captions[i], font='serif' if style == 'soft' else 'text', weight=500,
                               size=58, pos='lower', anim='rise', start=min(0.3, d * 0.2), fade_in=0.5,
                               fade_out=min(0.4, d * 0.2), plate=0.35 if style == 'dynamic' else 0.0, track=0.02))
        hits = [0.0] if style == 'dynamic' and i % 2 == 0 else []
        code = _scene_code(m['name'], style, i == 0 and not title, i, with_sound, hits)
        sid = studio.add_scene(after=after, name=m['name'][:40], code=code, dur=round(d, 3), layers=layers,
                               fx=_fx_for(style, i, n, d, i == 0 and not title, i == n - 1 and not end_title))
        added.append(sid)
        after = sid
    if end_title:
        layers = [dict(type='text', text=end_title, font=font, weight=700, size=130 if font == 'title' else 110,
                       track=0.2 if font == 'title' else 0.02, pos='center', anim='scale', fade_in=0.8, fade_out=0.6,
                       color='#EEF0F4')]
        if end_sub:
            layers.append(dict(type='text', text=end_sub, font='text', weight=400, size=44, pos='custom', x=960, y=650,
                               align='c', anim='fade', start=0.8, fade_in=0.6, fade_out=0.6, track=0.35, color='#AEB5C2'))
        sid = studio.add_scene(after=after, name='Финал', code=_title_code('am_end', style, with_sound, end=True),
                               dur=end_d, layers=layers, fx=[dict(name='fade_in', dur=0.5), dict(name='fade_out', dur=1.2)])
        added.append(sid)
    if opts.get('apply_look', True):
        studio.set_look(st['look'])
    if mus and opts.get('replace'):
        studio.set_audio(dict(generated=False))      # ролик целиком под музыку — без сгенерированного звука
    elif not mus and not studio.p['audio'].get('generated', True):
        studio.set_audio(dict(generated=True))
    return dict(added=added, version=ver['id'], tempo=mus['tempo'] if mus else None, duration=round(sum(durs) + title_d + end_d, 2))
