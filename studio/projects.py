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
    items.sort(key=lambda x: (not x['current'], -x['mtime']))
    return items


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
    for sub in ('scenes', 'assets', 'audio', 'fonts', 'exports'):
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
             look=dict(letterbox=fmt == '16:9', vignette=True, grain=0.05, hits=True),
             audio=dict(generated=True, generated_volume=1.0, music_file=None, music_volume=0.8, music_offset=0,
                        fade_out=1.5),
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
