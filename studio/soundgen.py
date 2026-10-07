"""Звук для сцен: автоматический генератор и обмен с ИИ.

1) Автоматически: по каждой сцене берём длину, удары (HITS), склейку с соседями, моменты появления надписей
   и слоёв — и пишем функцию sound() по правилам выбранного настроения (MOOD).
2) Через ИИ: задание со всем кодом сцен по порядку; ответ ИИ разбирается по сценам и заменяет только sound()
   (и при желании AMBIENCE / WIND), код картинки не трогается.
"""
import ast
import re

from . import ai as aimod

MOODS = {
    'epic': dict(label='Эпично', chord=['D3', 'A3', 'D4'], notes=['D5', 'A4', 'F4', 'A4'], amb=(0.5, 0.6), wind=(0.15, 0.15)),
    'tragic': dict(label='Трагично', chord=['D3', 'F3', 'A3'], notes=['A4', 'F4', 'E4', 'D4'], amb=(0.35, 0.3), wind=(0.35, 0.45)),
    'tense': dict(label='Напряжённо', chord=['D2', 'A2'], notes=['D4', 'Eb4'], amb=(0.55, 0.65), wind=(0.2, 0.25)),
    'action': dict(label='Экшен', chord=['D3', 'A3'], notes=['D4', 'F4'], amb=(0.6, 0.6), wind=(0.1, 0.1)),
    'hopeful': dict(label='Светло / надежда', chord=['D3', 'F#3', 'A3'], notes=['F#4', 'A4', 'D5', 'A4'], amb=(0.3, 0.3), wind=(0.1, 0.1)),
    'mystery': dict(label='Загадочно', chord=['D3', 'G3', 'A3'], notes=['A4', 'G4', 'D5'], amb=(0.45, 0.5), wind=(0.3, 0.3)),
    'calm': dict(label='Спокойно', chord=['D3', 'A3', 'E4'], notes=['E4', 'A4', 'F#4'], amb=(0.25, 0.25), wind=(0.2, 0.2)),
}
ORDER = ['epic', 'tragic', 'tense', 'action', 'hopeful', 'mystery', 'calm']

# слова, по которым угадываем настроение, если его не задали
_GUESS = [
    ('tragic', r'lost|loss|left|behind|leave|didn.?t|never|dead|die|grave|cry|alone|end|gone|silence|forgot|потер|умер|погиб|смерт|один|тишин|слёз|слез|утрат|не вернул'),
    ('action', r'run|fight|war|attack|scaveng|hunt|escape|fast|chase|беги|бег|бой|атак|погон|драк|вылаз'),
    ('tense', r'danger|dark|fear|alarm|warn|day \d|underground|threat|опасн|страх|тревог|угроз|подзем|темн'),
    ('hopeful', r'hope|home|build|together|light|new|family|надежд|дом|вместе|свет|семь|строй|новый'),
    ('epic', r'title|logo|finale|coming|survive|endure|shelter|легенд|финал|логотип|скоро|выжив'),
    ('mystery', r'secret|map|strange|who|unknown|signal|тайн|карта|странн|сигнал|неизвест'),
]


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _const(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def scene_mood(code, stored=None):
    """Настроение: MOOD в коде > выбор в редакторе > угадывание. Возвращает (mood, источник)."""
    try:
        tree = ast.parse(code)
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], 'id', '') == 'MOOD':
                v = _const(n.value)
                if v in MOODS:
                    return v, 'code'
    except SyntaxError:
        pass
    if stored in MOODS:
        return stored, 'set'
    return None, 'auto'


def guess_mood(text):
    t = text.lower()
    for mood, rx in _GUESS:
        if re.search(rx, t):
            return mood
    return 'tense'


def text_accents(code, dur):
    """Моменты появления надписей: t0 у вызовов text/bold/serif, если это число."""
    out = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('text', 'bold', 'serif'):
            t0 = None
            if len(n.args) >= 3:
                t0 = _num(_const(n.args[2]))
            for kw in n.keywords:
                if kw.arg == 't0':
                    t0 = _num(_const(kw.value))
            if t0 is not None and 0 <= t0 < dur - 0.15:
                out.append(round(t0, 2))
    return out


