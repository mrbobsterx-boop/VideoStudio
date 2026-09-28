"""Локальный веб-сервер редактора: http://127.0.0.1:8765

Защита: сервер слушает только 127.0.0.1; принимает запросы только с адресом 127.0.0.1/localhost
(защита от DNS-rebinding); все изменяющие запросы (POST) требуют секретный токен,
который знает только открытая страница редактора (защита от чужих сайтов в браузере).
"""
import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from . import ai, automontage, engine, fx, library, media, projects, soundgen, versions
from .engine import Studio

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
IMG_EXT = engine.IMG_EXT
VID_EXT = engine.VIDEO_EXT
AUD_EXT = ('.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac')
FONT_EXT = ('.ttf', '.otf')
MAX_JSON = 8 << 20            # 8 МБ
MAX_UPLOAD = 8 << 30          # 8 ГБ (видео)
WIN_RESERVED = {'con', 'prn', 'aux', 'nul'} | {'com%d' % i for i in range(1, 10)} | {'lpt%d' % i for i in range(1, 10)}
S = None          # Studio
TOKEN = secrets.token_urlsafe(24)
PORT = 0
_THUMBS = {}
_SWITCH = threading.Lock()


def switch_project(path):
    """Открыть другой проект без перезапуска программы."""
    global S
    with _SWITCH:
        old = S
        if old is not None and os.path.abspath(old.dir) == os.path.abspath(path):
            return
        if old is not None:
            if old.export_state.get('state') == 'running':
                raise ValueError('Сейчас идёт экспорт — дождитесь его окончания')
            old.save(now=True)
            projects.save_cover(old)
        new = Studio(path, workers=old.nworkers if old else None)
        S = new
        _THUMBS.clear()
        projects.remember(path)
        if old is not None:
            old.shutdown()


def safe_name(name, exts):
    base = os.path.basename(unquote(name or ''))
    stem, ext = os.path.splitext(base)
    stem = re.sub(r'[^\w\-]+', '_', stem, flags=re.UNICODE).strip('_') or 'file'
    if stem.lower() in WIN_RESERVED:
        stem += '_'
    ext = ext.lower()
    if ext not in exts:
        raise ValueError('Неподдерживаемый формат: %s' % (ext or 'без расширения'))
    return stem[:80] + ext


def safe_folder(name):
    """Имя папки внутри «Медиа»: одна папка, без опасных символов."""
    name = os.path.basename(unquote(str(name or '')).replace('\\', '/').strip('/'))
    name = re.sub(r'[^\w\- ]+', '_', name, flags=re.UNICODE).strip(' _.')
    if name.lower() in WIN_RESERVED:
        name += '_'
    return name[:60]


def _image_ok(path):
    # np.fromfile + imdecode: cv2.imread не открывает файлы с русскими буквами в пути на Windows
    try:
        return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED) is not None or path.lower().endswith('.webp')
    except Exception:
        return False


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


