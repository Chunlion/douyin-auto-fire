@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "LOGIN_PYTHON=%CD%\.venv\Scripts\python.exe"
"%LOGIN_PYTHON%" -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo 登录环境不可用，请先完成 Windows 安装步骤。
    pause
    exit /b 1
)

"%LOGIN_PYTHON%" scripts\login.py
set "LOGIN_EXIT=%ERRORLEVEL%"
if not "%LOGIN_EXIT%"=="0" pause
exit /b %LOGIN_EXIT%
