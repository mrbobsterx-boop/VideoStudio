"""Подгонка сцен под живой голос (пакет озвучки Glimpsy: voice/voice.wav + voice/words.json).

    plan = voicefit.plan(project_dir)          # ничего не меняет: новые длины, warp, отчёт
    voicefit.apply(studio, plan)               # записать в project.json (перед этим — версия проекта)

Шаги:
1. Текст сцен и «якоря» битов — из scenes.md проекта (карточки `### SNN · … `sNN_*.py``, строка **Озвучка**,
   таблица битов «| 0.0–4.3 | ТИП | На словах «…» …»). Нет scenes.md — абзацы script.md по порядку, без якорей.
   Разбор сохраняется в voice/script_map.json.
2. Весь текст сценария выравнивается со словами words.json: точные совпадения (difflib) + в промежутках —
   взвешенное выравнивание с нечётким сравнением слов (whisper путает окончания и имена). Числа — словами.
3. Новые длины: начало сцены = её первое слово − 0.25 с (не раньше конца прошлой речи), длина = до начала
   следующей; последняя — до конца голоса + её «хвост». Сцены без текста сохраняют длину.
4. Время внутри сцены: warp [[t_new, t_src], …] — кусочно-линейно, наклон 0.5…2.0, монотонно. Код сцены
   по-прежнему получает старое время и старую длину (dur_src).

Формат пакета — VOICE-GLIMPSY-PROMPT (format: glimpsy-voice, version 1). Неизвестные поля игнорируются.
"""
import difflib
import json
import os
import re

LEAD = 0.25            # сцена начинается чуть раньше первого слова
SLOPE = (0.5, 2.0)     # допустимый наклон warp (скорость времени сцены)
OLD_WPM = 140.0        # темп, по которому считались старые тайминги
WEAK = 0.60            # доля совпавших слов, ниже которой сопоставление считается слабым
FILLERS = {'э', 'ээ', 'эээ', 'эм', 'эмм', 'м', 'мм', 'ммм', 'ну', 'короче', 'типа', 'ааа', 'аа'}


# ================================================================ нормализация и числа
_U = ['ноль', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять', 'десять', 'одиннадцать',
      'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать', 'шестнадцать', 'семнадцать', 'восемнадцать',
      'девятнадцать']
_T = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто']
_H = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот', 'восемьсот', 'девятьсот']


