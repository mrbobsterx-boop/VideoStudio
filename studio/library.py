"""Библиотека сцен: готовые шаблоны и ваши сохранённые сцены (папка library/ рядом с программой).

Сцена в библиотеке — папка:
    library/<id>/scene.py     код
    library/<id>/meta.json    название, описание, длина, слои, эффекты, тексты
    library/<id>/assets/      картинки и видео, которые нужны сцене
    library/<id>/thumb_*.jpg  обложки для разных форматов (делаются сами)
"""
import datetime
import json
import os
import re
import shutil
import time
import uuid

from . import engine

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'library')
TX_RE = re.compile(r"""\btx\(\s*(['"])(\w+)\1""")


def _safe_id(i):
    i = os.path.basename(str(i or ''))
    if not re.fullmatch(r'[\w\-]+', i):
        raise ValueError('Неверный id сцены библиотеки')
    return i


def _dir(i):
    return os.path.join(LIB, _safe_id(i))


def load(i):
    d = _dir(i)
    with open(os.path.join(d, 'meta.json'), 'r', encoding='utf-8') as f:
        m = json.load(f)
    with open(os.path.join(d, 'scene.py'), 'r', encoding='utf-8') as f:
        code = f.read()
    m['id'] = os.path.basename(d)
    m['code'] = code
    m['dir'] = d
    return m


def list_items():
    out = []
    if not os.path.isdir(LIB):
        return out
    for i in sorted(os.listdir(LIB)):
        try:
            m = load(i)
        except (OSError, ValueError):
            continue
        out.append(dict(id=m['id'], name=m.get('name', i), desc=m.get('desc', ''), category=m.get('category', 'Мои сцены'),
                        dur=m.get('dur', 3.0), builtin=bool(m.get('builtin')), created=m.get('created', 0),
                        layers=len(m.get('layers', [])), fx=[e.get('name') for e in m.get('fx', [])],
                        mtime=os.path.getmtime(os.path.join(m['dir'], 'scene.py')),
                        needs=m.get('needs', '')))
    order = {'Титры': 0, 'Медиа': 1, 'Текст': 2, 'Динамика': 3}
    out.sort(key=lambda x: (x['builtin'], order.get(x['category'], -1 if not x['builtin'] else 9), x['category'], x['name']))
    return out


def _task(studio, m, t):
    task = studio.base_task()
    texts = dict(task['texts'])
    texts.update(m.get('texts', {}))
    layers = []
    for n, L in enumerate(m.get('layers', [])):
        L = dict(L)
        if L.get('type') == 'text':
            L['key'] = L.get('key') or 'lib_text_%d' % n
            texts[L['key']] = L.get('text', '')
        layers.append(L)
    task.update(path=os.path.join(m['dir'], 'scene.py'), code=m['code'], t=float(t), dur=float(m.get('dur', 3)),
                lfi=int(t * 30), texts=texts, layers=layers, fx=m.get('fx', []))
    task['asset_dirs'] = task['asset_dirs'] + [os.path.join(m['dir'], 'assets')]
    task['font_dirs'] = task['font_dirs'] + [os.path.join(m['dir'], 'fonts')]
    return task


def frame(studio, i, t, width=640):
    m = load(i)
    t = max(0.0, min(float(m.get('dur', 3)) - 0.001, float(t)))
    key = ('lib', m['id'], os.path.getmtime(os.path.join(m['dir'], 'scene.py')), round(t, 2), width)
    task = _task(studio, m, t)
    task['width'] = width
    return studio.render_virtual(key, task)


def thumb(studio, i):
    m = load(i)
    p = os.path.join(m['dir'], 'thumb_%dx%d.jpg' % tuple(studio.size))     # своя обложка для каждого формата
    if os.path.isfile(p) and os.path.getmtime(p) >= os.path.getmtime(os.path.join(m['dir'], 'scene.py')):
        with open(p, 'rb') as f:
            return f.read()
    jpg = frame(studio, i, float(m.get('dur', 3)) * float(m.get('thumb_at', 0.55)), width=480)
    try:
        with open(p, 'wb') as f:
            f.write(jpg)
    except OSError:
        pass
    return jpg


