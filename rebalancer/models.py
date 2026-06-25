"""数据模型。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# 裸期货/期权合约代码（无交易所后缀），如 IF2406 / IC2409 / T2412 / IO2406-C-3900
_BARE_FUTURES_RE = re.compile(r"^[A-Za-z]{1,2}\d{3,4}([-.].*)?$")


@dataclass
class Holding:
    """单个产品中的一笔持仓。"""

    code: str                 # 资产代码，如 600276.SH / 1177.HK
    name: str                 # 资产名称
    category: str             # 大类：股票/债券/基金/期货/现金
    price: float              # 公允价格（外币标的为外币计价）
    quantity: float           # 持仓数量
    market_value: float       # 持仓市值（人民币）
    weight: float = 0.0       # 持仓权重

    @property
    def market(self) -> str:
        """交易市场后缀，如 SH/SZ/HK/CFE，取代码点号后部分（大写）。"""
        if "." in self.code:
            return self.code.rsplit(".", 1)[1].upper()
        return ""

    @property
    def cny_unit_price(self) -> Optional[float]:
        """每股人民币单价。

        对持仓中的标的，用 持仓市值/数量 反推，自动包含汇率；
        数量为 0 时返回 None（由引擎按公允价格+汇率兜底）。
        """
        if self.quantity:
            return self.market_value / self.quantity
        return None


@dataclass
class Product:
    """一个产品（对应 product 文件夹下一个 Excel 文件）。"""

    name: str                                  # 产品名，如 稳进9号
    date: str = ""                             # 数据日期，如 20260610
    source_file: str = ""                      # 源文件路径
    total_assets: float = 0.0                  # 产品总资产（全部汇总行的持仓市值）
    stock_total_mv: float = 0.0                # 股票大类总市值
    holdings: list[Holding] = field(default_factory=list)
    # code -> Holding，便于快速查找
    by_code: dict[str, Holding] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def stocks(self) -> list[Holding]:
        """仅股票大类持仓。"""
        from .config import STOCK_KEYWORD

        return [h for h in self.holdings if STOCK_KEYWORD in h.category]

    def securities(self) -> list[Holding]:
        """可调仓的证券池：股票/债券/基金等，排除现金/期货/回购。

        不要求 category 非空——产品表若缺「分类」列，持仓 category 为空仍应可调仓，
        靠 现金/期货/回购 关键字排除；category 为空时再按 市场后缀/名称 兜底剔除
        现金、期货、回购（否则缺分类列的产品会把现金/期货也放进可调仓池）。
        """
        from .config import POOL_EXCLUDE_CATEGORIES, FUTURES_MARKETS

        out = []
        for h in self.holdings:
            cat = h.category or ""
            if any(x in cat for x in POOL_EXCLUDE_CATEGORIES):
                continue
            if not cat:                       # 无分类信息：按市场/代码/名称兜底剔除非可下单标的
                if h.market in FUTURES_MARKETS:
                    continue
                if "." not in h.code and _BARE_FUTURES_RE.match(h.code or ""):
                    continue                  # 无后缀的裸期货/期权合约码（IF2406 等）
                if any(k in (h.name or "")
                       for k in ("现金", "理财", "存款", "逆回购", "回购", "货币基金", "期货", "期权")):
                    continue
            out.append(h)
        return out

    def get(self, code: str) -> Optional[Holding]:
        return self.by_code.get(code)

    def rebuild_index(self) -> None:
        self.by_code = {h.code: h for h in self.holdings}


@dataclass
class StockPoolItem:
    """证券池中的一项（合并池仅含名称/代码/价格）。"""

    code: str
    name: str
    price: float                      # 展示股价（取首次出现的公允价格）
    cny_unit_price: Optional[float] = None  # 每股人民币单价（用于换算）
    products: list[str] = field(default_factory=list)  # 哪些产品持有


@dataclass
class TradeOrder:
    """一条交易指令。"""

    product: str
    direction: str        # 买入 / 卖出
    code: str
    name: str
    buy_qty: float = 0.0
    sell_qty: float = 0.0
    # 以下为辅助/审计信息，不一定写进最终下单表
    current_mv: float = 0.0
    target_mv: float = 0.0
    diff_mv: float = 0.0
    unit_price: float = 0.0
    note: str = ""
