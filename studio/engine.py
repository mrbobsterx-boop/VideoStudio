"""Движок: проект, рендер кадров в фоне, кэш превью, звук, экспорт."""
import bisect
import datetime
import hashlib
import inspect
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import types
import uuid
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

PREVIEW_W = 960
SR = 44100


# =====================================================================================
#  shared: scene loading + frame rendering (used in worker processes and main process)
# =====================================================================================
_MODS = {}
_GRAIN = []
_VIG = None


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which('ffmpeg') or 'ffmpeg'


def code_hash(code):
    return hashlib.sha1(code.encode('utf-8')).hexdigest()[:12]


def load_module(path, code):
    """Скомпилировать код сцены в модуль (кэшируется по хэшу кода)."""
    h = code_hash(code)
    key = (path, h)
    m = _MODS.get(key)
    if m is not None:
        return m
    for k in [k for k in _MODS if k[0] == path]:
        del _MODS[k]
    name = 'scene_' + re.sub(r'\W', '_', os.path.basename(path)) + '_' + h
    m = types.ModuleType(name)
    m.__file__ = path
    exec(compile(code, path, 'exec'), m.__dict__)
    _MODS[key] = m
    return m


def _call_render(mod, fr, t, dur):
    fn = getattr(mod, 'render', None)
    if fn is None:
        raise RuntimeError('В сцене нет функции render(fr, t, dur)')
    try:
        n = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        n = 3
    if n >= 3:
        fn(fr, t, dur)
    elif n == 2:
        fn(fr, t)
    else:
        fn(fr)


def _post(fr, t, lfi, hits, look):
    """Удары (тряска/вспышка), виньетка, зерно, кинополосы."""
    global _VIG
    from . import kit
    H, W = fr.shape[:2]
    k = 0.0
    if look.get('hits', True):
        for ti in hits or []:
            if 0 <= t - ti < 0.6:
                k = max(k, math.exp(-(t - ti) * 7))
    if k > 0.05:
        sx = int((math.sin(t * 93) * 18) * k)
        sy = int((math.cos(t * 71) * 12) * k)
        M = np.float32([[1 + 0.02 * k, 0, sx - W * 0.01 * k], [0, 1 + 0.02 * k, sy - H * 0.01 * k]])
        cv2.warpAffine(fr, M, (W, H), dst=fr, borderMode=cv2.BORDER_REPLICATE)
        d = int(8 * k)
        if d > 0:
            fr[:, d:, 0] = fr[:, :-d, 0].copy()
            fr[:, :-d, 2] = fr[:, d:, 2].copy()
        fl = np.full_like(fr, (255, 230, 200))
        cv2.addWeighted(fr, 1, fl, 0.35 * k ** 2, 0, dst=fr)
    if look.get('vignette', True):
        if _VIG is None:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            v = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (kit.VH * 0.75)) ** 2)
            g = (np.clip(1.15 - 0.55 * v ** 2, 0.25, 1) * 255).astype(np.uint8)
            _VIG = cv2.merge([g] * 3)
        cv2.multiply(fr, _VIG, dst=fr, scale=1 / 255)
    gr = float(look.get('grain', 0.07))
    if gr > 0:
        if not _GRAIN:
            for i in range(6):
                g = np.clip(128 + np.random.default_rng(i).normal(0, 22, (H, W)), 0, 255).astype(np.uint8)
                _GRAIN.append(cv2.merge([g] * 3))
        cv2.addWeighted(fr, 1, _GRAIN[lfi % 6], gr, -128 * gr, dst=fr)
    if look.get('letterbox', True):
        fr[:kit.VY] = 0
        fr[kit.VY + kit.VH:] = 0


def _error_frame(msg, W=1920, H=1080):
    fr = np.zeros((H, W, 3), np.uint8)
    fr[:] = (40, 10, 12)
    lines = ['ОШИБКА В СЦЕНЕ'] + msg.strip().splitlines()[-14:]
    from PIL import Image, ImageDraw, ImageFont
    im = Image.fromarray(fr)
    d = ImageDraw.Draw(im)
    try:
        from . import kit
        f1 = kit._font('oswald', 600, 64)
        f2 = kit._font('oswald', 300, 30)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    d.text((80, 80), lines[0], font=f1, fill=(255, 120, 100))
    y = 190
    for ln in lines[1:]:
        d.text((80, y), ln[:110], font=f2, fill=(240, 220, 210))
        y += 44
    return np.array(im)


