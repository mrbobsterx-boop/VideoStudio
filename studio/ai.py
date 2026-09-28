"""Помощник для сцен, которые пишет ИИ.

brief()  — собирает точное задание для ИИ: правила, справочник всех команд, список картинок/видео/шрифтов,
           пример сцены из проекта и описание того, что нужно сделать.
check()  — проверяет ответ ИИ: синтаксис, запрещённые вызовы, пробный рендер нескольких кадров.
"""
import ast
import base64
import inspect
import os
import re
import textwrap

from . import engine, fx, kit

FORBIDDEN_MODULES = {'os', 'sys', 'subprocess', 'shutil', 'socket', 'requests', 'urllib', 'http', 'ftplib',
                     'pathlib', 'ctypes', 'multiprocessing', 'threading', 'asyncio', 'importlib', 'pickle',
                     'webbrowser', 'smtplib', 'glob', 'tempfile', 'signal'}
FORBIDDEN_CALLS = {'open', 'exec', 'eval', '__import__', 'compile', 'input', 'exit', 'quit', 'globals', 'breakpoint'}
ALLOWED_MODULES = {'studio.kit', 'math', 'random', 'numpy', 'cv2', 'colorsys', 'itertools', 'functools'}


def _sig(fn):
    try:
        return str(inspect.signature(fn))
    except (TypeError, ValueError):
        return '(...)'


def _doc(fn, n=3):
    d = inspect.getdoc(fn) or ''
    lines = [ln for ln in d.splitlines() if ln.strip()][:n]
    return ' '.join(lines)


def api_reference():
    """Справочник команд kit (из самого кода — всегда актуален)."""
    groups = [
        ('Время и плавность', ['clamp', 'prog', 'lerp', 'oc', 'ic', 'ioc', 'oexp', 'iexp', 'oback', 'obounce']),
        ('Тексты', ['tx', 'text', 'bold', 'serif', 'text_size']),
        ('Картинки и видео', ['image', 'sprite', 'portrait', 'video', 'video_info', 'cover', 'contain', 'kb', 'place',
                              'blit', 'card']),
        ('Эффекты кадра', ['fill', 'darkbg', 'dim', 'blur', 'grayscale', 'shade_bottom', 'glow_circle', 'glow_ellipse',
                           'dust', 'embers', 'diamond', 'effect']),
    ]
    out = []
    for title, names in groups:
        out.append('### %s' % title)
        for nm in names:
            fn = getattr(kit, nm, None)
            if fn is None:
                continue
            d = _doc(fn)
            out.append('- `%s%s`%s' % (nm, _sig(fn), (' — ' + d) if d else ''))
        out.append('')
    return '\n'.join(out)


def fx_reference():
    out = []
    for e in fx.catalog():
        ps = []
        for q in e['params']:
            if q['type'] == 'num':
                ps.append('%s=%s (%s..%s)' % (q['k'], q['default'], q['min'], q['max']))
            else:
                ps.append("%s='%s' (%s)" % (q['k'], q['default'], ', '.join("'%s'" % o[0] for o in q['options'])))
        out.append("- `effect(fr, t, dur, '%s'%s)` — %s" % (e['name'], (', ' + ', '.join(ps)) if ps else '', e['label']))
    return '\n'.join(out)


def sound_reference():
    from .sound import SceneAudio
    out = []
    for nm, fn in inspect.getmembers(SceneAudio, inspect.isfunction):
        if nm.startswith('_') or nm in ('add', 'noise'):
            continue
        d = _doc(fn, 1)
        out.append('- `a.%s%s`%s' % (nm, _sig(fn).replace('(self, ', '(').replace('(self)', '()'), (' — ' + d) if d else ''))
    return '\n'.join(out)


def assets_list(studio, names=None):
    from . import media
    d = os.path.join(studio.dir, 'assets')
    rows = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        stem, ext = os.path.splitext(f)
        ext = ext.lower()
        if names and stem not in names:
            continue
        p = os.path.join(d, f)
        if ext in engine.VIDEO_EXT:
            try:
                i = media.info(p)
                rows.append("- `video('%s', t)` — видео %dx%d, %.1f с" % (stem, i['w'], i['h'], i['dur']))
            except Exception:
                rows.append("- `video('%s', t)` — видео" % stem)
        elif ext in engine.IMG_EXT:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    w, h = im.size
                    alpha = im.mode in ('RGBA', 'LA', 'P') and ext == '.png'
            except Exception:
                w = h = 0
                alpha = False
            if alpha:
                rows.append("- `sprite('%s')` — вырезанный объект с прозрачностью, %dx%d" % (stem, w, h))
            else:
                rows.append("- `image('%s')` — картинка %dx%d" % (stem, w, h))
    return '\n'.join(rows) or '- (картинок пока нет — используйте только графику из кода)'


