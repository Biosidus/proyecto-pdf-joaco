@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "APP=%~dp0app.py"
set "URL=http://127.0.0.1:8000"

if not exist "%PY%" goto sin_venv

rem Si ya está corriendo, sólo abro el navegador.
curl.exe -s -o nul --max-time 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto abrir

echo.
echo   Levantando el enderezador de páginas dobles...
start "Enderezador de páginas dobles" "%PY%" "%APP%"

set /a intentos=0
:esperar
ping -n 2 127.0.0.1 >nul
curl.exe -s -o nul --max-time 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto abrir
set /a intentos+=1
if %intentos% lss 30 goto esperar

echo.
echo   El servidor no arrancó. Mirá la otra ventana para ver el detalle.
echo.
pause
exit /b 1

:abrir
start "" "%URL%"
exit /b 0

:sin_venv
echo.
echo   Falta el entorno virtual (.venv). Se crea una sola vez, desde esta carpeta:
echo.
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1
