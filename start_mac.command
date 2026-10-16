#!/bin/bash
# Shelter Studio — запуск на Mac (двойной щелчок; если macOS не даёт открыть — правый щелчок → «Открыть»)
cd "$(dirname "$0")"
PY=python3
if ! command -v $PY >/dev/null 2>&1; then
  echo "Не найден Python 3. Установите его с https://www.python.org/downloads/ и запустите снова."
  read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Первый запуск: устанавливаю библиотеки, это займёт 2–5 минут…"
  rm -rf .venv
  if ! ($PY -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip); then
    echo "Не удалось создать окружение Python (.venv). Проверьте, что установлен python3-venv, и запустите снова."
    rm -rf .venv
    read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
  fi
fi
# библиотеки: при первом запуске и каждый раз, когда изменился requirements.txt (после git pull)
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Устанавливаю/обновляю библиотеки (requirements.txt)…"
  if .venv/bin/python -m pip install -r requirements.txt; then
    cp requirements.txt .venv/requirements.installed
  else
    echo "Не всё поставилось одной командой — ставлю по одной, редактор запустится в любом случае…"
    .venv/bin/python -m studio.install_check --each requirements.txt
  fi
  if ! .venv/bin/python -m studio.install_check; then
    echo "Основные библиотеки не установились. Проверьте интернет и запустите снова."
    read -n 1 -s -r -p "Нажмите любую клавишу…"; exit 1
  fi
  cp requirements.txt .venv/requirements.installed
fi
.venv/bin/python run.py "$@"
code=$?
if [ $code -eq 137 ] || [ $code -eq 143 ] || [ $code -eq 9 ] || [ $code -eq 15 ]; then
  echo
  echo "Программу закрыла система (код $code; в консоли «Убито»/«Завершено» / «Killed»/«Terminated»)."
  echo "Чаще всего — не хватило памяти: заполнен swap или мало свободной RAM (проверить: free -h)."
  echo "Закройте лишние программы или запустите с меньшим числом потоков:  bash $0 --workers 2"
  read -n 1 -s -r -p "Нажмите любую клавишу…"
fi
exit $code