def _words(code, texts):
    """Все строки сцены (докстрока, тексты по умолчанию и из вкладки «Тексты») — для угадывания настроения."""
    words = []
    try:
        tree = ast.parse(code)
        words.append(ast.get_docstring(tree) or '')
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'tx' and n.args:
                k = _const(n.args[0])
                d = _const(n.args[1]) if len(n.args) > 1 else ''
                words.append(str(texts.get(k, d) or ''))
    except SyntaxError:
        pass
    return ' '.join(words)


def _dedupe(ts, gap=0.18):
    out = []
    for t in sorted(ts):
        if not out or t - out[-1] >= gap:
            out.append(t)
    return out


def analyze(studio):
    """Сведения о каждой сцене для генератора и для интерфейса."""
    with studio.lock:
        tl, total = studio.timeline()
        fps = studio.p['fps']
        texts = dict(studio.p['texts'])
        res = []
        for s, f0, n in tl:
            code = studio.codes.get(s['id'], '')
            dur = float(s['dur'])
            meta = studio.meta.get(s['id'], {})
            accents = text_accents(code, dur)
            for L in s.get('layers', []):
                st = float(L.get('start') or 0)
                if L.get('hidden') or st >= dur - 0.15:
                    continue
                if L['type'] == 'text':
                    accents.append(round(st + min(0.15, float(L.get('fade_in') or 0) * 0.3), 2))
                    texts_l = texts.get(L.get('key'), '')
                    code += '\n# ' + texts_l
                elif st > 0.05:
                    accents.append(round(st, 2))
            mood, src = scene_mood(code, s.get('mood'))
            guessed = guess_mood(s['name'] + ' ' + _words(code, texts))
            has_sound = bool(re.search(r'^def sound\(', code, re.M)) and not re.search(
                r'^def sound\([^)]*\):\s*\n\s+pass\s*$', code, re.M)
            res.append(dict(id=s['id'], name=s['name'], file=s['file'], dur=dur, start=round(f0 / fps, 3),
                            hits=[h for h in meta.get('hits', []) if 0 <= h < dur], accents=_dedupe(accents),
                            mood=mood or guessed, mood_src=src, guessed=guessed, has_sound=has_sound))
    return res


# ------------------------------------------------------------------ генератор
def _f(x):
    return ('%.2f' % x).rstrip('0').rstrip('.') if abs(x - round(x)) > 1e-6 else str(int(round(x)))