def _scene_texts(studio, sid, code, layers):
    keys = set(studio.used.get(sid, set())) | {m.group(2) for m in TX_RE.finditer(code)}
    return {k: studio.p['texts'][k] for k in sorted(keys) if k in studio.p['texts']}


def save_scene(studio, sid, name=None, desc='', category='Мои сцены'):
    with studio.lock:
        s = studio.scene(sid)
        code = studio.codes[sid]
        layers = []
        for L in s.get('layers', []):
            L = dict(L)
            if L['type'] == 'text':
                L['text'] = studio.p['texts'].get(L.get('key'), '')
                L['key'] = ''
            L['id'] = ''
            layers.append(L)
        fx = [dict(e) for e in s.get('fx', [])]
        texts = _scene_texts(studio, sid, code, layers)
        assets = set(studio.assets_used.get(sid, set())) | {L.get('src') for L in layers if L.get('src')}
        dur = s['dur']
        name = str(name or s['name'])[:60]
    iid = engine.slug(name) + '_' + uuid.uuid4().hex[:5]
    d = os.path.join(LIB, iid)
    os.makedirs(os.path.join(d, 'assets'), exist_ok=True)
    copied = []
    for a in sorted(assets):
        p = studio.asset_path(a)
        if p:
            shutil.copy2(p, os.path.join(d, 'assets', os.path.basename(p)))
            copied.append(os.path.basename(p))
    with open(os.path.join(d, 'scene.py'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(code)
    meta = dict(name=name, desc=str(desc or '')[:300], category=str(category or 'Мои сцены')[:40], dur=dur,
                layers=layers, fx=fx, texts=texts, assets=copied, created=time.time(), builtin=False)
    with open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    j = studio.scene_thumb(sid)
    if j:
        with open(os.path.join(d, 'thumb_%dx%d.jpg' % tuple(studio.size)), 'wb') as f:
            f.write(j)
    return iid


def insert(studio, i, after=None, name=None):
    """Добавить сцену из библиотеки в ролик. Нужные картинки копируются в assets/ проекта,
    ключи текстов, которые уже заняты в проекте другим текстом, переименовываются."""
    m = load(i)
    adir = os.path.join(studio.dir, 'assets')
    os.makedirs(adir, exist_ok=True)
    for fn in m.get('assets', []):
        src = os.path.join(m['dir'], 'assets', os.path.basename(fn))
        dst = os.path.join(adir, os.path.basename(fn))
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    code = m['code']
    texts = dict(m.get('texts', {}))
    keys = {g.group(2) for g in TX_RE.finditer(code)} | set(texts)
    with studio.lock:
        taken = [k for k in keys if k in studio.p['texts'] and studio.p['texts'][k] != texts.get(k, studio.p['texts'][k])]
        used_by_other = [k for k in keys if k in studio.p['texts']]
    rename = {}
    if taken or used_by_other:
        # тот же шаблон второй раз — дать текстам свои ключи, чтобы правка одной сцены не меняла другую
        n = 2
        while any(('%s_%d' % (k, n)) in studio.p['texts'] for k in keys):
            n += 1
        rename = {k: '%s_%d' % (k, n) for k in keys}
        for old, new in rename.items():
            code = re.sub(r"""(\btx\(\s*['"])%s(['"])""" % re.escape(old), r'\g<1>%s\g<2>' % new, code)
        texts = {rename.get(k, k): v for k, v in texts.items()}
    layers = []
    for L in m.get('layers', []):
        L = dict(L)
        L['id'] = ''
        if L.get('type') == 'text':
            L['key'] = ''
        layers.append(L)
    return studio.add_scene(after=after, name=name or m.get('name', 'Scene'), code=code, dur=m.get('dur', 3.0),
                            layers=layers, fx=m.get('fx', []), texts=texts)


def delete(i):
    m = load(i)
    if m.get('builtin'):
        raise ValueError('Встроенные шаблоны удалить нельзя')
    trash = os.path.join(LIB, '_trash')
    os.makedirs(trash, exist_ok=True)
    shutil.move(m['dir'], os.path.join(trash, datetime.datetime.now().strftime('%Y%m%d-%H%M%S_') + m['id']))
    return True
