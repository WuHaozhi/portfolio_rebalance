#!/usr/bin/env python3
"""批量调仓下单工具 —— 暗色专业交易界面（PySide6）。

三级结构（树）：
  一级 产品  →  二级 交易组(方向/金额/方式，均必填)  →  三级 证券(证券池/价格/股数/调整)
交互：
  - 右键空白处「新增产品」；右键产品「新增交易组」；右键交易组「新增证券」；右键任意项「删除」。
  - 单击单元格即可编辑/选股（产品、方向、方式下拉；金额、调整输入；证券池单击弹出选股框）。
  - 任意改动自动重算股数；价格自动取自 product 文件，经理不填。
  - 右上角「预览」→ 校验必填(缺则弹窗) → 弹出下单核对(卖出标黄在前) → 确认并导出 Excel。
买入=天蓝、卖出=红；数字右对齐等宽；列宽可拖。
"""
from __future__ import annotations

import os
import re
import sys
import traceback

from PySide6.QtCore import (Qt, QSettings, QObject, Signal, QUrl,
                            QTranslator, QLibraryInfo, QLocale)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QRadioButton, QScrollArea, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from rebalancer import (
    DirectionGroup, StockEntry, StockPoolItem, build_orders, compute_group_shares,
    config, default_cny_price, merged_security_pool, normalize_code, normalize_direction,
    read_product_folder, write_orders, write_orders_per_product,
)
from rebalancer.engine import clamp_sell_to_holding, round_buy
from rebalancer.excel_io import safe_filename
from rebalancer import __version__ as APP_VERSION

APP_TITLE = "批量调仓下单工具"


def _ver_tuple(s):
    """把 '1.2' / 'v1.2.0' 解析成可比较的数字元组；非数字段忽略。"""
    nums = []
    for part in str(s).lstrip("vV").split("."):
        d = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(d) if d else 0)
    return tuple(nums)