def generate(info, prev=None, nxt=None, music=False):
    """Код функции sound() для одной сцены. music=True — поверх своей музыки: только акценты, тише."""
    m = info['mood']
    P = MOODS[m]
    dur = info['dur']
    hits = info['hits']
    acc = [t for t in info['accents'] if all(abs(t - h) > 0.2 for h in hits)]
    L = []
    q = 0.6 if music else 1.0          # с музыкой — тише и без подложек

    def add(s):
        L.append('    ' + s)
    # подложка и ритм по длине сцены
    if not music and dur >= 1.2:
        if m in ('tragic', 'hopeful', 'calm', 'mystery', 'epic'):
            add("a.pad(0, %r, dur, %s)" % (P['chord'], {'epic': '0.06', 'tragic': '0.08', 'hopeful': '0.07',
                                                         'calm': '0.06', 'mystery': '0.07'}[m]))
        elif m == 'tense':
            add("a.pulse(0, dur, 0.18)")
        elif m == 'action':
            add("a.war_drums(0, dur, g=0.8)")
    # удары
    for h in hits:
        if m == 'epic':
            add("a.braam(%s, %s)" % (_f(h), _f(0.9 * q)))
            add("a.taiko(%s, %s)" % (_f(h), _f(0.7 * q)))
        elif m == 'action':
            add("a.taiko(%s, %s)" % (_f(h), _f(0.9 * q)))
            add("a.bass(%s, 'D2', %s)" % (_f(h), _f(0.25 * q)))
        elif m == 'tragic':
            add("a.braam(%s, %s, root=29.14)" % (_f(h), _f(0.45 * q)))
        elif m == 'tense':
            add("a.taiko(%s, %s)" % (_f(h), _f(0.6 * q)))
            add("a.tick(%s, %s)" % (_f(h), _f(0.4 * q)))
        elif m in ('hopeful', 'calm'):
            add("a.piano(%s, 'D5', %s)" % (_f(h), _f(0.2 * q)))
        else:
            add("a.tick(%s, %s)" % (_f(h), _f(0.35 * q)))
            add("a.heart(%s, %s)" % (_f(h), _f(0.6 * q)))
    # вход в сцену на склейке (если сцена не начинается с удара)
    if prev is not None and not any(h < 0.1 for h in hits):
        if m in ('action', 'tense'):
            add("a.whoosh(0, 0.4, %s)" % _f(0.3 * q))
        elif m == 'epic':
            add("a.taiko(0, %s)" % _f(0.5 * q))
    # появления надписей
    for i, t in enumerate(acc):
        if m in ('tragic', 'hopeful', 'calm', 'mystery'):
            add("a.piano(%s, %r, %s)" % (_f(t), P['notes'][i % len(P['notes'])], _f(0.18 * q)))
        elif m == 'tense':
            add("a.tick(%s, %s)" % (_f(t), _f(0.35 * q)))
        else:
            add("a.taiko(%s, %s)" % (_f(t), _f(0.45 * q)))
    # длинные сцены: мелодия / тиканье
    if not music and dur >= 4:
        if m in ('tragic', 'hopeful') and not acc:
            add("a.melody(0.3, %r, step=%s, g=0.14)" % (P['notes'], _f(min(1.0, (dur - 0.6) / len(P['notes'])))))
        elif m == 'tense':
            add("a.ticks(0.2, dur - 0.2, g=0.18)")
    # сердце в тихих драматичных сценах
    if m in ('tragic', 'tense', 'mystery') and not hits and not acc and dur >= 1.2:
        add("a.heart(0.3, %s)" % _f(0.8 * q))
    # нарастание к удару в начале следующей сцены
    if nxt is not None and dur >= 1.5 and m not in ('calm', 'tragic') and (
            any(h < 0.1 for h in nxt['hits']) or nxt['mood'] in ('epic', 'action')):
        add("a.riser(max(0, dur - 1.4), 1.4, %s)" % _f(0.35 * q))
    head = '    # авто-звук · %s%s%s' % (P['label'].lower(),
                                        (' · удары: ' + ', '.join(_f(h) for h in hits)) if hits else '',
                                        (' · надписи: ' + ', '.join(_f(t) for t in acc)) if acc else '')
    if not L:
        L = ['    pass']
    return 'def sound(a, dur):\n' + head + '\n' + '\n'.join(L) + '\n'


def _replace_top(code, name, new_text, kind='func'):
    """Заменить функцию или присваивание верхнего уровня; если нет — добавить."""
    tree = ast.parse(code)
    lines = code.split('\n')
    for n in tree.body:
        hit = (kind == 'func' and isinstance(n, ast.FunctionDef) and n.name == name) or (
            kind == 'assign' and isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], 'id', '') == name)
        if hit:
            a = n.lineno - 1 - (len(n.decorator_list) if kind == 'func' else 0)
            b = n.end_lineno
            new = lines[:a] + new_text.rstrip('\n').split('\n') + lines[b:]
            return '\n'.join(new)
    if kind == 'func':
        return code.rstrip('\n') + '\n\n\n' + new_text.rstrip('\n') + '\n'
    # присваивание — после импорта kit (или в начало)
    idx = 0
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)) or (isinstance(n, ast.Expr) and isinstance(getattr(n, 'value', None), ast.Constant)):
            idx = n.end_lineno
        else:
            break
    return '\n'.join(lines[:idx] + [new_text] + lines[idx:])


def apply_sound(code, func_code, amb=None, wind=None, mood=None):
    """Новый код сцены: заменена sound() (и по желанию AMBIENCE / WIND / MOOD)."""
    code = _replace_top(code, 'sound', func_code, 'func')
    if amb is not None:
        code = _replace_top(code, 'AMBIENCE', 'AMBIENCE = %s' % (amb,), 'assign')
    if wind is not None:
        code = _replace_top(code, 'WIND', 'WIND = %s' % (wind,), 'assign')
    if mood is not None:
        code = _replace_top(code, 'MOOD', "MOOD = %r            # настроение звука: %s" % (mood, ', '.join(ORDER)), 'assign')
    return code if code.endswith('\n') else code + '\n'


