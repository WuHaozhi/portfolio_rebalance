"""回归测试：2026-06-26 独立复审报告的修复。

覆盖：取整归零不再静默丢单（HIGH）、金额守恒汇总（MED1）、
normalize_code 深市 B 股/回购（LOW2）、空产品名引擎拦截（LOW3）、reader 双重单位二选一（LOW1）。
"""
from rebalancer import DirectionGroup, StockEntry, build_orders, merged_security_pool
from rebalancer.models import Holding, Product
from rebalancer.engine import normalize_code
from rebalancer.reader import _to_float


def _product(name, holdings):
    p = Product(name=name)
    p.holdings = holdings
    p.rebuild_index()
    return p


# ---------------- HIGH：系统算出的股数取整归零，必须告警（不再静默丢单） ----------------
def test_buy_round_to_zero_now_warns():
    p = _product("A", [Holding("600000.SH", "浦发", "股票", 10.0, 100000, 1e6, 0.1),
                       Holding("600519.SH", "茅台", "股票", 1700.0, 100, 170000.0, 0.02)])
    g = DirectionGroup("A", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600519.SH", price=1700.0)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert not any(o.code == "600519.SH" for o in res.orders)          # 茅台仍不足一手被丢
    assert any("600519.SH" in w and "未下单" in w for w in res.warnings)  # 但不再静默


def test_sell_proportional_round_to_zero_now_warns():
    p = _product("B", [Holding("600000.SH", "浦发", "股票", 10.0, 100000, 1e6, 0.5),
                       Holding("600036.SH", "招行", "股票", 40.0, 100, 4000.0, 0.002)])
    g = DirectionGroup("B", "卖出", 20000, "当前持仓比例",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600036.SH", price=40.0)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert not any(o.code == "600036.SH" for o in res.orders)
    assert any("600036.SH" in w and "未下单" in w for w in res.warnings)


def test_sell_oddlot_round_to_zero_now_warns():
    p = _product("C", [Holding("600000.SH", "浦发", "股票", 10.0, 150, 1500.0, 1.0)])
    g = DirectionGroup("C", "卖出", 500, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert res.orders == []
    assert any("600000.SH" in w and "未下单" in w for w in res.warnings)


# ---------------- MED1：金额守恒汇总 ----------------
def test_amount_conservation_summary():
    p = _product("A", [Holding("600000.SH", "浦发", "股票", 10.0, 100000, 1e6, 0.1),
                       Holding("600519.SH", "茅台", "股票", 1700.0, 100, 170000.0, 0.02)])
    g = DirectionGroup("A", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600519.SH", price=1700.0)])
    res = build_orders([g], [p], merged_security_pool([p]))
    assert any("不会自动重分配" in w for w in res.warnings)


# ---------------- LOW2：normalize_code 深市 B 股(200)/回购(131) → .SZ ----------------
def test_normalize_code_szb_and_repo():
    assert normalize_code("200002") == ("200002.SZ", True)   # 深市 B 股（原误判 .SH）
    assert normalize_code("131810") == ("131810.SZ", True)   # 深市回购（原误判 .SH）
    assert normalize_code("600000") == ("600000.SH", True)   # 沪市股票不变
    assert normalize_code("000001") == ("000001.SZ", True)   # 深市股票不变


# ---------------- LOW3：空产品名组被引擎拦截，不产孤儿订单 ----------------
def test_empty_product_name_skipped():
    g = DirectionGroup("", "买入", 10000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [], merged_security_pool([]))
    assert res.orders == []
    assert any("未指定产品" in w for w in res.warnings)


# ---------------- LOW1：reader 双重单位二选一（表头有单位时禁用值级万/亿） ----------------
def test_to_float_unit_suffix_toggle():
    assert _to_float("3.5万") == 35000.0                  # 表头无单位：值级「万」生效
    assert _to_float("3.5万", unit_suffix=False) == 3.5   # 表头已带「万元」：值级「万」剥离但不再放大
    assert _to_float("2亿", unit_suffix=False) == 2.0
    assert _to_float("3.5") == 3.5
