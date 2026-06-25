@echo off
chcp 65001 >nul
REM 直接用 Python 源码运行（用于开发/测试，无需打包）。需已安装 Python 3.10+。
setlocal
cd /d "%~dp0.."
python --version >nul 2>&1 || (echo 未检测到 Python，请先安装并勾选 Add to PATH & pause & exit /b 1)
if not exist ".venv" python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python app.py
pause