def plan(studio, moods=None, only=None):
    """Сгенерированный звук для сцен (без записи). moods — {sid: mood} из интерфейса."""
    info = analyze(studio)
    for it in info:
        if moods and moods.get(it['id']) in MOODS:
            it['mood'] = moods[it['id']]
    music = bool(studio.p['audio'].get('music_file'))      # своя музыка есть — звук сцен сдержаннее
    out = []
    for i, it in enumerate(info):
        if only and it['id'] not in only:
            continue
        code = generate(it, info[i - 1] if i else None, info[i + 1] if i + 1 < len(info) else None, music)
        out.append(dict(it, code=code))
    return out


def apply_generated(studio, moods=None, only=None, set_levels=True):
    from . import versions
    items = plan(studio, moods, only)
    if not items:
        return 0
    versions.create(studio, 'Перед генерацией звука', auto=True)
    n = 0
    for it in items:
        with studio.lock:
            s = studio.scene(it['id'])
            s['mood'] = it['mood']
            old = studio.codes[it['id']]
        P = MOODS[it['mood']]
        try:
            new = apply_sound(old, it['code'], P['amb'] if set_levels else None, P['wind'] if set_levels else None)
            ast.parse(new)
        except SyntaxError:
            continue
        if new != old:
            studio.save_code(it['id'], new)
            n += 1
    studio.save()
    return n


def set_mood(studio, sid, mood):
    with studio.lock:
        s = studio.scene(sid)
        s['mood'] = mood if mood in MOODS else None
    studio.save()


# ------------------------------------------------------------------ через ИИ
SAFE_CALLS = {'range', 'min', 'max', 'abs', 'round', 'len', 'enumerate', 'int', 'float', 'zip', 'list', 'reversed',
              'sorted', 'sum', 'lerp', 'clamp', 'prog'}


