"""Движок: проект, рендер кадров в фоне, кэш превью, звук, экспорт.

Код сцен выполняется только в процессах рендера (пул), никогда в процессе сервера:
зависшая или упавшая сцена не останавливает редактор — пул перезапускается сам.
"""
import ast
import bisect
import copy
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
from concurrent.futures.process import BrokenProcessPool

import cv2
import numpy as np

PREVIEW_W = 960
SR = 44100
MAX_CACHE = 3000          # кадров превью в памяти
HANG_SECONDS = 40         # столько может считаться один кадр/звук сцены, потом пул перезапускается
VIDEO_EXT = ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')


# =====================================================================================
#  shared: scene loading + frame rendering (used in worker processes)
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
            try:
                ti = float(ti)
            except (TypeError, ValueError):
                continue
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


def _error_frame(msg, W=1920, H=1080, title='ОШИБКА В СЦЕНЕ'):
    fr = np.zeros((H, W, 3), np.uint8)
    fr[:] = (30, 12, 16)
    lines = [title] + msg.strip().splitlines()[-14:]
    from PIL import Image, ImageDraw, ImageFont
    im = Image.fromarray(fr)
    d = ImageDraw.Draw(im)
    try:
        from . import kit
        f1 = kit._font('oswald', 600, 64)
        f2 = kit._font('oswald', 300, 30)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    d.text((80, 80), lines[0], font=f1, fill=(255, 130, 140))
    y = 190
    for ln in lines[1:]:
        d.text((80, y), ln[:110], font=f2, fill=(240, 222, 226))
        y += 44
    return np.array(im)


def _setup_kit(task):
    from . import kit
    kit.TEXTS = dict(task.get('texts') or {})
    kit.USED = set()
    kit.NEW_DEFAULTS = {}
    kit.ASSETS_USED = set()
    kit.FONT_ROLES = dict(task.get('fonts') or {})
    kit.LETTERBOX = (task.get('look') or {}).get('letterbox', True) is not False
    if task.get('asset_dirs'):
        kit.ASSET_DIRS = list(task['asset_dirs'])
    if task.get('font_dirs'):
        kit.FONT_DIRS = list(task['font_dirs'])
    return kit


def render_one(task):
    """task: dict(path, code, t, dur, lfi, look, texts, layers, fx, fonts, asset_dirs, font_dirs).
    Возвращает (кадр RGB, used, new_defaults, err, assets_used)."""
    from . import fx, layers
    kit = _setup_kit(task)
    err = None
    try:
        fr = np.zeros((kit.H, kit.W, 3), np.uint8)
        t, dur = task['t'], task['dur']
        lays = task.get('layers') or []
        layers.draw(fr, t, dur, lays, 'bottom')
        hits = []
        if task.get('code', '').strip():
            mod = load_module(task['path'], task['code'])
            _call_render(mod, fr, t, dur)
            hits = getattr(mod, 'HITS', []) or []
        layers.draw(fr, t, dur, lays, 'top')
        fx.apply_all(fr, t, dur, task.get('fx'), task.get('lfi', 0))
        _post(fr, t, task['lfi'], hits, task['look'])
    except Exception:
        err = _clean_tb(task['path'])
        fr = _error_frame(err)
    return fr, sorted(kit.USED), dict(kit.NEW_DEFAULTS), err, sorted(kit.ASSETS_USED)


def _clean_tb(path):
    tb = traceback.format_exc()
    # оставить только строки, относящиеся к сцене и kit
    out = []
    keep = False
    for ln in tb.splitlines():
        if ln.startswith('Traceback'):
            continue
        if 'File "' in ln:
            keep = (path in ln) or ('kit.py' in ln) or ('sound.py' in ln) or ('layers.py' in ln)
            if keep:
                ln = ln.replace(path, os.path.basename(path))
                ln = re.sub(r'File ".*[\\/](kit\.py|sound\.py|layers\.py)"', r'File "\1"', ln)
        if keep or not ln.startswith('  '):
            out.append(ln)
    return '\n'.join(out[-16:])


