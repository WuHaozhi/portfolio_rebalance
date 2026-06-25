"""证券池构建：每个产品各自的证券池 + 所有产品合并的证券池。

证券池含股票/债券/基金等（排除现金、期货），见 Product.securities()。
"""
from __future__ import annotations

from .models import Product, StockPoolItem


def merged_security_pool(products: list[Product]) -> list[StockPoolItem]:
    """所有产品持仓合并后的证券池（去重，仅名称/代码/价格）。

    同一标的若在多个产品出现，价格取首个非空公允价格，
    人民币单价取首个可得值，并记录持有的产品列表。
    """
    by_code: dict[str, StockPoolItem] = {}
    for p in products:
        for h in p.securities():
            item = by_code.get(h.code)
            if item is None:
                by_code[h.code] = StockPoolItem(
                    code=h.code,
                    name=h.name,
                    price=h.price,
                    cny_unit_price=h.cny_unit_price,
                    products=[p.name],
                )
            else:
                if p.name not in item.products:
                    item.products.append(p.name)
                if (not item.price) and h.price:
                    item.price = h.price
                if item.cny_unit_price is None and h.cny_unit_price is not None:
                    item.cny_unit_price = h.cny_unit_price
                if not item.name and h.name:
                    item.name = h.name
    return [by_code[c] for c in sorted(by_code)]