def check_sound(chunk_tree, func):
    """В ответе ИИ: никаких импортов; внутри sound — только a.… и безопасные функции."""
    errs = []
    for n in ast.walk(chunk_tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            errs.append('Импорт не нужен и запрещён (строка %d)' % n.lineno)
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            f = n.func
            ok = (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'a') or \
                 (isinstance(f, ast.Name) and f.id in SAFE_CALLS)
            if not ok:
                errs.append('Недопустимый вызов в sound() (строка %d) — можно только a.…' % n.lineno)
        elif isinstance(n, ast.Attribute) and n.attr.startswith('_'):
            errs.append('Служебный атрибут %s' % n.attr)
    return errs

MARK = re.compile(r'^\s*#\s*={2,}\s*scene\s*:\s*(\S+?)\s*={2,}\s*$', re.M | re.I)


def brief(studio):
    """Задание для ИИ: весь ролик по порядку + правила. Ответ — блоки «# === scene: файл.py ===» с def sound."""
    info = analyze(studio)
    with studio.lock:
        title = studio.p.get('title', '')
        music = studio.p['audio'].get('music_file')
        gen_on = studio.p['audio'].get('generated', True)
        codes = {s['id']: studio.codes.get(s['id'], '') for s in studio.p['scenes']}
        texts = dict(studio.p['texts'])
    total = sum(i['dur'] for i in info)
    parts = []
    for i, it in enumerate(info):
        code = codes[it['id']]
        used = sorted({m.group(2) for m in re.finditer(r"""\btx\(\s*(['"])(\w+)\1""", code)})
        tv = '\n'.join('#   %s = %r' % (k, texts[k]) for k in used if k in texts)
        parts.append('### %d. %s — файл `%s`\nНачало в ролике: %.2f с · длина: %.2f с · удары HITS: %s · надписи появляются: %s\n'
                     'Настроение (подсказка): %s\n%s```python\n%s\n```' % (
                         i + 1, it['name'], it['file'], it['start'], it['dur'], it['hits'] or '—', it['accents'] or '—',
                         MOODS[it['mood']]['label'], ('Тексты на экране:\n```\n%s\n```\n' % tv) if tv else '', code.strip()))
    music_note = ('В проекте есть своя музыка (%s) — звук сцен должен быть сдержанным: акценты и удары, '
                  'без громких подложек.' % music) if music else 'Своей музыки нет — саундтрек целиком состоит из sound() сцен.'
    if not gen_on:
        music_note += ' Сейчас сгенерированный звук выключен в настройках — его нужно будет включить.'
    return """# Задание: звук для всех сцен ролика «%s» (%.1f с, сцен: %d)

Ты — звукорежиссёр трейлера. Ниже весь ролик по порядку: код каждой сцены (render рисует картинку, sound — звук),
её место в ролике, удары и моменты появления надписей. Напиши НОВУЮ функцию `sound(a, dur)` для КАЖДОЙ сцены так,
чтобы весь ролик звучал как единый саундтрек в одном стиле: общая тональность (ре минор, D), нарастание к кульминации,
удары точно на HITS и на склейках, мягкие акценты на появлении надписей, тишина там, где нужна пауза.
%s

## Формат ответа — строго так, для каждой сцены по порядку
```python
# === scene: имя_файла.py ===
AMBIENCE = (0.4, 0.5)   # необязательно: фоновый гул в начале и конце сцены 0..1, None — как у прошлой
WIND = (0.1, 0.2)       # необязательно: ветер
def sound(a, dur):
    a.braam(0, 0.9)
    ...
```
- Разделитель `# === scene: файл.py ===` обязателен (имя файла — как в заголовках ниже). Можно одним блоком кода на всё.
- Только функция sound и (по желанию) AMBIENCE / WIND. НЕ присылай render и HITS — картинку не трогаем.
- Внутри sound — только вызовы `a.…` из справочника, числа, циклы и `dur`. Никаких импортов, файлов, print.
- Время — секунды от начала сцены (0 … dur). Звук может звучать ещё до 6 с после конца сцены (хвосты).
- Громкости g: удары 0.6–1.3, барабаны 0.4–1.0, пианино 0.12–0.3, подложки pad 0.04–0.1, pulse 0.12–0.25.
  Не перегружай: 3–8 событий на сцену обычно достаточно.

## Справочник звуков (объект a)
%s

## Сцены по порядку
%s
""" % (title, total, len(info), music_note, aimod.sound_reference(), '\n\n'.join(parts))


def parse_answer(studio, text):
    """Разобрать ответ ИИ: [{file, id, name, code (новый код сцены), ok, error}]."""
    text = str(text or '').replace('\r\n', '\n')
    blocks = re.findall(r'```(?:python|py)?[ \t]*\n(.*?)```', text, re.S)
    body = '\n'.join(blocks) if blocks else text
    marks = list(MARK.finditer(body))
    with studio.lock:
        by_file = {s['file']: s for s in studio.p['scenes']}
        codes = dict(studio.codes)
    out = []
    for i, m in enumerate(marks):
        fn = m.group(1).strip('`\'"')
        chunk = body[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        s = by_file.get(fn) or by_file.get(fn + '.py')
        row = dict(file=fn, id=s['id'] if s else None, name=s['name'] if s else fn, ok=False, error=None)
        if not s:
            row['error'] = 'Нет такой сцены в проекте'
            out.append(row)
            continue
        try:
            tree = ast.parse(chunk)
        except SyntaxError as e:
            row['error'] = 'Ошибка в коде: %s (строка %s)' % (e.msg, e.lineno)
            out.append(row)
            continue
        func = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'sound'), None)
        if func is None:
            row['error'] = 'Нет функции sound(a, dur)'
            out.append(row)
            continue
        bad = check_sound(tree, func)
        if bad:
            row['error'] = '; '.join(sorted(set(bad)))
            out.append(row)
            continue
        lines = chunk.split('\n')
        func_code = '\n'.join(lines[func.lineno - 1:func.end_lineno])
        amb = wind = None
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], 'id', '') in ('AMBIENCE', 'WIND'):
                seg = ast.get_source_segment(chunk, n.value)
                if n.targets[0].id == 'AMBIENCE':
                    amb = seg
                else:
                    wind = seg
        new = apply_sound(codes[s['id']], func_code, amb, wind)
        errs, warns, _ = aimod.static_check(new)
        if errs:
            row['error'] = '; '.join(errs)
        else:
            row.update(ok=True, code=new, sound=func_code, events=func_code.count('a.'))
        out.append(row)
    return out


def apply_answer(studio, text):
    from . import versions
    rows = parse_answer(studio, text)
    good = [r for r in rows if r['ok']]
    if good:
        versions.create(studio, 'Перед звуком от ИИ', auto=True)
        for r in good:
            studio.save_code(r['id'], r['code'])
    return rows
