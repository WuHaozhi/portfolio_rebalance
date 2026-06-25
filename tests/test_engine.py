"""调仓引擎（直接交易指令模型）测试。"""
import os

import pytest

from rebalancer import (DirectionGroup, StockEntry, build_orders,
                        compute_group_shares, default_cny_price,
                        merged_security_pool, normalize_direction, normalize_method)
from rebalancer.engine import (build_fx_map, clamp_sell_to_holding, lot_size,
                               round_buy, round_sell)
from rebalancer import config


# --------------------------- 归一化 ---------------------------
def test_normalize_direction():
    assert normalize_direction("买入") == config.DIR_BUY
    assert normalize_direction("买") == config.DIR_BUY
    assert normalize_direction("卖出") == config.DIR_SELL
    assert normalize_direction("") is None
    assert normalize_direction("双向") is None  # 组方向只能买/卖


def test_normalize_method_required():
    assert normalize_method("等金额") == config.METHOD_EQUAL
    assert normalize_method("当前持仓比例") == config.METHOD_HOLDING
    assert normalize_method("市值") == config.METHOD_HOLDING
    assert normalize_method("") is None     # 必填，留空返回 None
    assert normalize_method(None) is None


# --------------------------- 手数 ---------------------------
def test_lot_and_round():
    assert lot_size("600000.SH") == 100
    assert lot_size("00700.HK") == config.HK_DEFAULT_LOT
    assert round_buy(1234, "600000.SH") == 1200    # 主板 100 整数倍
    # 科创板：≥200，之后 1 股递增
    assert round_buy(150, "688981.SH") == 0        # 不足 200 不买
    assert round_buy(250, "688981.SH") == 250      # 1 股递增，不再被取整成 200
    assert round_buy(333, "688981.SH") == 333
    # 创业板：≥100，1 股递增
    assert round_buy(50, "300750.SZ") == 0
    assert round_buy(333, "300750.SZ") == 333
    # 北交所：≥100，1 股递增
    assert round_buy(333, "830799.BJ") == 333
    # 主板不足 100 不买；可转债 10 张
    assert round_buy(50, "600000.SH") == 0
    assert round_buy(135, "113050.SH") == 130


def test_lot_rule():
    from rebalancer.engine import lot_rule
    assert lot_rule("600000.SH") == (100, 100)
    assert lot_rule("688981.SH") == (1, 200)
    assert lot_rule("300750.SZ") == (1, 100)
    assert lot_rule("830799.BJ") == (1, 100)
    assert lot_rule("113050.SH") == (10, 10)
    assert lot_rule("00700.HK") == (config.HK_DEFAULT_LOT, config.HK_DEFAULT_LOT)


def test_round_sell_no_oversell():
    assert round_sell(8000, 8000, "1177.HK") == 8000   # 清仓
    assert round_sell(901, 1000, "600000.SH") == 900   # 不超卖
    assert round_sell(75, 150, "600000.SH") == 0
    assert round_sell(99999, 5000, "600000.SH") == 5000  # 不超持仓


def test_clamp_sell_to_holding():
    assert clamp_sell_to_holding(60000, 50000, "600000.SH") == 50000  # 手填超持仓 -> 上限
    assert clamp_sell_to_holding(1234, 5000, "600000.SH") == 1200
    assert clamp_sell_to_holding(5000, 5000, "600000.SH") == 5000


def test_build_fx_map(synth_product):
    fx = build_fx_map([synth_product])
    assert fx["HK"] == pytest.approx(0.92)
    assert fx["SH"] == pytest.approx(1.0)


def test_default_cny_price(synth_product, synth_merged):
    assert default_cny_price("00700.HK", [synth_product], synth_merged) == pytest.approx(92.0)
    assert default_cny_price("600000.SH", [synth_product], synth_merged) == pytest.approx(10.0)
    assert default_cny_price("999999.SH", [synth_product], synth_merged) is None


