"""Запуск Manim из «Подготовки» со шрифтами проекта (без установки шрифтов в систему).

    python -m studio.manim_run '<json-список .ttf>' -- render --format png --transparent … файл.py Сцена
"""
import json
import sys


def main():
    args = sys.argv[1:]
    fonts = json.loads(args[0]) if args else []
    rest = args[args.index('--') + 1:] if '--' in args else args[1:]
    try:
        import manimpango
        for f in fonts:
            try:
                manimpango.register_font(f)        # Pango видит шрифт по имени семейства: Text(..., font='Manrope')
            except Exception as e:
                print('шрифт %s: %s' % (f, e))
    except Exception as e:
        print('manimpango: %s' % e)
    from manim.__main__ import main as manim_main
    sys.argv = ['manim'] + rest
    manim_main()


if __name__ == '__main__':
    main()
