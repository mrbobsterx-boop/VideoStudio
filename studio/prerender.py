"""«Подготовка»: тяжёлое считается один раз до рендера и кладётся в <проект>/cache/, сцены берут готовое.

    python -m studio.prerender <папка проекта> [--force]

1. 3D-модели: какие ракурсы нужны сценам (`model(...)`), — рендер PyVista в cache/models/.
2. Скрипты <проект>/prerender/*.py:
   - с `from manim import …` — каждая сцена Manim рендерится кадрами PNG с прозрачностью
     в cache/manim/<ИмяСцены>/ (в сцене ролика: `place(fr, video('cache/manim/Chart', t), …)`);
     шрифты проекта регистрируются для Pango, LaTeX не нужен (только Text, без MathTex);
   - остальные — обычный Python (облёты, тяжёлые размытия …), помощники — в этом модуле:
     `from studio import prerender as P; P.cache('blur/bg.png')`.
   Скрипт пересчитывается, только если он (или шрифты) изменился; --force — всё заново.

Скрипты prerender/ — это обычный Python с полным доступом к компьютеру (не сцены): запускайте только свои проекты.
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.environ.get('STUDIO_PROJECT', '')


# ------------------------------------------------------------------ помощники для скриптов prerender/*.py
def cache(rel=''):
    """Абсолютный путь внутри <проект>/cache/ (папки создаются). В сцене этот файл — 'cache/<rel>'."""
    p = os.path.join(PROJECT or '.', 'cache', *str(rel).replace('\\', '/').split('/'))
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p


def asset(rel):
    """Абсолютный путь к файлу из <проект>/assets/."""
    return os.path.join(PROJECT or '.', 'assets', *str(rel).replace('\\', '/').split('/'))


def save_frames(name, frames, fps=30):
    """Сохранить кадры (numpy RGB/RGBA) как последовательность PNG: в сцене — video('cache/<name>', t)."""
    import cv2
    d = cache(name)
    for f in os.listdir(d):
        if f.endswith('.png'):
            os.remove(os.path.join(d, f))
    n = 0
    for i, fr in enumerate(frames):
        code = cv2.COLOR_RGBA2BGRA if fr.shape[2] == 4 else cv2.COLOR_RGB2BGR
        cv2.imwrite(os.path.join(d, '%05d.png' % i), cv2.cvtColor(fr, code))
        n += 1
    with open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(fps=fps, frames=n), f)
    return d


def orbit(name, elevation=15.0, zoom=1.0, light='studio', size=None, shadow=True, floor=True, up=None, step=2,
          frame=(1920, 1080), log=print):
    """Заранее отрендерить полный облёт модели (те же параметры, что у model() в сцене)."""
    from . import kit, model3d
    kit.PROJECT = PROJECT
    kit.ASSET_DIRS = [os.path.join(PROJECT, 'assets')]
    kit.set_frame(*frame)
    spec, key = kit.model_spec(name, elevation, zoom, light, size, shadow, floor, up, step)
    if spec is None:
        raise FileNotFoundError('Нет модели %s в assets/models/' % name)
    return model3d.render_spec(spec, os.path.join(PROJECT, 'cache', 'models', key), list(range(0, 360, spec['step'])), log)


# ------------------------------------------------------------------ проект
def _project(project_dir):
    with open(os.path.join(project_dir, 'project.json'), 'r', encoding='utf-8') as f:
        return json.load(f)


def _frame_size(p):
    from . import kit
    return kit.FORMATS.get(p.get('format', '16:9'), (1920, 1080))


def _font_files(project_dir):
    from . import engine
    out = []
    for d in engine.project_dirs(project_dir, 'fonts'):
        if os.path.isdir(d):
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(('.ttf', '.otf'))]
    return out


def _sig_fonts(project_dir):
    return ';'.join('%s:%d' % (os.path.basename(f), os.path.getsize(f)) for f in _font_files(project_dir))


def scripts(project_dir):
    d = os.path.join(project_dir, 'prerender')
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith('.py') and not f.startswith('_')]


def _is_manim(code):
    return 'from manim' in code or 'import manim' in code


def manim_scenes(code):
    """Классы-сцены Manim в файле (по коду, без запуска)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out = []
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            for b in n.bases:
                nm = b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else '')
                if nm.endswith('Scene'):
                    out.append(n.name)
                    break
    return out