class UpdateChecker(QObject):
    """手动「检查更新」：经理点击时才后台联网一次（启动不联网）。三种结果回主线程。"""

    found = Signal(str, str)    # 有新版：(新版本号, 下载地址)
    uptodate = Signal(str)      # 已最新：(当前版本)
    failed = Signal(str)        # 失败：(原因)

    def check_async(self):
        import threading
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        import json
        import urllib.request
        try:
            if config.UPDATE_MANIFEST_URL:
                req = urllib.request.Request(config.UPDATE_MANIFEST_URL,
                                             headers={"User-Agent": "portfolio-adjust"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    d = json.load(r)
                ver, url = d.get("version", ""), d.get("url", "")
            elif config.UPDATE_REPO:
                api = f"https://api.github.com/repos/{config.UPDATE_REPO}/releases/latest"
                req = urllib.request.Request(api, headers={"User-Agent": "portfolio-adjust"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    d = json.load(r)
                ver = d.get("tag_name", "")
                assets = d.get("assets") or []
                url = (assets[0].get("browser_download_url") if assets else "") or d.get("html_url", "")
            else:
                self.failed.emit("未配置更新地址（请在 config.py 填 UPDATE_REPO）")
                return
            if ver and _ver_tuple(ver) > _ver_tuple(APP_VERSION):
                self.found.emit(str(ver), str(url))
            else:
                self.uptodate.emit(APP_VERSION)
        except Exception:  # noqa: BLE001 离线/超时/限流
            self.failed.emit("无法连接更新服务器，请检查网络后重试")

# 新增证券持久化文件：放在用户主目录（不在程序目录），换新 .exe/.app 重新部署后仍保留。
CUSTOM_DIR = os.path.join(os.path.expanduser("~"), ".portfolio_adjust")
CUSTOM_FILE = os.path.join(CUSTOM_DIR, "custom_securities.json")

COL_PRODUCT, COL_DIR, COL_POOL, COL_AMOUNT, COL_METHOD, COL_PRICE, COL_SHARES, COL_ADJUST = range(8)
HEADERS = ["产品", "方向", "证券池", "金额(元)", "方式", "价格", "股数", "调整(股数)"]
RIGHT_COLS = {COL_AMOUNT, COL_PRICE, COL_SHARES, COL_ADJUST}

LV_PRODUCT, LV_GROUP, LV_STOCK = 1, 2, 3
ROLE_LEVEL = Qt.UserRole
ROLE_CODE = Qt.UserRole + 1
ROLE_NAME = Qt.UserRole + 2

# ---- 配色（华泰 Win10Dark + TradingView 暗色） ----
C_BG = "#0f1218"
C_PANEL = "#1a1e27"
C_PRODUCT = "#1f2735"     # 一级 产品行底色
C_GROUP = "#181d27"       # 二级 交易组行底色
C_HEADER = "#161a22"
C_BORDER = "#262c38"
C_GRIDLINE = "#1e232d"
C_TEXT = "#e8eaee"
C_DIM = "#7e8794"
C_SEL = "#15324f"
C_BUY = "#2f9bff"
C_SELL = "#f6465d"
C_PRIMARY = "#2f81f7"
C_REQ = "#bd7077"          # 必填未填：淡红色边框/文字（柔和提醒，不刺眼）
C_REQ_BG = "#241c20"       # 必填未填：单元格淡红底提示

DARK_QSS = f"""
QWidget {{ background:{C_BG}; color:{C_TEXT}; font-size:13px; }}
QMainWindow, QDialog {{ background:{C_BG}; }}
QLabel {{ background:transparent; color:{C_DIM}; }}
QToolTip {{ background:{C_PANEL}; color:{C_TEXT}; border:1px solid {C_BORDER}; }}

QPushButton {{
    background:{C_PANEL}; color:{C_TEXT}; border:1px solid {C_BORDER};
    padding:7px 16px; border-radius:6px;
}}
QPushButton:hover {{ background:#222734; border-color:#39404e; }}
QPushButton:pressed {{ background:#12151c; }}
QPushButton#primary {{ background:{C_PRIMARY}; color:#fff; border:none; font-weight:600; padding:7px 22px; }}
QPushButton#primary:hover {{ background:#3a8dff; }}

QTreeWidget {{
    background:{C_BG}; border:1px solid {C_BORDER}; border-radius:6px;
    gridline-color:{C_GRIDLINE};
    selection-background-color:{C_SEL}; selection-color:{C_TEXT}; outline:0;
    show-decoration-selected:1;
}}
QTreeWidget::item {{ height:30px; border-right:1px solid {C_GRIDLINE}; }}
QTreeWidget::item:selected {{ background:{C_SEL}; color:{C_TEXT}; }}
QHeaderView::section {{
    background:{C_HEADER}; color:{C_DIM}; padding:8px 8px; border:0px;
    border-right:1px solid {C_GRIDLINE}; border-bottom:1px solid {C_BORDER};
    font-weight:600;
}}
QHeaderView::section:last {{ border-right:0; }}

QComboBox, QLineEdit {{
    background:{C_PANEL}; color:{C_TEXT}; border:1px solid {C_PRIMARY};
    border-radius:4px; padding:2px 6px; selection-background-color:{C_PRIMARY};
}}
QComboBox QAbstractItemView {{
    background:{C_PANEL}; color:{C_TEXT}; border:1px solid {C_BORDER};
    selection-background-color:{C_PRIMARY}; outline:0;
}}
QComboBox::drop-down {{ border:0; width:16px; }}
QRadioButton {{ background:transparent; color:{C_TEXT}; padding:4px; }}

QMenu {{ background:{C_PANEL}; color:{C_TEXT}; border:1px solid {C_BORDER}; padding:4px; }}
QMenu::item {{ padding:6px 22px; border-radius:4px; }}
QMenu::item:selected {{ background:{C_PRIMARY}; color:#fff; }}
QMenu::separator {{ height:1px; background:{C_BORDER}; margin:4px 6px; }}

QTableWidget {{
    background:{C_BG}; alternate-background-color:#141821; gridline-color:{C_GRIDLINE};
    border:1px solid {C_BORDER}; selection-background-color:{C_SEL}; selection-color:{C_TEXT}; outline:0;
}}
QTextEdit {{ background:{C_BG}; color:{C_TEXT}; border:1px solid {C_BORDER}; border-radius:4px; }}

QScrollBar:vertical {{ background:{C_BG}; width:11px; margin:0; }}
QScrollBar::handle:vertical {{ background:#333a47; border-radius:5px; min-height:24px; }}
QScrollBar::handle:vertical:hover {{ background:#434b5a; }}
QScrollBar:horizontal {{ background:{C_BG}; height:11px; margin:0; }}
QScrollBar::handle:horizontal {{ background:#333a47; border-radius:5px; min-width:24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
QStatusBar {{ background:{C_PANEL}; color:{C_DIM}; }}
"""

# 空表时的虚线「＋新增产品」按钮
DASH_BTN_QSS = (
    f"QPushButton{{border:2px dashed {C_BORDER};border-radius:12px;color:{C_DIM};"
    f"background:transparent;padding:22px 56px;font-size:16px;}}"
    f"QPushButton:hover{{border-color:{C_PRIMARY};color:{C_TEXT};}}"
)

# 单元格内常驻下拉框：平铺透明、带下拉箭头，点击即展开
CELL_COMBO_QSS = (
    f"QComboBox{{background:transparent;border:none;padding-left:8px;color:{C_TEXT};}}"
    f"QComboBox::drop-down{{border:0;width:18px;}}"
    f"QComboBox QAbstractItemView{{background:{C_PANEL};color:{C_TEXT};"
    f"selection-background-color:{C_PRIMARY};border:1px solid {C_BORDER};outline:0;}}"
)


def _to_float(s):
    try:
        s = str(s).strip().replace(",", "").replace("，", "")
        if not s:
            return None
        f = float(s)
    except (ValueError, TypeError):
        return None
    import math
    return f if math.isfinite(f) else None    # 拒绝 inf/nan（金额/价格输入）


def _to_int(s):
    f = _to_float(s)
    return int(round(f)) if f is not None else None


def _mono():
    f = QFont("Menlo"); f.setStyleHint(QFont.Monospace); f.setPointSize(12)
    return f


def _dot(color, d=11):
    """渲染一个实心圆点图标（无需外部图片，打包安全）。"""
    pm = QPixmap(d, d); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color)); p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, d - 2, d - 2); p.end()
    return QIcon(pm)


class Scrim(QWidget):
    """半透明遮罩：盖在父窗内容上，把下层压暗，凸显最上层弹窗的层次。"""

    def __init__(self, host):
        super().__init__(host)
        self.setStyleSheet("background: rgba(0,0,0,115);")
        self.setGeometry(host.rect())
        self.show(); self.raise_()


def exec_with_scrim(dialog, host):
    """在 host 上铺 scrim 后模态执行 dialog，结束自动移除。"""
    scrim = Scrim(host)
    try:
        return dialog.exec()
    finally:
        scrim.deleteLater()


class TradeTree(QTreeWidget):
    """空表时在中央显示一个虚线「＋新增产品」按钮（而非靠右键）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay = None

    def set_overlay(self, w):
        self._overlay = w
        self._reposition(); self.update_overlay()

    def _reposition(self):
        if self._overlay:
            self._overlay.adjustSize()
            r = self.viewport().rect(); s = self._overlay.size()
            self._overlay.move(r.center().x() - s.width() // 2, r.center().y() - s.height() // 2)

    def update_overlay(self):
        if self._overlay:
            self._overlay.setVisible(self.topLevelItemCount() == 0)
            self._reposition()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reposition()


# ---------------------------------------------------------------------------
# 单元格编辑委托：按「层级 + 列」决定编辑器（下拉/输入/不可编辑）
# ---------------------------------------------------------------------------
class TreeDelegate(QStyledItemDelegate):
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def _level(self, index):
        item = self.win.tree.itemFromIndex(index)
        return item.data(0, ROLE_LEVEL) if item else None

    def createEditor(self, parent, option, index):
        # 产品/方向/方式 用常驻下拉控件(setItemWidget)；这里只处理 金额/调整 文本输入
        lv, col = self._level(index), index.column()
        if (lv == LV_GROUP and col == COL_AMOUNT) or (lv == LV_STOCK and col == COL_ADJUST):
            le = QLineEdit(parent)
            # 不加 QDoubleValidator：否则清空(空串=未完成态)无法提交，导致"删了数字旧值还在"。
            # 非数字会被 _to_float/_to_int 宽松解析为"未填"，不影响。
            return le
        return None

    def setEditorData(self, editor, index):
        if isinstance(editor, QLineEdit):
            editor.setText(str(index.data(Qt.EditRole) or ""))

    def setModelData(self, editor, model, index):
        if isinstance(editor, QLineEdit):
            model.setData(index, editor.text().strip(), Qt.EditRole)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        # 给「金额」「证券池」未填的单元格画淡红边框（下拉框的红框由其自身样式负责）
        item = self.win.tree.itemFromIndex(index)
        if item is None:
            return
        lv, col = item.data(0, ROLE_LEVEL), index.column()
        red = False
        if lv == LV_GROUP and col == COL_AMOUNT:
            amt = _to_float(item.text(COL_AMOUNT))
            red = amt is None or amt <= 0
        elif lv == LV_STOCK and col == COL_POOL:
            red = not item.data(COL_POOL, ROLE_CODE)
        if red:
            painter.save()
            pen = QPen(QColor(C_REQ)); pen.setWidth(1)
            painter.setPen(pen); painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -2, -2), 4, 4)
            painter.restore()


class CheckList(QListWidget):
    """点行任意处=切换勾选（且只切一次，避免点复选框时原生+信号双切相互抵消）。"""

    def mousePressEvent(self, e):
        it = self.itemAt(e.position().toPoint()) if hasattr(e, "position") else self.itemAt(e.pos())
        if it is not None and (it.flags() & Qt.ItemIsUserCheckable):
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
            self.setCurrentItem(it)
            return   # 吃掉事件：阻止原生再切一次
        super().mousePressEvent(e)


# ---------------------------------------------------------------------------
# 选股对话框（当前产品 / 全部产品 / 新增）—— 不让填价格，支持批量
# ---------------------------------------------------------------------------
class SecurityPicker(QDialog):
    """选股框：支持【批量勾选】——筛选后点行即勾选，可选多只，一次性加入。"""

    def __init__(self, parent, product, merged):
        super().__init__(parent)
        self.setWindowTitle("选择证券（可多选）")
        self.resize(500, 620)
        self.product = product
        self.merged = merged
        self.picked = []          # list[(code, name, price)]
        self.checked = {}         # code -> name：跨筛选/跨来源保留的勾选（_refresh 不会清掉）
        v = QVBoxLayout(self)
        src = QHBoxLayout()
        self.rb_cur = QRadioButton(config.SOURCE_CURRENT)
        self.rb_all = QRadioButton(config.SOURCE_ALL)
        self.rb_new = QRadioButton(config.SOURCE_NEW)
        self.rb_cur.setChecked(True)
        g = QButtonGroup(self)
        for rb in (self.rb_cur, self.rb_all, self.rb_new):
            g.addButton(rb); src.addWidget(rb); rb.toggled.connect(self._refresh)
        v.addLayout(src)

        self.search = QLineEdit(); self.search.setPlaceholderText("输入代码或名称筛选…")
        self.search.setStyleSheet(f"border:1px solid {C_BORDER};")
        self.search.textChanged.connect(self._refresh)
        v.addWidget(self.search)

        tools = QHBoxLayout()
        self.lbl_sel = QLabel("已选 0 只"); self.lbl_sel.setStyleSheet(f"color:{C_TEXT};")
        self.btn_all = QPushButton("全选")
        self.btn_all.clicked.connect(self._toggle_all)             # 再按一次=全部取消
        tools.addWidget(self.lbl_sel); tools.addStretch(1); tools.addWidget(self.btn_all)
        v.addLayout(tools)

        self.listw = CheckList()
        self.listw.itemChanged.connect(self._on_item_changed)     # 勾选变化 -> 记入持久集合
        v.addWidget(self.listw, 1)

        # 新增页：最多 10 行（代码 + 名称），填几行算几行；新增会被记住，下次仍在证券池
        self.new_box = QWidget()
        nb = QVBoxLayout(self.new_box); nb.setContentsMargins(0, 0, 0, 0); nb.setSpacing(6)
        nb.addWidget(QLabel("批量新增证券，填代码、名称、价格（新增的票不在持仓里，需填价格才能算股数）："))
        self.new_rows = []
        for _ in range(10):
            row = QHBoxLayout()
            code = QLineEdit(); code.setPlaceholderText("代码 如 600000.SH")
            name = QLineEdit(); name.setPlaceholderText("名称")
            price = QLineEdit(); price.setPlaceholderText("价格(元)")
            for w in (code, name, price):
                w.setStyleSheet(f"border:1px solid {C_BORDER};")
            row.addWidget(code, 3); row.addWidget(name, 3); row.addWidget(price, 2)
            nb.addLayout(row)
            self.new_rows.append((code, name, price))
        nb.addStretch(1)
        v.addWidget(self.new_box)

        bb = QDialogButtonBox()
        ok = bb.addButton("确定", QDialogButtonBox.AcceptRole); ok.setObjectName("primary")
        bb.addButton("取消", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._refresh()

    def _source(self):
        return (config.SOURCE_ALL if self.rb_all.isChecked()
                else config.SOURCE_NEW if self.rb_new.isChecked() else config.SOURCE_CURRENT)

    def _refresh(self):
        is_new = self._source() == config.SOURCE_NEW
        self.new_box.setVisible(is_new)
        for w in (self.listw, self.search, self.lbl_sel, self.btn_all):
            w.setVisible(not is_new)
        if is_new:
            return
        kw = self.search.text().strip().lower()
        self.listw.blockSignals(True)
        self.listw.clear()
        if self._source() == config.SOURCE_CURRENT:
            items = [(h.code, h.name) for h in (self.product.securities() if self.product else [])]
        else:
            items = [(it.code, it.name) for it in self.merged]
        for code, name in items:
            if kw and kw not in code.lower() and kw not in (name or "").lower():
                continue
            it = QListWidgetItem(f"{code}    {name}")
            it.setData(Qt.UserRole, code); it.setData(Qt.UserRole + 1, name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if code in self.checked else Qt.Unchecked)  # 恢复已勾选
            self.listw.addItem(it)
        self.listw.blockSignals(False)
        self._update_count()

    def _on_item_changed(self, item):
        code = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self.checked[code] = item.data(Qt.UserRole + 1) or ""
        else:
            self.checked.pop(code, None)
        self._update_count()

    def _check_all(self, checked):
        st = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.listw.count()):
            self.listw.item(i).setCheckState(st)   # 触发 itemChanged -> 同步到 self.checked

    def _toggle_all(self):
        # 针对当前可见(筛选后)行：全勾选则全取消，否则全勾选
        n = self.listw.count()
        all_checked = n > 0 and all(self.listw.item(i).checkState() == Qt.Checked for i in range(n))
        self._check_all(not all_checked)

    def _update_count(self, *_):
        self.lbl_sel.setText(f"已选 {len(self.checked)} 只")   # 跨筛选/来源的总数

    def _accept(self):
        if self._source() == config.SOURCE_NEW:
            name_by_code = {it.code: it.name for it in self.merged}
            picks, seen, guessed = [], set(), []
            for code_edit, name_edit, price_edit in self.new_rows:
                raw = code_edit.text().strip()
                if not raw:
                    continue
                code, was_guessed = normalize_code(raw)
                if was_guessed:
                    guessed.append((raw, code))
                if code and code not in seen:
                    seen.add(code)
                    name = name_edit.text().strip() or name_by_code.get(code, "")
                    price = _to_float(price_edit.text())
                    picks.append((code, name, price))
            if not picks:
                QMessageBox.warning(self, "提示", "请至少填写一只证券代码"); return
            if guessed:
                # 逐行显示实际推断结果，避免「700→000700.SZ」这种错市场被忽略
                lines = "\n".join(f"  {raw}  →  {code}" for raw, code in guessed)
                if QMessageBox.question(
                        self, "确认代码", f"以下代码缺市场后缀，已推断为：\n\n{lines}\n\n"
                        f"（港股请务必带 .HK 后缀，裸数字会被当成 A 股）\n确认使用？",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                    return
            self.picked = picks
        else:
            # 用持久集合 self.checked（跨筛选/跨来源），不只读当前可见行
            self.picked = [(code, name, None) for code, name in self.checked.items()]
            if not self.picked:
                QMessageBox.warning(self, "提示", "请勾选至少一只证券"); return
        self.accept()


# ---------------------------------------------------------------------------
# 导出对话框（自绘小面板：居中、暗色、两个模式一致；只在「更改」时才弹原生选夹）
# ---------------------------------------------------------------------------
class ExportDialog(QDialog):
    def __init__(self, parent, win, mode, date_tag, init_dir):
        super().__init__(parent)
        self.win = win
        self.mode = mode               # 'single' / 'split'
        self.folder = init_dir
        self.setWindowTitle("导出下单指令" if mode == "single" else "分产品导出")
        self.setModal(True)
        self.setMinimumWidth(440)
        v = QVBoxLayout(self); v.setContentsMargins(20, 18, 20, 16); v.setSpacing(14)

        # 保存到文件夹
        frow = QHBoxLayout()
        flab = QLabel("保存到："); flab.setStyleSheet(f"color:{C_DIM};")
        self.folder_edit = QLineEdit(self.folder)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setStyleSheet(f"background:{C_PANEL}; border:1px solid {C_BORDER}; border-radius:5px; padding:6px;")
        btn_change = QPushButton("更改…"); btn_change.clicked.connect(self._change_dir)
        frow.addWidget(flab); frow.addWidget(self.folder_edit, 1); frow.addWidget(btn_change)
        v.addLayout(frow)

        # 文件名（单文件可改；分产品为自动命名说明）
        nrow = QHBoxLayout()
        nlab = QLabel("文件名："); nlab.setStyleSheet(f"color:{C_DIM};")
        if mode == "single":
            self.name_edit = QLineEdit(f"交易指令_{date_tag}.xlsx")
            self.name_edit.setStyleSheet(f"background:{C_PANEL}; border:1px solid {C_BORDER}; border-radius:5px; padding:6px;")
            nrow.addWidget(nlab); nrow.addWidget(self.name_edit, 1)
        else:
            self.name_edit = None
            tip = QLabel(f"交易指令_产品名_{date_tag}.xlsx")
            tip.setStyleSheet(f"color:{C_DIM};")
            nrow.addWidget(nlab); nrow.addWidget(tip, 1)
        v.addLayout(nrow)

        bb = QDialogButtonBox()
        ok = bb.addButton("导出", QDialogButtonBox.AcceptRole); ok.setObjectName("primary")
        bb.addButton("取消", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存文件夹", self.folder or os.getcwd())
        if d:
            self.folder = d
            self.folder_edit.setText(d)

    def filename(self):
        return self.name_edit.text().strip() if self.name_edit else ""

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parent()
        if p is not None:
            pg = p.frameGeometry()
            self.move(pg.center().x() - self.width() // 2, pg.center().y() - self.height() // 2)


# ---------------------------------------------------------------------------
# 预览/确认对话框（output.png 样式：卖出标黄在前）
# ---------------------------------------------------------------------------
class PreviewDialog(QDialog):
    def __init__(self, parent, result):
        super().__init__(parent)
        self.win = parent
        self.result = result
        self.setWindowTitle("预览下单指令")
        self.resize(820, 580)
        v = QVBoxLayout(self); v.setSpacing(10)
        lbl = QLabel(f"共 {len(result.orders)} 条交易指令，核对后导出：")
        lbl.setStyleSheet(f"color:{C_TEXT}; font-size:14px; font-weight:600;")
        v.addWidget(lbl)

        # 每个产品一张表（序号列表头=产品名，与 output.png 一致），多产品之间留空隙
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border:0; }} QWidget {{ background:{C_BG}; }}")
        holder = QWidget(); hv = QVBoxLayout(holder); hv.setSpacing(18); hv.setContentsMargins(0, 0, 0, 0)
        for pname in result.products():
            hv.addWidget(self._product_table(pname, result.orders_for(pname)))
        hv.addStretch(1)
        scroll.setWidget(holder)
        v.addWidget(scroll, 1)

        if result.warnings:
            box = QTextEdit(); box.setReadOnly(True); box.setMaximumHeight(96)
            box.setStyleSheet("color:#ffb454;")
            box.setPlainText("提示（%d）：\n" % len(result.warnings) + "\n".join(result.warnings))
            v.addWidget(box)

        # 「关闭」靠左，两个导出按钮靠右（主操作在右）
        row = QHBoxLayout()
        close = QPushButton("关闭"); close.clicked.connect(self.reject)
        ok = QPushButton("确认并导出"); ok.setObjectName("primary")
        ok.setToolTip("所有产品合并到一个 Excel，每个产品一个 Sheet")
        split = QPushButton("分产品导出"); split.setObjectName("primary")
        split.setToolTip("每个产品单独导出一个 Excel 文件")
        ok.clicked.connect(lambda: self.win._export_single(self.result, self))
        split.clicked.connect(lambda: self.win._export_split(self.result, self))
        if not result.orders:
            ok.setEnabled(False); split.setEnabled(False)
        row.addWidget(close)
        row.addStretch(1)
        row.addWidget(split)
        row.addWidget(ok)
        v.addLayout(row)

    def _product_table(self, pname, orders):
        rowh = 30
        t = QTableWidget(len(orders), 6)
        # 第一列表头 = 产品名（序号列），其余与券商下单格式一致
        t.setHorizontalHeaderLabels([pname, "交易方向", "证券代码", "证券名称", "买入数量", "卖出数量"])
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        yellow = QColor("#ffe600"); black = QColor("#111111")
        for i, o in enumerate(orders):     # orders 已是卖出在前
            vals = [i + 1, o.direction, o.code, o.name,
                    int(o.buy_qty) if o.buy_qty else "", int(o.sell_qty) if o.sell_qty else ""]
            is_sell = o.direction == config.DIR_SELL
            for c, val in enumerate(vals):
                cell = QTableWidgetItem("" if val == "" else str(val))
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if c == 3 else Qt.AlignCenter))
                if is_sell:
                    cell.setBackground(yellow); cell.setForeground(black)
                elif c == 1:
                    cell.setForeground(QColor(C_BUY))
                t.setItem(i, c, cell)
            t.setRowHeight(i, rowh)
        # 列宽：买入/卖出等宽；其余按内容
        t.resizeColumnsToContents()
        for c in (4, 5):
            t.setColumnWidth(c, 96)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)  # 证券名称撑开
        hdr_h = t.horizontalHeader().height()
        t.setFixedHeight(hdr_h + rowh * len(orders) + 2)
        return t


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1080, 660)
        self.settings = QSettings("PortfolioAdjust", "调仓工具")
        self.products = []
        self.merged = []
        self.folder = ""
        self.custom = self._load_custom()      # 经理新增过的票（持久化，跨启动保留）
        if self._migrated and self.custom:     # 旧 QSettings 数据迁移后立即落盘一次
            self._save_custom()
        self._build_ui()
        last = self.settings.value("last_folder", "", str)
        if last and os.path.isdir(last):
            self._load_folder(last)
        elif os.path.isdir(os.path.join(os.getcwd(), "product")):
            self._load_folder(os.path.join(os.getcwd(), "product"))

        # 更新检查器：启动不联网，仅在经理点「检查更新」时才联网一次
        self._updater = UpdateChecker(self)
        self._updater.found.connect(self._on_update_found)
        self._updater.uptodate.connect(self._on_update_uptodate)
        self._updater.failed.connect(self._on_update_failed)

    def _show_more_menu(self):
        menu = QMenu(self)
        menu.addAction("检查更新…", self.on_check_update)
        menu.addAction("关于 调仓工具", self._on_about)
        menu.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def on_check_update(self):
        self.btn_more.setEnabled(False)
        self.statusBar().showMessage("正在检查更新…")
        self._updater.check_async()

    def _reset_update_btn(self):
        self.btn_more.setEnabled(True)
        self.statusBar().showMessage("就绪")

    def _on_update_found(self, ver, url):
        self._reset_update_btn()
        if QMessageBox.question(
                self, "发现新版本", f"检测到新版本 {ver}（当前 {APP_VERSION}）。\n是否前往下载更新？\n\n"
                f"下载后双击新安装包覆盖安装即可，你的设置与新增证券会保留。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes and url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_update_uptodate(self, ver):
        self._reset_update_btn()
        QMessageBox.information(self, "检查更新", f"当前已是最新版本（{ver}）。")

    def _on_update_failed(self, reason):
        self._reset_update_btn()
        QMessageBox.warning(self, "检查更新", reason)

    def _on_about(self):
        QMessageBox.information(self, "关于", f"批量调仓下单工具\n版本 {APP_VERSION}")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(14, 12, 14, 12); root.setSpacing(10)

        bar = QHBoxLayout(); bar.setSpacing(10)
        self.btn_open = QPushButton("📁 选择产品文件夹")
        self.btn_open.clicked.connect(self.on_open_folder)
        self.lbl_count = QLabel("")
        bar.addWidget(self.btn_open)
        bar.addWidget(self.lbl_count)
        bar.addStretch(1)
        self.btn_more = QPushButton("更多")            # 低频工具：检查更新/关于（弹出菜单）
        self.btn_more.clicked.connect(self._show_more_menu)
        bar.addWidget(self.btn_more)
        self.btn_new = QPushButton("新增产品")        # 常驻入口，表满了也能加（不依赖右键空白）
        self.btn_new.clicked.connect(self._add_product)
        bar.addWidget(self.btn_new)
        self.btn_preview = QPushButton("预览")
        self.btn_preview.setObjectName("primary")
        self.btn_preview.clicked.connect(self.on_preview)
        bar.addWidget(self.btn_preview)
        root.addLayout(bar)

        self.tree = TradeTree()
        self.tree.setColumnCount(len(HEADERS))
        self.tree.setHeaderLabels(HEADERS)
        self.tree.setItemDelegate(TreeDelegate(self))
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)    # 由 itemClicked 控制单击即编辑
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemChanged.connect(self._on_changed)
        hh = self.tree.header()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(COL_POOL, QHeaderView.Stretch)         # 证券池自适应填充
        for c, w in zip(range(len(HEADERS)), [140, 100, 220, 120, 130, 100, 90, 100]):
            self.tree.setColumnWidth(c, w)
        # 表头对齐：数字右、证券池左、其余居中（与单元格一致，防错位）
        hi = self.tree.headerItem()
        for c in range(len(HEADERS)):
            hi.setTextAlignment(c, Qt.AlignVCenter | (
                Qt.AlignRight if c in RIGHT_COLS else Qt.AlignLeft if c == COL_POOL else Qt.AlignHCenter))
        root.addWidget(self.tree, 1)
        # 空表时居中的虚线「＋新增产品」按钮（点击出三行；之后右键继续新增）
        self.add_btn = QPushButton("＋  新增产品", self.tree.viewport())
        self.add_btn.setStyleSheet(DASH_BTN_QSS)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_product)
        self.tree.set_overlay(self.add_btn)
        self.statusBar().showMessage("就绪")

    # ------------------------------------------------------------- 文件夹
    def on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 product 文件夹", self.folder or os.getcwd())
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder):
        try:
            products = read_product_folder(folder)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", f"无法读取文件夹：\n{exc}"); return
        if not products:
            QMessageBox.warning(self, "提示", "该文件夹下没有产品 Excel（.xlsx）"); return
        self.folder = folder
        self.products = products
        self.merged = merged_security_pool(products)
        self.settings.setValue("last_folder", folder)
        self.lbl_count.setText(f"已加载 {len(products)} 个产品")
        self.tree.update_overlay()       # 空表则显示虚线「＋新增产品」按钮（不自动建默认行）
        wlines = self._product_warning_lines(products)
        if wlines:
            self.statusBar().showMessage(f"⚠ 持仓表有 {len(wlines)} 条解析提示（请核对）", 8000)
            QMessageBox.information(
                self, "持仓表解析提示",
                "以下产品在解析持仓表时有提示，请核对（不影响继续使用）：\n\n"
                + "\n".join(wlines[:30]) + ("\n  …" if len(wlines) > 30 else ""))

    def _rescan(self):
        """重新扫描当前文件夹（用户可能中途往里加/删了产品文件）。
        刷新产品列表、合并证券池，并同步所有已存在的产品下拉选项（保留当前选择）。"""
        if not self.folder or not os.path.isdir(self.folder):
            return
        try:
            products = read_product_folder(self.folder)
        except Exception:  # noqa: BLE001 扫描失败则维持现状
            return
        if not products:
            return
        before = {p.name for p in self.products}
        self.products = products
        self.merged = merged_security_pool(products)
        self.lbl_count.setText(f"已加载 {len(products)} 个产品")
        names = self._product_names()
        for i in range(self.tree.topLevelItemCount()):
            cb = self.tree.itemWidget(self.tree.topLevelItem(i), COL_PRODUCT)
            if isinstance(cb, QComboBox):
                cur = cb.currentText()
                cb.blockSignals(True)
                cb.clear(); cb.addItem(getattr(cb, "_ph", "选择产品…")); cb.addItems(names)
                idx = cb.findText(cur)
                cb.setCurrentIndex(idx if idx >= 0 else 0)
                cb.blockSignals(False)
        wlines = self._product_warning_lines(products)
        added = [n for n in names if n not in before]
        if wlines:
            self.statusBar().showMessage(f"⚠ 持仓表有 {len(wlines)} 条解析提示（请核对）", 6000)
        elif added:
            self.statusBar().showMessage(f"已发现新产品：{'、'.join(added)}", 4000)

    @staticmethod
    def _product_warning_lines(products):
        """汇总各产品持仓表解析告警，供 UI 非阻断提示。"""
        return [f"· {p.name}：{w}" for p in products for w in p.warnings]

    def _product_names(self):
        return [p.name for p in self.products]

    def _product_by_name(self, name):
        return next((p for p in self.products if p.name == name), None)

    # ------------------------------------------------------------- 节点构造
    def _new_item(self, parent, level):
        it = QTreeWidgetItem(parent)
        it.setData(0, ROLE_LEVEL, level)
        for c in range(len(HEADERS)):
            if c in RIGHT_COLS:
                it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                it.setFont(c, _mono())
            else:
                it.setTextAlignment(c, Qt.AlignVCenter | (Qt.AlignLeft if c in (COL_PRODUCT, COL_POOL) else Qt.AlignHCenter))
        return it

    def _cell_combo(self, items, placeholder):
        """常驻下拉框：第 0 项为占位（代表"未选"），默认选它——绝不预填真实值。

        用占位项而非 setCurrentIndex(-1)：避免 macOS 下拉弹出时把第一项(如"买入")
        高亮成"已选"的假象。打开后高亮落在占位项上，一目了然没选。
        """
        cb = QComboBox()
        cb.addItem(placeholder)
        cb.addItems(items)
        cb.setCurrentIndex(0)
        cb._ph = placeholder
        cb.setStyleSheet(CELL_COMBO_QSS + f"QComboBox{{border:1px solid {C_REQ};border-radius:4px;}}")
        return cb

    def _combo_text(self, item, col):
        w = self.tree.itemWidget(item, col)
        if not isinstance(w, QComboBox):
            return ""
        t = w.currentText()
        return "" if t == getattr(w, "_ph", "") else t   # 占位项视为"未选"

    def _style_combo(self, item, col, kind):
        """按是否已选设置边框：未选=红框提醒；方向已选则蓝/红着色并在行首打彩点。"""
        cb = self.tree.itemWidget(item, col)
        if not isinstance(cb, QComboBox):
            return
        val = cb.currentText().strip()
        if val == getattr(cb, "_ph", ""):    # 占位项=未选
            val = ""
        border = "none" if val else f"1px solid {C_REQ}"
        extra = ""
        if kind == "dir":
            if val:
                c = C_BUY if val == config.DIR_BUY else C_SELL
                extra = f"color:{c};font-weight:bold;"
                item.setIcon(COL_PRODUCT, _dot(c))
            else:
                item.setIcon(COL_PRODUCT, QIcon())
        cb.setStyleSheet(CELL_COMBO_QSS + f"QComboBox{{border:{border};border-radius:4px;{extra}}}")

    def _mark_required(self):
        """扫描全表，给未填的必填项（产品/方向/方式/金额/证券）标淡红提醒。"""
        for i in range(self.tree.topLevelItemCount()):
            pnode = self.tree.topLevelItem(i)
            self._style_combo(pnode, COL_PRODUCT, "plain")
            for j in range(pnode.childCount()):
                g = pnode.child(j)
                if g.data(0, ROLE_LEVEL) != LV_GROUP:
                    continue
                self._style_combo(g, COL_DIR, "dir")
                self._style_combo(g, COL_METHOD, "plain")
                # 金额/证券池 的淡红边框由 delegate.paint 负责；这里只把占位文字置灰
                for k in range(g.childCount()):
                    s = g.child(k)
                    if not s.data(COL_POOL, ROLE_CODE):
                        s.setForeground(COL_POOL, QColor(C_DIM))

    def _add_product(self, _checked=False):
        """点虚线按钮/右键：新增一个产品，并自动带出「交易组 + 证券」共三行（三级），均为空。"""
        self._rescan()      # 先重扫文件夹，确保新加进 product/ 的产品文件能立刻被选到
        if not self.products:
            QMessageBox.warning(self, "提示", "请先选择产品文件夹"); return None
        self.tree.blockSignals(True)
        try:
            p = self._new_item(self.tree, LV_PRODUCT)
            for c in range(len(HEADERS)):
                p.setBackground(c, QColor(C_PRODUCT))
            p.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        cb = self._cell_combo(self._product_names(), "选择产品…")   # 无默认值，不预填
        self.tree.setItemWidget(p, COL_PRODUCT, cb)
        cb.currentTextChanged.connect(self.recompute)
        self._add_group(p)          # 交易组（内部再带出一行空证券）
        self.tree.update_overlay()
        self.recompute()
        self.tree.setCurrentItem(p)
        self.tree.scrollToItem(p)   # 表满时滚动到新加的产品，确保可见
        return p

    def _add_group(self, pnode=None, _checked=False):
        pnode = pnode or self._product_node(self.tree.currentItem())
        if pnode is None:
            QMessageBox.warning(self, "提示", "请先在某个产品上新增交易组"); return None
        self.tree.blockSignals(True)
        try:
            g = self._new_item(pnode, LV_GROUP)
            g.setFlags(g.flags() | Qt.ItemIsEditable)
            for c in range(len(HEADERS)):
                g.setBackground(c, QColor(C_GROUP))
            g.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        cb_d = self._cell_combo([config.DIR_BUY, config.DIR_SELL], "选择方向…")   # 无默认值
        self.tree.setItemWidget(g, COL_DIR, cb_d)
        cb_m = self._cell_combo([config.METHOD_EQUAL, config.METHOD_HOLDING], "选择方式…")  # 无默认值
        self.tree.setItemWidget(g, COL_METHOD, cb_m)
        cb_d.currentTextChanged.connect(self.recompute)
        cb_m.currentTextChanged.connect(self.recompute)
        pnode.setExpanded(True)
        self._add_empty_stock(g)    # 带出一行空证券（点它可批量选）
        self.tree.setCurrentItem(g)
        self.recompute()
        return g

    def _new_stock_node(self, gnode):
        s = self._new_item(gnode, LV_STOCK)
        s.setFlags(s.flags() | Qt.ItemIsEditable)
        return s

    def _add_empty_stock(self, gnode):
        """加一行空证券占位（点击该格弹出可多选的选股框）。"""
        self.tree.blockSignals(True)
        try:
            s = self._new_stock_node(gnode)
            s.setText(COL_POOL, "选择证券…")
            s.setForeground(COL_POOL, QColor(C_DIM))
            gnode.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        return s

    def _set_stock(self, node, code, name):
        node.setData(COL_POOL, ROLE_CODE, code); node.setData(COL_POOL, ROLE_NAME, name)
        node.setText(COL_POOL, f"{code}  {name}".strip())
        node.setForeground(COL_POOL, QColor(C_TEXT))

    def _pick_securities(self, gnode):
        self._rescan()      # 重扫文件夹，使「当前产品/全部产品」证券池反映最新文件
        # 组里若还没选产品，「当前产品」回退到第一个产品，避免列表空白
        product = self._product_by_name(self._combo_text(gnode.parent(), COL_PRODUCT))
        if product is None and self.products:
            product = self.products[0]
        dlg = SecurityPicker(self, product, self._all_pool())   # 全部产品 + 历史新增
        if dlg.exec() == QDialog.Accepted and dlg.picked:
            self._remember_custom(dlg.picked)   # 记住新增的票
            return dlg.picked
        return []

    # ------------------------------------------------------------- 新增票持久化
    # 存到 ~/.portfolio_adjust/custom_securities.json（用户主目录，跨重启/重新部署保留）。
    def _load_custom(self):
        """返回 [(code, name, price)]；优先读 JSON 文件，找不到则迁移旧 QSettings 数据。

        self._migrated 标记本次是否来自 QSettings 迁移，供 __init__ 迁移后落盘一次。
        """
        import json
        self._migrated = False
        data = None
        try:
            if os.path.exists(CUSTOM_FILE):
                with open(CUSTOM_FILE, encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:  # noqa: BLE001 文件损坏/非法 -> 当作没有
            data = None
        if data is None:                       # 兼容老版本：从 QSettings 迁移
            raw = self.settings.value("custom_securities", "", str)
            try:
                data = json.loads(raw) if raw else []
            except Exception:  # noqa: BLE001
                data = []
            self._migrated = True
        out = []
        if isinstance(data, list):             # 校验形状：必须是 list-of-list，code 为非空字符串
            for d in data:
                if isinstance(d, (list, tuple)) and d and isinstance(d[0], str) and d[0].strip():
                    name = d[1] if len(d) > 1 and isinstance(d[1], str) else ""
                    price = (d[2] if len(d) > 2 and isinstance(d[2], (int, float))
                             and not isinstance(d[2], bool) else None)   # 排除 true/false 被当价格
                    out.append((d[0].strip(), name, price))
        return out

    @property
    def _custom_price(self):
        return {c: p for c, _n, p in self.custom if p}

    def _save_custom(self):
        import json
        seen, uniq = set(), []
        for c, n, p in self.custom:
            if c not in seen:
                seen.add(c); uniq.append([c, n, p])
        self.custom = [(c, n, p) for c, n, p in uniq]
        try:
            os.makedirs(CUSTOM_DIR, exist_ok=True)
            with open(CUSTOM_FILE, "w", encoding="utf-8") as f:
                json.dump(uniq, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", f"新增证券未能保存到磁盘：\n{exc}")
        # 同时写 QSettings 作为冗余备份
        self.settings.setValue("custom_securities", json.dumps(uniq, ensure_ascii=False))

    def _remember_custom(self, picks):
        """把新票（含手填价格）记下来，下次启动仍能在证券池找到。

        已在产品池里的代码：仅当经理手填了价格才记录（作为对文件价的更正），无价则不记。
        """
        prod_codes = {it.code for it in self.merged}
        by_code = {c: (c, n, p) for c, n, p in self.custom}
        changed = False
        for c, n, p in picks:
            if not c or (c in prod_codes and p is None):
                continue
            old = by_code.get(c)
            if old is None or (p is not None and p != old[2]) or (n and n != old[1]):
                by_code[c] = (c, n or (old[1] if old else ""), p if p is not None else (old[2] if old else None))
                changed = True
        if changed:
            self.custom = list(by_code.values())
            self._save_custom()

    def _all_pool(self):
        """证券池 = 全部产品合并池 + 历史新增（含未持仓的自定义票，带手填价格）。"""
        items = list(self.merged)
        known = {it.code for it in self.merged}
        for c, n, p in self.custom:
            if c not in known:
                items.append(StockPoolItem(code=c, name=n, price=p or 0.0, cny_unit_price=p))
        return items

    def _price_of(self, code, product=None):
        """价格：经理手填的自定义价优先（含对已持仓票的更正），其次按所属产品取文件反推价。"""
        manual = self._custom_price.get(code)
        if manual is not None:
            return manual
        return default_cny_price(code, self.products, self.merged, prefer_product=product)

    def _add_stock(self, gnode=None, _checked=False):
        """右键「新增证券」：弹出选股框，一次可勾选多只，全部加入。"""
        gnode = gnode or self._group_node(self.tree.currentItem())
        if gnode is None:
            QMessageBox.warning(self, "提示", "请先在某个交易组上新增证券"); return
        picks = self._pick_securities(gnode)
        if not picks:
            return
        self.tree.blockSignals(True)
        try:
            for code, name, _price in picks:
                self._set_stock(self._new_stock_node(gnode), code, name)
            gnode.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
        self.recompute()

    def _del_item(self, _checked=False):
        it = self.tree.currentItem()
        if it is None:
            return
        parent = it.parent()
        (parent or self.tree.invisibleRootItem()).removeChild(it)
        self.tree.update_overlay()
        self.recompute()

    # ------------------------------------------------------------- 辅助
    def _product_node(self, item):
        while item is not None:
            if item.data(0, ROLE_LEVEL) == LV_PRODUCT:
                return item
            item = item.parent()
        return None

    def _group_node(self, item):
        while item is not None:
            if item.data(0, ROLE_LEVEL) == LV_GROUP:
                return item
            item = item.parent()
        return None

    # ------------------------------------------------------------- 交互
    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        lv = item.data(0, ROLE_LEVEL) if item else None
        if lv == LV_PRODUCT:
            menu.addAction("＋ 新增交易组", lambda: self._add_group(item))
            menu.addSeparator()
            menu.addAction("✕ 删除产品", self._del_item)
        elif lv == LV_GROUP:
            menu.addAction("＋ 新增证券", lambda: self._add_stock(item))
            menu.addSeparator()
            menu.addAction("✕ 删除交易组", self._del_item)
        elif lv == LV_STOCK:
            menu.addAction("✕ 删除证券", self._del_item)
        else:
            menu.addAction("＋ 新增产品", self._add_product)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_clicked(self, item, col):
        lv = item.data(0, ROLE_LEVEL)
        if lv == LV_STOCK and col == COL_POOL:
            gnode = item.parent()
            picks = self._pick_securities(gnode) if gnode else []
            if picks:
                self.tree.blockSignals(True)
                try:
                    self._set_stock(item, picks[0][0], picks[0][1])      # 第一只填当前行
                    for code, name, _price in picks[1:]:                 # 其余批量加新行
                        self._set_stock(self._new_stock_node(gnode), code, name)
                    gnode.setExpanded(True)
                finally:
                    self.tree.blockSignals(False)
                self.recompute()
            return
        # 金额/调整 文本单元格：单击立即进入编辑（产品/方向/方式是常驻下拉，无需此处理）
        if (lv == LV_GROUP and col == COL_AMOUNT) or (lv == LV_STOCK and col == COL_ADJUST):
            self.tree.editItem(item, col)

    def _on_changed(self, item, col):
        self.recompute()

    # ------------------------------------------------------------- 收集/计算
    def _collect(self):
        """遍历树 -> [(DirectionGroup, [(StockEntry, stock_item)])]。"""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            pnode = self.tree.topLevelItem(i)
            if pnode.data(0, ROLE_LEVEL) != LV_PRODUCT:
                continue
            pname = self._combo_text(pnode, COL_PRODUCT).strip()
            prod = self._product_by_name(pname)
            for j in range(pnode.childCount()):
                gnode = pnode.child(j)
                if gnode.data(0, ROLE_LEVEL) != LV_GROUP:
                    continue
                group = DirectionGroup(product=pname,
                                       direction=self._combo_text(gnode, COL_DIR).strip(),
                                       amount=_to_float(gnode.text(COL_AMOUNT)),
                                       method=self._combo_text(gnode, COL_METHOD).strip())
                rows = []
                for k in range(gnode.childCount()):
                    snode = gnode.child(k)
                    code = snode.data(COL_POOL, ROLE_CODE) or ""
                    if not code:
                        continue
                    e = StockEntry(code=code, name=snode.data(COL_POOL, ROLE_NAME) or "",
                                   price=self._price_of(code, prod),
                                   adjust=_to_int(snode.text(COL_ADJUST)))
                    group.stocks.append(e); rows.append((e, snode))
                out.append((group, rows))
        return out

    def recompute(self):
        if not self.products:
            return
        self.tree.blockSignals(True)
        warns_all, err = [], None
        try:
            sold_so_far = {}   # (产品,代码)->已显示卖出量，跨组封顶，使界面卖出之和=实际卖出
            for group, rows in self._collect():
                try:           # 单组出错不影响其他组（避免一只产品异常把后面所有产品的股数清零）
                    product = self._product_by_name(group.product)
                    for e, snode in rows:
                        snode.setText(COL_PRICE, (f"{e.price:.3f}".rstrip("0").rstrip(".")) if e.price else "")
                        snode.setForeground(COL_PRICE, QColor(C_DIM))
                    w, _ok = compute_group_shares(group, product)
                    warns_all.extend(w)
                    gwarn = w[0] if w else ""
                    direction = normalize_direction(group.direction)
                    for e, snode in rows:
                        disp = e.shares
                        if direction == config.DIR_SELL and product is not None and e.shares:
                            h = product.get(e.code)
                            cur = h.quantity if h else 0.0
                            already = sold_so_far.get((group.product, e.code), 0)
                            remaining = max(0.0, cur - already)
                            disp = clamp_sell_to_holding(e.shares, remaining, e.code, product)
                            if disp > 0:
                                sold_so_far[(group.product, e.code)] = already + disp
                        snode.setText(COL_SHARES, str(disp) if disp else "0")
                        snode.setForeground(COL_SHARES, QColor(C_TEXT))
                        # 股数为 0 时，把"为何是 0"的原因挂成悬停提示（卖未持有/持仓比例无基准/无价等）
                        snode.setToolTip(COL_SHARES, "" if disp else gwarn)
                except Exception as ex:  # noqa: BLE001
                    err = ex
            self._mark_required()      # 标红未填的必填项（仍在 blockSignals 内，避免回环）
        except Exception as ex:  # noqa: BLE001
            err = ex
        finally:
            self.tree.blockSignals(False)
        self.tree.viewport().update()      # 刷新 delegate 的淡红必填边框
        # 把"为何股数是 0"的提示实时显示到状态栏，不必等到「预览」才知道
        if err is not None:
            self.statusBar().showMessage(f"⚠ 计算出错：{err}", 8000)
        elif warns_all:
            more = f"（共 {len(warns_all)} 条，详见预览）" if len(warns_all) > 1 else ""
            self.statusBar().showMessage("⚠ " + warns_all[0] + more, 8000)
        else:
            self.statusBar().clearMessage()

    # ------------------------------------------------------------- 预览导出
    def _validate(self):
        """校验必填：产品已选 + 每个交易组 方向/金额/方式 齐全 + 至少一只股票。"""
        problems = []
        for i in range(self.tree.topLevelItemCount()):
            pnode = self.tree.topLevelItem(i)
            pname = self._combo_text(pnode, COL_PRODUCT).strip()
            tag = pname or f"第{i + 1}个产品"
            if not pname:
                problems.append(f"{tag}：未选择产品")
            for j in range(pnode.childCount()):
                g = pnode.child(j)
                direction = self._combo_text(g, COL_DIR).strip()
                miss = []
                if not direction:
                    miss.append("方向")
                if _to_float(g.text(COL_AMOUNT)) is None or (_to_float(g.text(COL_AMOUNT)) or 0) <= 0:
                    miss.append("金额")
                if not self._combo_text(g, COL_METHOD).strip():
                    miss.append("方式")
                stocks = sum(1 for k in range(g.childCount()) if g.child(k).data(COL_POOL, ROLE_CODE))
                if miss:
                    problems.append(f"{tag} · {direction or '交易组'}：缺 {'、'.join(miss)}")
                elif stocks == 0:
                    problems.append(f"{tag} · {direction}组：未添加证券")
        return problems

    def on_preview(self):
        if not self.products:
            QMessageBox.warning(self, "提示", "请先选择产品文件夹"); return
        groups = [g for g, _ in self._collect()]
        if not groups:
            QMessageBox.warning(self, "提示", "请先右键新增产品/交易组/股票"); return
        problems = self._validate()
        if problems:
            QMessageBox.warning(self, "请补全必填项", "以下内容需要填写：\n\n• " + "\n• ".join(problems))
            return
        try:
            result = build_orders(groups, self.products, self.merged)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "计算失败", f"{exc}\n\n{traceback.format_exc()}"); return
        # 预览窗常开：导出在窗内进行，导出完不关闭，方便核对/再次导出，由「关闭」收起。
        # 用 scrim 把主窗压暗，让预览窗层次分明。
        exec_with_scrim(PreviewDialog(self, result), self.centralWidget())

    def _export_dir(self):
        """上次导出目录（记忆）；失效或没有则用产品文件夹/当前目录。"""
        d = self.settings.value("last_export_dir", "", str)
        if d and os.path.isdir(d):
            return d
        return self.folder or os.getcwd()

    def _remember_export_dir(self, path):
        d = path if os.path.isdir(path) else os.path.dirname(path)
        if d:
            self.settings.setValue("last_export_dir", d)

    def _confirm_overwrite(self, paths):
        """已存在的文件给出覆盖确认。返回 True=继续。"""
        exist = [p for p in paths if os.path.exists(p)]
        if not exist:
            return True
        names = "\n".join(os.path.basename(p) for p in exist[:8])
        more = f"\n…等 {len(exist)} 个文件" if len(exist) > 8 else ""
        return QMessageBox.question(
            self, "文件已存在", f"以下文件已存在，是否覆盖？\n\n{names}{more}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _confirm_self_trades(self, result, host):
        """存在同标的买卖（对倒/自成交）时，导出前强制二次确认。返回 True=继续。"""
        pairs = getattr(result, "self_trades", None)
        if not pairs:
            return True
        codes = "、".join(c for _, c in pairs[:8]) + ("…" if len(pairs) > 8 else "")
        return QMessageBox.question(
            host, "存在自成交 / 对倒",
            f"以下标的同时有买单和卖单：{codes}\n\n"
            f"直接发券商会形成对倒（双向佣金 / 合规风险）。建议先合并或删除其一。\n\n确定仍要导出吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _export_single(self, result, parent=None):
        if not result.orders:
            return
        host = parent or self
        if not self._confirm_self_trades(result, host):
            return
        dlg = ExportDialog(host, self, "single", self._date_tag(), self._export_dir())
        if exec_with_scrim(dlg, host) != QDialog.Accepted:
            return
        name = dlg.filename() or f"交易指令_{self._date_tag()}.xlsx"
        if name.lower().endswith(".xlsx"):
            name = name[:-5]
        name = safe_filename(name).strip() or f"交易指令_{self._date_tag()}"  # 统一净化非法字符
        path = os.path.join(dlg.folder, name + ".xlsx")
        if not self._confirm_overwrite([path]):
            return
        try:
            write_orders(result.orders, path)
            self._remember_export_dir(dlg.folder)
            QMessageBox.information(self, "完成", f"下单指令已导出：\n{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))

    def _export_split(self, result, parent=None):
        if not result.orders:
            return
        host = parent or self
        if not self._confirm_self_trades(result, host):
            return
        dlg = ExportDialog(host, self, "split", self._date_tag(), self._export_dir())
        if exec_with_scrim(dlg, host) != QDialog.Accepted:
            return
        # 预判将生成的文件名（与 excel_io.write_orders_per_product 同款净化+去重），检查是否覆盖
        tag = self._date_tag()
        expected, used = [], set()
        for p in result.products():
            base = f"交易指令_{safe_filename(p)}_{tag}"
            fname, k = base, 1
            while fname in used:           # 与写出端一致的 _2/_3 去重
                k += 1; fname = f"{base}_{k}"
            used.add(fname)
            expected.append(os.path.join(dlg.folder, fname + ".xlsx"))
        if not self._confirm_overwrite(expected):
            return
        try:
            paths = write_orders_per_product(result.orders, dlg.folder, date=tag)
            self._remember_export_dir(dlg.folder)
            QMessageBox.information(self, "完成", "已按产品导出 %d 个文件到：\n%s\n\n%s" % (
                len(paths), dlg.folder, "\n".join(os.path.basename(p) for p in paths)))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))

    def _date_tag(self):
        from datetime import date
        return date.today().strftime("%Y%m%d")   # 下单当天日期，作为导出文件名后缀


def _selftest():
    import tempfile
    from rebalancer.models import Holding, Product
    p = Product(name="自检产品", total_assets=1_000_000.0)
    p.holdings = [Holding("600000.SH", "甲", "股票", 10.0, 1000, 10000.0, 0.01)]
    p.rebuild_index()
    mp = merged_security_pool([p])
    g = DirectionGroup(product="自检产品", direction="买入", amount=50000, method="等金额",
                       stocks=[StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [p], mp)
    assert res.orders and res.orders[0].buy_qty == 5000, res.orders
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "o.xlsx"); write_orders(res.orders, out)
        assert os.path.exists(out)
    # 打包成「窗口程序」(console=False) 时 sys.stdout 可能为 None，print 会抛错——加保护，
    # 避免无界面 CI 上崩溃触发不可见错误对话框把冒烟测试卡死。
    try:
        if sys.stdout:
            print("SELFTEST OK：依赖完整，核心流程通过。")
    except Exception:
        pass
    return 0


def main():
    if "--selftest" in sys.argv:
        try:
            code = _selftest()
        except BaseException as exc:   # 任何异常都干净退出，绝不把未捕获异常抛到窗口程序外
            try:
                if sys.stderr:
                    print(f"SELFTEST FAIL: {exc}", file=sys.stderr)
            except Exception:
                pass
            code = 1
        sys.exit(code)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    _install_chinese(app)              # 统一标准按钮为简体中文（OK→确定 / Cancel→取消 / Yes→是 / No→否）
    app.setStyleSheet(DARK_QSS)
    f = app.font(); f.setPointSize(max(f.pointSize(), 10)); app.setFont(f)
    win = MainWindow(); win.show()
    sys.exit(app.exec())


# 进程级保留翻译器引用，防止被 GC 回收导致翻译失效
_ZH_TRANSLATORS: list = []


def _install_chinese(app):
    """把 Qt 标准控件文案统一成简体中文。

    默认语言环境设为中国，并加载 Qt 自带的 qtbase_zh_CN 翻译（覆盖 OK/Cancel/Yes/No 等
    标准按钮与对话框文案）。打包时翻译文件随 PySide6 一起带上（见 .spec 的 translations）。
    """
    QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
    try:
        base = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    except Exception:  # noqa: BLE001 兼容旧枚举写法
        base = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    cands = [base]
    mei = getattr(sys, "_MEIPASS", None)        # 打包后翻译文件可能在不同子目录，逐一兜底
    if mei:
        cands += [os.path.join(mei, "PySide6", "Qt", "translations"),
                  os.path.join(mei, "PySide6", "translations"),
                  os.path.join(mei, "translations")]
    for name in ("qtbase_zh_CN", "qt_zh_CN"):
        for cand in cands:
            tr = QTranslator(app)
            if tr.load(name, cand):
                app.installTranslator(tr)
                _ZH_TRANSLATORS.append(tr)
                break


if __name__ == "__main__":
    main()
