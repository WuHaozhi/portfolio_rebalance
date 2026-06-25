@echo off
chcp 65001 >nul
REM ============================================================
REM   一键把「调仓工具」打包成 Windows 绿色版 .exe 和 安装包
REM   在任意装有 Python 3.10+ 的 Windows 电脑上双击运行本文件即可
REM   产物：dist\portfolio_rebalance.exe（绿色版）
REM         dist\portfolio_rebalance_setup_v1.1.2.exe（安装包，需装 Inno Setup）
REM ============================================================
setlocal
cd /d "%~dp0.."

echo.
echo [1/5] 检查 Python ...
python --version >nul 2>&1
if errorlevel 1 (
    echo   未检测到 Python。请先到 https://www.python.org/downloads/ 安装 Python 3.10 以上版本，
    echo   安装时务必勾选 "Add Python to PATH"，然后重新运行本文件。
    pause
    exit /b 1
)
python --version

echo.
echo [2/5] 创建虚拟环境并安装依赖 ...
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo   依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo.
echo [3/5] 打包绿色版 exe（首次较慢，请耐心等待）...
pyinstaller build\调仓工具.spec --noconfirm --clean
if errorlevel 1 (
    echo   打包失败。
    pause
    exit /b 1
)

echo.
echo [4/5] 冒烟自检 ...
dist\portfolio_rebalance.exe --selftest

echo.
echo [5/5] 生成安装包（需 Inno Setup）...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" build\installer.iss
    echo   安装包已生成： %cd%\dist\portfolio_rebalance_setup_v1.1.2.exe
) else (
    where ISCC >nul 2>&1 && ( ISCC build\installer.iss && echo   安装包已生成： %cd%\dist\portfolio_rebalance_setup_v1.1.2.exe ) || (
        echo   未检测到 Inno Setup，已跳过安装包，仅生成绿色版 dist\portfolio_rebalance.exe
        echo   如需安装包：到 https://jrsoftware.org/isdl.php 安装 Inno Setup 6 后，重跑本文件，
        echo   或手动执行： ISCC build\installer.iss
    )
)

echo.
echo 完成！产物在 dist\ 目录：
echo   - portfolio_rebalance.exe              绿色版，双击即用（无需安装）
echo   - portfolio_rebalance_setup_v1.1.2.exe   安装包，双击安装（带开始菜单/桌面快捷方式/卸载）
echo.
pause
