"""Проекты: список роликов, новый проект, копия, последний открытый.

Проекты лежат рядом с программой: папка project/ (SHELTER) и папка projects/ — все новые.
Проект — любая папка с project.json.
"""
import json
import os
import shutil

from . import engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, 'projects')
LAST = os.path.join(ROOT, '.last_project')
RECENT = os.path.join(ROOT, '.recent_projects')     # проекты из других папок, которые уже открывали
SKIP = {'.cache', 'exports', '_versions'}


def _is_project(d):
    return os.path.isfile(os.path.join(d, 'project.json'))


def _pid(d):
    d = os.path.abspath(d)
    try:
        rel = os.path.relpath(d, ROOT)
    except ValueError:          # другой диск в Windows
        return d
    return d if rel.startswith('..') else rel.replace(os.sep, '/')


def candidates(current=None):
    out = [os.path.join(ROOT, 'project')]
    if os.path.isdir(PROJECTS):
        out += [os.path.join(PROJECTS, x) for x in sorted(os.listdir(PROJECTS))]
    if current:
        out.append(current)
    last = last_project()
    if last:
        out.append(last)
    out += _recent()
    seen, res = set(), []
    for d in out:
        d = os.path.abspath(d)
        if d not in seen and _is_project(d):
            seen.add(d)
            res.append(d)
    return res


def info(d, current=None):
    try:
        with open(os.path.join(d, 'project.json'), 'r', encoding='utf-8') as f:
            p = json.load(f)
    except (OSError, ValueError):
        return None
    scenes = p.get('scenes', [])
    return dict(id=_pid(d), path=d, title=p.get('title') or os.path.basename(d), format=p.get('format', '16:9'),
                scenes=len(scenes), duration=round(sum(float(s.get('dur', 0)) for s in scenes), 1),
                mtime=os.path.getmtime(os.path.join(d, 'project.json')),
                current=bool(current and os.path.abspath(current) == os.path.abspath(d)),
                cover=os.path.isfile(os.path.join(d, '.cache', 'cover.jpg')))


def list_projects(current=None):
    items = [x for x in (info(d, current) for d in candidates(current)) if x]
    for x in items:
        x['known'] = x['current'] or is_known(x['path'])
    items.sort(key=lambda x: (not x['current'], -x['mtime']))
    return items + zips_in_projects()


def resolve(pid, current=None):
    """id из списка -> путь к папке (только известные проекты)."""
    for d in candidates(current):
        if _pid(d) == pid or os.path.abspath(d) == os.path.abspath(str(pid)):
            return d
    raise ValueError('Проект не найден')


def last_project():
    try:
        with open(LAST, 'r', encoding='utf-8') as f:
            d = f.read().strip()
    except OSError:
        return None
    if d and not os.path.isabs(d):
        d = os.path.join(ROOT, d)
    return d if d and _is_project(d) else None


def _recent():
    try:
        with open(RECENT, 'r', encoding='utf-8') as f:
            return [x for x in json.load(f) if isinstance(x, str)]
    except (OSError, ValueError):
        return []


