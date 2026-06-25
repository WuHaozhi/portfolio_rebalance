import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rebalancer.models import Holding, Product, StockPoolItem  # noqa: E402


@pytest.fixture
def sample_file():
    """真实样例产品文件路径（若不存在则跳过相关测试）。"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "product", "稳进9号-实时监控20260610.xlsx")
    if not os.path.exists(path):
        pytest.skip("样例文件不存在")
    return path


@pytest.fixture
def synth_product():
    """构造一个确定性的合成产品，便于精确断言。

    总资产 1,000,000；股票：
      A股 600000.SH 价10 量5000 市值50000（单价10）
      A股 600001.SH 价20 量1000 市值20000（单价20）
      港股 00700.HK 价100(港元) 量1000 市值92000（人民币单价92，隐含汇率0.92）
    """
    p = Product(name="测试1号", date="20260610", total_assets=1_000_000.0)
    p.holdings = [
        Holding("600000.SH", "甲股", "股票(3)", 10.0, 5000, 50000.0, 0.05),
        Holding("600001.SH", "乙股", "股票(3)", 20.0, 1000, 20000.0, 0.02),
        Holding("00700.HK", "丙股", "股票(3)", 100.0, 1000, 92000.0, 0.092),
        Holding("CNY", "人民币", "现金", 1.0, 838000, 838000.0, 0.838),
    ]
    p.stock_total_mv = 162000.0
    p.rebuild_index()
    return p


@pytest.fixture
def synth_merged(synth_product):
    from rebalancer.pools import merged_security_pool
    return merged_security_pool([synth_product])
