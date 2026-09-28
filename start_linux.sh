#!/bin/bash
# Shelter Studio — запуск на Linux: bash start_linux.sh
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
.venv/bin/python run.py project