def remember(d):
    try:
        with open(LAST, 'w', encoding='utf-8') as f:
            f.write(_pid(d))
        d = os.path.abspath(d)
        rec = [x for x in _recent() if os.path.abspath(x) != d and _is_project(x)]
        with open(RECENT, 'w', encoding='utf-8') as f:
            json.dump(([d] + rec)[:30], f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _new_dir(title):
    os.makedirs(PROJECTS, exist_ok=True)
    base = engine.slug(title) or 'video'
    d = os.path.join(PROJECTS, base)
    i = 2
    while os.path.exists(d):
        d = os.path.join(PROJECTS, '%s_%d' % (base, i))
        i += 1
    return d


def create(title, fmt='16:9', fonts_from=None):
    """Новый пустой проект: одна сцена-титр, шрифты копируются из текущего проекта."""
    from . import kit
    title = str(title or 'Новый ролик').strip()[:80] or 'Новый ролик'
    if fmt not in kit.FORMATS:
        fmt = '16:9'
    d = _new_dir(title)
    for sub in ('scenes', 'assets', 'audio', 'fonts', 'exports', 'lib'):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    src_fonts = os.path.join(fonts_from or os.path.join(ROOT, 'project'), 'fonts')
    if os.path.isdir(src_fonts):
        for f in os.listdir(src_fonts):
            if f.lower().endswith(('.ttf', '.otf', '.txt')):
                shutil.copy2(os.path.join(src_fonts, f), os.path.join(d, 'fonts', f))
    code = engine.TEMPLATES['title'].replace('{key}', 'intro')
    with open(os.path.join(d, 'scenes', 'intro.py'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(code)
    p = dict(title=title, fps=30, format=fmt,
             look=dict(letterbox=False, vignette=False, grain=0.0, hits=True),
             audio=dict(generated=False, ambience=False, generated_volume=1.0, music_file=None, music_volume=0.8,
                        music_offset=0, fade_out=1.5),
             scenes=[dict(id='s' + os.urandom(3).hex(), file='intro.py', name='Intro', dur=3.0, layers=[], fx=[])],
             texts=dict(intro_title=title.upper(), intro_sub=''), fonts={})
    with open(os.path.join(d, 'project.json'), 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return d


def duplicate(src, title=None):
    """Копия проекта (без готовых видео, кэша и версий)."""
    with open(os.path.join(src, 'project.json'), 'r', encoding='utf-8') as f:
        p = json.load(f)
    title = str(title or (p.get('title', 'Ролик') + ' — копия'))[:80]
    d = _new_dir(title)

    def ignore(folder, names):
        rel = os.path.relpath(folder, src)
        out = [n for n in names if rel == '.' and n in SKIP]
        if os.path.basename(folder) == 'scenes':
            out += [n for n in names if n in ('_history', '_trash')]
        return out
    shutil.copytree(src, d, ignore=ignore)
    p['title'] = title
    with open(os.path.join(d, 'project.json'), 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return d


def save_cover(studio):
    """Обложка проекта для списка — кадр из уже посчитанного превью."""
    try:
        with studio.lock:
            ids = [s['id'] for s in studio.p['scenes']]
        for sid in ids[1:3] + ids[:1]:
            j = studio.scene_thumb(sid)
            if j:
                c = os.path.join(studio.dir, '.cache')
                os.makedirs(c, exist_ok=True)
                with open(os.path.join(c, 'cover.jpg'), 'wb') as f:
                    f.write(j)
                return True
    except Exception:
        pass
    return False


# =====================================================================================
#  Открыть проект из папки или zip-архива
# =====================================================================================
import re
import zipfile

from . import VERSION

MAX_FILES = 50000
MAX_TOTAL = 40 << 30          # 40 ГБ распакованного
SKIP_IN_ZIP = {'__pycache__', '.cache', '_versions', '.git', '__MACOSX'}


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split('.')[:3])
    except ValueError:
        return (0,)


def find_root(path, depth=4):
    """Папка проекта: сама path, если в ней project.json, иначе ближайшая вложенная (до depth уровней)."""
    path = os.path.abspath(path)
    if _is_project(path):
        return path
    level = [path]
    for _ in range(depth):
        nxt = []
        for d in level:
            try:
                subs = sorted(os.listdir(d))
            except OSError:
                continue
            for x in subs:
                f = os.path.join(d, x)
                if os.path.isdir(f) and x not in SKIP_IN_ZIP and not x.startswith('.'):
                    if _is_project(f):
                        return f
                    nxt.append(f)
        level = nxt
    return None


def inspect(d):
    """Что внутри проекта — для окна подтверждения перед первым открытием."""
    with open(os.path.join(d, 'project.json'), 'r', encoding='utf-8') as f:
        p = json.load(f)
    scenes = p.get('scenes', [])
    py = 0
    lib = []
    for sub in ('scenes', 'lib'):
        base = os.path.join(d, sub)
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in ('__pycache__', '_history', '_trash')]
            for fn in files:
                if fn.endswith('.py'):
                    py += 1
                    if sub == 'lib':
                        lib.append(os.path.relpath(os.path.join(root, fn), base).replace(os.sep, '/'))
    need = p.get('editor_min')
    too_old = bool(need) and _ver(need) > _ver(VERSION)
    return dict(id=_pid(d), path=d, title=p.get('title') or os.path.basename(d), scenes=len(scenes),
                duration=round(sum(float(s.get('dur', 0)) for s in scenes), 1), py=py, lib=sorted(lib),
                editor_min=need, editor=VERSION, too_old=too_old, known=is_known(d))


def is_known(d):
    """Проект уже открывали в этой программе (или это стартовый project/) — без повторного предупреждения."""
    d = os.path.abspath(d)
    if d == os.path.abspath(os.path.join(ROOT, 'project')):
        return True
    return any(os.path.abspath(x) == d for x in _recent()) or (last_project() and os.path.abspath(last_project()) == d)


def _zip_name(info):
    """Имя файла в архиве: zip из Проводника Windows пишет русские имена в cp866, а не в UTF-8."""
    n = info.filename
    if not (info.flag_bits & 0x800):
        try:
            raw = n.encode('cp437')
            try:
                n = raw.decode('utf-8')
            except UnicodeDecodeError:
                n = raw.decode('cp866')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return n.replace('\\', '/')


def _safe_parts(name):
    """Части пути внутри архива; None — если путь опасный (абсолютный, с «..», с диском)."""
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        return None
    parts = [p for p in name.split('/') if p not in ('', '.')]
    if any(p == '..' for p in parts):
        return None
    return parts


def import_zip(zip_path, title_hint=None):
    """Распаковать проект из zip в projects/<имя>/ (безопасно) и вернуть папку.
    В архиве ищется project.json (можно во вложенной папке); всё, что вне папки проекта, пропускается.
    Защита: пути с «..» и абсолютные, ссылки (symlink), слишком большие и «zip-бомбы» — не распаковываются."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise ValueError('Это не zip-архив или он повреждён')
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError('В архиве слишком много файлов (%d)' % len(infos))
        entries = []
        total = 0
        for i in infos:
            name = _zip_name(i)
            parts = _safe_parts(name)
            if parts is None:
                raise ValueError('В архиве небезопасный путь: %s' % name)
            if i.is_dir() or not parts:
                continue
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                continue                                   # символическая ссылка — пропустить
            if any(p in SKIP_IN_ZIP for p in parts):
                continue
            total += i.file_size
            if i.compress_size and i.file_size > (100 << 20) and i.file_size / i.compress_size > 200:
                raise ValueError('Подозрительный архив (сильно сжатый файл %s)' % name)
            entries.append((i, parts))
        if total > MAX_TOTAL:
            raise ValueError('Архив слишком большой после распаковки')
        roots = sorted((parts[:-1] for i, parts in entries if parts[-1] == 'project.json'), key=len)
        if not roots:
            raise ValueError('В архиве нет project.json — это не проект VideoStudio')
        root = roots[0]
        try:
            with zf.open([i for i, parts in entries if parts == root + ['project.json']][0]) as f:
                pj = json.load(f)
            title = pj.get('title')
        except Exception:
            raise ValueError('project.json в архиве не читается')
        base = engine.slug(root[-1] if root else (title_hint or title or 'project')) or 'project'
        os.makedirs(PROJECTS, exist_ok=True)
        dest = os.path.join(PROJECTS, base)
        k = 2
        while os.path.exists(dest):
            dest = os.path.join(PROJECTS, '%s_%d' % (base, k))
            k += 1
        tmp = os.path.join(PROJECTS, '.importing_' + os.urandom(4).hex())
        os.makedirs(tmp)
        skipped = 0
        try:
            for i, parts in entries:
                if parts[:len(root)] != root:
                    skipped += 1
                    continue
                rel = parts[len(root):]
                out = os.path.abspath(os.path.join(tmp, *rel))
                if os.path.commonpath([out, os.path.abspath(tmp)]) != os.path.abspath(tmp):
                    raise ValueError('В архиве небезопасный путь')
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with zf.open(i) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            for sub in ('scenes', 'assets', 'audio', 'fonts', 'exports', 'lib'):
                os.makedirs(os.path.join(tmp, sub), exist_ok=True)
            os.makedirs(os.path.join(tmp, '.cache'), exist_ok=True)
            with open(os.path.join(tmp, '.cache', 'imported_from.json'), 'w', encoding='utf-8') as f:
                json.dump(dict(zip=os.path.basename(zip_path), size=os.path.getsize(zip_path),
                               skipped=skipped), f, ensure_ascii=False)
            os.replace(tmp, dest)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    return dest, skipped


def zips_in_projects():
    """Zip-архивы, которые просто положили в папку projects/ и ещё не распаковали."""
    if not os.path.isdir(PROJECTS):
        return []
    done = set()
    for x in os.listdir(PROJECTS):
        f = os.path.join(PROJECTS, x, '.cache', 'imported_from.json')
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                j = json.load(fh)
            done.add((j.get('zip'), j.get('size')))
        except (OSError, ValueError):
            pass
    out = []
    for x in sorted(os.listdir(PROJECTS)):
        f = os.path.join(PROJECTS, x)
        if x.lower().endswith('.zip') and os.path.isfile(f) and (x, os.path.getsize(f)) not in done:
            out.append(dict(id='zip:' + x, kind='zip', title=os.path.splitext(x)[0], path=f, mtime=os.path.getmtime(f),
                            size=os.path.getsize(f)))
    return out


def discard(d):
    """Удалить только что распакованный проект (если открыть его отказались). Только внутри projects/."""
    d = os.path.abspath(d)
    if os.path.dirname(d) != os.path.abspath(PROJECTS) or not os.path.isfile(os.path.join(d, '.cache', 'imported_from.json')):
        raise ValueError('Удалять можно только что распакованный проект')
    shutil.rmtree(d, ignore_errors=True)


_PICK = r'''
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    print('!notk'); sys.exit(0)
r = tk.Tk(); r.withdraw()
try:
    r.attributes('-topmost', True)
except Exception:
    pass
if sys.argv[1] == 'zip':
    p = filedialog.askopenfilename(title='Zip-архив проекта', filetypes=[('Zip', '*.zip'), ('Все файлы', '*.*')])
else:
    p = filedialog.askdirectory(title='Папка проекта (где лежит project.json)')
sys.stdout.buffer.write((p or '').encode('utf-8'))
'''


def pick(kind='dir'):
    """Системное окно выбора папки/zip (на компьютере, где запущен редактор). Возвращает путь или ''."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, '-c', _PICK, 'zip' if kind == 'zip' else 'dir'], capture_output=True, timeout=900)
    out = r.stdout.decode('utf-8', 'replace').strip()
    if out == '!notk':
        raise ValueError('Окно выбора папки недоступно (нет tkinter). Вставьте путь к папке или zip вручную.')
    return out
