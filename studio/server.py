"""Локальный веб-сервер редактора: http://127.0.0.1:8765"""
import argparse
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from .engine import Studio

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')
AUD_EXT = ('.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac')
S = None          # Studio
_THUMBS = {}


def safe_name(name, exts):
    base = os.path.basename(unquote(name or ''))
    stem, ext = os.path.splitext(base)
    stem = re.sub(r'[^\w\-]+', '_', stem, flags=re.UNICODE).strip('_') or 'file'
    ext = ext.lower()
    if ext not in exts:
        raise ValueError('Неподдерживаемый формат: %s' % ext)
    return stem + ext


def key_white(a, tol=18, feather=1.2):
    """Убрать однотонный светлый фон (заливка от краёв)."""
    h, w = a.shape[:2]
    m = np.zeros((h + 2, w + 2), np.uint8)
    b = a.copy()
    for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if a[p[1], p[0]].min() > 200:
            cv2.floodFill(b, m, p, (0, 0, 0), (tol,) * 3, (tol,) * 3, cv2.FLOODFILL_MASK_ONLY | (255 << 8) | 8)
    alpha = 1 - m[1:-1, 1:-1].astype(np.float32) / 255
    alpha = cv2.erode(alpha, np.ones((2, 2), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (0, 0), feather)
    return np.dstack([a.astype(np.float32), alpha * 255]).clip(0, 255).astype(np.uint8)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        e = sys.exc_info()[1]
        if isinstance(e, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    # ---------------- helpers
    def send(self, code=200, body=b'', ctype='application/json', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def js(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    def jbody(self):
        b = self.body()
        return json.loads(b.decode('utf-8')) if b else {}

    def file(self, path, ctype=None, download=None):
        if not os.path.isfile(path):
            return self.send(404, 'not found', 'text/plain')
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        extra = {'Accept-Ranges': 'bytes'}
        if download:
            extra['Content-Disposition'] = 'attachment; filename="%s"' % download
        start, end, code = 0, size - 1, 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(size - 1, int(m.group(2)))
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                code = 206
                extra['Content-Range'] = 'bytes %d-%d/%d' % (start, end, size)
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ---------------- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        try:
            if p == '/' or p == '/index.html':
                return self.file(os.path.join(UI, 'index.html'), 'text/html; charset=utf-8')
            if p.startswith('/ui/'):
                f = os.path.normpath(os.path.join(UI, p[4:]))
                if not f.startswith(UI):
                    return self.send(403)
                return self.file(f)
            if p == '/api/state':
                return self.js(S.state())
            if p == '/api/cache':
                return self.send(200, S.cache_map(), 'text/plain')
            if p == '/api/frame':
                jpg = S.frame(int(q.get('f', 0)), wait=q.get('nowait') != '1')
                if jpg is None:
                    return self.send(204)
                return self.send(200, jpg, 'image/jpeg')
            if p == '/api/scene':
                s = S.scene(q['id'])
                return self.js(dict(id=s['id'], file=s['file'], code=S.codes[s['id']], error=S.errors.get(s['id'])))
            if p == '/api/audio.wav':
                return self.file(S.audio_path(), 'audio/wav')
            if p == '/api/waveform':
                return self.js(dict(ver=S.audio_ver, peaks=S.audio_peaks, rate=getattr(S, 'audio_peaks_rate', 1)))
            if p == '/api/assets':
                return self.js(self.list_assets())
            if p == '/api/thumb':
                return self.thumb(q.get('name', ''))
            if p.startswith('/exports/'):
                name = os.path.basename(unquote(p[len('/exports/'):]))
                return self.file(os.path.join(S.dir, 'exports', name), 'video/mp4',
                                 download=name if q.get('dl') else None)
            return self.send(404, 'not found', 'text/plain')
        except KeyError as e:
            return self.js(dict(error='not found: %s' % e), 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.js(dict(error=str(e)), 500)

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        try:
            if p == '/api/playhead':
                S.playhead = int(self.jbody().get('f', 0))
                return self.js(dict(ok=True))
            if p == '/api/scene/save':
                b = self.jbody()
                return self.js(S.save_code(b['id'], b['code']))
            if p == '/api/scene/update':
                b = self.jbody()
                S.update_scene(b['id'], b.get('name'), b.get('dur'))
                return self.js(dict(ok=True))
            if p == '/api/scene/add':
                b = self.jbody()
                sid = S.add_scene(b.get('after'), b.get('template', 'image'), b.get('name') or 'New scene')
                return self.js(dict(ok=True, id=sid))
            if p == '/api/scene/duplicate':
                return self.js(dict(ok=True, id=S.duplicate_scene(self.jbody()['id'])))
            if p == '/api/scene/delete':
                S.delete_scene(self.jbody()['id'])
                return self.js(dict(ok=True))
            if p == '/api/scene/move':
                b = self.jbody()
                S.move_scene(b['id'], b['index'])
                return self.js(dict(ok=True))
            if p == '/api/texts':
                return self.js(dict(ok=True, affected=S.set_texts(self.jbody())))
            if p == '/api/look':
                S.set_look(self.jbody())
                return self.js(dict(ok=True))
            if p == '/api/audio':
                S.set_audio(self.jbody())
                return self.js(dict(ok=True))
            if p == '/api/project':
                b = self.jbody()
                if 'title' in b:
                    S.p['title'] = str(b['title'])[:80]
                if 'fps' in b and int(b['fps']) in (24, 25, 30, 50, 60):
                    S.p['fps'] = int(b['fps'])
                    S.cache.clear()
                    S.invalidate()
                    S._audio_dirty.set()
                S.save()
                return self.js(dict(ok=True))
            if p == '/api/assets/upload':
                name = safe_name(q.get('name'), IMG_EXT)
                data = self.body()
                d = os.path.join(S.dir, 'assets')
                os.makedirs(d, exist_ok=True)
                if q.get('cutout') == '1':
                    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if arr is None:
                        raise ValueError('Не удалось прочитать картинку')
                    rgba = key_white(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
                    name = os.path.splitext(name)[0] + '_cut.png'
                    cv2.imencode('.png', cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1].tofile(os.path.join(d, name))
                else:
                    with open(os.path.join(d, name), 'wb') as f:
                        f.write(data)
                _THUMBS.pop(os.path.splitext(name)[0], None)
                return self.js(dict(ok=True, name=os.path.splitext(name)[0]))
            if p == '/api/music/upload':
                name = safe_name(q.get('name'), AUD_EXT)
                d = os.path.join(S.dir, 'audio')
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, name), 'wb') as f:
                    f.write(self.body())
                S.set_audio(dict(music_file=name))
                return self.js(dict(ok=True, name=name))
            if p == '/api/export':
                S.export(int(self.jbody().get('crf', 18)))
                return self.js(dict(ok=True))
            if p == '/api/export/cancel':
                S.cancel_export()
                return self.js(dict(ok=True))
            if p == '/api/open':
                what = self.jbody().get('what', 'exports')
                path = os.path.join(S.dir, what if what in ('exports', 'assets', 'scenes', 'audio') else '')
                open_folder(path)
                return self.js(dict(ok=True, path=path))
            return self.send(404, 'not found', 'text/plain')
        except KeyError as e:
            return self.js(dict(error='not found: %s' % e), 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.js(dict(error=str(e)), 500)

    # ---------------- assets
    def list_assets(self):
        d = os.path.join(S.dir, 'assets')
        out = []
        for f in sorted(os.listdir(d)):
            if os.path.splitext(f)[1].lower() in IMG_EXT:
                path = os.path.join(d, f)
                name = os.path.splitext(f)[0]
                alpha = f.lower().endswith('.png') and _has_alpha(path)
                out.append(dict(name=name, file=f, alpha=alpha, mtime=os.path.getmtime(path)))
        return out

    def thumb(self, name):
        name = os.path.basename(name)
        d = os.path.join(S.dir, 'assets')
        path = None
        for ext in IMG_EXT:
            if os.path.isfile(os.path.join(d, name + ext)):
                path = os.path.join(d, name + ext)
        if not path:
            return self.send(404)
        key = (name, os.path.getmtime(path))
        if _THUMBS.get(name, (None,))[0] != key:
            im = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
            h, w = im.shape[:2]
            s = 260 / max(w, h)
            im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.png', im)
            _THUMBS[name] = (key, buf.tobytes(), w, h)
        return self.send(200, _THUMBS[name][1], 'image/png')


_ALPHA = {}


def _has_alpha(path):
    k = (path, os.path.getmtime(path))
    if k not in _ALPHA:
        try:
            with open(path, 'rb') as f:
                head = f.read(26)
            _ALPHA[k] = len(head) > 25 and head[25] in (4, 6)
        except Exception:
            _ALPHA[k] = False
    return _ALPHA[k]


def open_folder(path):
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


def free_port(start):
    for p in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    return start


def main():
    global S
    ap = argparse.ArgumentParser(description='Shelter Studio')
    ap.add_argument('project', nargs='?', default=os.path.join(os.getcwd(), 'project'))
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    if not os.path.isfile(os.path.join(a.project, 'project.json')):
        print('Не найден project.json в папке', a.project)
        sys.exit(1)
    print('Загружаю проект…')
    S = Studio(a.project, workers=a.workers or None)
    port = free_port(a.port)
    srv = Server(('127.0.0.1', port), H)
    url = 'http://127.0.0.1:%d' % port
    print('\n  Shelter Studio запущена:  %s' % url)
    print('  Потоков рендера: %d' % S.nworkers)
    print('  Чтобы остановить — закройте это окно или нажмите Ctrl+C\n')
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        S.shutdown()
