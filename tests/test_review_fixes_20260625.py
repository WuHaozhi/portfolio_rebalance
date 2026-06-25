"""第三/四轮审查确认项的回归测试（2026-06-25 全修）。

覆盖：reader 解析加固（万元单位 / 币种符号 / % / 表头优先级 / 无分类列汇总行 /
代码归一化 / 同码合并 / 表头探测）、engine 数量与取价（负市值汇率 / 取价产品 /
未持有告警 / 0 价单拦截 / 重复买入告警 / 自成交记录）、models 证券池兜底剔除。
"""
import openpyxl
import pytest

from rebalancer import (DirectionGroup, StockEntry, build_orders,
                        default_cny_price, merged_security_pool)
from rebalancer import config
from rebalancer.engine import build_fx_map
from rebalancer.models import Holding, Product
from rebalancer.reader import _to_float, read_product_file


# ----------------------------- reader._to_float -----------------------------
def test_to_float_currency_and_unit():
    """P0-5：剥离前导币种符与尾部单位字。"""
    assert _to_float("¥3.50") == 3.5
    assert _to_float("3.5元") == 3.5
    assert _to_float("$10") == 10.0
    assert _to_float("￥1,234.5") == 1234.5
    assert _to_float("100股") == 100.0


def test_to_float_percent_only_for_weight():
    """P0-6：% 仅在 percent=True（权重列）按百分比；其余列遇 % 当脏数据 → None。"""
    assert _to_float("12%") is None          # 价格/市值/数量列：不得静默缩成 0.12
    assert _to_float("12％") is None          # 全角
    assert _to_float("12%", percent=True) == pytest.approx(0.12)
    assert _to_float("5%", percent=True) == pytest.approx(0.05)


def test_to_float_value_level_magnitude():
    """复核#1：值级 万/亿 量级单位也应还原（不是只处理表头单位）。"""
    assert _to_float("3.5万") == pytest.approx(35000.0)
    assert _to_float("2亿") == pytest.approx(2e8)
    assert _to_float("1.2万元") == pytest.approx(12000.0)   # 先剥「元」再识别「万」
    assert _to_float("100") == 100.0                        # 纯数字不受影响


def _mk(path, header, data, sheet=None):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = sheet or config.HOLDING_SHEET
    ws.append(header)
    for row in data:
        ws.append(row)
    wb.save(str(path))


# ------------------------------- reader 解析 --------------------------------
def test_wan_yuan_unit_scaling(tmp_path):
    """P0-3：「持仓市值（万元）」按 ×1e4 还原，杜绝万倍超买。"""
    path = tmp_path / "万元20260610.xlsx"
    _mk(path,
        ["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值（万元）", "持仓权重"],
        [["   股票(1)", None, None, "-", None, 50, 1],
         [None, "600000.SH", "浦发", 50.0, 10000, 50, 1]])
    p = read_product_file(str(path))
    h = p.get("600000.SH")
    assert h.market_value == pytest.approx(500000.0)      # 50 万元 -> 500000 元
    assert h.cny_unit_price == pytest.approx(50.0)         # 反推单价正常，而非 0.005


def test_header_alias_priority(tmp_path):
    """P0-7：短别名「持仓」不得抢在「持仓数量」前绑错 quantity。"""
    path = tmp_path / "重复列20260610.xlsx"
    _mk(path,
        ["分类", "资产代码", "资产名称", "公允价格", "持仓", "持仓数量", "持仓市值", "持仓权重"],
        [[None, "600000.SH", "浦发", 10.0, 999, 1000, 10000.0, 1]])
    p = read_product_file(str(path))
    assert p.get("600000.SH").quantity == 1000            # 绑到「持仓数量」而非「持仓」(999)


def test_no_category_column_skips_summary_rows(tmp_path):
    """P0-1：无「分类」列时，代码列里的「全部/股票」大类标签应作汇总行，不进证券池。"""
    path = tmp_path / "无分类汇总20260610.xlsx"
    _mk(path,
        ["资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"],
        [["全部", None, "-", None, 170000, 1],
         ["股票", None, "-", None, 100000, 1],
         ["600000.SH", "浦发", 10.0, 1000, 10000.0, 0.1]])
    p = read_product_file(str(path))
    codes = {h.code for h in p.securities()}
    assert "全部" not in codes and "股票" not in codes
    assert "600000.SH" in codes
    assert p.total_assets == pytest.approx(170000.0)       # 取「全部」行，而非全表求和