def _example(studio, sid=None):
    with studio.lock:
        ids = [s['id'] for s in studio.p['scenes'] if not studio.errors.get(s['id'])]
        pick = sid if sid in studio.codes else None
        if pick is None:
            best = None
            for i in ids:
                c = studio.codes[i]
                n = len(c)
                if 600 < n < 2600 and (best is None or abs(n - 1400) < abs(len(studio.codes[best]) - 1400)):
                    best = i
            pick = best or (ids[0] if ids else None)
        return studio.codes.get(pick, engine.TEMPLATES['title'])


def brief(studio, goal='', dur=4.0, name='', assets=None, style='', example_sid=None, prefix=''):
    """Готовый текст задания для ИИ (вставьте его в чат с ИИ целиком)."""
    with studio.lock:
        title = studio.p.get('title', '')
        look = dict(studio.p['look'])
        roles = studio.font_roles()
        scenes = [(s['name'], studio.meta.get(s['id'], {}).get('doc', ''), s['dur']) for s in studio.p['scenes']]
    fonts_dir = os.path.join(studio.dir, 'fonts')
    fonts = sorted({os.path.splitext(f)[0] for f in os.listdir(fonts_dir)
                    if f.lower().endswith(('.ttf', '.otf'))}) if os.path.isdir(fonts_dir) else []
    prefix = engine.slug(prefix or name or 'scene')[:16]
    dur = float(dur or 4)
    safe = ('Полезная область кадра — между кинополосами: по вертикали от VY=%d до VY+VH=%d (полосы включены). '
            'Всё важное держите внутри неё.' % (kit.VY, kit.VY + kit.VH)) if look.get('letterbox', True) else \
        'Кинополосы выключены — можно использовать весь кадр 1920×1080.'
    scene_list = '\n'.join('%d. %s (%.1f с)%s' % (i + 1, n, d, (' — ' + doc) if doc else '') for i, (n, doc, d) in enumerate(scenes[:40]))
    example = _example(studio, example_sid)
    text = f"""# Задание: одна сцена для видеоредактора Shelter Studio (Python)

Ты пишешь **один файл сцены** на Python для видеоредактора Shelter Studio. Редактор сам вызывает функции сцены
для каждого кадра и склеивает ролик. Ответь **только одним блоком кода** ```python ... ``` без пояснений до и после.

## Что нужно сделать
{goal.strip() or '(опишите здесь, что должно происходить в сцене)'}

- Название сцены: {name or 'New scene'}
- Длина сцены: {dur:g} секунд (параметр `dur` в функциях — используйте его, а не число)
{('- Стиль: ' + style) if style else ''}
- Проект: «{title}». Сцены ролика по порядку:
{scene_list or '(пока нет)'}

## Жёсткие правила
1. Первая строка — докстрока с кратким описанием сцены по-русски: `\"\"\"Что происходит в сцене.\"\"\"`
2. Вторая строка — `from studio.kit import *` . Больше ничего импортировать нельзя, кроме `math`, `random`
   (уже доступны `np` = numpy, `cv2` = OpenCV, `math`). Запрещены файлы, сеть, `os`, `sys`, `subprocess`, `open`, `eval`, `exec`.
3. Обязательно функция `def render(fr, t, dur):` — рисует ОДИН кадр:
   - `fr` — numpy-массив 1080×1920×3, RGB, uint8. Рисовать прямо в него (изменять на месте), ничего не возвращать.
   - `t` — секунды от начала сцены (0 … dur), `dur` — длина сцены.
   - Кадры считаются независимо и в любом порядке: НЕ храни состояние между вызовами, всё вычисляй из `t`.
   - Сначала закрась весь кадр (например `darkbg(fr)` или `cover(fr, image('...'))`), иначе останется мусор.
4. Необязательно: `def sound(a, dur):` — звуковые события сцены (см. ниже). Если своя музыка в проекте — можно `pass`.
5. Переменные в начале файла:
   - `HITS = [...]` — секунды «ударов» (тряска + вспышка), например `[0.0]`, или `[]`.
   - `AMBIENCE = (a, b)` — громкость фонового гула в начале и конце сцены 0..1, или `None` (как в прошлой сцене).
   - `WIND = (a, b)` — громкость ветра, или `None`.
6. Все надписи — только через `tx('{prefix}_имя', 'Текст по умолчанию')`: так их можно будет менять без кода.
   Ключи начинай с `{prefix}_`, чтобы они не пересеклись с другими сценами. Тексты — на языке ролика.
7. Кадр должен считаться быстро: меньше ~0.3 с. Не делай циклы по пикселям на Python — используй numpy/cv2
   и готовые функции ниже. Тяжёлое (размытие больших картинок) — через параметры `image(..., blur=)`, они кэшируются.
8. Размеры: `W, H` = 1920, 1080. {safe}
9. Цвета — кортежи RGB `(r, g, b)` 0..255. Готовые: `CREAM, EMBER, RED, WHITE, BLACK`.
10. Появление/исчезновение делай плавным (`prog`, `oc`, `ioc`, параметры `fin`/`fout` у текстов).

## Шрифты
Роли (выбираются в настройках проекта): `fam='title'` → {roles.get('title')}, `fam='serif'` → {roles.get('serif')},
`fam='text'` → {roles.get('text')}. Файлы шрифтов проекта: {', '.join(fonts) or 'нет'}.
`bold()` использует роль title, `serif()` — serif, `text()` — text. `w=` — толщина (200..700 для переменных шрифтов).

## Картинки и видео проекта (только эти имена!)
{assets_list(studio, assets)}

Видео: `frame = video('имя', t, start=0, speed=1)` возвращает кадр видео как картинку;
дальше `cover(fr, frame)` — на весь кадр, `kb(fr, frame, cx, cy, w)` — «камера» по кадру, `place(...)` — спрайтом.

## Справочник команд (from studio.kit import *)
{api_reference()}
## Готовые эффекты — одной строкой в render()
Вызывай ПОСЛЕ рисования кадра. `t0=`/`t1=` — когда эффект действует (по умолчанию — вся сцена).
{fx_reference()}

## Звук — def sound(a, dur)
Время — секунды от начала сцены, g — громкость (~0..1.5). Ноты: 'C4', 'D#3', 'Bb2'.
{sound_reference()}

## Пример сцены из этого проекта (стиль и приёмы)
```python
{example.strip()}
```

## Шаблон ответа
```python
\"\"\"Коротко: что происходит.\"\"\"
from studio.kit import *

HITS = []
AMBIENCE = None
WIND = None


def render(fr, t, dur):
    u = t / dur                 # доля сцены 0..1
    darkbg(fr)
    bold(fr, t, 0.2, dur - 0.1, tx('{prefix}_title', 'TITLE'), size=150)


def sound(a, dur):
    pass
```

Проверь перед ответом: нет лишних импортов, все имена картинок из списка выше, render ничего не возвращает,
нет состояния между кадрами, всё видно в кадре от t=0 до t=dur.
"""
    return re.sub(r'\n{3,}', '\n\n', text)


