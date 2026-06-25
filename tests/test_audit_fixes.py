"""v1.1 深度审查后的修复回归测试。"""
import pytest

from rebalancer import (DirectionGroup, StockEntry, build_orders,
                        compute_group_shares, normalize_code, normalize_direction,
                        normalize_method)
from rebalancer.engine import clamp_sell_to_holding, round_sell
from rebalancer.models import Holding, Product
from rebalancer import config


@pytest.fixture
def prod_with_short():
    """含期货空头(负市值)的产品。"""
    p = Product(name="P", total_assets=1_000_000.0)
    p.holdings = [
        Holding("600276.SH", "恒瑞", "股票", 47.0, 10000, 470000.0, 0.47),
        Holding("IM2606.CFE", "期货", "期货", 8000.0, -1, -50000.0, -0.05),
    ]
    p.rebuild_index()
    return p


# ---- #1 负市值不污染持仓比例权重，正股不超买 ----
def test_negative_mv_excluded(prod_with_short):
    from rebalancer.pools import merged_security_pool
    mp = merged_security_pool([prod_with_short])
    g = DirectionGroup("P", "买入", 100000, "当前持仓比例",
                       [StockEntry("600276.SH", price=47.0),
                        StockEntry("IM2606.CFE", price=8000.0)])
    res = build_orders([g], [prod_with_short], mp)
    # 恒瑞权重应=1（期货被排除），买入金额≤组金额10万
    o = [x for x in res.orders if x.code == "600276.SH"][0]
    assert o.buy_qty * 47.0 <= 100000 + 1
    assert o.buy_qty == 2100   # 100000/47=2127 -> 取整2100
    assert any("市值为负" in w for w in res.warnings)


# ---- #2 adjust 取整到手 / 688最小200 / 死代码复活 ----
def test_buy_adjust_lot_rounded(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0, adjust=333)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].buy_qty == 300   # 333 -> 取整到手300