def test_no_category_column_keeps_dirty_named_holding(tmp_path):
    """复核#2（HIGH 回归修复）：无分类列时，代码列含关键字子串的真实持仓不得被误当汇总行丢弃。"""
    path = tmp_path / "脏代码列20260610.xlsx"
    _mk(path,
        ["资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"],
        [["南方中证500ETF联接基金", "南方500ETF联接", 1.5, 10000, 15000.0, 0.5],  # 含「基金」子串
         ["国债逆回购991", "逆回购", 100.0, 1000, 100000.0, 0.4],                 # 含「回购」子串
         ["600000.SH", "浦发", 10.0, 1000, 10000.0, 0.1]])
    p = read_product_file(str(path))
    codes = {h.code for h in p.holdings}
    assert "南方中证500ETF联接基金" in codes and "国债逆回购991" in codes        # 不被误删
    assert "600000.SH" in codes
    assert len(p.holdings) == 3                                                 # 一行都不少


def test_numeric_code_normalized_on_read(tmp_path):
    """新-A：产品文件里的数字代码读入时补全市场后缀。"""
    path = tmp_path / "裸码20260610.xlsx"
    _mk(path,
        ["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"],
        [[None, 600000, "浦发", 10.0, 1000, 10000.0, 0.5],
         [None, 1, "平安", 12.0, 1000, 12000.0, 0.5]])
    p = read_product_file(str(path))
    codes = {h.code for h in p.holdings}
    assert "600000.SH" in codes and "000001.SZ" in codes   # 600000→.SH、1→000001.SZ
    assert any("缺市场后缀" in w for w in p.warnings)


def test_duplicate_code_rows_merged(tmp_path):
    """P0-4：同一代码多行 → 合并数量/市值，避免漏卖。"""
    path = tmp_path / "同码多行20260610.xlsx"
    _mk(path,
        ["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"],
        [[None, "600276.SH", "恒瑞", 30.0, 1000, 30000.0, 0.5],
         [None, "600276.SH", "恒瑞", 30.0, 3000, 90000.0, 0.5]])
    p = read_product_file(str(path))
    h = p.get("600276.SH")
    assert h.quantity == pytest.approx(4000.0)             # 1000+3000，而非只剩 3000
    assert h.market_value == pytest.approx(120000.0)
    assert any("多行持仓" in w for w in p.warnings)


def test_header_not_in_first_row(tmp_path):
    """新-E：首行是 banner、真表头在第 2 行时仍能解析，并提示。"""
    path = tmp_path / "带banner20260610.xlsx"
    _mk(path,
        ["示例产品 持仓监控 20260101", None, None, None, None, None, None],   # banner 作为首行
        [["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"],
         [None, "600000.SH", "浦发", 10.0, 1000, 10000.0, 1]])
    p = read_product_file(str(path))
    assert p.get("600000.SH") is not None and p.get("600000.SH").quantity == 1000
    assert any("表头不在首行" in w for w in p.warnings)


# ------------------------------- models 证券池 ------------------------------
def test_securities_excludes_cash_futures_without_category():
    """新-C / sweep-4：category 为空时按名称/市场兜底剔除现金、期货。"""
    p = Product(name="P")
    p.holdings = [
        Holding("600000.SH", "浦发", "", 10.0, 1000, 10000.0, 0.0),
        Holding("CNY", "现金", "", 1.0, 100000, 100000.0, 0.0),
        Holding("IM2606.CFE", "中证1000期货", "", 0.0, 1, -50000.0, 0.0),
    ]
    p.rebuild_index()
    codes = {h.code for h in p.securities()}
    assert codes == {"600000.SH"}                          # 现金、期货被剔除


def test_securities_excludes_bare_futures_code():
    """复核#3：无分类、无后缀的裸期货合约码（IF2406）也应被兜底剔除。"""
    p = Product(name="P")
    p.holdings = [Holding("IF2406", "股指期货IF2406", "", 0.0, 1, 50000.0, 0.0),
                  Holding("600000.SH", "浦发", "", 10.0, 1000, 10000.0, 0.0)]
    p.rebuild_index()
    assert {h.code for h in p.securities()} == {"600000.SH"}