def _num_words(n):
    """Целое → слова (именительный, мужской род): 2325 → две тысячи триста двадцать пять."""
    n = int(n)
    if n < 20:
        return [_U[n]]
    if n < 100:
        return [_T[n // 10]] + ([_U[n % 10]] if n % 10 else [])
    if n < 1000:
        return [_H[n // 100]] + (_num_words(n % 100) if n % 100 else [])
    if n < 1000000:
        th, r = divmod(n, 1000)
        w = _num_words(th)
        if th % 100 not in range(11, 20) and th % 10 in (1, 2):
            w[-1] = {'один': 'одна', 'два': 'две'}[w[-1]]
        k = th % 100
        form = 'тысяч' if 11 <= k <= 19 or th % 10 in (0, 5, 6, 7, 8, 9) else ('тысяча' if th % 10 == 1 else 'тысячи')
        return w + [form] + (_num_words(r) if r else [])
    return [str(n)]


def norm_tokens(text):
    """Текст → нормализованные слова: нижний регистр, ё→е, без пунктуации, числа словами."""
    text = str(text).lower().replace('ё', 'е').replace('%', ' процентов ')
    text = re.sub(r'[‐-―—–/]', ' ', text)
    out = []
    for raw in text.split():
        for part in re.findall(r'\d+(?:[.,]\d+)?|[^\W\d_]+(?:[-\'’][^\W\d_]+)*', raw):
            if part[0].isdigit():
                for p in re.split(r'[.,]', part):
                    if p:
                        out += _num_words(p) if len(p) <= 6 else [p]
            else:
                out.append(re.sub(r'[-\'’]', '', part))
    return out


def _sim(a, b):
    """Похожесть слов 0..1 (whisper ошибается в окончаниях и именах)."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if min(la, lb) >= 4:
        k = 0
        while k < min(la, lb) and a[k] == b[k]:
            k += 1
        if k >= max(3, min(la, lb) - 2):
            return 0.85
    if abs(la - lb) > max(la, lb) * 0.5:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return r * 0.9 if r >= 0.72 else 0.0


# ================================================================ разбор сценария
_CARD = re.compile(r'^###\s+(S\d+)\b.*?`([^`]+\.py)`', re.M)
_VOICE = re.compile(r'^\*\*Озвучка\*\*[^:]*:\s*«(.*)»\s*$', re.M)
_BIT = re.compile(r'^\|\s*(\d+(?:[.,]\d+)?)\s*[–—-]\s*(\d+(?:[.,]\d+)?)\s*\|(.*)$', re.M)
_ANCHOR = re.compile(r'На\s+(?:словах\s+)?[«„"“]([^»“"”]+)[»“"”]')


def parse_scenes_md(path):
    """scenes.md → {файл сцены: dict(id, text, bits=[dict(t, phrase)])}."""
    with open(path, 'r', encoding='utf-8') as f:
        md = f.read()
    heads = list(_CARD.finditer(md))
    out = {}
    for i, m in enumerate(heads):
        body = md[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(md)]
        v = _VOICE.search(body)
        bits = []
        for b in _BIT.finditer(body):
            t0 = float(b.group(1).replace(',', '.'))
            a = _ANCHOR.search(b.group(3))
            phrase = a.group(1).strip(' .…,') if a else None
            bits.append(dict(t=t0, t1=float(b.group(2).replace(',', '.')), phrase=phrase or None))
        out[m.group(2)] = dict(id=m.group(1), text=v.group(1).strip() if v else '', bits=bits)
    return out


def parse_script_md(path):
    """script.md → абзацы текста озвучки (без заголовков, ремарок [..] и списков)."""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')
    paras, cur = [], []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(('#', '[', '-', '*', '|', '>', '---')):
            if cur:
                paras.append(' '.join(cur))
                cur = []
            continue
        cur.append(re.sub(r'\[[^\]]*\]', '', s).strip())
    if cur:
        paras.append(' '.join(cur))
    return [p for p in paras if p]


def script_map(project_dir, scenes):
    """Текст и якоря каждой сцены проекта (по имени файла). Пишется в voice/script_map.json."""
    md = os.path.join(project_dir, 'scenes.md')
    src = None
    per = {}
    if os.path.isfile(md):
        per = parse_scenes_md(md)
        src = 'scenes.md'
    out = []
    missing = [s for s in scenes if s['file'] not in per]
    paras = []
    if missing and os.path.isfile(os.path.join(project_dir, 'script.md')):
        paras = parse_script_md(os.path.join(project_dir, 'script.md'))
        src = src or 'script.md'
    pi = 0
    for s in scenes:
        e = per.get(s['file'])
        if e is not None:
            out.append(dict(id=s['id'], file=s['file'], text=e['text'], bits=e['bits']))
        elif paras and not per:
            out.append(dict(id=s['id'], file=s['file'], text=paras[pi] if pi < len(paras) else '', bits=[]))
            pi += 1
        else:
            out.append(dict(id=s['id'], file=s['file'], text='', bits=[]))
    if paras and not per and pi < len(paras) and out:
        out[-1]['text'] = (out[-1]['text'] + ' ' + ' '.join(paras[pi:])).strip()
    res = dict(source=src, scenes=out)
    vd = os.path.join(project_dir, 'voice')
    try:
        os.makedirs(vd, exist_ok=True)
        with open(os.path.join(vd, 'script_map.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return res


# ================================================================ пакет озвучки
def load_words(path):
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    if d.get('format') not in (None, 'glimpsy-voice'):
        raise ValueError('Это не пакет озвучки Glimpsy (format=%s)' % d.get('format'))
    words = []
    for w in d.get('words') or []:
        try:
            words.append((str(w['w']), float(w['start']), float(w['end'])))
        except (KeyError, TypeError, ValueError):
            continue
    words.sort(key=lambda x: x[1])
    if not words:
        raise ValueError('В words.json нет слов')
    return d, words


def find_package(project_dir):
    """voice/words.json и аудио из него (или voice/voice.wav)."""
    vd = os.path.join(project_dir, 'voice')
    wj = os.path.join(vd, 'words.json')
    if not os.path.isfile(wj):
        return None, None
    audio = 'voice.wav'
    try:
        with open(wj, 'r', encoding='utf-8') as f:
            audio = json.load(f).get('audio') or audio
    except (OSError, ValueError):
        pass
    ap = os.path.join(vd, os.path.basename(str(audio)))
    if not os.path.isfile(ap):
        alt = [f for f in sorted(os.listdir(vd)) if f.lower().startswith('voice.') and
               f.lower().endswith(('.wav', '.flac', '.mp3', '.m4a', '.ogg', '.aac'))]
        ap = os.path.join(vd, alt[0]) if alt else None
    return wj, ap


# ================================================================ выравнивание
def align(script_tokens, voice_tokens):
    """Индекс слова голоса для каждого слова сценария (или None) и оценка совпадения (0..1)."""
    n, m = len(script_tokens), len(voice_tokens)
    match = [None] * n
    score = [0.0] * n
    sm = difflib.SequenceMatcher(None, script_tokens, voice_tokens, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2 or (b.size == 1 and len(script_tokens[b.a]) >= 6)]
    blocks = [b for b in blocks if b.size]
    pa = pb = 0
    for b in blocks + [difflib.Match(n, m, 0)]:
        _fill_gap(script_tokens, voice_tokens, pa, b.a, pb, b.b, match, score)
        for k in range(b.size):
            match[b.a + k] = b.b + k
            score[b.a + k] = 1.0
        pa, pb = b.a + b.size, b.b + b.size
    return match, score


def _fill_gap(S, V, a0, a1, b0, b1, match, score):
    """Промежуток без точных совпадений: взвешенный LCS с нечётким сравнением слов."""
    na, nb = a1 - a0, b1 - b0
    if na <= 0 or nb <= 0 or na * nb > 2500000:
        return
    import numpy as np
    sim = np.zeros((na, nb), np.float32)
    for i in range(na):
        si = S[a0 + i]
        for j in range(nb):
            sim[i, j] = _sim(si, V[b0 + j])
    sim[sim < 0.6] = 0
    dp = np.zeros((na + 1, nb + 1), np.float32)
    for i in range(1, na + 1):
        row, prev, s = dp[i], dp[i - 1], sim[i - 1]
        for j in range(1, nb + 1):
            v = prev[j - 1] + s[j - 1] if s[j - 1] > 0 else -1.0
            row[j] = max(prev[j], row[j - 1], v)
    i, j = na, nb
    while i > 0 and j > 0:
        s = sim[i - 1, j - 1]
        if s > 0 and dp[i, j] == dp[i - 1, j - 1] + s:
            match[a0 + i - 1] = b0 + j - 1
            score[a0 + i - 1] = float(s)
            i -= 1
            j -= 1
        elif dp[i, j] == dp[i, j - 1]:        # при равенстве — более позднее слово сценария
            j -= 1
        else:
            i -= 1


def _wnorm(w):
    t = norm_tokens(w)
    return t[0] if len(t) == 1 else ' '.join(t)


def token_times(match, words):
    """Время (начало, конец) каждого слова сценария. Несовпавшие слова между двумя совпавшими:
    если в голосе на этом месте столько же «лишних» слов (whisper ошибся) — пара по порядку;
    если слов в голосе нет (автор пропустил) — нулевой длины вплотную к следующему слову;
    иначе — равномерно по времени тех слов голоса. Возвращает (начала, концы, точность: 2 — совпало,
    1 — по соседству, 0 — оценка)."""
    n = len(match)
    st = [0.0] * n
    en = [0.0] * n
    q = [0] * n
    known = [i for i in range(n) if match[i] is not None]
    if not known:
        return st, en, q
    for i in known:
        st[i], en[i], q[i] = words[match[i]][1], words[match[i]][2], 2
    bounds = [None] + known + [None]
    for prv, nxt in zip(bounds, bounds[1:]):
        lo = 0 if prv is None else prv + 1
        hi = n if nxt is None else nxt
        if hi <= lo:
            continue
        run = list(range(lo, hi))
        v0 = 0 if prv is None else match[prv] + 1
        v1 = len(words) if nxt is None else match[nxt]
        free = list(range(v0, v1))
        free = [k for k in free if _wnorm(words[k][0]) not in FILLERS]
        if prv is None and nxt is not None:
            free = free[-len(run):]              # до первого совпадения: ближайшие к нему слова
        elif nxt is None and prv is not None:
            free = free[:len(run)]
        if free and len(free) == len(run):
            for i, k in zip(run, free):
                st[i], en[i], q[i] = words[k][1], words[k][2], 1
        elif free:
            a, b = words[free[0]][1], words[free[-1]][2]
            for j, i in enumerate(run):
                st[i] = a + (b - a) * j / len(run)
                en[i] = a + (b - a) * (j + 1) / len(run)
        elif nxt is not None:
            for i in run:
                st[i] = en[i] = st[nxt]
        else:
            for i in run:
                st[i] = en[i] = en[prv]
    return st, en, q


def _find_phrase(tokens, phrase_tokens, lo, hi):
    """Позиция фразы-якоря в словах сцены (с lo), по первым словам; None — не нашли уверенно."""
    k = min(4, len(phrase_tokens))
    if not k:
        return None
    best, bi = 0.0, None
    for i in range(lo, max(lo, hi - k + 1)):
        s = sum(_sim(tokens[i + j], phrase_tokens[j]) for j in range(k)) / k
        if s > best + 1e-6:
            best, bi = s, i
            if s >= 0.999:
                break
    return bi if best >= 0.7 else None


# ================================================================ план
def warp_eval(warp, t):
    """t_new → t_src по точкам warp (кусочно-линейно)."""
    if not warp:
        return t
    if t <= warp[0][0]:
        return warp[0][1] + (t - warp[0][0])
    for (x0, y0), (x1, y1) in zip(warp, warp[1:]):
        if t <= x1:
            return y0 + (y1 - y0) * (t - x0) / max(1e-9, x1 - x0)
    return warp[-1][1] + (t - warp[-1][0])


def warp_inverse(warp, ts):
    """t_src → t_new (для HITS и отображения)."""
    if not warp:
        return ts
    inv = [[b, a] for a, b in warp]
    return warp_eval(inv, ts)


def _build_warp(points, dur, dur_src):
    """(0,0) + якоря + (dur, dur_src) с ограничением наклона; плохие якоря пропускаются."""
    lo, hi = SLOPE
    pts = [(0.0, 0.0)]
    used = []
    for tn, ts, bi in sorted(points):
        x0, y0 = pts[-1]
        if tn <= x0 + 0.05 or ts <= y0 + 0.05 or tn >= dur - 0.05 or ts >= dur_src - 0.05:
            continue
        sl = (ts - y0) / (tn - x0)
        if not (lo <= sl <= hi):
            continue
        pts.append((tn, ts))
        used.append(bi)
    x0, y0 = pts[-1]
    sl = (dur_src - y0) / max(1e-9, dur - x0)
    if sl > hi:                      # голос заметно быстрее: сцена доигрывает с наклоном 2 и обрезается
        pts.append((dur, y0 + hi * (dur - x0)))
    elif sl < lo:                    # голос заметно медленнее: наклон 0.5, потом последний кадр стоит
        pts.append((x0 + (dur_src - y0) / lo, dur_src))
        pts.append((dur, dur_src))
    else:
        pts.append((dur, dur_src))
    if len(pts) == 2 and abs(dur - dur_src) < 1e-6:
        return None, used
    return [[round(a, 4), round(b, 4)] for a, b in pts], used


def plan(project_dir, words_path=None):
    """Посчитать подгонку (без изменений проекта). Возвращает dict(scenes=[…], voice, total, …)."""
    with open(os.path.join(project_dir, 'project.json'), 'r', encoding='utf-8') as f:
        proj = json.load(f)
    fps = float(proj.get('fps', 30))
    scenes = proj['scenes']
    if words_path is None:
        words_path, _ = find_package(project_dir)
        if not words_path:
            raise FileNotFoundError('Нет voice/words.json — положите пакет озвучки Glimpsy в папку voice/ проекта')
    meta, words = load_words(words_path)
    smap = script_map(project_dir, scenes)['scenes']
    # все слова сценария подряд, с номером сцены
    S, owner = [], []
    spans = []
    for i, e in enumerate(smap):
        toks = norm_tokens(e['text'])
        spans.append((len(S), len(S) + len(toks)))
        S += toks
        owner += [i] * len(toks)
    V = []
    vmap = []
    for k, (w, a, b) in enumerate(words):
        for t in norm_tokens(w) or ['']:
            V.append(t)
            vmap.append(k)
    match_v, score = align(S, V)
    match = [vmap[k] if k is not None else None for k in match_v]
    st, en, tq = token_times(match, words)
    voice_end = words[-1][2]

    def src_dur(s):
        return float(s.get('dur_src') or s['dur'])

    # ведущие сцены без текста (заставка) — голос сдвигается на их длину
    offset = 0.0
    for i, s in enumerate(scenes):
        if spans[i][1] > spans[i][0]:
            break
        offset += src_dur(s)
    offset = round(offset * fps) / fps
    starts = [0.0] * len(scenes)
    rows = []
    last_voiced = max((i for i in range(len(scenes)) if spans[i][1] > spans[i][0]), default=-1)
    if last_voiced < 0:
        raise ValueError('Не нашлось текста сцен: нет scenes.md / script.md с озвучкой')
    prev_word_end = 0.0
    last_start = 0.0
    for i, s in enumerate(scenes):
        a, b = spans[i]
        if i == 0:
            starts[i] = 0.0
        elif a < b:
            first = st[a] + offset
            starts[i] = max(first - LEAD, prev_word_end, last_start + 0.5)
        else:
            starts[i] = None                # сцена без слов — поставим ниже
        if starts[i] is not None:
            last_start = starts[i]
        if a < b:
            prev_word_end = en[b - 1] + offset
    # сцены без слов: стоят перед следующей сценой с текстом, сохраняя длину (если хватает места)
    for i, s in enumerate(scenes):
        if starts[i] is not None:
            continue
        j = next((k for k in range(i + 1, len(scenes)) if starts[k] is not None), None)
        if j is None or j > last_voiced:
            starts[i] = None
            continue
        need = sum(src_dur(scenes[k]) for k in range(i, j))
        prev = starts[i - 1] if i else 0.0
        starts[i] = max(prev + 0.5, starts[j] - need)
    # хвост последней сцены с текстом и сцены после неё
    ls = scenes[last_voiced]
    a, b = spans[last_voiced]
    old_speech = (b - a) / (OLD_WPM / 60.0)
    tail = max(1.0, src_dur(ls) - old_speech)
    t_end = voice_end + offset + tail
    for i in range(last_voiced + 1, len(scenes)):
        starts[i] = t_end if starts[i] is None else starts[i]
        t_end += src_dur(scenes[i])
    # в кадры
    fr = [int(round(x * fps)) for x in starts] + [int(round(t_end * fps))]
    for i in range(1, len(fr)):
        fr[i] = max(fr[i], fr[i - 1] + 1)
    total = fr[-1] / fps
    weak = []
    for i, s in enumerate(scenes):
        a, b = spans[i]
        n_new = fr[i + 1] - fr[i]
        dur = n_new / fps
        dsrc = src_dur(s)
        start = fr[i] / fps
        bits = smap[i]['bits']
        anchors = [x for x in bits if x['phrase']]
        pts = []
        found = 0
        lo = a
        for bi, x in enumerate(anchors):
            ptoks = norm_tokens(x['phrase'])
            pos = _find_phrase(S, ptoks, lo, b) if a < b else None
            if pos is None or tq[pos] == 0:
                continue
            found += 1
            lo = pos + 1
            tn = st[pos] + offset - start
            pts.append((tn, float(x['t']), bi))
        warp, used = _build_warp(pts, dur, dsrc)
        ratio = (sum(1 for k in range(a, b) if score[k] > 0) / (b - a)) if b > a else None
        anchor_rows = []
        for tn, ts, bi in pts:
            anchor_rows.append(dict(phrase=anchors[bi]['phrase'], t_src=ts, t_new=round(tn, 3), used=bi in used))
        row = dict(id=s['id'], name=s.get('name', s['id']), file=s['file'], start=round(start, 3),
                   dur_old=round(float(s['dur']), 3), dur_src=round(dsrc, 3), dur=round(dur, 3), warp=warp,
                   words=b - a, matched=ratio, anchors=len(anchors), found=found, used=len(used),
                   anchor_rows=anchor_rows, first_word=round(st[a] + offset, 3) if a < b else None,
                   weak=ratio is not None and ratio <= WEAK)
        if row['weak']:
            weak.append(dict(id=s['id'], name=row['name'], at=row['first_word'] or start))
        rows.append(row)
    return dict(scenes=rows, total=round(total, 3), voice_end=round(voice_end, 3), voice_offset=offset,
                tail=round(tail, 3), words=len(words), script_words=len(S),
                matched=round(sum(1 for x in score if x > 0) / max(1, len(S)), 3), weak=weak, fps=fps,
                language=meta.get('language'), words_path=words_path, source=smap and 'scenes')


def apply(studio, p, audio_rel=None):
    """Записать подгонку в проект (перед этим — версия проекта для отмены). Возвращает id версии."""
    from . import versions
    vid = None
    try:
        vid = versions.create(studio, 'Перед подгонкой под голос', auto=False)
        vid = vid.get('id') if isinstance(vid, dict) else vid
    except Exception:
        pass
    by_id = {r['id']: r for r in p['scenes']}
    with studio.lock:
        for s in studio.p['scenes']:
            r = by_id.get(s['id'])
            if r is None:
                continue
            s['dur_src'] = r['dur_src']
            s['dur'] = r['dur']
            if r['warp']:
                s['warp'] = r['warp']
            else:
                s.pop('warp', None)
            if abs(s['dur'] - s['dur_src']) < 1e-6 and not r['warp']:
                s.pop('dur_src', None)
        A = studio.p['audio']
        if audio_rel:
            A['voice_file'] = audio_rel
        A.setdefault('voice_volume', 1.0)
        A['voice_on'] = True
        A['voice_offset'] = p.get('voice_offset', 0.0)
        A['voice_fit'] = dict(words=os.path.relpath(p['words_path'], studio.dir).replace(os.sep, '/'),
                              total=p['total'], matched=p['matched'])
    studio.invalidate()
    studio._audio_dirty.set()
    studio.save(now=True)
    return vid
