"""Проверка библиотек после установки (вызывают start_*.sh / start_windows.bat): что есть, чего нет и что делать."""
import importlib
import platform
import sys

CORE = ['numpy', 'cv2', 'PIL', 'scipy', 'imageio_ffmpeg']
OPTIONAL = [('skia', 'skia-python', 'Skia-графика: canvas(), sk_*, code_block()'),
            ('pyvista', 'pyvista', '3D-модели в «Подготовке»'),
            ('trimesh', 'trimesh', '3D-модели в «Подготовке»'),
            ('pygments', 'pygments', 'подсветка кода: code_block()'),
            ('fontTools', 'fonttools', 'толщина вариативных шрифтов в старых Skia'),
            ('manim', 'manim', 'графики Manim в «Подготовке» (необязательно, requirements-manim.txt)')]


def install_each(path):
    """Поставить строки requirements по одной: одна неудачная библиотека не мешает остальным."""
    import subprocess
    failed = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            req = line.split('#', 1)[0].strip()
            if not req:
                continue
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', req])
            if r.returncode != 0:
                failed.append(req.split(';')[0].strip())
    for x in failed:
        print('  ✗ не установилось: %s' % x)
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--each':
        return install_each(sys.argv[2])
    bad = [m for m in CORE if not _ok(m)[0]]
    if bad:
        print('НЕ установлены основные библиотеки: %s' % ', '.join(bad))
        return 1
    for mod, pkg, what in OPTIONAL:
        ok, err = _ok(mod)
        if ok:
            continue
        hint = ''
        if mod == 'skia' and 'libEGL' in err:
            hint = ' — нужна системная libEGL: sudo apt install libegl1 (Debian/Ubuntu) или sudo dnf install mesa-libEGL'
        elif mod == 'skia' and sys.platform == 'darwin' and platform.machine() == 'x86_64' and sys.version_info >= (3, 13):
            hint = ' — для Mac с Intel колёс под Python 3.13+ нет: поставьте Python 3.12 с python.org и удалите папку .venv'
        elif mod == 'manim':
            continue                   # необязательная, без сообщения
        print('  · нет %s (%s)%s' % (pkg, what, hint))
    return 0


def _ok(mod):
    try:
        importlib.import_module(mod)
        return True, ''
    except Exception as e:
        return False, str(e)


if __name__ == '__main__':
    sys.exit(main())