def _jpeg(fr, width=PREVIEW_W, q=84):
    h = int(width * fr.shape[0] / fr.shape[1])
    sm = cv2.resize(fr, (width, h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(sm, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes()


# ---------------- worker process entry points ----------------
def _winit(project_dir, pkg_parent):
    if pkg_parent not in sys.path:
        sys.path.insert(0, pkg_parent)
    from . import kit
    kit.PROJECT = project_dir
    kit.ASSET_DIRS = [os.path.join(project_dir, 'assets')]
    kit.FONT_DIRS = [os.path.join(project_dir, 'fonts')]
    cv2.setNumThreads(1)


def w_preview(task):
    fr, used, newd, err, assets = render_one(task)
    return _jpeg(fr, task.get('width', PREVIEW_W)), used, newd, err, assets


def w_meta(task):
    """HITS / AMBIENCE / WIND, если они вычисляются кодом (не простые числа)."""
    try:
        mod = load_module(task['path'], task['code'])
        return dict(hits=[float(x) for x in (getattr(mod, 'HITS', None) or [])],
                    amb=getattr(mod, 'AMBIENCE', None), wind=getattr(mod, 'WIND', None), err=None)
    except Exception:
        return dict(hits=[], amb=None, wind=None, err=_clean_tb(task['path']))


def w_sound(task):
    """Звук одной сцены: вызов её sound(a, dur). Возвращает (L, R, WET, ошибка)."""
    from .sound import SceneAudio
    a = SceneAudio(task['dur'], seed=task['seed'])
    err = None
    try:
        if task['code'].strip():
            mod = load_module(task['path'], task['code'])
            fn = getattr(mod, 'sound', None)
            if fn:
                try:
                    n = len(inspect.signature(fn).parameters)
                except Exception:
                    n = 2
                fn(a, task['dur']) if n >= 2 else fn(a)
    except Exception:
        err = 'Ошибка в sound():\n' + _clean_tb(task['path'])
    return a.L.astype(np.float32), a.R.astype(np.float32), a.WET.astype(np.float32), err


def w_check(task):
    """Проверка сцены (для ИИ-кода): несколько кадров, время рендера, ошибки."""
    out = []
    for t in task['times']:
        t0 = time.time()
        sub = dict(task, t=t, lfi=int(t * 30))
        fr, used, newd, err, assets = render_one(sub)
        out.append(dict(t=t, ms=int((time.time() - t0) * 1000), err=err, jpg=_jpeg(fr, 480, 80)))
        if err:
            break
    return out


def w_chunk(job):
    """Отрендерить кусок кадров в полном качестве и закодировать в отдельный mp4."""
    from . import kit
    out = job['out']
    cmd = [job['ffmpeg'], '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', '%dx%d' % (kit.W, kit.H), '-r', str(job['fps']), '-i', '-',
           '-c:v', 'libx264', '-preset', job.get('preset', 'medium'), '-crf', str(job.get('crf', 18)),
           '-pix_fmt', 'yuv420p', out]
    log = open(out + '.log', 'w')
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
    err = None
    cancelled = False
    try:
        for i, fr_task in enumerate(job['frames']):
            if i % 5 == 0 and os.path.exists(job['cancel_flag']):
                cancelled = True
                break
            sc = job['scenes'][fr_task['sid']]
            task = dict(sc, look=job['look'], texts=job['texts'], fonts=job['fonts'],
                        t=fr_task['t'], lfi=fr_task['lfi'])
            fr, used, newd, e, assets = render_one(task)
            if e and not err:
                err = '%s\n%s' % (sc['name'], e)
            p.stdin.write(fr.tobytes())
    except (BrokenPipeError, OSError) as e:
        err = err or 'ffmpeg остановился: %s' % e
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
        p.wait()
        log.close()
    if p.returncode != 0 and not cancelled and not err:
        try:
            with open(out + '.log', 'r', errors='replace') as f:
                err = 'ffmpeg: ' + f.read()[-600:]
        except OSError:
            err = 'ffmpeg завершился с ошибкой %s' % p.returncode
    return out, err, cancelled


# =====================================================================================
#  helpers for the main process
# =====================================================================================
def slug(s):
    s = re.sub(r'[^A-Za-z0-9]+', '_', str(s).lower()).strip('_')
    return s[:28] or 'scene'


def static_meta(code):
    """Данные сцены без выполнения кода: докстрока, HITS, AMBIENCE, WIND, синтаксис."""
    meta = dict(hits=[], amb=None, wind=None, doc='', dynamic=False, err=None, line=None)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        meta['err'] = '%s (строка %s)' % (e.msg, e.lineno)
        meta['line'] = e.lineno
        return meta
    meta['doc'] = ((ast.get_docstring(tree) or '').strip().splitlines() or [''])[0]
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm not in ('HITS', 'AMBIENCE', 'WIND'):
                continue
            try:
                v = ast.literal_eval(node.value)
            except Exception:
                meta['dynamic'] = True
                continue
            if nm == 'HITS':
                try:
                    meta['hits'] = [float(x) for x in (v or [])]
                except (TypeError, ValueError):
                    meta['hits'] = []
            else:
                meta['amb' if nm == 'AMBIENCE' else 'wind'] = _level(v)
    return meta


def _level(v):
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return (float(v), float(v))
        a, b = v
        return (float(a), float(b))
    except (TypeError, ValueError):
        return None


def _num(v, d, lo, hi):
    try:
        v = float(v)
        if not math.isfinite(v):
            return d
    except (TypeError, ValueError):
        return d
    return max(lo, min(hi, v))


TEMPLATES = {
    'title': '''"""Титр: крупная надпись на тёмном фоне."""
from studio.kit import *

HITS = [0.0]            # удары (тряска + вспышка), секунды от начала сцены
AMBIENCE = (0.6, 0.6)   # громкость фонового гула в начале и в конце сцены (0..1)
WIND = (0.1, 0.1)       # громкость ветра


def render(fr, t, dur):
    darkbg(fr, (12, 13, 16))
    dust(fr, t, amt=0.3)
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
    'layers': '''"""Сцена из слоёв: видео, картинки и тексты настраиваются во вкладке «Слои»."""
from studio.kit import *

HITS = []
AMBIENCE = None
WIND = None


def render(fr, t, dur):
    # слои «под кодом» уже нарисованы в fr, слои «над кодом» лягут сверху.
    # Здесь можно добавить что-то своё, например: dust(fr, t, amt=0.3)
    pass


def sound(a, dur):
    pass
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


# =====================================================================================
#  main process
# =====================================================================================
class Studio:
    def __init__(self, project_dir, workers=None):
        self.dir = os.path.abspath(project_dir)
        self.pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.lock = threading.RLock()
        self._io_lock = threading.Lock()
        self.cache = {}          # (sid, lfi) -> (gen, jpeg)
        self.inflight = {}       # (sid, lfi, gen) -> future
        self.gen = {}            # sid -> int
        self.errors = {}         # sid -> str
        self.used = {}           # sid -> set(text keys)
        self.assets_used = {}    # sid -> set(asset names)
        self.meta = {}           # sid -> dict(hash, hits, amb, wind, doc, err)
        self.codes = {}          # sid -> code text
        self.hung = {}           # sid -> (code hash, сообщение) — сцена зависла, не пересчитывать
        self._watch = {}         # future -> (время отправки, вид, sid)
        self._virtual = {}       # кэш кадров для превью библиотеки / проверки кода
        self.playhead = 0
        self.export_state = {'state': 'idle'}
        self.audio_ver = 0
        self.audio_state = 'idle'
        self.audio_peaks = []
        self.audio_peaks_rate = 1
        self.save_error = None
        self._stems = {}
        self._audio_dirty = threading.Event()
        self._music = None
        self._save_timer = None
        self.running = True
        self.ffmpeg = ffmpeg_exe()
        self.load()
        from . import kit
        kit.PROJECT = self.dir
        kit.ASSET_DIRS = [os.path.join(self.dir, 'assets')]
        kit.FONT_DIRS = [os.path.join(self.dir, 'fonts')]
        n = workers or max(1, min((os.cpu_count() or 2) - 1, 6))
        self.nworkers = n
        self.pool = self._new_pool()
        threading.Thread(target=self._scheduler, daemon=True).start()
        threading.Thread(target=self._audio_loop, daemon=True).start()
        self._audio_dirty.set()

    # ------------------------------------------------------------------ pool
    def _new_pool(self):
        return ProcessPoolExecutor(self.nworkers, mp_context=mp.get_context('spawn'), initializer=_winit,
                                   initargs=(self.dir, self.pkg_parent))

    def submit(self, fn, arg, kind='preview', sid=None):
        """Отправить задачу в пул; если пул сломан (упал процесс) — пересоздать его."""
        if not self.running:
            raise RuntimeError('Студия остановлена')
        with self.lock:
            try:
                fut = self.pool.submit(fn, arg)
            except (BrokenProcessPool, RuntimeError):
                self._restart_pool('пул рендера был сломан')
                fut = self.pool.submit(fn, arg)
            self._watch[fut] = (time.time(), kind, sid)
        fut.add_done_callback(lambda f: self._watch.pop(f, None))
        return fut

    def _restart_pool(self, reason=''):
        with self.lock:
            old = self.pool
            self.pool = self._new_pool()
            self.inflight.clear()
            self._watch = {}
        print('  Перезапуск процессов рендера: %s' % reason)
        procs = list((getattr(old, '_processes', None) or {}).values())
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        try:
            old.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            old.shutdown(wait=False)
        except Exception:
            pass

    def _watchdog(self):
        if self.export_state.get('state') == 'running':
            return
        now = time.time()
        with self.lock:
            stuck = [(f, v) for f, v in self._watch.items() if not f.done() and now - v[0] > HANG_SECONDS]
        if not stuck:
            return
        for f, (t0, kind, sid) in stuck:
            if sid and sid in self.meta:
                msg = ('Сцена считается дольше %d секунд и была остановлена.\n'
                       'Возможно, в коде бесконечный цикл или слишком тяжёлые вычисления.\n'
                       'Исправьте код — сцена пересчитается.' % HANG_SECONDS)
                with self.lock:
                    self.hung[sid] = (self.meta[sid]['hash'], msg)
                    self.errors[sid] = msg
        self._restart_pool('сцена зависла')

    # ------------------------------------------------------------------ project io
    @property
    def pj(self):
        return os.path.join(self.dir, 'project.json')

    def load(self):
        with open(self.pj, 'r', encoding='utf-8') as f:
            p = json.load(f)
        p.setdefault('title', 'Project')
        p.setdefault('fps', 30)
        p.setdefault('look', {})
        p.setdefault('audio', {})
        p.setdefault('texts', {})
        p.setdefault('fonts', {})
        p.setdefault('scenes', [])
        from . import fx, layers
        for s in p['scenes']:
            s['layers'] = [x for x in (layers.clean(L) for L in s.get('layers', [])) if x]
            s['fx'] = [x for x in (fx.clean(e) for e in s.get('fx', [])) if x]
        with self.lock:
            self.p = p
            for s in p['scenes']:
                self._read_code(s)

    def reload(self):
        """Перечитать проект с диска (после восстановления версии)."""
        with self.lock:
            old_ids = list(self.gen)
            self.load()
            for sid in set(old_ids) | {s['id'] for s in self.p['scenes']}:
                self.gen[sid] = self.gen.get(sid, 0) + 1
            self.cache.clear()
            self.inflight.clear()
            self.hung.clear()
            self._stems.clear()
            self.used.clear()
        self._audio_dirty.set()

    def save(self, now=False):
        with self.lock:
            if self._save_timer:
                self._save_timer.cancel()
                self._save_timer = None
            if not now:
                self._save_timer = threading.Timer(0.4, self._write)
                self._save_timer.daemon = True
                self._save_timer.start()
                return
        self._write()

    def _write(self):
        with self.lock:
            data = json.dumps(self.p, ensure_ascii=False, indent=2)
            self._save_timer = None
        with self._io_lock:
            tmp = self.pj + '.tmp'
            err = None
            for i in range(6):
                try:
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(data)
                    os.replace(tmp, self.pj)      # Windows: файл может быть занят антивирусом — повторить
                    err = None
                    break
                except OSError as e:
                    err = e
                    time.sleep(0.15 * (i + 1))
            self.save_error = None if err is None else 'Не удалось сохранить project.json: %s' % err
            if err:
                print('  ' + self.save_error)

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
        """Запомнить код и его данные. Код НЕ выполняется здесь — только разбирается."""
        sid = s['id']
        old = self.codes.get(sid)
        self.codes[sid] = code
        meta = static_meta(code)
        meta['hash'] = code_hash(code)
        self.meta[sid] = meta
        if meta['err']:
            self.errors[sid] = meta['err']
        else:
            self.errors.pop(sid, None)
        self.hung.pop(sid, None)
        if old != code:
            self._bump(sid)
        if meta['dynamic'] and not meta['err']:
            fut = self.submit(w_meta, dict(path=self.scene_path(s), code=code), 'meta', sid)
            h = meta['hash']

            def done(f, sid=sid, h=h):
                try:
                    r = f.result()
                except Exception:
                    return
                with self.lock:
                    m = self.meta.get(sid)
                    if not m or m['hash'] != h:
                        return
                    m['hits'] = r['hits']
                    m['amb'] = _level(r['amb'])
                    m['wind'] = _level(r['wind'])
                    if r['err']:
                        m['err'] = r['err']
                        self.errors[sid] = r['err']
                self._audio_dirty.set()
            fut.add_done_callback(done)

    def _bump(self, sid):
        """Новое поколение сцены: старые кадры больше не годятся."""
        self.gen[sid] = self.gen.get(sid, 0) + 1
        for k in [k for k in self.cache if k[0] == sid]:
            del self.cache[k]
        for k in [k for k in self.inflight if k[0] == sid]:
            self.inflight.pop(k).cancel()

    def scene(self, sid):
        for s in self.p['scenes']:
            if s['id'] == sid:
                return s
        raise KeyError(sid)

    # ------------------------------------------------------------------ timeline
    def timeline(self):
        with self.lock:
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

    def _layers_view(self, s):
        out = []
        for L in s.get('layers', []):
            L = dict(L)
            if L['type'] == 'text':
                L['text'] = self.p['texts'].get(L.get('key'), '')
            out.append(L)
        return out

    def state(self):
        tl, total = self.timeline()
        with self.lock:
            fps = self.p['fps']
            scenes = []
            for s, f0, n in tl:
                m = self.meta.get(s['id'], {})
                scenes.append(dict(id=s['id'], name=s['name'], file=s['file'], dur=s['dur'], f0=f0, n=n,
                                   hits=m.get('hits', []), doc=m.get('doc', ''), gen=self.gen.get(s['id'], 0),
                                   error=self.errors.get(s['id']), used=sorted(self.used.get(s['id'], [])),
                                   layers=self._layers_view(s), fx=copy.deepcopy(s.get('fx', [])),
                                   assets=sorted(self.assets_used.get(s['id'], []))))
            return dict(title=self.p.get('title', 'Project'), fps=fps, total=total, scenes=scenes,
                        texts=dict(self.p['texts']), look=dict(self.p['look']), audio=dict(self.p['audio']),
                        fonts=self.font_roles(), audio_ver=self.audio_ver, audio_state=self.audio_state,
                        export={k: v for k, v in self.export_state.items() if k != 'flag'},
                        workers=self.nworkers, dir=self.dir, save_error=self.save_error)

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
    def font_roles(self):
        from . import kit
        r = dict(kit.DEFAULT_ROLES)
        r.update({k: v for k, v in self.p.get('fonts', {}).items() if v})
        return r

    def _task(self, s, lfi):
        fps = self.p['fps']
        return dict(path=self.scene_path(s), code=self.codes[s['id']], t=lfi / fps, dur=float(s['dur']),
                    lfi=lfi, look=dict(self.p['look']), texts=dict(self.p['texts']),
                    layers=copy.deepcopy(s.get('layers', [])), fx=copy.deepcopy(s.get('fx', [])),
                    fonts=self.font_roles(), asset_dirs=[os.path.join(self.dir, 'assets')],
                    font_dirs=[os.path.join(self.dir, 'fonts')])

    def _submit(self, s, lfi):
        sid = s['id']
        with self.lock:
            g = self.gen.get(sid, 0)
            key = (sid, lfi, g)
            fut = self.inflight.get(key)
            if fut is not None:
                return fut
            fut = self.submit(w_preview, self._task(s, lfi), 'preview', sid)
            self.inflight[key] = fut

        def done(f, key=key):
            with self.lock:
                if self.inflight.get(key) is f:
                    self.inflight.pop(key, None)
                try:
                    jpg, used, newd, err, assets = f.result()
                except Exception:
                    return
                sid_, lfi_, g_ = key
                if self.gen.get(sid_, 0) != g_:
                    return
                self.cache[(sid_, lfi_)] = (g_, jpg)
                self.used.setdefault(sid_, set()).update(used)
                self.assets_used.setdefault(sid_, set()).update(assets)
                if err:
                    self.errors[sid_] = err
                elif not self.meta.get(sid_, {}).get('err') and sid_ not in self.hung:
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

    def _hung_frame(self, sid):
        h = self.hung.get(sid)
        if not h:
            return None
        key = ('hung', sid, h[0])
        j = self._virtual.get(key)
        if j is None:
            j = self._virtual[key] = _jpeg(_error_frame(h[1], title='СЦЕНА ЗАВИСЛА'))
        return j

    def frame_sl(self, sid, lfi, wait=True):
        """Кадр превью сцены sid (номер кадра внутри сцены). Возвращает (jpeg, gen) или (None, gen)."""
        with self.lock:
            s = self.scene(sid)
            fps = self.p['fps']
            n = max(1, int(round(float(s['dur']) * fps)))
            lfi = max(0, min(n - 1, int(lfi)))
            g = self.gen.get(sid, 0)
            c = self.cache.get((sid, lfi))
            if c and c[0] == g:
                return c[1], g
            hj = self._hung_frame(sid)
            if hj is not None and self.hung[sid][0] == self.meta[sid]['hash']:
                return hj, g
        if not wait:
            return None, g
        fut = self._submit(s, lfi)
        try:
            jpg = fut.result(timeout=HANG_SECONDS + 10)[0]
        except Exception:
            return self._hung_frame(sid), g
        return jpg, g

    def frame(self, fi, wait=True):
        loc = self.locate(fi)
        if loc is None:
            return None
        s, lfi = loc
        return self.frame_sl(s['id'], lfi, wait)[0]

    def scene_thumb(self, sid):
        """Уже готовый кадр из середины сцены (для таймлайна) или None."""
        with self.lock:
            s = self.scene(sid)
            n = max(1, int(round(float(s['dur']) * self.p['fps'])))
            g = self.gen.get(sid, 0)
            for d in range(0, n):
                for l in (n // 2 + d, n // 2 - d):
                    c = self.cache.get((sid, l))
                    if c and c[0] == g:
                        return c[1]
        return None

    def _scheduler(self):
        last_wd = 0
        while self.running:
            time.sleep(0.03)
            if time.time() - last_wd > 1:
                last_wd = time.time()
                try:
                    self._watchdog()
                except Exception:
                    traceback.print_exc()
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
                starts = [x[1] for x in tl]
                for fi in order:
                    if busy >= limit:
                        break
                    i = bisect.bisect_right(starts, fi) - 1
                    s, f0, n = tl[i]
                    lfi = fi - f0
                    with self.lock:
                        if s['id'] not in self.gen:
                            continue
                        g = self.gen.get(s['id'], 0)
                        h = self.hung.get(s['id'])
                        if h and h[0] == self.meta[s['id']]['hash']:
                            continue
                        c = self.cache.get((s['id'], lfi))
                        if (c and c[0] == g) or (s['id'], lfi, g) in self.inflight:
                            continue
                    self._submit(s, lfi)
                    busy += 1
                if len(self.cache) > MAX_CACHE:
                    self._evict(tl, ph)
            except Exception:
                if not self.running:
                    break
                traceback.print_exc()
                time.sleep(0.5)

    def _evict(self, tl, ph):
        """Убрать кадры, дальше всего отстоящие от курсора."""
        f0 = {s['id']: a for s, a, n in tl}
        with self.lock:
            keys = list(self.cache.keys())
            keys.sort(key=lambda k: -abs(f0.get(k[0], -10 ** 9) + k[1] - ph))
            for k in keys[:len(keys) - int(MAX_CACHE * 0.8)]:
                self.cache.pop(k, None)

    def invalidate(self, sids=None):
        with self.lock:
            for s in self.p['scenes']:
                if sids is None or s['id'] in sids:
                    self._bump(s['id'])

    def invalidate_asset(self, name):
        """Картинка/видео заменены: пересчитать сцены, которые их используют (или ещё не считались)."""
        with self.lock:
            hit = []
            for s in self.p['scenes']:
                sid = s['id']
                uses = name in self.assets_used.get(sid, set()) or any(L.get('src') == name for L in s.get('layers', []))
                if uses or sid not in self.assets_used or name in self.codes.get(sid, ''):
                    hit.append(sid)
            self.invalidate(hit)
        self._audio_dirty.set()

    # ------------------------------------------------------------------ virtual renders (library, AI check)
    def render_virtual(self, key, task, timeout=60):
        """Кадр для сцены вне проекта (превью библиотеки). Кэшируется по key."""
        with self.lock:
            j = self._virtual.get(key)
            if j is not None:
                return j
        fut = self.submit(w_preview, task, 'virtual')
        jpg = fut.result(timeout=timeout)[0]
        with self.lock:
            self._virtual[key] = jpg
            while len(self._virtual) > 400:
                self._virtual.pop(next(iter(self._virtual)))
        return jpg

    def base_task(self):
        with self.lock:
            return dict(look=dict(self.p['look']), texts=dict(self.p['texts']), fonts=self.font_roles(),
                        asset_dirs=[os.path.join(self.dir, 'assets')], font_dirs=[os.path.join(self.dir, 'fonts')],
                        layers=[], fx=[])

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
        code = str(code)
        with self.lock:
            s = self.scene(sid)
            if code != self.codes.get(sid):
                self._backup(s)
            with open(self.scene_path(s), 'w', encoding='utf-8', newline='\n') as f:
                f.write(code)
            self._set_code(s, code)
            m = self.meta[sid]
            syntax = dict(line=m['line'], msg=m['err']) if m.get('line') else None
            res = dict(ok=not m['err'], syntax=syntax, error=m['err'], gen=self.gen[sid])
        self._audio_dirty.set()
        return res

    def _text_key(self, sid, lid):
        return '%s_%s' % (sid, lid)

    def _clean_layers(self, sid, layers_in, texts_out):
        from . import layers
        out = []
        for L in layers_in or []:
            c = layers.clean(L)
            if not c:
                continue
            if not c['id']:
                c['id'] = 'L' + uuid.uuid4().hex[:5]
            if c['type'] == 'text':
                if not c.get('key'):
                    c['key'] = self._text_key(sid, c['id'])
                if 'text' in L:
                    texts_out[c['key']] = str(L['text'])[:2000]
            out.append(c)
        return out[:40]

    def update_scene(self, sid, name=None, dur=None, layers=None, fx=None):
        from . import fx as fxm
        changed_texts = {}
        with self.lock:
            s = self.scene(sid)
            bump = False
            if name is not None:
                s['name'] = str(name)[:60]
            if dur is not None:
                d = round(_num(dur, s['dur'], 0.2, 600.0), 3)
                if d != s['dur']:
                    s['dur'] = d
                    bump = True        # сцены часто используют dur в расчётах
            if layers is not None:
                s['layers'] = self._clean_layers(sid, layers, changed_texts)
                bump = True
            if fx is not None:
                s['fx'] = [x for x in (fxm.clean(e) for e in fx) if x][:30]
                bump = True
            if bump:
                self._bump(sid)
        if changed_texts:
            self.set_texts(changed_texts, save=False)
        if bump:
            self._audio_dirty.set()
        self.save()

    def add_scene(self, after=None, template='image', name='New scene', code=None, dur=3.0, layers=None, fx=None,
                  texts=None, index=None):
        from . import fx as fxm
        name = str(name or 'New scene')[:60]
        sid = 's' + uuid.uuid4().hex[:6]
        base = slug(name)
        with self.lock:
            fn = base + '.py'
            i = 2
            while os.path.exists(os.path.join(self.dir, 'scenes', fn)):
                fn = '%s_%d.py' % (base, i)
                i += 1
            if code is None:
                code = TEMPLATES.get(template, TEMPLATES['empty']).replace('{key}', base if base != 'new_scene' else sid)
            os.makedirs(os.path.join(self.dir, 'scenes'), exist_ok=True)
            with open(os.path.join(self.dir, 'scenes', fn), 'w', encoding='utf-8', newline='\n') as f:
                f.write(code)
            new_texts = dict(texts or {})
            s = dict(id=sid, file=fn, name=name, dur=round(_num(dur, 3.0, 0.2, 600.0), 3), layers=[], fx=[])
            s['layers'] = self._clean_layers(sid, layers, new_texts)
            s['fx'] = [x for x in (fxm.clean(e) for e in (fx or [])) if x]
            idx = len(self.p['scenes'])
            if index is not None:
                idx = max(0, min(idx, int(index)))
            elif after:
                for k, x in enumerate(self.p['scenes']):
                    if x['id'] == after:
                        idx = k + 1
            self.p['scenes'].insert(idx, s)
            for k, v in new_texts.items():
                if k not in self.p['texts'] or (layers and any(L.get('key') == k for L in s['layers'])):
                    self.p['texts'][k] = v
            self._set_code(s, code)
        self._audio_dirty.set()
        self.save()
        return sid

    def duplicate_scene(self, sid):
        with self.lock:
            s = self.scene(sid)
            nid_layers = copy.deepcopy(s.get('layers', []))
            texts = {}
            for L in nid_layers:
                L['id'] = ''
                if L['type'] == 'text':
                    L['text'] = self.p['texts'].get(L.get('key'), '')
                    L['key'] = ''
            code = self.codes[sid]
            idx = self.p['scenes'].index(s) + 1
            name, dur, fxl = s['name'] + ' copy', s['dur'], copy.deepcopy(s.get('fx', []))
        return self.add_scene(name=name, code=code, dur=dur, layers=nid_layers, fx=fxl, texts=texts, index=idx)

    def delete_scene(self, sid):
        with self.lock:
            s = self.scene(sid)
            trash = os.path.join(self.dir, 'scenes', '_trash')
            os.makedirs(trash, exist_ok=True)
            src = self.scene_path(s)
            if os.path.exists(src):
                dst = os.path.join(trash, datetime.datetime.now().strftime('%Y%m%d-%H%M%S_') + s['file'])
                shutil.move(src, dst)
                with open(dst[:-3] + '.json', 'w', encoding='utf-8') as f:   # слои и эффекты — чтобы можно было вернуть
                    json.dump(s, f, ensure_ascii=False, indent=2)
            self.p['scenes'].remove(s)
            self._bump(sid)
            for d in (self.gen, self.codes, self.meta, self.used, self.assets_used, self.errors, self.hung, self._stems):
                d.pop(sid, None)
        self._audio_dirty.set()
        self.save()

    def move_scene(self, sid, index):
        with self.lock:
            s = self.scene(sid)
            self.p['scenes'].remove(s)
            index = max(0, min(len(self.p['scenes']), int(index)))
            self.p['scenes'].insert(index, s)
        self._audio_dirty.set()
        self.save()

    def set_texts(self, changes, save=True):
        affected = set()
        with self.lock:
            for k, v in changes.items():
                k = str(k)[:80]
                v = str(v)[:2000]
                if self.p['texts'].get(k) != v:
                    self.p['texts'][k] = v
                    for sid, used in self.used.items():
                        if k in used:
                            affected.add(sid)
                    for s in self.p['scenes']:            # сцены, которые ещё не рендерились, и текстовые слои
                        if s['id'] not in self.used or any(L.get('key') == k for L in s.get('layers', [])):
                            affected.add(s['id'])
            if affected:
                self.invalidate(affected)
        if save:
            self.save()
        return sorted(affected)

    def set_look(self, look):
        with self.lock:
            L = self.p['look']
            for k in ('letterbox', 'vignette', 'hits'):
                if k in look:
                    L[k] = bool(look[k])
            if 'grain' in look:
                L['grain'] = _num(look['grain'], 0.07, 0.0, 0.5)
            self.invalidate()
        self.save()

    def set_audio(self, audio):
        with self.lock:
            A = self.p['audio']
            if 'generated' in audio:
                A['generated'] = bool(audio['generated'])
            for k, d, lo, hi in (('generated_volume', 1.0, 0, 3), ('music_volume', 0.8, 0, 3),
                                 ('music_offset', 0.0, -3600, 3600), ('fade_out', 1.5, 0, 30)):
                if k in audio:
                    A[k] = _num(audio[k], d, lo, hi)
            if 'music_file' in audio:
                fn = audio['music_file']
                if fn:
                    fn = os.path.basename(str(fn))
                    if not os.path.isfile(os.path.join(self.dir, 'audio', fn)):
                        raise ValueError('Файл музыки не найден: %s' % fn)
                A['music_file'] = fn or None
        self._audio_dirty.set()
        self.save()

    def set_project(self, title=None, fps=None):
        with self.lock:
            if title is not None:
                self.p['title'] = str(title)[:80]
            if fps is not None and int(fps) in (24, 25, 30, 50, 60) and int(fps) != self.p['fps']:
                self.p['fps'] = int(fps)
                self.cache.clear()
                self.invalidate()
                self._audio_dirty.set()
        self.save()

    def set_fonts(self, roles):
        with self.lock:
            F = self.p.setdefault('fonts', {})
            for k in ('title', 'serif', 'text'):
                if k in roles:
                    v = os.path.splitext(os.path.basename(str(roles[k] or '')))[0]
                    if v and not any(os.path.isfile(os.path.join(self.dir, 'fonts', v + e)) for e in ('.ttf', '.otf', '.TTF', '.OTF')):
                        raise ValueError('Шрифт не найден: %s' % v)
                    F[k] = v or None
            self.invalidate()
        self.save()

    # ------------------------------------------------------------------ audio
    def _stems_for(self, tl):
        """Звук всех сцен (считается в процессах рендера, параллельно)."""
        need = []
        with self.lock:
            for s, f0, n in tl:
                sid = s['id']
                key = (self.meta.get(sid, {}).get('hash'), float(s['dur']))
                c = self._stems.get(sid)
                if not (c and c[0] == key):
                    task = dict(path=self.scene_path(s), code=self.codes[sid], dur=float(s['dur']),
                                seed=int(hashlib.md5(sid.encode()).hexdigest()[:6], 16))
                    need.append((sid, key, self.submit(w_sound, task, 'sound', sid)))
        for sid, key, fut in need:
            try:
                L, R, WET, err = fut.result(timeout=HANG_SECONDS + 15)
            except Exception:
                L = R = WET = None
                err = 'Звук сцены не посчитался (сцена зависла или упала).'
            if L is None:
                from .sound import TAIL
                with self.lock:
                    try:
                        dur = float(self.scene(sid)['dur'])
                    except KeyError:
                        continue
                m = int((dur + TAIL) * SR)
                L = R = WET = np.zeros(m, np.float32)
            with self.lock:
                self._stems[sid] = (key, (L, R, WET))
                if err:
                    self.errors[sid] = err
        with self.lock:
            return {s['id']: self._stems[s['id']][1] for s, f0, n in tl if s['id'] in self._stems}

    def _music_track(self, n):
        a = self.p['audio']
        fn = a.get('music_file')
        if not fn:
            return None
        path = os.path.join(self.dir, 'audio', os.path.basename(fn))
        if not os.path.isfile(path):
            return None
        m = self.music_samples(path)
        off = int(float(a.get('music_offset', 0)) * SR)
        out = np.zeros((n, 2))
        if off >= 0:
            src = m[:max(0, n - off)]
            out[off:off + len(src)] = src
        else:
            src = m[-off:-off + n]
            out[:len(src)] = src
        return out

    def music_samples(self, path):
        key = (path, os.path.getmtime(path))
        if not self._music or self._music[0] != key:
            cmd = [self.ffmpeg, '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-']
            raw = subprocess.run(cmd, capture_output=True).stdout
            m = np.frombuffer(raw[:len(raw) // 8 * 8], np.float32).reshape(-1, 2).astype(np.float64)
            self._music = (key, m)
        return self._music[1]

    def _video_audio(self, tl, fps, N):
        """Звук из видеослоёв, у которых громкость больше нуля."""
        from . import media
        out = None
        for s, f0, n in tl:
            for L in s.get('layers', []):
                if L.get('type') != 'video' or L.get('hidden') or float(L.get('volume') or 0) <= 0:
                    continue
                if abs(float(L.get('speed', 1)) - 1) > 1e-3:
                    continue
                path = self.asset_path(L.get('src', ''), VIDEO_EXT)
                if not path:
                    continue
                dur = float(s['dur'])
                t0 = float(L.get('start') or 0)
                t1 = dur if L.get('end') is None else min(dur, float(L['end']))
                if t1 <= t0:
                    continue
                a = media.audio(self.ffmpeg, path, float(L.get('trim') or 0), t1 - t0, SR).copy()
                k = len(a)
                env = np.ones(k)
                fi, fo = int(float(L.get('fade_in') or 0) * SR), int(float(L.get('fade_out') or 0) * SR)
                if fi > 0:
                    env[:min(k, fi)] = np.linspace(0, 1, min(k, fi))
                if fo > 0:
                    env[max(0, k - fo):] *= np.linspace(1, 0, k - max(0, k - fo))
                a *= (env * float(L['volume']) * float(L.get('opacity', 1)))[:, None]
                i = int((f0 / fps + t0) * SR)
                j = min(N, i + k)
                if j <= i:
                    continue
                if out is None:
                    out = np.zeros((N, 2))
                out[i:j] += a[:j - i]
        return out

    def mix_audio(self):
        from .sound import lp, TAIL
        from scipy.signal import fftconvolve
        tl, total = self.timeline()
        with self.lock:
            fps = self.p['fps']
            acfg = dict(self.p['audio'])
            tl = [(copy.deepcopy(s), f0, n) for s, f0, n in tl]
            metas = {s['id']: dict(self.meta.get(s['id'], {})) for s, f0, n in tl}
        dur = total / fps
        N = int(dur * SR)
        M = N + int(TAIL * SR)
        L = np.zeros(M); R = np.zeros(M); WET = np.zeros(M)
        gen_on = acfg.get('generated', True)
        if gen_on and N > 0:
            stems = self._stems_for(tl)
            for s, f0, n in tl:
                st = stems.get(s['id'])
                if st is None:
                    continue
                sl, sr, sw = st
                i = int(f0 / fps * SR)
                j = min(M, i + len(sl))
                L[i:j] += sl[:j - i]; R[i:j] += sr[:j - i]; WET[i:j] += sw[:j - i]
            # ambience automation
            pts_a, pts_w = [], []
            prev_a, prev_w = 0.4, 0.3
            for s, f0, n in tl:
                m = metas.get(s['id'], {})
                t0, t1 = f0 / fps, (f0 + n) / fps
                aa = m.get('amb') or (prev_a, prev_a)
                ww = m.get('wind') or (prev_w, prev_w)
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
        mix *= float(acfg.get('generated_volume', 1.0))
        extra = False
        mus = self._music_track(N)
        if mus is not None:
            mix = mix + mus * float(acfg.get('music_volume', 0.8))
            extra = True
        with self.lock:
            vtl = [(s, f0, n) for s, f0, n in tl]
        va = self._video_audio(vtl, fps, N)
        if va is not None:
            mix = mix + va
            extra = True
        if extra:
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
            if self.export_state.get('state') == 'running':
                self._audio_dirty.set()        # звук для превью — после экспорта
                time.sleep(1)
                continue
            self.audio_state = 'mixing'
            try:
                mix = self.mix_audio()
                cdir = os.path.join(self.dir, '.cache')
                os.makedirs(cdir, exist_ok=True)
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

    # ------------------------------------------------------------------ assets
    def asset_path(self, name, exts=IMG_EXT + VIDEO_EXT):
        name = os.path.basename(str(name or ''))
        if not name:
            return None
        d = os.path.join(self.dir, 'assets')
        for ext in ('',) + tuple(exts):
            p = os.path.join(d, name + ext)
            if os.path.isfile(p):
                return p
        return None

    # ------------------------------------------------------------------ export
    def export(self, crf=18):
        crf = int(_num(crf, 18, 12, 35))
        with self.lock:
            if self.export_state.get('state') == 'running':
                return False
            st = dict(state='running', progress=0.0, msg='Подготовка…', cancel=False, started=time.time())
            self.export_state = st
        threading.Thread(target=self._export, args=(crf, st), daemon=True).start()
        return True

    def cancel_export(self):
        st = self.export_state
        if st.get('state') == 'running':
            st['cancel'] = True
            flag = st.get('flag')
            if flag:
                try:
                    open(flag, 'w').close()
                except OSError:
                    pass

    def _export(self, crf, st):
        tmpd = os.path.join(self.dir, '.cache', 'export_' + uuid.uuid4().hex[:8])
        st['flag'] = os.path.join(tmpd, 'CANCEL')
        try:
            os.makedirs(tmpd, exist_ok=True)
            os.makedirs(os.path.join(self.dir, 'exports'), exist_ok=True)
            try:
                from . import versions
                versions.create(self, 'Перед экспортом', auto=True)
            except Exception:
                traceback.print_exc()
            # подождать, пока закончатся текущие кадры превью
            t0 = time.time()
            while self.inflight and time.time() - t0 < 20:
                time.sleep(0.1)
            st['msg'] = 'Звук…'
            mix = self.mix_audio()           # звук сцен считается в пуле — до кадров
            tl, total = self.timeline()
            with self.lock:
                fps = self.p['fps']
                scenes = {}
                for s, _, _ in tl:
                    scenes[s['id']] = dict(path=self.scene_path(s), code=self.codes[s['id']], dur=float(s['dur']),
                                           name=s['name'], layers=copy.deepcopy(s.get('layers', [])),
                                           fx=copy.deepcopy(s.get('fx', [])),
                                           asset_dirs=[os.path.join(self.dir, 'assets')],
                                           font_dirs=[os.path.join(self.dir, 'fonts')])
                look, texts, fonts = dict(self.p['look']), dict(self.p['texts']), self.font_roles()
                title = self.p.get('title', 'video')
            frames = []
            for s, f0, n in tl:
                for l in range(n):
                    frames.append(dict(sid=s['id'], t=l / fps, lfi=l))
            if not frames:
                raise RuntimeError('В проекте нет сцен')
            chunk = 45
            jobs = []
            for ci, a in enumerate(range(0, total, chunk)):
                part = frames[a:a + chunk]
                need = {f['sid'] for f in part}
                jobs.append(dict(out=os.path.join(tmpd, 'seg%05d.mp4' % ci), frames=part, fps=fps, ffmpeg=self.ffmpeg,
                                 crf=crf, look=look, texts=texts, fonts=fonts, cancel_flag=st['flag'],
                                 scenes={k: v for k, v in scenes.items() if k in need}))
            st['msg'] = 'Рендер кадров…'
            futs = [self.submit(w_chunk, j, 'export') for j in jobs]
            done = 0
            errs = []
            for fu, j in zip(futs, jobs):
                while not fu.done():
                    time.sleep(0.1)
                    if st.get('cancel'):
                        for f2 in futs:
                            f2.cancel()
                        raise RuntimeError('Экспорт отменён')
                out, err, cancelled = fu.result()
                if cancelled or st.get('cancel'):
                    raise RuntimeError('Экспорт отменён')
                if err:
                    errs.append(err)
                    st['cancel'] = True
                    open(st['flag'], 'w').close()
                    break
                done += len(j['frames'])
                st['progress'] = done / total * 0.97
                el = time.time() - st['started']
                st['eta'] = el / max(1e-6, st['progress']) * (1 - st['progress'])
            if errs:
                raise RuntimeError('В сценах есть ошибки, экспорт остановлен:\n' + errs[0])
            st['msg'] = 'Сборка файла…'
            from scipy.io import wavfile
            wav = os.path.join(tmpd, 'audio.wav')
            wavfile.write(wav, SR, (np.clip(mix, -1, 1) * 32767).astype(np.int16))
            lst = os.path.join(tmpd, 'list.txt')
            with open(lst, 'w') as f:
                for j in jobs:
                    f.write("file '%s'\n" % os.path.basename(j['out']))
            name = '%s_%s.mp4' % (slug(title), datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            out = os.path.join(self.dir, 'exports', name)
            cmd = [self.ffmpeg, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', wav, '-c:v', 'copy',
                   '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError('ffmpeg: ' + r.stderr[-800:])
            self.export_state = dict(state='done', progress=1.0, file=name, path=out,
                                     seconds=round(time.time() - st['started'], 1))
        except Exception as e:
            self.export_state = dict(state='error', msg=str(e), progress=st.get('progress', 0))
            # незавершённые куски могли остаться в пуле — если он занят, перезапустить
            if any(not f.done() for f in list(self._watch)):
                self._restart_pool('экспорт остановлен')
        finally:
            for i in range(5):                  # Windows: файлы могут быть ещё заняты ffmpeg
                shutil.rmtree(tmpd, ignore_errors=True)
                if not os.path.exists(tmpd):
                    break
                time.sleep(0.5)
            self._audio_dirty.set()

    def shutdown(self):
        self.running = False
        with self.lock:
            pending = self._save_timer is not None
        if pending:
            self.save(now=True)
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.pool.shutdown(wait=False)
