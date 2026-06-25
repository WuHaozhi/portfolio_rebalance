#!/bin/bash
# ============================================================
#   把「调仓工具」打包成 macOS 应用（.app）
#   在 Mac 上双击本文件即可（或终端 bash build_mac.command）
#   产物：dist/调仓工具.app
# ============================================================
set -e
cd "$(dirname "$0")/.."

echo "[1/4] 检查 Python ..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "  未检测到 python3。请先安装 Python 3.10+（https://www.python.org/downloads/）"
    exit 1
fi
python3 --version

echo "[2/4] 创建虚拟环境并安装依赖 ..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo "[3/4] 打包中（首次较慢）..."
pyinstaller build/调仓工具.spec --noconfirm --clean

echo "[4/4] 完成！"
echo "  应用位于：$(pwd)/dist/调仓工具.app"
echo "  双击 dist/调仓工具.app 即可运行。"
echo
echo "  注意：未做苹果签名/公证，首次打开若被拦截，请在 访达 里右键应用→打开，"
echo "       或到 系统设置→隐私与安全性 点「仍要打开」。"
