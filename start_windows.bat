@echo off
chcp 65001 >nul
title Shelter Studio
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopy

echo Первый запуск: устанавливаю библиотеки, это займёт 1-3 минуты...
%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

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
echo Не удалось установить библиотеки. Проверьте интернет и запустите файл снова.
if exist .venv rmdir /s /q .venv
pause
