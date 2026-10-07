"""Чтение видеофайлов покадрово (в процессах рендера) и звука из них (в основном процессе)."""
import os
import subprocess
from collections import OrderedDict

import cv2
import numpy as np

VIDEO_EXT = ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi')
MAX_W = 1920          # кадры больше Full HD сразу уменьшаются — рендер всё равно 1920x1080


def _short_path(path):
    """Windows: короткое имя файла (8.3) — только латиница, если такие имена включены на диске."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
        return buf.value if 0 < n < 1024 else None
    except Exception:
        return None


def _ascii_alias(path):
    """Windows: ссылка/копия видео в папке с латинским путём (C:\\Users\\Public\\ShelterStudio)."""
    import hashlib
    import shutil
    key = hashlib.sha1(('%s|%s' % (path, os.path.getmtime(path))).encode('utf-8')).hexdigest()[:16]
    ext = os.path.splitext(path)[1].lower()
    for base in (os.environ.get('PUBLIC', ''), os.path.splitdrive(path)[0] + os.sep):
        if not base or not base.isascii():
            continue
        d = os.path.join(base, 'ShelterStudio', 'video_cache')
        dst = os.path.join(d, key + ext)
        try:
            os.makedirs(d, exist_ok=True)
            if not os.path.isfile(dst):
                try:
                    os.link(path, dst)          # тот же диск — мгновенно и без лишнего места
                except OSError:
                    shutil.copy2(path, dst)
            return dst
        except OSError:
            continue
    return None


def open_capture(path):
    """cv2.VideoCapture с запасными путями для Windows, если в пути есть русские буквы."""
    cap = cv2.VideoCapture(path)
    if cap.isOpened() or os.name != 'nt' or path.isascii():
        return cap
    for alt in (_short_path(path), None):
        if alt is None:
            alt = _ascii_alias(path)
        if alt and alt.isascii():
            c2 = cv2.VideoCapture(alt)
            if c2.isOpened():
                return c2
    return cap


class _Reader:
    """Последовательное чтение с дешёвыми шагами вперёд и перемоткой назад."""

    def __init__(self, path):
        self.path = path
        self.cap = open_capture(path)
        if not self.cap.isOpened():
            raise IOError("Не удалось открыть видео '%s'" % os.path.basename(path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        if not (1 <= self.fps <= 240):
            self.fps = 30.0
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.pos = 0
        self.recent = OrderedDict()

    def frame(self, idx):
        if self.n > 0:
            idx = max(0, min(self.n - 1, idx))
        f = self.recent.get(idx)
        if f is not None:
            self.recent.move_to_end(idx)
            return f
        if idx < self.pos or idx - self.pos > 48:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            self.pos = idx
        while self.pos < idx:
            if not self.cap.grab():
                break
            self.pos += 1
        ok, bgr = self.cap.read()
        if not ok or bgr is None:
            # счётчик кадров у некоторых файлов завышен — вернуть последний удачный кадр
            if self.recent:
                return next(reversed(self.recent.values()))
            return np.zeros((1080, 1920, 3), np.uint8)
        self.pos += 1
        h, w = bgr.shape[:2]
        if w > MAX_W:
            bgr = cv2.resize(bgr, (MAX_W, int(h * MAX_W / w)), interpolation=cv2.INTER_AREA)
        f = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.recent[idx] = f
        if len(self.recent) > 6:
            self.recent.popitem(last=False)
        return f

    def close(self):
        try:
            self.cap.release()
        except Exception:
            pass


_READERS = OrderedDict()


def _reader(path):
    key = (path, os.path.getmtime(path))
    r = _READERS.get(key)
    if r is None:
        r = _Reader(path)
        _READERS[key] = r
        while len(_READERS) > 6:
            _READERS.popitem(last=False)[1].close()
    else:
        _READERS.move_to_end(key)
    return r


def frame_at(path, t, loop=True):
    """Кадр видео (RGB) в момент t секунд от начала файла."""
    r = _reader(path)
    idx = int(max(0.0, t) * r.fps + 1e-6)
    if r.n > 0:
        idx = idx % r.n if loop else min(idx, r.n - 1)
    return r.frame(idx)


_INFO = {}


def info(path):
    """dict(w, h, fps, frames, dur) — кэшируется по времени изменения файла."""
    key = (path, os.path.getmtime(path))
    if key not in _INFO:
        cap = open_capture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if not (1 <= fps <= 240):
            fps = 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
        _INFO[key] = dict(w=w, h=h, fps=round(fps, 3), frames=n, dur=round(n / fps, 3) if n else 0.0)
    return _INFO[key]


def thumbnail(path, t=1.0):
    """Кадр для превью в списке (BGR)."""
    cap = open_capture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if n:
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(n - 1, int(t * fps)))
    ok, bgr = cap.read()
    cap.release()
    return bgr if ok else None


_AUDIO = OrderedDict()


def audio(ffmpeg, path, start, dur, sr):
    """Звук из видео: стерео float64 длиной dur секунд (тишина, если дорожки нет)."""
    n = int(round(dur * sr))
    key = (path, os.path.getmtime(path), round(start, 3), n, sr)
    a = _AUDIO.get(key)
    if a is None:
        cmd = [ffmpeg, '-v', 'error', '-ss', '%.3f' % max(0.0, start), '-t', '%.3f' % dur, '-i', path,
               '-vn', '-f', 'f32le', '-ac', '2', '-ar', str(sr), '-']
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
        except Exception:
            raw = b''
        m = np.frombuffer(raw[:len(raw) // 8 * 8], np.float32).reshape(-1, 2).astype(np.float64)
        a = np.zeros((n, 2))
        a[:min(n, len(m))] = m[:n]
        _AUDIO[key] = a
        while len(_AUDIO) > 24:
            _AUDIO.popitem(last=False)
    return a