def extract_code(text):
    """Код из ответа ИИ: содержимое блока ```python ...``` или весь текст."""
    text = str(text or '').replace('\r\n', '\n')
    blocks = re.findall(r'```(?:python|py)?[ \t]*\n(.*?)```', text, re.S)
    if blocks:
        blocks.sort(key=lambda b: ('def render' in b, len(b)), reverse=True)
        return textwrap.dedent(blocks[0]).strip() + '\n'
    return text.strip() + '\n'


def static_check(code):
    """Ошибки (errors) — нельзя добавлять; предупреждения (warnings) — стоит посмотреть."""
    errors, warnings = [], []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ['Синтаксическая ошибка: %s (строка %s)' % (e.msg, e.lineno)], warnings, None
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if 'render' not in names:
        errors.append('Нет функции render(fr, t, dur)')
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            for m in mods:
                root = m.split('.')[0]
                if root in FORBIDDEN_MODULES:
                    errors.append('Запрещённый импорт «%s» (строка %d)' % (m, node.lineno))
                elif m not in ALLOWED_MODULES and root not in ALLOWED_MODULES:
                    warnings.append('Необычный импорт «%s» (строка %d)' % (m, node.lineno))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            errors.append('Запрещённый вызов %s() (строка %d)' % (node.func.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__') and node.attr not in ('__doc__', '__name__'):
            errors.append('Служебный атрибут %s (строка %d)' % (node.attr, node.lineno))
        elif isinstance(node, ast.While):
            warnings.append('Цикл while (строка %d) — убедитесь, что он заканчивается' % node.lineno)
    doc = (ast.get_docstring(tree) or '').strip().splitlines()
    return errors, warnings, (doc[0] if doc else '')


def check(studio, code, dur=4.0):
    code = extract_code(code)
    errors, warnings, doc = static_check(code)
    res = dict(code=code, errors=errors, warnings=warnings, doc=doc, frames=[])
    if errors:
        return res
    dur = max(0.2, min(600.0, float(dur or 4)))
    task = studio.base_task()
    task.update(path=os.path.join(studio.dir, 'scenes', '_ai_check.py'), code=code, dur=dur,
                times=[round(x, 3) for x in (0.05, dur * 0.25, dur * 0.5, dur * 0.75, max(0.0, dur - 0.05))])
    fut = studio.submit(engine.w_check, task, 'check')
    try:
        frames = fut.result(timeout=engine.HANG_SECONDS)
    except Exception:
        res['errors'].append('Сцена считается слишком долго (или зависла). Попросите ИИ упростить её.')
        return res
    for f in frames:
        res['frames'].append(dict(t=f['t'], ms=f['ms'], err=f['err'],
                                  jpg='data:image/jpeg;base64,' + base64.b64encode(f['jpg']).decode()))
        if f['err']:
            res['errors'].append('Ошибка при рендере (t=%.2f с):\n%s' % (f['t'], f['err']))
    slow = [f for f in frames if f['ms'] > 700]
    if slow:
        warnings.append('Медленно: до %d мс на кадр. Экспорт будет долгим — можно попросить ИИ ускорить.'
                        % max(f['ms'] for f in slow))
    return res