def test_securities_excludes_repo_category():
    """sweep-4：回购大类被排除。"""
    p = Product(name="P")
    p.holdings = [Holding("131810.SZ", "GC001", "回购", 1.0, 1000, 1000.0, 0.0),
                  Holding("600000.SH", "浦发", "股票", 10.0, 1000, 10000.0, 0.0)]
    p.rebuild_index()
    assert {h.code for h in p.securities()} == {"600000.SH"}


# ------------------------------- engine 取价/汇率 ---------------------------
def test_fx_map_ignores_negative_mv():
    """新-D：负市值不参与汇率反推，单只异常不拉偏整市场。"""
    p = Product(name="P")
    p.holdings = [Holding("0700.HK", "腾讯", "股票", 100.0, 1000, 92000.0, 0.5),
                  Holding("9988.HK", "阿里", "股票", 100.0, 1000, -50000.0, 0.5)]
    p.rebuild_index()
    assert build_fx_map([p])["HK"] == pytest.approx(0.92)  # 不被 -0.5 拉到 ~0.21


def test_default_price_prefers_request_product():
    """P1-11：多产品共持时优先用所属产品自己的反推价。"""
    a = Product(name="A"); a.holdings = [Holding("00700.HK", "腾讯", "股票", 100.0, 1000, 100000.0, 1.0)]; a.rebuild_index()
    b = Product(name="B"); b.holdings = [Holding("00700.HK", "腾讯", "股票", 100.0, 1000, 360000.0, 1.0)]; b.rebuild_index()
    assert default_cny_price("00700.HK", [a, b], prefer_product=a) == pytest.approx(100.0)
    assert default_cny_price("00700.HK", [a, b], prefer_product=b) == pytest.approx(360.0)


# ------------------------------- engine 下单逻辑 ----------------------------
def _prod_600000():
    p = Product(name="P")
    p.holdings = [Holding("600000.SH", "浦发", "股票", 10.0, 5000, 50000.0, 1.0)]
    p.rebuild_index()
    return p


def test_unheld_in_holding_ratio_warns():
    """P1-9：买入用「当前持仓比例」选了未持有票 → 告警（而非静默丢）。"""
    p = _prod_600000()
    g = DirectionGroup("P", "买入", 100000, "当前持仓比例",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600519.SH", price=1700.0)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert any("未持有" in w for w in res.warnings)


def test_no_price_with_adjust_not_ordered():
    """P1-10：无有效价但手填 adjust → 不下 0 价单。"""
    p = _prod_600000()
    g = DirectionGroup("P", "买入", 10000, "等金额",
                       [StockEntry("600000.SH", price=None, adjust=100)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert res.orders == []
    assert any("0 价单" in w or "无有效价格" in w for w in res.warnings)


def test_duplicate_buy_groups_warn():
    """P0-2 残留：同 (产品,代码) 买入来自多个组 → 告警提示核对。"""
    p = _prod_600000()
    g1 = DirectionGroup("P", "买入", 100000, "等金额", [StockEntry("600000.SH", price=10.0)])
    g2 = DirectionGroup("P", "买入", 100000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g1, g2], [p], merged_security_pool([p]))
    assert any("多个交易组" in w or "误重复" in w for w in res.warnings)


def test_self_trade_recorded():
    """P1-14：同标的买卖记入 result.self_trades，供导出前强制确认。"""
    p = _prod_600000()
    gb = DirectionGroup("P", "买入", 100000, "等金额", [StockEntry("600000.SH", price=10.0)])
    gs = DirectionGroup("P", "卖出", 20000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([gb, gs], [p], merged_security_pool([p]))
    assert ("P", "600000.SH") in res.self_trades


def test_cross_group_sell_cap_not_oversell():
    """P0/卖出：同票两个卖出组合计不超过持仓。"""
    p = _prod_600000()                                     # 持仓 5000
    g1 = DirectionGroup("P", "卖出", 40000, "等金额", [StockEntry("600000.SH", price=10.0)])
    g2 = DirectionGroup("P", "卖出", 40000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g1, g2], [p], merged_security_pool([p]))
    total_sell = sum(o.sell_qty for o in res.orders if o.code == "600000.SH")
    assert total_sell <= 5000
