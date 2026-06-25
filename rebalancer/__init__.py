"""调仓工具核心包：读取产品持仓、构建证券池、按交易组生成下单指令、写下单 Excel。"""
from __future__ import annotations

from .engine import (
    DirectionGroup,
    RebalanceResult,
    StockEntry,
    build_orders,
    compute_group_shares,
    default_cny_price,
    normalize_code,
    normalize_direction,
    normalize_method,
)
from .excel_io import write_orders, write_orders_per_product
from .models import Holding, Product, StockPoolItem, TradeOrder
from .pools import merged_security_pool
from .reader import read_product_file, read_product_folder

__all__ = [
    "DirectionGroup", "StockEntry", "RebalanceResult",
    "build_orders", "compute_group_shares", "default_cny_price",
    "normalize_code", "normalize_direction", "normalize_method",
    "write_orders", "write_orders_per_product",
    "Holding", "Product", "StockPoolItem", "TradeOrder",
    "merged_security_pool",
    "read_product_file", "read_product_folder",
]

__version__ = "1.1.9"
