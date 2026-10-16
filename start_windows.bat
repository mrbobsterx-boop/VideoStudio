@echo off
chcp 65001 >nul
title Shelter Studio
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopy

echo Первый запуск: устанавливаю библиотеки, это займёт 2-5 минут...
%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -q --upgrade pip

:deps
rem библиотеки: при первом запуске и каждый раз, когда изменился requirements.txt (после git pull)
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if not errorlevel 1 goto run
echo Устанавливаю/обновляю библиотеки (requirements.txt)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not errorlevel 1 goto check
echo Не всё поставилось одной командой - ставлю по одной, редактор запустится в любом случае...
".venv\Scripts\python.exe" -m studio.install_check --each requirements.txt
:check
".venv\Scripts\python.exe" -m studio.install_check
if errorlevel 1 goto fail
copy /y requirements.txt ".venv\requirements.installed" >nul

:run
".venv\Scripts\python.exe" run.py
pause
exit /b

:nopy
echo Не найден Python. Установите Python 3.10 или новее с https://www.python.org/downloads/
echo При установке отметьте галочку "Add python.exe to PATH", затем запустите этот файл снова.
pause
exit /b

:fail
echo Не удалось установить основные библиотеки. Проверьте интернет и запустите файл снова.
echo Если ошибка повторяется - удалите папку .venv рядом с этим файлом и запустите снова.
pause
