@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "APP=%~dp0app.py"
set "REQ=%~dp0requirements.txt"
set "URL=http://127.0.0.1:8000"
set "LOGDIR=%~dp0workdir\logs"
set "LOG=%LOGDIR%\servidor.log"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem --- El entorno virtual se arma solo la primera vez ------------------
if not exist "%PY%" goto crear_entorno

rem Puede existir y aun no servir: o el interprete quedo apuntando a un
rem Python que ya no esta, o faltan las dependencias.
"%PY%" -c "import fastapi, uvicorn" >>"%LOG%" 2>&1
if errorlevel 1 goto entorno_roto

goto arrancar


:crear_entorno
if exist "%VENV%" rmdir /s /q "%VENV%"
call :buscar_python
if not defined PYEXE goto sin_python

echo.
echo   Primera vez: armando el entorno virtual con Python %PYVERSION%.
echo   Se hace una sola vez y necesita internet.
echo.
"%PYEXE%" -m venv "%VENV%"
if errorlevel 1 goto fallo_entorno

echo   Instalando dependencias (tarda un poco)...
echo.
"%PY%" -m pip install --disable-pip-version-check -r "%REQ%"
if errorlevel 1 goto fallo_entorno
goto arrancar


:entorno_roto
rem Si el interprete del entorno arranca, lo que falta son las dependencias y
rem se reinstalan sin borrar nada. Si no arranca, no hay nada que rescatar.
"%PY%" -c "print(1)" >>"%LOG%" 2>&1
if errorlevel 1 goto crear_entorno

echo.
echo   Al entorno le faltan dependencias. Las instalo de nuevo.
echo.
"%PY%" -m pip install --disable-pip-version-check -r "%REQ%"
if errorlevel 1 goto fallo_entorno
goto arrancar


:arrancar
rem Si ya esta corriendo, solo abro el navegador.
curl.exe -s -o nul --max-time 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto abrir

echo.
echo   Levantando el enderezador de paginas dobles...
start "Enderezador de paginas dobles" "%PY%" "%APP%"

set /a intentos=0
:esperar
ping -n 2 127.0.0.1 >nul
curl.exe -s -o nul --max-time 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto abrir
set /a intentos+=1
if %intentos% lss 30 goto esperar

echo.
echo   El servidor no arranco. Ultimas lineas del registro:
echo.
call :mostrar_log
echo.
echo   Registro completo: %LOG%
echo.
pause
exit /b 1


:abrir
start "" "%URL%"
exit /b 0


:buscar_python
set "PYEXE="
set "PYVERSION="
call :probar_python python
if defined PYEXE exit /b 0
call :probar_python py
exit /b 0


:probar_python
rem Dos trampas encadenadas aca.
rem
rem La primera: si Python no esta instalado, el comando `python` puede ser el
rem alias de la Microsoft Store, que abre la tienda en vez de avisar. Asi que no
rem alcanza con mirar el errorlevel, hay que comprobar que imprima la version.
rem
rem La segunda: si el comando no existe, cmd aborta el archivo entero cuando
rem aparece dentro de una tuberia, y sin decir nada. Por eso se descarta antes
rem con `where`. Tampoco se copia la salida a una variable para compararla,
rem porque el texto del alias podria traer comillas y romper el archivo.
where %1 >nul 2>&1
if errorlevel 1 exit /b 0

%1 -c "import sys;print(sys.version_info[0],sys.version_info[1])" 2>nul | findstr /r /c:"^3 [0-9][0-9]*$" >nul
if errorlevel 1 exit /b 0

set "PYEXE=%1"
for /f "tokens=1,2" %%A in ('%1 -c "import sys;print(sys.version_info[0],sys.version_info[1])" 2^>nul') do set "PYVERSION=%%A.%%B"
if not defined PYVERSION set "PYVERSION=3"
exit /b 0


:mostrar_log
if not exist "%LOG%" exit /b 0
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 20 -Encoding UTF8" 2>nul
exit /b 0


:sin_python
echo.
echo   No encontre Python en esta computadora.
echo.
echo   Descargalo de https://www.python.org/downloads/ y volve a abrir este
echo   archivo. En el instalador marca la casilla "Add python.exe to PATH".
echo.
pause
exit /b 1


:fallo_entorno
echo.
echo   No se pudo armar el entorno virtual: el error esta arriba.
echo.
echo   Si es la primera vez, revisa que tengas internet.
echo.
pause
exit /b 1