def render_one(task):
    """task: dict(path, code, t, dur, lfi, look, texts). Возвращает (кадр RGB, used, new_defaults, err)."""
    from . import kit
    kit.TEXTS = dict(task['texts'])
    kit.USED = set()
    kit.NEW_DEFAULTS = {}
    err = None
    try:
        mod = load_module(task['path'], task['code'])
        fr = np.zeros((kit.H, kit.W, 3), np.uint8)
        _call_render(mod, fr, task['t'], task['dur'])
        _post(fr, task['t'], task['lfi'], getattr(mod, 'HITS', []), task['look'])
    except Exception:
        err = _clean_tb(task['path'])
        fr = _error_frame(err)
    return fr, sorted(kit.USED), dict(kit.NEW_DEFAULTS), err


def _clean_tb(path):
    tb = traceback.format_exc()
    # оставить только строки, относящиеся к сцене и kit
    out = []
    keep = False
    for ln in tb.splitlines():
        if ln.startswith('Traceback'):
            continue
        if 'File "' in ln:
            keep = (path in ln) or ('kit.py' in ln) or ('sound.py' in ln)
            if keep:
                ln = ln.replace(path, os.path.basename(path))
                ln = re.sub(r'File ".*[\\/](kit\.py|sound\.py)"', r'File "\1"', ln)
        if keep or not ln.startswith('  '):
            out.append(ln)
    return '\n'.join(out[-16:])


# ---------------- worker process entry points ----------------
def _winit(project_dir, pkg_parent):
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)
    from . import kit
    kit.PROJECT = project_dir
    cv2.setNumThreads(1)