def test_buy_adjust_688_min(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", 100000, "等金额",
                       [StockEntry("688981.SH", price=50.0, adjust=100)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0  # 100<200 科创板最小买入 -> 0，不下单


def test_sell_adjust_lot_rounded(synth_product, synth_merged):
    # 持有600000 5000股，手填卖777 -> 取整到手700（adjust 覆盖系统算的股数）
    g = DirectionGroup("测试1号", "卖出", 50000, "等金额",
                       [StockEntry("600000.SH", price=10.0, adjust=777)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].sell_qty == 700   # 777 -> 700


def test_clamp_sell_to_holding_now_used():
    # 死代码复活验证：函数本身行为
    assert clamp_sell_to_holding(150, 1500, "600000.SH") == 100
    assert clamp_sell_to_holding(777, 1500, "600000.SH") == 700
    assert clamp_sell_to_holding(2000, 1500, "600000.SH") == 1500  # 封顶


# ---- #5 小数持仓清仓用截断不四舍五入，绝不超卖 ----
def test_fractional_holding_no_oversell():
    assert round_sell(2000, 1000.6, "510010.SH") == 1000   # 截断，不进位到1001
    assert clamp_sell_to_holding(2000, 1000.6, "510010.SH") == 1000


# ---- #4 数字代码补全市场后缀 ----
def test_normalize_code():
    assert normalize_code("600066") == ("600066.SH", True)
    assert normalize_code("000001") == ("000001.SZ", True)
    assert normalize_code("688981") == ("688981.SH", True)
    assert normalize_code(1) == ("000001.SZ", True)        # Excel数字丢前导零
    assert normalize_code("600066.SH") == ("600066.SH", False)  # 已有后缀不动
    assert normalize_code("830799") == ("830799.BJ", True)


# ---- #9 否定词不被模糊匹配 ----
def test_negation_not_matched():
    assert normalize_direction("不买入") is None
    assert normalize_method("非等金额") is None
    assert normalize_direction("买入") == config.DIR_BUY  # 正常仍可


# ============ code-review (max) 修复回归 ============

def test_merge_no_oversell_two_groups(synth_product, synth_merged):
    """CRITICAL：同一产品同一股票分两个卖出组，合并后绝不超持仓。"""
    # 600000 持仓5000股 价10。两组各卖4万元=4000股 -> 合计本会8000 > 5000
    g1 = DirectionGroup("测试1号", "卖出", 40000, "等金额", [StockEntry("600000.SH", price=10.0)])
    g2 = DirectionGroup("测试1号", "卖出", 40000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g1, g2], [synth_product], synth_merged)
    total = sum(o.sell_qty for o in res.orders if o.code == "600000.SH")
    assert total == 5000, f"超卖! total={total}"
    assert any("累计卖出不能超过持仓" in w for w in res.warnings)


def test_merge_no_oversell_same_group_dup(synth_product, synth_merged):
    """同一卖出组里同一股票出现两次，合并后不超持仓。"""
    g = DirectionGroup("测试1号", "卖出", 80000, "等金额",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    total = sum(o.sell_qty for o in res.orders if o.code == "600000.SH")
    assert total == 5000


def test_invalid_group_with_adjust_skipped(synth_product, synth_merged):
    """#6：持仓比例但组内无持仓(无效组)，即便手填adjust也不下单。"""
    g = DirectionGroup("测试1号", "买入", 100000, "当前持仓比例",
                       [StockEntry("600999.SH", price=10.0, adjust=300)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0


def test_round_buy_float_epsilon():
    """#10/#11：浮点误差落在整手边界下方不应少算一手。"""
    from rebalancer.engine import round_buy
    assert round_buy(500 - 5e-11, "600000.SH") == 500   # 含eps -> 500 而非 400


def test_to_float_rejects_nonfinite():
    """#7：inf/NaN 各种写法都返回 None。"""
    from rebalancer.reader import _to_float
    for v in ("inf", "-inf", "NaN", "NAN", "Infinity", float("inf"), float("nan")):
        assert _to_float(v) is None, v
    assert _to_float("12.5") == 12.5


def test_norm_choice_ambiguous_rejected():
    """#8：含糊子串(同时命中买/卖)拒绝匹配。"""
    assert normalize_direction("买卖") is None
    assert normalize_direction("买/卖") is None
    assert normalize_direction("买入") == config.DIR_BUY


def test_unrecognized_direction_skipped_at_engine(synth_product, synth_merged):
    """#3 引擎层安全网：方向无法识别(如'清仓')绝不被当买入，整组跳过。"""
    g = DirectionGroup("测试1号", "清仓", 100000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0
    assert any("方向无效" in w for w in res.warnings)


# ============ 证券池：含债券/基金 + 可转债手数 ============

def test_securities_excludes_cash_futures_real_file():
    """证券池：现金/期货被排除，且不多于总持仓（用 product/ 下持仓最丰富的真实文件验证）。"""
    from rebalancer import read_product_folder
    import os as _os
    folder = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "product")
    files = [f for f in (_os.listdir(folder) if _os.path.isdir(folder) else [])
             if f.lower().endswith((".xlsx", ".xlsm"))
             and not f.startswith(("~$", "交易指令", "调仓输入"))]
    if not files:
        import pytest as _pt; _pt.skip("样例产品文件不存在")
    ps = read_product_folder(folder)
    rich = max(ps, key=lambda p: len(p.holdings))     # 取持仓最丰富的产品（不依赖具体产品名）
    secs = rich.securities()
    cats = {h.category for h in secs}
    assert secs                                       # 能选出可调仓证券
    assert not any("现金" in c or "期货" in c or "回购" in c for c in cats)   # 排除现金/期货/回购
    assert len(secs) <= len(rich.holdings)            # 不多于总持仓


def test_convertible_bond_lot_is_10():
    from rebalancer.engine import lot_size, round_buy
    assert lot_size("127098.SZ") == 10     # 可转债 1手=10张
    assert lot_size("113001.SH") == 10
    assert lot_size("600000.SH") == 100    # 股票仍100
    assert round_buy(135, "127098.SZ") == 130   # 取整到10


# ============ 外部审查报告修复回归 ============

def test_securities_no_category_column(tmp_path):
    """#1 产品表缺「分类」列：持仓仍应可调仓（不被空类别排除）。"""
    import openpyxl
    from rebalancer.reader import read_product_file
    path = str(tmp_path / "无分类20260610.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = config.HOLDING_SHEET
    ws.append(["资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"])
    ws.append(["600000.SH", "浦发", 10.0, 1000, 10000.0, 0.5])
    ws.append(["000001.SZ", "平安", 12.0, 1000, 12000.0, 0.5])
    wb.save(path)
    p = read_product_file(path)
    assert len(p.securities()) == 2   # 不再因空类别被排除


def test_duplicate_product_names_disambiguated(tmp_path):
    """#2 同名产品文件：去重，不互相覆盖丢持仓。"""
    import openpyxl
    from rebalancer import read_product_folder
    def mk(fn):
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = config.HOLDING_SHEET
        ws.append(["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"])
        ws.append(["   全部(1)", None, None, "-", None, 100000, 1])
        ws.append(["   股票(1)", None, None, "-", None, 50000, 0.5])
        ws.append([None, "600000.SH", "浦发", 10, 5000, 50000, 0.5])
        wb.save(str(tmp_path / fn))
    mk("测试产品-A20260101.xlsx"); mk("测试产品-B20260101.xlsx")
    ps = read_product_folder(str(tmp_path))
    assert len({p.name for p in ps}) == 2   # 两个产品名互不相同（已去重）


def test_normalize_code_market_inference():
    """#13/#4 裸码市场推断：沪市可转债→.SH，深市→.SZ。"""
    from rebalancer.engine import normalize_code, lot_rule
    assert normalize_code("113050") == ("113050.SH", True)   # 沪市可转债
    assert lot_rule("113050.SH") == (10, 10)                 # 手数 10 张
    assert normalize_code("127098") == ("127098.SZ", True)   # 深市可转债
    assert normalize_code("600000") == ("600000.SH", True)
    assert normalize_code("000001") == ("000001.SZ", True)
    assert normalize_code("300750") == ("300750.SZ", True)


def test_holding_ratio_warns_zero_mv_held(synth_product, synth_merged):
    """#5 当前持仓比例下，持有但市值为0的标的应告警（会被静默跳过）。"""
    from rebalancer.models import Holding
    synth_product.holdings.append(Holding("600002.SH", "丙", "股票", 0.0, 1000, 0.0, 0.0))
    synth_product.rebuild_index()
    g = DirectionGroup("测试1号", "卖出", 50000, "当前持仓比例",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600002.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert any("市值为 0" in w for w in res.warnings)


def test_self_trade_warning(synth_product, synth_merged):
    """#12 同票既买又卖：自成交告警。"""
    gb = DirectionGroup("测试1号", "买入", 100000, "等金额", [StockEntry("600000.SH", price=10.0)])
    gs = DirectionGroup("测试1号", "卖出", 20000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([gb, gs], [synth_product], synth_merged)
    assert any("自成交" in w or "对倒" in w for w in res.warnings)


def test_safe_filename_unified():
    """#19 文件名净化统一，覆盖 Windows 全部非法字符。"""
    from rebalancer.excel_io import safe_filename
    assert safe_filename('a/b:c*d?e"f<g>h|i[j]') == "a_b_c_d_e_f_g_h_i_j_"
