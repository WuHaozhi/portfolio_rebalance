# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把调仓工具打成单文件 Windows .exe。

用法（在 Windows 上）：
    pip install -r requirements.txt pyinstaller
    pyinstaller build/调仓工具.spec --noconfirm
产物在 dist/portfolio_rebalance.exe（Windows）/ dist/调仓工具.app（macOS）
"""
import os

block_cipher = None

# 项目根目录 = 本 spec 文件所在目录(build/)的上一级，保证从任意 CWD 运行都能找到源码
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

# 仅打包用到的 Qt 模块，减小体积、加快启动
EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.Qt3DCore", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtCharts",
    "tkinter", "matplotlib", "numpy", "scipy", "PIL", "pandas",
]

# 带上 Qt 简体中文翻译（OK/Cancel/Yes/No 等标准按钮汉化），放到与 QLibraryInfo 一致的子目录
import PySide6 as _ps6
_TR_SRC = os.path.join(os.path.dirname(_ps6.__file__), "Qt", "translations")
_TR_DATAS = [(os.path.join(_TR_SRC, f"{n}.qm"), os.path.join("PySide6", "Qt", "translations"))
             for n in ("qtbase_zh_CN", "qt_zh_CN")
             if os.path.exists(os.path.join(_TR_SRC, f"{n}.qm"))]

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=_TR_DATAS,
    hiddenimports=["openpyxl.cell._writer"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

import sys
IS_MAC = sys.platform == "darwin"

if IS_MAC:
    # macOS：onedir + BUNDLE（.app）。比 onefile+BUNDLE 更稳：不每次解压到临时目录、
    # 不触发 PyInstaller v7 对 onefile+BUNDLE 的弃用、与 macOS 安全机制更友好。
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="调仓工具",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=False, disable_windowed_traceback=False,
        target_arch=None, codesign_identity=None, entitlements_file=None, icon=None,
    )
    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False, upx=False, upx_exclude=[], name="调仓工具",
    )
    app = BUNDLE(
        coll,
        name="调仓工具.app",
        icon=None,          # 如需图标：build/icon.icns 并改为 icon="build/icon.icns"
        bundle_identifier="com.portfolioadjust.tool",
        info_plist={
            "CFBundleName": "调仓工具",
            "CFBundleDisplayName": "批量调仓下单工具",
            "CFBundleShortVersionString": "1.1.9",
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows：单文件 .exe，双击即用。
    # 文件名用 ASCII「portfolio_rebalance」——GitHub Release 会吞掉中文附件名；
    # 程序窗口标题/安装后的快捷方式仍是中文「调仓工具」（见 app.py 与 installer.iss）。
    exe = EXE(
        pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
        name="portfolio_rebalance",
        debug=False, bootloader_ignore_signals=False, strip=False,
        upx=False,              # 不依赖 UPX：避免 CI 无 UPX 的噪音与部分杀软误报
        upx_exclude=[], runtime_tmpdir=None,
        console=False,          # 不弹黑色命令行窗口
        disable_windowed_traceback=False,
        target_arch=None, codesign_identity=None, entitlements_file=None,
        icon=None,              # 如需图标：放 build/icon.ico 并改为 icon="build/icon.ico"
    )
