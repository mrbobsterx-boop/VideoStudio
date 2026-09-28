"""Запуск редактора:  python run.py            (откроет последний проект, в первый раз — project/)
                    python run.py path/to/project"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    from studio.server import main
    main()
