"""从 app.ICON_SVG 生成打包用图标：Windows `build/icon.ico` 与 macOS `build/icon.icns`。

各尺寸单独从 SVG 渲染（比从大图缩放更锐利）。改了图标 SVG 后重跑本脚本即可。

依赖（仅生成时需要，运行时/打包不需要）：
    - Pillow            生成多尺寸 .ico
    - iconutil（macOS） 生成 .icns
用法：
    python build/make_icons.py
"""
import io
import os
import sys
import shutil
import subprocess

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import QByteArray, Qt, QBuffer, QIODevice
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

from app import ICON_SVG

HERE = os.path.dirname(os.path.abspath(__file__))
app = QApplication([])


def png_bytes(size):
    im = QImage(size, size, QImage.Format_ARGB32)
    im.fill(Qt.transparent)
    p = QPainter(im)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    QSvgRenderer(QByteArray(ICON_SVG.encode("utf-8"))).render(p)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    im.save(buf, "PNG")
    return bytes(buf.data())


# ---- Windows .ico（多尺寸，各自从 SVG 锐利渲染）----
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
by_size = {s: Image.open(io.BytesIO(png_bytes(s))) for s in ICO_SIZES}
by_size[256].save(os.path.join(HERE, "icon.ico"), format="ICO",
                  sizes=[(s, s) for s in ICO_SIZES],
                  append_images=[by_size[s] for s in ICO_SIZES if s != 256])
print("wrote build/icon.ico", ICO_SIZES)

# ---- macOS .icns（iconset + iconutil）----
iconset = os.path.join(HERE, "icon.iconset")
os.makedirs(iconset, exist_ok=True)
for size, name in [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
                   (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
                   (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x")]:
    with open(os.path.join(iconset, f"icon_{name}.png"), "wb") as f:
        f.write(png_bytes(size))
try:
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "icon.icns")], check=True)
    print("wrote build/icon.icns")
finally:
    shutil.rmtree(iconset, ignore_errors=True)