def w_preview(task):
    fr, used, newd, err = render_one(task)
    h = int(PREVIEW_W * fr.shape[0] / fr.shape[1])
    sm = cv2.resize(fr, (PREVIEW_W, h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(sm, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 84])
    return buf.tobytes(), used, newd, err


def w_chunk(job):
    """Отрендерить кусок кадров в полном качестве и закодировать в отдельный mp4."""
    from . import kit
    out = job['out']
    cmd = [job['ffmpeg'], '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', '%dx%d' % (kit.W, kit.H), '-r', str(job['fps']), '-i', '-',
           '-c:v', 'libx264', '-preset', job.get('preset', 'medium'), '-crf', str(job.get('crf', 18)),
           '-pix_fmt', 'yuv420p', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    err = None
    try:
        for fr_task in job['frames']:
            sc = job['scenes'][fr_task['sid']]
            task = dict(path=sc['path'], code=sc['code'], dur=sc['dur'], look=job['look'], texts=job['texts'],
                        t=fr_task['t'], lfi=fr_task['lfi'])
            fr, used, newd, e = render_one(task)
            if e and not err:
                err = '%s\n%s' % (sc['name'], e)
            p.stdin.write(fr.tobytes())
    finally:
        p.stdin.close()
        p.wait()
    return out, err


# =====================================================================================
#  main process
# =====================================================================================
def slug(s):
    s = re.sub(r'[^A-Za-z0-9]+', '_', s.lower()).strip('_')
    return s[:28] or 'scene'


TEMPLATES = {
    'title': '''"""Титр: крупная надпись на тёмном фоне."""
from studio.kit import *

HITS = [0.0]            # удары (тряска + вспышка), секунды от начала сцены
AMBIENCE = (0.6, 0.6)   # громкость фонового гула в начале и в конце сцены (0..1)
WIND = (0.1, 0.1)       # громкость ветра


def render(fr, t, dur):
    darkbg(fr, (14, 12, 12))
    embers(fr, t, 0.7)
    bold(fr, t, 0.0, dur, tx('{key}_title', 'NEW TITLE'), size=190, track=0.3, blur=False, fin=0.2, fout=0.3)
    serif(fr, t, 0.4, dur, tx('{key}_sub', 'A new line of the story.'), cy=H / 2 + 150, size=56)


def sound(a, dur):
    a.braam(0, 0.9)
    a.taiko(0, 0.8)
''',
    'image': '''"""Картинка с движением камеры и субтитром."""
from studio.kit import *

HITS = []
AMBIENCE = None         # None — продолжить уровень гула предыдущей сцены
WIND = None


def render(fr, t, dur):
    u = t / dur                                   # 0 в начале сцены, 1 в конце
    img = image('street', sat=0.6, con=1.1, bright=0.85)
    # камера: центр (cx, cy) в пикселях картинки и ширина кадра — плавный наезд
    kb(fr, img, lerp(900, 1000, ioc(u)), 420, lerp(1500, 1250, ioc(u)))
    dust(fr, t, amt=0.35)
    serif(fr, t, 0.4, dur - 0.1, tx('{key}_line', 'Write your line here.'))
    if t < 0.4:
        dim(fr, prog(t, 0, 0.4))                  # плавное появление из чёрного


def sound(a, dur):
    a.piano(0.2, 'D4', 0.2)
''',
    'empty': '''"""Новая сцена."""
from studio.kit import *

HITS = []
AMBIENCE = None
WIND = None


def render(fr, t, dur):
    # fr — кадр 1920x1080 (numpy RGB), t — секунды от начала сцены, dur — длина сцены
    darkbg(fr)


def sound(a, dur):
    pass
''',
}


class Studio:
    def __init__(self, project_dir, workers=None):
        self.dir = os.path.abspath(project_dir)
        self.pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.lock = threading.RLock()
        self.cache = {}          # (sid, lfi) -> (gen, jpeg)
        self.inflight = {}       # (sid, lfi, gen) -> future
        self.gen = {}            # sid -> int
        self.errors = {}         # sid -> str
        self.used = {}           # sid -> set(text keys)
        self.meta = {}           # sid -> dict(hash, hits, amb, wind, doc, err)
        self.codes = {}          # sid -> code text
        self.playhead = 0
        self.export_state = {'state': 'idle'}
        self.audio_ver = 0
        self.audio_state = 'idle'
        self.audio_peaks = []
        self._stems = {}
        self._audio_dirty = threading.Event()
        self._music = None
        self._save_timer = None
        self.running = True
        self.load()
        from . import kit
        kit.PROJECT = self.dir
        n = workers or max(1, min((os.cpu_count() or 2) - 1, 6))
        self.nworkers = n
        self.pool = ProcessPoolExecutor(n, mp_context=mp.get_context('spawn'), initializer=_winit,
                                        initargs=(self.dir, self.pkg_parent))
        threading.Thread(target=self._scheduler, daemon=True).start()
        threading.Thread(target=self._audio_loop, daemon=True).start()
        self._audio_dirty.set()

    # ------------------------------------------------------------------ project io
    @property
    def pj(self):
        return os.path.join(self.dir, 'project.json')

    def load(self):
        with open(self.pj, 'r', encoding='utf-8') as f:
            self.p = json.load(f)
        self.p.setdefault('fps', 30)
        self.p.setdefault('look', {})
        self.p.setdefault('audio', {})
        self.p.setdefault('texts', {})
        for s in self.p['scenes']:
            self._read_code(s)

    def save(self, now=False):
        def _do():
            with self.lock:
                tmp = self.pj + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(self.p, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.pj)
        if now:
            _do()
            return
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.4, _do)
        self._save_timer.start()

    def scene_path(self, s):
        return os.path.join(self.dir, 'scenes', s['file'])

    def _read_code(self, s):
        try:
            with open(self.scene_path(s), 'r', encoding='utf-8') as f:
                code = f.read()
        except FileNotFoundError:
            code = TEMPLATES['empty']
        self._set_code(s, code)

    def _set_code(self, s, code):
        sid = s['id']
        old = self.codes.get(sid)
        self.codes[sid] = code
        h = code_hash(code)
        meta = {'hash': h, 'hits': [], 'amb': None, 'wind': None, 'doc': '', 'err': None}
        try:
            mod = load_module(self.scene_path(s), code)
            meta['hits'] = [float(x) for x in (getattr(mod, 'HITS', None) or [])]
            meta['amb'] = getattr(mod, 'AMBIENCE', None)
            meta['wind'] = getattr(mod, 'WIND', None)
            meta['doc'] = ((mod.__doc__ or '').strip().splitlines() or [''])[0]
        except Exception:
            meta['err'] = _clean_tb(self.scene_path(s))
        self.meta[sid] = meta
        if meta['err']:
            self.errors[sid] = meta['err']
        else:
            self.errors.pop(sid, None)
        if old != code:
            self.gen[sid] = self.gen.get(sid, 0) + 1

    def scene(self, sid):
        for s in self.p['scenes']:
            if s['id'] == sid:
                return s
        raise KeyError(sid)

    # ------------------------------------------------------------------ timeline
    def timeline(self):
        fps = self.p['fps']
        out = []
        f0 = 0
        for s in self.p['scenes']:
            n = max(1, int(round(float(s['dur']) * fps)))
            out.append((s, f0, n))
            f0 += n
        return out, f0

    def locate(self, fi):
        tl, total = self.timeline()
        if not tl:
            return None
        fi = max(0, min(total - 1, fi))
        starts = [x[1] for x in tl]
        i = bisect.bisect_right(starts, fi) - 1
        s, f0, n = tl[i]
        return s, fi - f0

    def state(self):
        tl, total = self.timeline()
        fps = self.p['fps']
        scenes = []
        for s, f0, n in tl:
            m = self.meta.get(s['id'], {})
            scenes.append(dict(id=s['id'], name=s['name'], file=s['file'], dur=s['dur'], f0=f0, n=n,
                               hits=m.get('hits', []), doc=m.get('doc', ''), gen=self.gen.get(s['id'], 0),
                               error=self.errors.get(s['id']), used=sorted(self.used.get(s['id'], []))))
        return dict(title=self.p.get('title', 'Project'), fps=fps, total=total, scenes=scenes,
                    texts=self.p['texts'], look=self.p['look'], audio=self.p['audio'],
                    audio_ver=self.audio_ver, audio_state=self.audio_state,
                    export=self.export_state, workers=self.nworkers, dir=self.dir)

    def cache_map(self):
        tl, total = self.timeline()
        out = bytearray(b'0' * total)
        with self.lock:
            for s, f0, n in tl:
                g = self.gen.get(s['id'], 0)
                for l in range(n):
                    c = self.cache.get((s['id'], l))
                    if c and c[0] == g:
                        out[f0 + l] = ord('1')
        return out.decode()

    # ------------------------------------------------------------------ rendering
    def _task(self, s, lfi):
        fps = self.p['fps']
        return dict(path=self.scene_path(s), code=self.codes[s['id']], t=lfi / fps, dur=float(s['dur']),
                    lfi=lfi, look=self.p['look'], texts=self.p['texts'])

    def _submit(self, s, lfi):
        sid = s['id']
        g = self.gen.get(sid, 0)
        key = (sid, lfi, g)
        with self.lock:
            fut = self.inflight.get(key)
            if fut is not None:
                return fut
            fut = self.pool.submit(w_preview, self._task(s, lfi))
            self.inflight[key] = fut

        def done(f, key=key):
            with self.lock:
                self.inflight.pop(key, None)
                try:
                    jpg, used, newd, err = f.result()
                except Exception as e:
                    return
                sid_, lfi_, g_ = key
                if self.gen.get(sid_, 0) != g_:
                    return
                self.cache[(sid_, lfi_)] = (g_, jpg)
                self.used.setdefault(sid_, set()).update(used)
                if err:
                    self.errors[sid_] = err
                elif not self.meta.get(sid_, {}).get('err'):
                    self.errors.pop(sid_, None)
                if newd:
                    changed = False
                    for k, v in newd.items():
                        if k not in self.p['texts']:
                            self.p['texts'][k] = v
                            changed = True
                    if changed:
                        self.save()
        fut.add_done_callback(done)
        return fut

    def frame(self, fi, wait=True):
        loc = self.locate(fi)
        if loc is None:
            return None
        s, lfi = loc
        with self.lock:
            c = self.cache.get((s['id'], lfi))
            if c and c[0] == self.gen.get(s['id'], 0):
                return c[1]
        if not wait:
            return None
        fut = self._submit(s, lfi)
        try:
            jpg = fut.result(timeout=120)[0]
        except Exception:
            return None
        return jpg

    def _scheduler(self):
        while self.running:
            time.sleep(0.03)
            if self.export_state.get('state') == 'running':
                continue
            try:
                tl, total = self.timeline()
                if not total:
                    continue
                limit = self.nworkers * 2
                with self.lock:
                    busy = len(self.inflight)
                if busy >= limit:
                    continue
                ph = max(0, min(total - 1, self.playhead))
                window = min(total, 2400)
                rest = window - (total - ph)
                order = list(range(ph, min(total, ph + window))) + (list(range(0, min(ph, rest))) if rest > 0 else [])
                for fi in order:
                    if busy >= limit:
                        break
                    s, lfi = self.locate(fi)
                    g = self.gen.get(s['id'], 0)
                    with self.lock:
                        c = self.cache.get((s['id'], lfi))
                        if (c and c[0] == g) or (s['id'], lfi, g) in self.inflight:
                            continue
                    self._submit(s, lfi)
                    busy += 1
                # освободить старые кадры, если проект очень длинный
                if len(self.cache) > 6000:
                    with self.lock:
                        for k in list(self.cache.keys())[:1000]:
                            self.cache.pop(k, None)
            except Exception:
                if not self.running:
                    break
                traceback.print_exc()
                time.sleep(0.5)

    def invalidate(self, sids=None):
        with self.lock:
            for s in self.p['scenes']:
                if sids is None or s['id'] in sids:
                    self.gen[s['id']] = self.gen.get(s['id'], 0) + 1

    # ------------------------------------------------------------------ edits
    def _backup(self, s):
        """Копия прошлой версии сцены в scenes/_history (не чаще раза в 2 минуты)."""
        src = self.scene_path(s)
        if not os.path.isfile(src):
            return
        hist = os.path.join(self.dir, 'scenes', '_history')
        os.makedirs(hist, exist_ok=True)
        base = os.path.splitext(s['file'])[0]
        old = sorted(f for f in os.listdir(hist) if f.startswith(base + '__'))
        if old and time.time() - os.path.getmtime(os.path.join(hist, old[-1])) < 120:
            return
        dst = os.path.join(hist, '%s__%s.py' % (base, datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
        shutil.copy2(src, dst)
        os.utime(dst, None)
        for f in old[:-19]:
            try:
                os.remove(os.path.join(hist, f))
            except OSError:
                pass

    def save_code(self, sid, code):
        s = self.scene(sid)
        if code != self.codes.get(sid):
            self._backup(s)
        with open(self.scene_path(s), 'w', encoding='utf-8', newline='\n') as f:
            f.write(code)
        with self.lock:
            self._set_code(s, code)
        self._audio_dirty.set()
        err = None
        try:
            compile(code, s['file'], 'exec')
        except SyntaxError as e:
            err = dict(line=e.lineno, msg='%s (строка %s)' % (e.msg, e.lineno))
        return dict(ok=err is None and not self.meta[sid]['err'], syntax=err, error=self.meta[sid]['err'],
                    gen=self.gen[sid])

    def update_scene(self, sid, name=None, dur=None):
        s = self.scene(sid)
        if name is not None:
            s['name'] = str(name)[:60]
        if dur is not None:
            d = max(0.2, min(600.0, round(float(dur), 3)))
            if d != s['dur']:
                s['dur'] = d
                self.invalidate([sid])       # сцены часто используют dur в расчётах
                self._audio_dirty.set()
        self.save()

    def add_scene(self, after=None, template='image', name='New scene'):
        sid = 's' + uuid.uuid4().hex[:6]
        base = slug(name)
        fn = base + '.py'
        i = 2
        while os.path.exists(os.path.join(self.dir, 'scenes', fn)):
            fn = '%s_%d.py' % (base, i)
            i += 1
        code = TEMPLATES.get(template, TEMPLATES['empty']).replace('{key}', slug(name) if slug(name) != 'new_scene' else sid)
        with open(os.path.join(self.dir, 'scenes', fn), 'w', encoding='utf-8', newline='\n') as f:
            f.write(code)
        s = dict(id=sid, file=fn, name=name, dur=3.0)
        idx = len(self.p['scenes'])
        if after:
            for k, x in enumerate(self.p['scenes']):
                if x['id'] == after:
                    idx = k + 1
        self.p['scenes'].insert(idx, s)
        with self.lock:
            self._set_code(s, code)
        self._audio_dirty.set()
        self.save()
        return sid

    def duplicate_scene(self, sid):
        s = self.scene(sid)
        nid = 's' + uuid.uuid4().hex[:6]
        base = os.path.splitext(s['file'])[0]
        fn = base + '_copy.py'
        i = 2
        while os.path.exists(os.path.join(self.dir, 'scenes', fn)):
            fn = '%s_copy%d.py' % (base, i)
            i += 1
        with open(os.path.join(self.dir, 'scenes', fn), 'w', encoding='utf-8', newline='\n') as f:
            f.write(self.codes[sid])
        ns = dict(id=nid, file=fn, name=s['name'] + ' copy', dur=s['dur'])
        idx = self.p['scenes'].index(s) + 1
        self.p['scenes'].insert(idx, ns)
        with self.lock:
            self._set_code(ns, self.codes[sid])
        self._audio_dirty.set()
        self.save()
        return nid

    def delete_scene(self, sid):
        s = self.scene(sid)
        trash = os.path.join(self.dir, 'scenes', '_trash')
        os.makedirs(trash, exist_ok=True)
        src = self.scene_path(s)
        if os.path.exists(src):
            dst = os.path.join(trash, datetime.datetime.now().strftime('%Y%m%d-%H%M%S_') + s['file'])
            shutil.move(src, dst)
        self.p['scenes'].remove(s)
        self._audio_dirty.set()
        self.save()

    def move_scene(self, sid, index):
        s = self.scene(sid)
        self.p['scenes'].remove(s)
        index = max(0, min(len(self.p['scenes']), int(index)))
        self.p['scenes'].insert(index, s)
        self._audio_dirty.set()
        self.save()

    def set_texts(self, changes):
        affected = set()
        for k, v in changes.items():
            if self.p['texts'].get(k) != v:
                self.p['texts'][k] = v
                for sid, used in self.used.items():
                    if k in used:
                        affected.add(sid)
                for s in self.p['scenes']:            # сцены, которые ещё не рендерились
                    if s['id'] not in self.used:
                        affected.add(s['id'])
        if affected:
            self.invalidate(affected)
        self.save()
        return sorted(affected)

    def set_look(self, look):
        self.p['look'].update(look)
        self.invalidate()
        self.save()

    def set_audio(self, audio):
        self.p['audio'].update(audio)
        self._audio_dirty.set()
        self.save()

    # ------------------------------------------------------------------ audio
    def _stem(self, s):
        from .sound import SceneAudio
        sid = s['id']
        code = self.codes[sid]
        key = (code_hash(code), float(s['dur']))
        c = self._stems.get(sid)
        if c and c[0] == key:
            return c[1]
        a = SceneAudio(float(s['dur']), seed=int(hashlib.md5(sid.encode()).hexdigest()[:6], 16))
        try:
            mod = load_module(self.scene_path(s), code)
            fn = getattr(mod, 'sound', None)
            if fn:
                try:
                    n = len(inspect.signature(fn).parameters)
                except Exception:
                    n = 2
                fn(a, float(s['dur'])) if n >= 2 else fn(a)
        except Exception:
            self.errors[sid] = 'Ошибка в sound():\n' + _clean_tb(self.scene_path(s))
        res = (a.L, a.R, a.WET)
        self._stems[sid] = (key, res)
        return res

    def _music_track(self, n):
        a = self.p['audio']
        fn = a.get('music_file')
        if not fn:
            return None
        path = os.path.join(self.dir, 'audio', fn)
        if not os.path.isfile(path):
            return None
        key = (path, os.path.getmtime(path))
        if not self._music or self._music[0] != key:
            cmd = [ffmpeg_exe(), '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-']
            raw = subprocess.run(cmd, capture_output=True).stdout
            m = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
            self._music = (key, m)
        m = self._music[1]
        off = int(float(a.get('music_offset', 0)) * SR)
        out = np.zeros((n, 2))
        if off >= 0:
            src = m[:max(0, n - off)]
            out[off:off + len(src)] = src
        else:
            src = m[-off:-off + n]
            out[:len(src)] = src
        return out

    def mix_audio(self):
        from .sound import lp
        from scipy.signal import fftconvolve
        tl, total = self.timeline()
        fps = self.p['fps']
        dur = total / fps
        N = int(dur * SR)
        from .sound import TAIL
        M = N + int(TAIL * SR)
        L = np.zeros(M); R = np.zeros(M); WET = np.zeros(M)
        acfg = self.p['audio']
        gen_on = acfg.get('generated', True)
        if gen_on and N > 0:
            # stems
            for s, f0, n in tl:
                sl, sr, sw = self._stem(s)
                i = int(f0 / fps * SR)
                j = min(M, i + len(sl))
                L[i:j] += sl[:j - i]; R[i:j] += sr[:j - i]; WET[i:j] += sw[:j - i]
            # ambience automation
            pts_a, pts_w = [], []
            prev_a, prev_w = 0.4, 0.3
            for s, f0, n in tl:
                m = self.meta.get(s['id'], {})
                t0, t1 = f0 / fps, (f0 + n) / fps
                aa = m.get('amb'); ww = m.get('wind')
                aa = (prev_a, prev_a) if aa is None else ((aa, aa) if isinstance(aa, (int, float)) else tuple(aa))
                ww = (prev_w, prev_w) if ww is None else ((ww, ww) if isinstance(ww, (int, float)) else tuple(ww))
                pts_a += [(t0 + 0.001, aa[0]), (t1 - 0.001, aa[1])]
                pts_w += [(t0 + 0.001, ww[0]), (t1 - 0.001, ww[1])]
                prev_a, prev_w = aa[1], ww[1]
            t = np.arange(M) / SR
            auto = np.interp(t, [p[0] for p in pts_a], [p[1] for p in pts_a])
            wauto = np.interp(t, [p[0] for p in pts_w], [p[1] for p in pts_w])
            auto[N:] *= np.exp(-(t[N:] - dur) * 6)
            wauto[N:] *= np.exp(-(t[N:] - dur) * 6)
            dr = (np.sin(2 * np.pi * 36.71 * t) * 0.5 + np.sin(2 * np.pi * 55 * t + 1) * 0.3 +
                  np.sin(2 * np.pi * 73.42 * t) * 0.25) * (0.75 + 0.25 * np.sin(2 * np.pi * 0.13 * t))
            rng = np.random.default_rng(3)
            wind = lp(rng.standard_normal(M), 380, 2) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.21 * t + 2)) * 1.2
            L += dr * auto * 0.28 + wind * wauto * 0.25
            R += dr * auto * 0.28 + wind * wauto * 0.25 * 0.9
            # reverb
            if np.abs(WET).max() > 0:
                tI = np.arange(int(2.8 * SR)) / SR
                ir = rng.standard_normal(len(tI)) * np.exp(-tI / 0.7)
                ir = lp(ir, 4000)
                ir /= np.sqrt((ir ** 2).sum())
                rev = fftconvolve(WET, ir)[:M] * 0.5
                L += rev
                R += np.roll(rev, int(0.013 * SR))
        mix = np.stack([L, R], 1)[:N]
        peak = float(np.percentile(np.abs(mix), 99.97)) if N else 0
        if peak > 1e-6:
            mix = np.tanh(mix / peak * 1.6) / np.tanh(1.6) * 0.89
        vol = float(acfg.get('generated_volume', 1.0))
        mix *= vol
        mus = self._music_track(N)
        if mus is not None:
            mix = mix + mus * float(acfg.get('music_volume', 0.8))
            mix = np.tanh(mix * 1.05) / np.tanh(1.05)
        fo = float(acfg.get('fade_out', 1.5))
        if fo > 0 and N > 0:
            k = min(N, int(fo * SR))
            mix[N - k:] *= np.linspace(1, 0, k)[:, None]
        return mix

    def _audio_loop(self):
        from scipy.io import wavfile
        while self.running:
            self._audio_dirty.wait()
            time.sleep(0.4)
            self._audio_dirty.clear()
            self.audio_state = 'mixing'
            try:
                mix = self.mix_audio()
                os.makedirs(os.path.join(self.dir, '.cache'), exist_ok=True)
                cdir = os.path.join(self.dir, '.cache')
                path = os.path.join(cdir, 'audio_%d.wav' % (self.audio_ver + 1))
                wavfile.write(path, SR, (np.clip(mix, -1, 1) * 32767).astype(np.int16))
                self._audio_file = path
                for f in os.listdir(cdir):          # убрать старые версии (если не заняты)
                    if f.startswith('audio_') and f.endswith('.wav') and os.path.join(cdir, f) != path:
                        try:
                            os.remove(os.path.join(cdir, f))
                        except OSError:
                            pass
                n = 3000
                if len(mix):
                    mono = np.abs(mix).max(1)
                    k = max(1, len(mono) // n)
                    pk = mono[:k * (len(mono) // k)].reshape(-1, k).max(1)
                    self.audio_peaks = [round(float(x), 3) for x in pk]
                    self.audio_peaks_rate = SR / k
                else:
                    self.audio_peaks = []
                    self.audio_peaks_rate = 1
                self.audio_ver += 1
                self.audio_state = 'ready'
            except Exception:
                traceback.print_exc()
                self.audio_state = 'error: ' + traceback.format_exc().splitlines()[-1]

    def audio_path(self):
        return getattr(self, '_audio_file', '')

    # ------------------------------------------------------------------ export
    def export(self, crf=18):
        if self.export_state.get('state') == 'running':
            return
        threading.Thread(target=self._export, args=(crf,), daemon=True).start()

    def cancel_export(self):
        if self.export_state.get('state') == 'running':
            self.export_state['cancel'] = True

    def _export(self, crf):
        st = dict(state='running', progress=0.0, msg='Подготовка…', cancel=False, started=time.time())
        self.export_state = st
        tmpd = os.path.join(self.dir, '.cache', 'export')
        try:
            shutil.rmtree(tmpd, ignore_errors=True)
            os.makedirs(tmpd, exist_ok=True)
            os.makedirs(os.path.join(self.dir, 'exports'), exist_ok=True)
            # подождать, пока закончатся текущие кадры превью
            t0 = time.time()
            while self.inflight and time.time() - t0 < 20:
                time.sleep(0.1)
            tl, total = self.timeline()
            fps = self.p['fps']
            scenes = {s['id']: dict(path=self.scene_path(s), code=self.codes[s['id']], dur=float(s['dur']), name=s['name'])
                      for s, _, _ in tl}
            frames = []
            for s, f0, n in tl:
                for l in range(n):
                    frames.append(dict(sid=s['id'], t=l / fps, lfi=l))
            chunk = 45
            ff = ffmpeg_exe()
            jobs = []
            for ci, a in enumerate(range(0, total, chunk)):
                part = frames[a:a + chunk]
                need = {f['sid'] for f in part}
                jobs.append(dict(out=os.path.join(tmpd, 'seg%05d.mp4' % ci), frames=part, fps=fps, ffmpeg=ff, crf=crf,
                                 look=dict(self.p['look']), texts=dict(self.p['texts']),
                                 scenes={k: v for k, v in scenes.items() if k in need}))
            st['msg'] = 'Рендер кадров…'
            futs = [self.pool.submit(w_chunk, j) for j in jobs]
            done = 0
            errs = []
            for fu, j in zip(futs, jobs):
                while not fu.done():
                    time.sleep(0.1)
                    if st.get('cancel'):
                        for f2 in futs:
                            f2.cancel()
                        raise RuntimeError('Экспорт отменён')
                out, err = fu.result()
                if err:
                    errs.append(err)
                done += len(j['frames'])
                st['progress'] = done / total * 0.97
                el = time.time() - st['started']
                st['eta'] = el / max(1e-6, st['progress']) * (1 - st['progress'])
            if errs:
                raise RuntimeError('В сценах есть ошибки, экспорт остановлен:\n' + errs[0])
            st['msg'] = 'Сведение звука…'
            mix = self.mix_audio()
            from scipy.io import wavfile
            wav = os.path.join(tmpd, 'audio.wav')
            wavfile.write(wav, SR, (np.clip(mix, -1, 1) * 32767).astype(np.int16))
            lst = os.path.join(tmpd, 'list.txt')
            with open(lst, 'w') as f:
                for j in jobs:
                    f.write("file '%s'\n" % os.path.basename(j['out']))
            name = '%s_%s.mp4' % (slug(self.p.get('title', 'video')), datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            out = os.path.join(self.dir, 'exports', name)
            cmd = [ff, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', wav, '-c:v', 'copy',
                   '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError('ffmpeg: ' + r.stderr[-800:])
            self.export_state = dict(state='done', progress=1.0, file=name, path=out,
                                     seconds=round(time.time() - st['started'], 1))
        except Exception as e:
            self.export_state = dict(state='error', msg=str(e), progress=st.get('progress', 0))
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    def shutdown(self):
        self.running = False
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.pool.shutdown(wait=False)