# --------------------------- compute_group_shares ---------------------------
def test_equal_amount(synth_product):
    g = DirectionGroup("测试1号", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600001.SH", price=20.0)])
    compute_group_shares(g, synth_product)
    # 100000/2=50000 each -> 600000:5000股, 600001:2500股
    assert g.stocks[0].shares == 5000
    assert g.stocks[1].shares == 2500


def test_holding_ratio(synth_product):
    # 组内 600000持仓5万, 600001持仓2万 -> 权重 5:2，把 90000 分配：
    #   600000 = 90000*50000/70000 = 64285.7 /10 = 6428.6 -> 取整 6400
    #   600001 = 90000*20000/70000 = 25714.3 /20 = 1285.7 -> 取整 1200
    g = DirectionGroup("测试1号", "买入", 90000, "当前持仓比例",
                       [StockEntry("600000.SH", price=10.0), StockEntry("600001.SH", price=20.0)])
    compute_group_shares(g, synth_product)
    assert g.stocks[0].shares == 6400
    assert g.stocks[1].shares == 1200


def test_method_required_skips(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", 100000, "", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0
    assert any("方式必填" in w for w in res.warnings)


def test_amount_required_skips(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", None, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0
    assert any("金额" in w for w in res.warnings)


def test_holding_ratio_no_holding_skips(synth_product, synth_merged):
    # 当前持仓比例但组内都没持仓 -> 跳过该组并告警
    g = DirectionGroup("测试1号", "买入", 100000, "当前持仓比例",
                       [StockEntry("600999.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0
    assert any("无法分配" in w for w in res.warnings)


# --------------------------- build_orders ---------------------------
def test_build_buy(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    o = res.orders[0]
    assert o.direction == config.DIR_BUY and o.buy_qty == 10000 and o.sell_qty == 0


def test_adjust_override(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "买入", 100000, "等金额",
                       [StockEntry("600000.SH", price=10.0, adjust=6000)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].buy_qty == 6000


def test_sell_capped_at_holding(synth_product, synth_merged):
    # 手填调整卖 99999 但只持有 5000 -> 封顶 5000
    g = DirectionGroup("测试1号", "卖出", 999999, "等金额",
                       [StockEntry("600000.SH", price=10.0, adjust=99999)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].sell_qty == 5000
    assert any("超过持仓" in w for w in res.warnings)


def test_sell_unheld_warns(synth_product, synth_merged):
    g = DirectionGroup("测试1号", "卖出", 50000, "等金额",
                       [StockEntry("600999.SH", price=10.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert len(res.orders) == 0
    assert any("未持有" in w for w in res.warnings)


def test_hk_uses_cny_price(synth_product, synth_merged):
    # 港股人民币单价 92，买 184000 -> 2000股
    g = DirectionGroup("测试1号", "买入", 184000, "等金额",
                       [StockEntry("00700.HK", price=92.0)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].buy_qty == 2000


def test_sells_first_sorted(synth_product, synth_merged):
    gb = DirectionGroup("测试1号", "买入", 100000, "等金额", [StockEntry("600001.SH", price=20.0)])
    gs = DirectionGroup("测试1号", "卖出", 30000, "等金额", [StockEntry("600000.SH", price=10.0)])
    res = build_orders([gb, gs], [synth_product], synth_merged)
    assert res.orders[0].direction == config.DIR_SELL   # 卖出在前
    assert res.orders[1].direction == config.DIR_BUY


def test_new_stock_buy(synth_product, synth_merged):
    # 新增标的（不在任何产品），手填价格，买入
    g = DirectionGroup("测试1号", "买入", 50000, "等金额",
                       [StockEntry("000333.SZ", name="美的", price=50.0, source=config.SOURCE_NEW)])
    res = build_orders([g], [synth_product], synth_merged)
    assert res.orders[0].code == "000333.SZ" and res.orders[0].buy_qty == 1000


# --------------------------- 真实文件 ---------------------------
def test_real_file(sample_file):
    """端到端：用 product/ 下持仓最丰富的真实文件跑一遍取价+下单（不依赖具体产品名/代码）。"""
    from rebalancer import read_product_folder
    ps = read_product_folder(os.path.dirname(sample_file))
    mp = merged_security_pool(ps)
    rich = max(ps, key=lambda p: len(p.securities()))      # 持仓最丰富的产品
    picks = rich.securities()[:2]
    assert picks                                           # 能选出可调仓证券
    g = DirectionGroup(rich.name, "买入", 1_000_000, "等金额",
                       [StockEntry(s.code, price=default_cny_price(s.code, ps, mp, prefer_product=rich))
                        for s in picks])
    res = build_orders([g], ps, mp)
    assert len(res.orders) >= 1                            # 能产出下单指令
    assert all(o.buy_qty % 100 == 0 for o in res.orders)  # 取整到手
