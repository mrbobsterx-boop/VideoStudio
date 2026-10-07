"""Версии проекта: снимок project.json и кода всех сцен в папке project/_versions.

Картинки, видео и шрифты в снимок не копируются (они только добавляются и занимают много места).
"""
import datetime
import json
import os
import re
import shutil
import time

MAX_AUTO = 15


def _root(studio):
    return os.path.join(studio.dir, '_versions')


def _safe_id(vid):
    vid = os.path.basename(str(vid or ''))
    if not re.fullmatch(r'[\w\-]+', vid):
        raise ValueError('Неверная версия')
    return vid


def create(studio, name='', auto=False):
    root = _root(studio)
    os.makedirs(root, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    vid = stamp + ('_auto' if auto else '') + '_' + os.urandom(2).hex()
    d = os.path.join(root, vid)
    os.makedirs(os.path.join(d, 'scenes'))
    with studio.lock:
        p = json.loads(json.dumps(studio.p))
        codes = {s['file']: studio.codes.get(s['id'], '') for s in p['scenes']}
        tl, total = studio.timeline()
        fps = p['fps']
    with open(os.path.join(d, 'project.json'), 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    for fn, code in codes.items():
        with open(os.path.join(d, 'scenes', fn), 'w', encoding='utf-8', newline='\n') as f:
            f.write(code)
    meta = dict(id=vid, name=str(name or ('Автосохранение' if auto else 'Версия'))[:80], auto=bool(auto),
                created=time.time(), scenes=len(p['scenes']), duration=round(total / fps, 2), title=p.get('title', ''))
    with open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    if auto:
        autos = [v for v in list_versions(studio) if v['auto']]
        for v in autos[MAX_AUTO:]:
            shutil.rmtree(os.path.join(root, v['id']), ignore_errors=True)
    return meta


def list_versions(studio):
    root = _root(studio)
    out = []
    if not os.path.isdir(root):
        return out
    for vid in os.listdir(root):
        mp = os.path.join(root, vid, 'meta.json')
        try:
            with open(mp, 'r', encoding='utf-8') as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    out.sort(key=lambda v: v.get('created', 0), reverse=True)
    return out


def restore(studio, vid):
    vid = _safe_id(vid)
    d = os.path.join(_root(studio), vid)
    if not os.path.isfile(os.path.join(d, 'project.json')):
        raise ValueError('Версия не найдена')
    create(studio, 'До восстановления', auto=True)
    studio.save(now=True)
    sdir = os.path.join(studio.dir, 'scenes')
    trash = os.path.join(sdir, '_trash')
    os.makedirs(trash, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S_')
    with studio.lock:
        with open(os.path.join(d, 'project.json'), 'r', encoding='utf-8') as f:
            p = json.load(f)
        keep = {s['file'] for s in p['scenes']}
        # файлы сцен, которых нет в версии, — в корзину (их можно вернуть)
        for fn in os.listdir(sdir):
            if fn.endswith('.py') and fn not in keep and os.path.isfile(os.path.join(sdir, fn)):
                shutil.move(os.path.join(sdir, fn), os.path.join(trash, stamp + fn))
        for fn in keep:
            src = os.path.join(d, 'scenes', fn)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(sdir, fn))
        shutil.copy2(os.path.join(d, 'project.json'), studio.pj)
        studio.reload()
    return True


def delete(studio, vid):
    vid = _safe_id(vid)
    shutil.rmtree(os.path.join(_root(studio), vid), ignore_errors=True)
    return True


def rename(studio, vid, name):
    vid = _safe_id(vid)
    mp = os.path.join(_root(studio), vid, 'meta.json')
    with open(mp, 'r', encoding='utf-8') as f:
        m = json.load(f)
    m['name'] = str(name)[:80]
    m['auto'] = False
    with open(mp, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return m