def _manim_opts(code):
    """RESOLUTION = (w, h) и FPS = 30 в начале файла — необязательно."""
    res, fps = None, 30
    try:
        for n in ast.parse(code).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                v = ast.literal_eval(n.value) if isinstance(n.value, (ast.Tuple, ast.Constant, ast.List)) else None
                if n.targets[0].id == 'RESOLUTION' and v:
                    res = (int(v[0]), int(v[1]))
                elif n.targets[0].id == 'FPS' and v:
                    fps = int(v)
    except (SyntaxError, ValueError, TypeError):
        pass
    return res, fps


def _state_path(project_dir):
    return os.path.join(project_dir, 'cache', 'prerender.json')


def _load_state(project_dir):
    try:
        with open(_state_path(project_dir), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(project_dir, st):
    os.makedirs(os.path.dirname(_state_path(project_dir)), exist_ok=True)
    with open(_state_path(project_dir), 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _script_hash(project_dir, path):
    with open(path, 'rb') as f:
        h = hashlib.sha1(f.read())
    h.update(_sig_fonts(project_dir).encode())
    return h.hexdigest()[:16]


def _need_dir(project_dir):
    return os.path.join(project_dir, 'cache', 'models', '_need')


def needed_models(project_dir):
    """{ключ: (spec, set(ракурсов) или 'orbit')} — что просили сцены и чего ещё нет в кэше."""
    d = _need_dir(project_dir)
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.endswith('.json'):
            continue
        key = f[:-5]
        try:
            with open(os.path.join(d, f), 'r', encoding='utf-8') as fh:
                spec = json.load(fh)
            with open(os.path.join(d, key + '.angles'), 'r', encoding='utf-8') as fh:
                raw = {ln.strip() for ln in fh if ln.strip()}
        except (OSError, ValueError):
            continue
        st = max(1, int(spec.get('step', 2)))
        angles = set(range(0, 360, st)) if 'orbit' in raw else {int(a) for a in raw if a.lstrip('-').isdigit()}
        mdir = os.path.join(project_dir, 'cache', 'models', key)
        angles = {a for a in angles if not os.path.isfile(os.path.join(mdir, 'a%03d.png' % a))}
        if angles:
            out[key] = (spec, angles)
    return out


def status(project_dir):
    """Что сделает «Подготовка» (для кнопки в редакторе)."""
    st = _load_state(project_dir)
    rows = []
    for p in scripts(project_dir):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                code = f.read()
        except OSError:
            continue
        h = _script_hash(project_dir, p)
        rows.append(dict(file=os.path.basename(p), manim=_is_manim(code), scenes=manim_scenes(code) if _is_manim(code) else [],
                         stale=st.get(os.path.basename(p), {}).get('hash') != h,
                         error=st.get(os.path.basename(p), {}).get('error')))
    need = needed_models(project_dir)
    import importlib.util
    has = {m: importlib.util.find_spec(m) is not None for m in ('pyvista', 'trimesh', 'manim')}
    return dict(scripts=rows, models=[dict(file=s['file'], views=len(a)) for s, a in need.values()],
                todo=sum(1 for r in rows if r['stale']) + len(need), libs=has)


# ------------------------------------------------------------------ шаги
def collect_models(project_dir, log=print):
    """Пройти сцены с model(...) по времени, чтобы узнать нужные ракурсы (записываются в cache/models/_need)."""
    from . import engine, kit
    p = _project(project_dir)
    engine._winit(project_dir, ROOT)
    size = _frame_size(p)
    n = 0
    for s in p.get('scenes', []):
        path = os.path.join(project_dir, 'scenes', s['file'])
        try:
            with open(path, 'r', encoding='utf-8') as f:
                code = f.read()
        except OSError:
            continue
        if 'model(' not in code:
            continue
        dur = float(s.get('dur', 3))
        steps = max(2, min(240, int(dur * 4)))
        log('Сцена «%s»: ищу 3D-модели…' % s.get('name', s['file']))
        for i in range(steps + 1):
            t = dur * i / steps
            engine.render_one(dict(path=path, code=code, t=t, dur=dur, lfi=i, look=p.get('look', {}),
                                   texts=p.get('texts', {}), fonts=p.get('fonts', {}), size=size, layers=[], fx=[],
                                   asset_dirs=engine.project_dirs(project_dir, 'assets'),
                                   font_dirs=engine.project_dirs(project_dir, 'fonts')))
        n += 1
    kit._NEED.clear()
    return n


def render_models(project_dir, log=print, cancel=None):
    need = needed_models(project_dir)
    if not need:
        return 0
    try:
        from . import model3d
        import pyvista  # noqa: F401
        import trimesh  # noqa: F401
    except Exception as e:
        log('⚠ Нет pyvista/trimesh (%s) — 3D-модели пропущены. Запустите установку (start_…).' % e)
        return 0
    total = 0
    for key, (spec, angles) in need.items():
        if cancel and cancel():
            break
        if not os.path.isfile(spec['path']):
            log('⚠ Нет файла модели %s' % spec['file'])
            continue
        log('3D: %s — %d ракурсов…' % (spec['file'], len(angles)))
        try:
            total += model3d.render_spec(spec, os.path.join(project_dir, 'cache', 'models', key), sorted(angles), log, cancel)
        except Exception as e:
            log('⚠ %s: %s' % (spec['file'], e))
            continue
        if not needed_models(project_dir).get(key):
            for ext in ('.json', '.angles'):
                try:
                    os.remove(os.path.join(_need_dir(project_dir), key + ext))
                except OSError:
                    pass
    return total


def _env(project_dir):
    env = dict(os.environ, STUDIO_PROJECT=os.path.abspath(project_dir), PYTHONIOENCODING='utf-8')
    env['PYTHONPATH'] = ROOT + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def _run(cmd, project_dir, log, cancel, timeout=3600):
    """Запустить процесс, печатая его вывод в лог; возвращает код выхода."""
    p = subprocess.Popen(cmd, cwd=project_dir, env=_env(project_dir), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
    t0 = time.time()
    tail = []
    try:
        for ln in p.stdout:
            ln = ln.rstrip()
            if ln and 'bad X server' not in ln and 'vtkXOpenGLRenderWindow' not in ln:
                tail.append(ln)
                tail[:] = tail[-40:]
                log('    ' + ln[-300:])
            if (cancel and cancel()) or time.time() - t0 > timeout:
                p.kill()
                break
    finally:
        p.wait()
    return p.returncode, tail


_PNGF = []


def _png_format():
    """Manim ≥ 0.20: 'png' — только последний кадр, все кадры — 'png-sequence'; в старых версиях — 'png'."""
    if not _PNGF:
        try:
            r = subprocess.run([sys.executable, '-m', 'manim', 'render', '--help'], capture_output=True, text=True,
                               timeout=120, encoding='utf-8', errors='replace')
            _PNGF.append('png-sequence' if 'png-sequence' in r.stdout else 'png')
        except Exception:
            _PNGF.append('png')
    return _PNGF[0]


def run_manim(project_dir, path, log=print, cancel=None):
    with open(path, 'r', encoding='utf-8') as f:
        code = f.read()
    names = manim_scenes(code)
    if not names:
        log('  в %s нет классов-сцен Manim' % os.path.basename(path))
        return None
    import importlib.util
    if importlib.util.find_spec('manim') is None:
        return ('Нет Manim. Он нужен только для «Подготовки»: pip install -r requirements-manim.txt '
                '(на Linux/macOS сначала системные cairo и pango — см. README)')
    p = _project(project_dir)
    res, fps = _manim_opts(code)
    w, h = res or _frame_size(p)
    media = os.path.join(project_dir, 'cache', '_manim_media')
    fonts = _font_files(project_dir)
    for name in names:
        if cancel and cancel():
            break
        log('  Manim: %s (%d×%d, %d к/с)…' % (name, w, h, fps))
        shutil.rmtree(os.path.join(media, 'images'), ignore_errors=True)
        cmd = [sys.executable, '-m', 'studio.manim_run', json.dumps(fonts), '--', 'render', '--format', _png_format(),
               '--transparent', '-r', '%d,%d' % (w, h), '--fps', str(fps), '--media_dir', media,
               '--disable_caching', '--progress_bar', 'none', path, name]
        rc, tail = _run(cmd, project_dir, log, cancel)
        if rc != 0:
            hint = ''
            if any('latex' in t.lower() for t in tail):
                hint = ' — похоже, нужен LaTeX: используйте Text вместо MathTex/Tex'
            return 'Manim: сцена %s не отрендерилась (код %s)%s' % (name, rc, hint)
        pngs = []
        for dp, dn, fn in os.walk(os.path.join(media, 'images')):
            pngs += [os.path.join(dp, f) for f in fn if f.lower().endswith('.png')]
        pngs.sort()
        out = os.path.join(project_dir, 'cache', 'manim', name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        for i, src in enumerate(pngs):
            shutil.move(src, os.path.join(out, '%05d.png' % i))
        with open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(dict(fps=fps, frames=len(pngs), w=w, h=h, source=os.path.basename(path)), f)
        log('  → cache/manim/%s: %d кадров (%.1f с)' % (name, len(pngs), len(pngs) / max(1, fps)))
    shutil.rmtree(media, ignore_errors=True)
    return None


def run_script(project_dir, path, log=print, cancel=None):
    rc, tail = _run([sys.executable, path], project_dir, log, cancel)
    return None if rc == 0 else 'скрипт завершился с ошибкой (код %s): %s' % (rc, (tail[-1] if tail else ''))


def run(project_dir, log=print, force=False, cancel=None, collect=True):
    """Вся «Подготовка». Возвращает dict(ok, errors, models, scripts, seconds)."""
    global PROJECT
    project_dir = os.path.abspath(project_dir)
    PROJECT = project_dir
    t0 = time.time()
    errors = []
    os.makedirs(os.path.join(project_dir, 'cache'), exist_ok=True)
    if collect:
        try:
            collect_models(project_dir, log)
        except Exception as e:
            errors.append('Поиск моделей: %s' % e)
    nviews = render_models(project_dir, log, cancel)
    st = _load_state(project_dir)
    done = 0
    for path in scripts(project_dir):
        if cancel and cancel():
            break
        fn = os.path.basename(path)
        h = _script_hash(project_dir, path)
        if not force and st.get(fn, {}).get('hash') == h and not st.get(fn, {}).get('error'):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            code = f.read()
        log('prerender/%s…' % fn)
        t1 = time.time()
        try:
            err = run_manim(project_dir, path, log, cancel) if _is_manim(code) else run_script(project_dir, path, log, cancel)
        except Exception as e:
            err = str(e)
        if err:
            errors.append('%s: %s' % (fn, err))
            log('⚠ ' + err)
        st[fn] = dict(hash=h, error=err, seconds=round(time.time() - t1, 1), at=time.strftime('%Y-%m-%d %H:%M:%S'))
        _save_state(project_dir, st)
        done += 1
    res = dict(ok=not errors, errors=errors, models=nviews, scripts=done, seconds=round(time.time() - t0, 1))
    log('Готово: %d ракурсов 3D, %d скриптов, %.1f с%s' % (nviews, done, res['seconds'],
                                                             (', ошибок: %d' % len(errors)) if errors else ''))
    return res


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='«Подготовка» проекта VideoStudio: 3D, Manim, тяжёлые эффекты → cache/')
    ap.add_argument('project')
    ap.add_argument('--force', action='store_true', help='пересчитать все скрипты заново')
    ap.add_argument('--no-collect', action='store_true', help='не проходить сцены в поиске model(...)')
    a = ap.parse_args(argv)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    res = run(a.project, log=lambda s: print(s, flush=True), force=a.force, collect=not a.no_collect)
    print('@@RESULT ' + json.dumps(res, ensure_ascii=False), flush=True)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
