@echo off
setlocal
set "PYTHON_EXE="
set "PYTHON_ARGS="
cd /d "%~dp0"

rem Permite indicar uma instalacao fora dos caminhos usuais.
if defined EXTRATOR_PYTHON call :verificar "%EXTRATOR_PYTHON%"
if defined PYTHON_EXE goto executar

rem O launcher encontra instalacoes mesmo quando python.exe nao esta no PATH.
call :verificar py -3
if defined PYTHON_EXE goto executar
call :verificar python
if defined PYTHON_EXE goto executar
call :verificar python3
if defined PYTHON_EXE goto executar

rem Instalacoes registradas por usuario, por maquina e de 32 bits.
for %%R in ("HKCU\Software\Python\PythonCore" "HKLM\Software\Python\PythonCore" "HKLM\Software\WOW6432Node\Python\PythonCore") do (
    for /f "delims=" %%K in ('reg query "%%~R" 2^>nul') do call :registro "%%K\InstallPath"
)
if defined PYTHON_EXE goto executar

rem Pastas padrao, inclusive quando a instalacao nao foi registrada.
for /d %%D in ("%LocalAppData%\Programs\Python\Python*" "%ProgramFiles%\Python*" "%ProgramFiles(x86)%\Python*" "%SystemDrive%\Python*") do call :verificar "%%~D\python.exe"
if defined PYTHON_EXE goto executar

echo Nao foi encontrado um Python 3.10 ou mais recente com suporte a Tkinter.
echo Instale o Python de https://www.python.org/downloads/windows/
echo Inclua o launcher py e o componente Tcl/Tk na instalacao.
echo Para uma instalacao personalizada, defina EXTRATOR_PYTHON com o caminho
echo completo de python.exe, sem aspas no valor da variavel.
pause
exit /b 1

:executar
"%PYTHON_EXE%" %PYTHON_ARGS% -m aplicacao.ler_parquet %*
set "RESULTADO=%errorlevel%"
if not "%RESULTADO%"=="0" pause
exit /b %RESULTADO%

:verificar
if defined PYTHON_EXE exit /b
rem Testa o interpretador real; ignora aliases e versoes incompativeis.
"%~1" %~2 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 exit /b
set "PYTHON_EXE=%~1"
set "PYTHON_ARGS=%~2"
exit /b

:registro
if defined PYTHON_EXE exit /b
for /f "tokens=2,*" %%A in ('reg query "%~1" /ve 2^>nul') do if /i "%%A"=="REG_SZ" call :verificar "%%B\python.exe"
exit /b
