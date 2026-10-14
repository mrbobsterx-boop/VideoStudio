#!/bin/bash
# Shelter Studio — запуск на Mac (двойной щелчок; если macOS не даёт открыть — правый щелчок → «Открыть»)
cd "$(dirname "$0")"
PY=python3
if ! command -v $PY >/dev/null 2>&1; then
  echo "Не найден Python 3. Установите его с https://www.python.org/downloads/ и запустите снова."
  read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Первый запуск: устанавливаю библиотеки, это займёт 1–3 минуты…"
  rm -rf .venv
  if ! ($PY -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip && .venv/bin/python -m pip install -r requirements.txt); then
    echo "Не удалось установить библиотеки. Проверьте интернет и запустите снова."
    rm -rf .venv
    read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
  fi
fi
.venv/bin/python run.py "$@"
code=$?
if [ $code -eq 137 ] || [ $code -eq 9 ]; then
  echo
  echo "Программу закрыла система: не хватило оперативной памяти (в консоли «Убито» / «Killed»)."
  echo "Закройте лишние программы или запустите с меньшим числом потоков:  bash $0 --workers 2"
  read -n 1 -s -r -p "Нажмите любую клавишу…"
fi