class Refused(Exception):
    pass


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
        self.send_header('X-Content-Type-Options', 'nosniff')
        if code >= 400:
            # тело запроса могло остаться непрочитанным — не переиспользовать соединение
            self.send_header('Connection', 'close')
            self.close_connection = True
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

    def length(self, limit):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise ValueError('Неверная длина запроса')
        if n < 0 or n > limit:
            raise ValueError('Слишком большой запрос')
        return n

    def body(self, limit=MAX_JSON):
        n = self.length(limit)
        return self.rfile.read(n) if n else b''

    def jbody(self):
        b = self.body()
        if not b:
            return {}
        v = json.loads(b.decode('utf-8'))
        if not isinstance(v, dict):
            raise ValueError('Ожидался JSON-объект')
        return v

    def save_upload(self, path, limit=MAX_UPLOAD):
        """Записать тело запроса в файл кусками (большие видео не держим в памяти)."""
        n = self.length(limit)
        tmp = path + '.part'
        left = n
        with open(tmp, 'wb') as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left > 0:
            os.remove(tmp)
            raise ValueError('Загрузка прервалась')
        try:
            os.replace(tmp, path)
        except PermissionError:
            # Windows: заменяемый файл сейчас открыт (например, видео читается для превью)
            os.remove(tmp)
            raise ValueError('Файл «%s» сейчас занят программой. Переименуйте новый файл и загрузите его ещё раз.'
                             % os.path.basename(path))
        return n

    def file(self, path, ctype=None, download=None):
        if not path or not os.path.isfile(path):
            return self.send(404, 'not found', 'text/plain')
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        extra = {'Accept-Ranges': 'bytes'}
        if download:
            extra['Content-Disposition'] = 'attachment; filename="%s"' % re.sub(r'[^\w.\-]', '_', download)
        start, end, code = 0, size - 1, 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)$', rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(size - 1, int(m.group(2)))
                else:
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    return self.send(416, b'', 'text/plain', {'Content-Range': 'bytes */%d' % size})
                code = 206
                extra['Content-Range'] = 'bytes %d-%d/%d' % (start, end, size)
        length = max(0, end - start + 1)
        try:
            f = open(path, 'rb')
        except OSError:
            return self.send(404, 'not found', 'text/plain')
        with f:
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == 'HEAD':
                return
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    # ---------------- security
    def check_host(self):
        host = (self.headers.get('Host') or '').lower()
        if host not in ('127.0.0.1:%d' % PORT, 'localhost:%d' % PORT):
            raise Refused('bad host')

    def check_token(self):
        tok = self.headers.get('X-Studio-Token') or ''
        if not hmac.compare_digest(tok, TOKEN):
            raise Refused('bad token')
        origin = self.headers.get('Origin')
        if origin and origin.lower() not in ('http://127.0.0.1:%d' % PORT, 'http://localhost:%d' % PORT):
            raise Refused('bad origin')

    # ---------------- routing
    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        # никаких CORS: чужим страницам нельзя
        self.send(403, 'forbidden', 'text/plain')

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        try:
            self.check_host()
            if p == '/' or p == '/index.html':
                with open(os.path.join(UI, 'index.html'), 'r', encoding='utf-8') as f:
                    html = f.read().replace('%%STUDIO_TOKEN%%', TOKEN)
                return self.send(200, html, 'text/html; charset=utf-8',
                                 {'Content-Security-Policy': "default-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                                             "img-src 'self' data: blob:; media-src 'self' blob:; "
                                                             "frame-ancestors 'none'", 'X-Frame-Options': 'DENY'})
            if p.startswith('/ui/'):
                f = os.path.normpath(os.path.join(UI, unquote(p[4:])))
                if os.path.commonpath([f, UI]) != UI:
                    return self.send(403)
                return self.file(f)
            if p == '/api/state':
                return self.js(S.state())
            if p == '/api/cache':
                return self.send(200, S.cache_map(), 'text/plain')
            if p == '/api/frame':
                wait = q.get('nowait') != '1'
                if 'sid' in q:
                    jpg, g = S.frame_sl(q['sid'], int(q.get('l', 0)), wait=wait)
                else:
                    jpg, g = S.frame(int(q.get('f', 0)), wait=wait), -1
                if jpg is None:
                    return self.send(204, b'', 'text/plain', {'X-Gen': str(g)})
                return self.send(200, jpg, 'image/jpeg', {'X-Gen': str(g)})
            if p == '/api/scene':
                s = S.scene(q['id'])
                return self.js(dict(id=s['id'], file=s['file'], code=S.codes[s['id']], error=S.errors.get(s['id'])))
            if p == '/api/scene/thumb':
                j = S.scene_thumb(q['id'])
                return self.send(200, j, 'image/jpeg') if j else self.send(204, b'', 'text/plain')
            if p == '/api/audio.wav':
                return self.file(S.audio_path(), 'audio/wav')
            if p == '/api/waveform':
                return self.js(dict(ver=S.audio_ver, peaks=S.audio_peaks, rate=S.audio_peaks_rate))
            if p == '/api/assets':
                return self.js(self.list_assets())
            if p == '/api/thumb':
                return self.thumb(q.get('name', ''))
            if p == '/api/media':
                path = S.asset_path(q.get('name', ''))
                return self.file(path)
            if p == '/api/audiofile':
                return self.file(S.music_path(q.get('ref', '')))
            if p == '/api/fonts':
                return self.js(self.list_fonts())
            if p == '/api/font/sample':
                return self.font_sample(q.get('name', ''), q.get('text', ''), int(q.get('size', 44) or 44))
            if p == '/api/fx':
                return self.js(dict(effects=fx.catalog()))
            if p == '/api/library':
                return self.js(dict(items=library.list_items()))
            if p == '/api/library/thumb':
                return self.send(200, library.thumb(S, q['id']), 'image/jpeg')
            if p == '/api/library/frame':
                return self.send(200, library.frame(S, q['id'], float(q.get('t', 0)), int(q.get('w', 640))), 'image/jpeg')
            if p == '/api/library/code':
                m = library.load(q['id'])
                return self.js(dict(code=m['code'], name=m.get('name'), desc=m.get('desc'), dur=m.get('dur')))
            if p == '/api/projects':
                projects.save_cover(S)
                return self.js(dict(items=projects.list_projects(S.dir)))
            if p == '/api/projects/cover':
                d = projects.resolve(q.get('id', ''), S.dir)
                return self.file(os.path.join(d, '.cache', 'cover.jpg'), 'image/jpeg')
            if p == '/api/sound/plan':
                moods = json.loads(q['moods']) if q.get('moods') else None
                return self.js(dict(scenes=soundgen.plan(S, moods), moods=[dict(id=k, label=soundgen.MOODS[k]['label'])
                                                                          for k in soundgen.ORDER],
                                    music=S.p['audio'].get('music_file'), generated=S.p['audio'].get('generated', True)))
            if p == '/api/sound/brief':
                return self.js(dict(text=soundgen.brief(S)))
            if p == '/api/versions':
                return self.js(dict(items=versions.list_versions(S)))
            if p == '/api/automontage/info':
                return self.js(dict(media=automontage.media_list(S), music=self.music_summary(),
                                    styles=[dict(id=k, label=v['label'], desc=v['desc']) for k, v in automontage.STYLES.items()]))
            if p.startswith('/exports/'):
                name = os.path.basename(unquote(p[len('/exports/'):]))
                return self.file(os.path.join(S.dir, 'exports', name), 'video/mp4',
                                 download=name if q.get('dl') else None)
            return self.send(404, 'not found', 'text/plain')
        except Refused:
            return self.send(403, 'forbidden', 'text/plain')
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
            self.check_host()
            self.check_token()
            if p == '/api/playhead':
                S.playhead = int(self.jbody().get('f', 0))
                return self.js(dict(ok=True))
            if p == '/api/scene/save':
                b = self.jbody()
                return self.js(S.save_code(b['id'], b['code']))
            if p == '/api/scene/update':
                b = self.jbody()
                S.update_scene(b['id'], b.get('name'), b.get('dur'), b.get('layers'), b.get('fx'))
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
                S.set_project(b.get('title'), b.get('fps'), b.get('format'))
                return self.js(dict(ok=True))
            if p == '/api/fonts':
                S.set_fonts(self.jbody())
                return self.js(dict(ok=True))
            if p == '/api/assets/upload':
                return self.upload_asset(q)
            if p == '/api/music/upload':
                name = safe_name(q.get('name'), AUD_EXT)
                d = os.path.join(S.dir, 'audio')
                os.makedirs(d, exist_ok=True)
                self.save_upload(os.path.join(d, name), 1 << 30)
                S.set_audio(dict(music_file=name))
                return self.js(dict(ok=True, name=name))
            if p == '/api/fonts/upload':
                name = safe_name(q.get('name'), FONT_EXT)
                d = os.path.join(S.dir, 'fonts')
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, name)
                self.save_upload(path, 64 << 20)
                try:
                    from PIL import ImageFont
                    ImageFont.truetype(path, 20)
                except Exception:
                    os.remove(path)
                    raise ValueError('Файл не похож на шрифт TTF/OTF')
                S.invalidate()
                return self.js(dict(ok=True, name=os.path.splitext(name)[0]))
            if p == '/api/export':
                ok = S.export(self.jbody().get('crf', 18))
                return self.js(dict(ok=ok, error=None if ok else 'Экспорт уже идёт'))
            if p == '/api/export/cancel':
                S.cancel_export()
                return self.js(dict(ok=True))
            if p == '/api/open':
                b = self.jbody()
                what = b.get('what', 'exports')
                path = os.path.join(S.dir, what if what in ('exports', 'assets', 'scenes', 'audio', 'fonts', '_versions') else '')
                if what == 'library':
                    path = library.LIB
                sel = os.path.join(path, os.path.basename(b['file'])) if b.get('file') else None
                err = open_folder(path, sel)
                return self.js(dict(ok=not err, path=sel or path, error=err))
            # ---- библиотека
            if p == '/api/library/save':
                b = self.jbody()
                return self.js(dict(ok=True, id=library.save_scene(S, b['sid'], b.get('name'), b.get('desc', ''),
                                                                   b.get('category') or 'Мои сцены')))
            if p == '/api/library/insert':
                b = self.jbody()
                return self.js(dict(ok=True, id=library.insert(S, b['id'], b.get('after'))))
            if p == '/api/library/delete':
                library.delete(self.jbody()['id'])
                return self.js(dict(ok=True))
            # ---- проекты
            if p == '/api/projects/new':
                b = self.jbody()
                d = projects.create(b.get('title'), b.get('format', '16:9'), fonts_from=S.dir)
                switch_project(d)
                return self.js(dict(ok=True, id=projects._pid(d)))
            if p == '/api/projects/open':
                switch_project(projects.resolve(self.jbody().get('id', ''), S.dir))
                return self.js(dict(ok=True))
            if p == '/api/projects/duplicate':
                S.save(now=True)
                d = projects.duplicate(S.dir, self.jbody().get('title'))
                switch_project(d)
                return self.js(dict(ok=True, id=projects._pid(d)))
            # ---- звук
            if p == '/api/sound/generate':
                b = self.jbody()
                n = soundgen.apply_generated(S, b.get('moods'), b.get('only') or None, b.get('levels', True))
                if b.get('enable'):
                    S.set_audio(dict(generated=True))
                return self.js(dict(ok=True, changed=n))
            if p == '/api/sound/mood':
                b = self.jbody()
                soundgen.set_mood(S, b['id'], b.get('mood'))
                return self.js(dict(ok=True))
            if p == '/api/sound/ai_check':
                rows = soundgen.parse_answer(S, self.jbody().get('text', ''))
                return self.js(dict(rows=[{k: v for k, v in r.items() if k != 'code'} for r in rows]))
            if p == '/api/sound/ai_apply':
                b = self.jbody()
                rows = soundgen.apply_answer(S, b.get('text', ''))
                if b.get('enable'):
                    S.set_audio(dict(generated=True))
                return self.js(dict(ok=True, rows=[{k: v for k, v in r.items() if k != 'code'} for r in rows]))
            # ---- версии
            if p == '/api/versions/create':
                return self.js(dict(ok=True, version=versions.create(S, self.jbody().get('name', ''))))
            if p == '/api/versions/restore':
                versions.restore(S, self.jbody()['id'])
                return self.js(dict(ok=True))
            if p == '/api/versions/delete':
                versions.delete(S, self.jbody()['id'])
                return self.js(dict(ok=True))
            if p == '/api/versions/rename':
                b = self.jbody()
                return self.js(dict(ok=True, version=versions.rename(S, b['id'], b.get('name', ''))))
            # ---- ИИ
            if p == '/api/ai/brief':
                b = self.jbody()
                return self.js(dict(text=ai.brief(S, b.get('goal', ''), b.get('dur', 4), b.get('name', ''),
                                                  b.get('assets') or None, b.get('style', ''), b.get('example'))))
            if p == '/api/ai/check':
                b = self.jbody()
                return self.js(ai.check(S, b.get('code', ''), b.get('dur', 4)))
            if p == '/api/ai/add':
                b = self.jbody()
                code = ai.extract_code(b.get('code', ''))
                errors, warnings, doc = ai.static_check(code)
                if errors:
                    return self.js(dict(ok=False, error='\n'.join(errors)))
                sid = S.add_scene(b.get('after'), name=b.get('name') or doc[:40] or 'AI scene', code=code,
                                  dur=b.get('dur', 4))
                res = dict(ok=True, id=sid)
                if b.get('to_library'):
                    res['lib'] = library.save_scene(S, sid, b.get('name') or doc[:40], doc, 'Сцены от ИИ')
                return self.js(res)
            # ---- автомонтаж
            if p == '/api/automontage':
                return self.js(dict(ok=True, **automontage.build(S, self.jbody())))
            return self.send(404, 'not found', 'text/plain')
        except Refused:
            return self.send(403, 'forbidden: откройте редактор по адресу из консоли', 'text/plain; charset=utf-8')
        except KeyError as e:
            return self.js(dict(error='not found: %s' % e), 404)
        except ValueError as e:
            return self.js(dict(error=str(e)), 400)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.js(dict(error=str(e)), 500)

    # ---------------- assets
    def upload_asset(self, q):
        raw_name = q.get('name') or ''
        ext = os.path.splitext(raw_name)[1].lower()
        folder = safe_folder(q.get('folder'))
        d = os.path.join(S.dir, 'assets', folder) if folder else os.path.join(S.dir, 'assets')
        if ext in AUD_EXT:
            # звук: в папку медиа (если загружали папкой) или в audio/ — музыка ролика
            name = safe_name(raw_name, AUD_EXT)
            d = d if folder else os.path.join(S.dir, 'audio')
            os.makedirs(d, exist_ok=True)
            self.save_upload(os.path.join(d, name), 1 << 30)
            return self.js(dict(ok=True, name=((folder + '/') if folder else '') + os.path.splitext(name)[0], kind='audio'))
        os.makedirs(d, exist_ok=True)
        if ext in VID_EXT:
            name = safe_name(raw_name, VID_EXT)
            stem = os.path.splitext(name)[0]
            # у картинки и видео не должно быть одного имени
            for e in IMG_EXT:
                if os.path.exists(os.path.join(d, stem + e)):
                    stem += '_v'
                    name = stem + ext
                    break
            path = os.path.join(d, name)
            self.save_upload(path)
            try:
                i = media.info(path)
                if not i['frames'] and not i['w']:
                    raise ValueError
            except Exception:
                os.remove(path)
                raise ValueError('Не удалось прочитать видео. Попробуйте MP4 (H.264).')
        else:
            name = safe_name(raw_name, IMG_EXT)
            if q.get('cutout') == '1':
                data = self.body(256 << 20)
                arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if arr is None:
                    raise ValueError('Не удалось прочитать картинку')
                rgba = key_white(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
                name = os.path.splitext(name)[0] + '_cut.png'
                cv2.imencode('.png', cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1].tofile(os.path.join(d, name))
            else:
                path = os.path.join(d, name)
                self.save_upload(path, 256 << 20)
                if not _image_ok(path):
                    os.remove(path)
                    raise ValueError('Не удалось прочитать картинку')
        stem = ((folder + '/') if folder else '') + os.path.splitext(name)[0]
        _THUMBS.pop(stem, None)
        S.invalidate_asset(stem)
        return self.js(dict(ok=True, name=stem))

    def list_assets(self):
        return S.list_media()

    def thumb(self, name):
        path = S.asset_path(name)
        if not path:
            return self.send(404)
        key = (path, os.path.getmtime(path))
        if _THUMBS.get(name, (None,))[0] != key:
            if path.lower().endswith(VID_EXT):
                im = media.thumbnail(path)
            else:
                im = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_UNCHANGED)
            if im is None:
                return self.send(404)
            h, w = im.shape[:2]
            s = 320 / max(w, h)
            im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.png', im)
            _THUMBS[name] = (key, buf.tobytes())
        return self.send(200, _THUMBS[name][1], 'image/png')

    # ---------------- fonts
    def list_fonts(self):
        d = os.path.join(S.dir, 'fonts')
        out = []
        roles = S.font_roles()
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            stem, ext = os.path.splitext(f)
            if ext.lower() not in FONT_EXT:
                continue
            fam, style, axes = stem, '', None
            try:
                from PIL import ImageFont
                ft = ImageFont.truetype(os.path.join(d, f), 20)
                fam, style = ft.getname()
                try:
                    ax = ft.get_variation_axes()
                    axes = [int(ax[0]['minimum']), int(ax[0]['maximum'])] if ax else None
                except Exception:
                    axes = None
            except Exception:
                pass
            out.append(dict(name=stem, file=f, family=fam, style=style, weights=axes,
                            roles=[r for r, v in roles.items() if v == stem]))
        return dict(fonts=out, roles=roles)

    def font_sample(self, name, text, size):
        from PIL import Image, ImageDraw
        from . import kit
        text = (text or 'Съешь ещё этих мягких булок — Shelter 2026')[:80]
        size = max(10, min(120, size))
        f = kit._font(os.path.basename(name), 500, size)
        w = int(f.getlength(text)) + 24
        asc, desc = f.getmetrics()
        im = Image.new('RGBA', (min(w, 1600), asc + desc + 16), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((12, 8), text, font=f, fill=(236, 238, 243, 255))
        buf = cv2.imencode('.png', cv2.cvtColor(np.array(im), cv2.COLOR_RGBA2BGRA))[1]
        return self.send(200, buf.tobytes(), 'image/png')

    def music_summary(self):
        try:
            m = automontage.music_info(S)
        except Exception:
            m = None
        if not m:
            return None
        return dict(file=m['file'], dur=m['dur'], tempo=m['tempo'], beats=len(m['beats']))


def open_folder(path, select=None):
    """Открывает папку в проводнике; если задан select — выделяет этот файл.
    Возвращает текст ошибки или None."""
    if select and not os.path.isfile(select):
        select = None
    try:
        os.makedirs(path, exist_ok=True)
        if sys.platform.startswith('win'):
            if select:
                subprocess.Popen('explorer /select,"%s"' % os.path.normpath(select))
            else:
                subprocess.Popen(['explorer', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', select] if select else ['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception as e:
        return str(e)
    return None


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
    global S, PORT
    ap = argparse.ArgumentParser(description='Shelter Studio')
    ap.add_argument('project', nargs='?', default=None,
                    help='папка проекта (по умолчанию — последний открытый, иначе project/)')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    if not a.project:
        a.project = projects.last_project() or os.path.join(projects.ROOT, 'project')
    if not os.path.isfile(os.path.join(a.project, 'project.json')):
        print('Не найден project.json в папке', a.project)
        sys.exit(1)
    print('Загружаю проект…')
    S = Studio(a.project, workers=a.workers or None)
    projects.remember(a.project)
    PORT = free_port(a.port)
    srv = Server(('127.0.0.1', PORT), H)
    url = 'http://127.0.0.1:%d' % PORT
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
