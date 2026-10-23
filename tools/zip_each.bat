@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "PY="
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo   [错误] 没找到 Python。请先安装 Python 3.8+ 并勾选 Add Python to PATH。
  echo.
  pause
  exit /b 1
)

echo   脚本: zip_each.py
echo   目录: %~dp0
echo.

%PY% -X utf8 "%~dp0zip_each.py" %*
echo.
pause
