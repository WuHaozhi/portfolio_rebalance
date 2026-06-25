"""读取层健壮性回归测试（沿用上一轮审查的修复）。"""
import openpyxl
import pytest

from rebalancer.reader import parse_product_name_date, read_product_file
from rebalancer import config


def test_parse_name_date():
    assert parse_product_name_date("稳进9号-实时监控20260610.xlsx") == ("稳进9号", "20260610")
    assert parse_product_name_date("稳进9号20260610.xlsx") == ("稳进9号", "20260610")
    assert parse_product_name_date("组合12345678.xlsx") == ("组合12345678", "")  # 非法日期不截断
    assert parse_product_name_date("中证500增强.xlsx") == ("中证500增强", "")
    assert parse_product_name_date("产品20261301.xlsx")[1] == ""  # 13月非法


def test_ragged_rows_no_crash(tmp_path):
    path = str(tmp_path / "ragged.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = config.HOLDING_SHEET
    ws.append(["分类", "资产代码", "资产名称", "公允价格", "持仓数量", "持仓市值", "持仓权重"])
    ws.append(["   全部(1)", None, None, None, None, 100000, 1])
    ws.append(["   股票(1)", None, None, None, None, 100000, 1])
    ws.append([None, "600000.SH", "甲股", 10, 1000, 10000])  # 末列缺失
    wb.save(path)
    p = read_product_file(path)
    assert not any("读取失败" in w for w in p.warnings)
    assert p.get("600000.SH") is not None
    assert p.total_assets == 100000


def test_header_tolerant(tmp_path):
    path = str(tmp_path / "hdr.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = config.HOLDING_SHEET
    ws.append(["分类", "证券代码", "证券名称", "最新价", "持仓数量", "持仓市值(CNY)", "权重"])
    ws.append(["   股票(1)", None, None, None, None, 50000, 1])
    ws.append([None, "600000.SH", "甲股", 10, 5000, 50000, 1])
    wb.save(path)
    p = read_product_file(path)
    h = p.get("600000.SH")
    assert h is not None and h.market_value == 50000 and h.price == 10
