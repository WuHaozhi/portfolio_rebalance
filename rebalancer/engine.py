"""调仓下单引擎（直接交易指令模型）。

模型（已确认）：
- 输入是若干「交易组」：每组 = (产品, 方向[买入/卖出], 金额[元], 方式) + 一组股票。
- 方式必填：等金额=组内每只均分；当前持仓比例=按各股当前持仓市值占比。留空视为非法、跳过该组。
- 每只：分得金额 ÷ 人民币单价 = 股数，按手取整（A股/ETF 100，港股默认100，科创板688买入≥200），
  卖出不超过当前持仓。
- 经理可手填「调整」覆盖系统算出的股数；最终下单数量 = 调整(若填) 否则 股数。
- 价格默认取自 product 文件（昨日收盘/公允价格，统一为人民币单价）；新增标的由经理手填价格。
- 输出为券商下单指令（每产品一个 sheet，卖出在前标黄）。
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from . import config
from .models import Product, StockPoolItem, TradeOrder


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def _norm_choice(value, mapping: dict[str, list[str]]) -> Optional[str]:
    """把任意写法归一化到标准取值；无法识别返回 None。"""
    if value is None:
        return None
    s = str(value).strip().lower().replace(" ", "")
    if s == "":
        return None
    for canonical, aliases in mapping.items():
        if canonical.lower() == s or any(a and a.lower() == s for a in aliases):
            return canonical
    # 含否定词时不做模糊子串匹配，避免「不买入/禁止卖出」被误判
    if any(neg in s for neg in ("不", "非", "禁", "勿", "no", "not")):
        return None
    # 子串模糊匹配：仅当恰好命中一个标准值时才接受，含糊不清（如「买卖」同时命中买/卖）一律拒绝
    hits = [c for c, aliases in mapping.items() if any(a and a.lower() in s for a in aliases)]
    return hits[0] if len(hits) == 1 else None


def normalize_direction(value) -> Optional[str]:
    """归一化方向；只接受买入/卖出，无法识别返回 None。"""
    r = _norm_choice(value, {config.DIR_BUY: config.DIRECTIONS[config.DIR_BUY],
                             config.DIR_SELL: config.DIRECTIONS[config.DIR_SELL]})
    return r


def normalize_method(value) -> Optional[str]:
    """归一化分配方式；必填，留空/无法识别返回 None。"""
    return _norm_choice(value, config.METHODS)


def normalize_code(raw) -> tuple[str, bool]:
    """规范证券代码，补全市场后缀。返回 (代码, 是否做了推断)。

    Excel 里数字型代码会丢失前导零与后缀（如 '000001'→1、'600066'→无后缀）。
    这里按交易所规则补全，并标记『做了推断』以便上层提示人工复核。
    """
    if raw is None:
        return "", False
    s = str(raw).strip().upper()
    if not s or "." in s:
        return s, False
    if s.isdigit() and len(s) <= 6:
        d = s.zfill(6)
        p2, p3 = d[:2], d[:3]
        if d[0] == "6":                        # 6xx/688 -> 沪市股票/科创板
            return d + ".SH", True
        if p3 in ("110", "111", "113", "118", "120", "122"):
            return d + ".SH", True             # 沪市可转债
        if p2 in ("00", "30", "15", "16", "18") or p3 in ("123", "127", "128"):
            return d + ".SZ", True             # 深市股票/创业板/基金/深市可转债
        if d[0] in "48":                       # 北交所
            return d + ".BJ", True
        return d + ".SH", True
    return s, False


# ---------------------------------------------------------------------------
# 价格 / 汇率
# ---------------------------------------------------------------------------
def build_fx_map(products: list[Product]) -> dict[str, float]:
    """从各产品已持有标的反推每个市场的隐含汇率（外币->人民币）。

    跳过市值 ≤ 0 的行（期货空头/浮亏的负市值会反推出负汇率），并用中位数而非均值聚合，
    使单只异常标的不会拉偏整个市场的汇率（否则靠公允价×汇率定价的新票股数全偏）。
    """
    acc: dict[str, list[float]] = {}
    for p in products:
        for h in p.holdings:
            if h.quantity and h.price and h.market_value > 0:
                acc.setdefault(h.market, []).append(h.market_value / (h.quantity * h.price))
    return {m: statistics.median(v) for m, v in acc.items() if v}


def default_cny_price(code: str, products: list[Product],
                      merged: Optional[list[StockPoolItem]] = None,
                      prefer_product: Optional[Product] = None) -> Optional[float]:
    """某标的的默认人民币单价（用于 UI 自动填价）。

    优先级：任一产品持仓反推(持仓市值/数量) > 合并池中的人民币单价 >
            公允价格×隐含汇率。找不到返回 None（由 UI 让用户手填）。
    prefer_product：取价时优先用「请求所属产品」自身的反推价/公允价，
            避免多产品共持同一标的（如 00700.HK）时误用了别的产品的价与隐含汇率。
    """
    fx = build_fx_map(products)
    ordered = list(products)
    if prefer_product is not None:
        ordered = [prefer_product] + [p for p in ordered if p is not prefer_product]
    for p in ordered:
        if p is None:
            continue
        h = p.get(code)
        if h is not None and h.cny_unit_price is not None:
            return h.cny_unit_price
    if merged:
        for it in merged:
            if it.code == code:
                if it.cny_unit_price is not None:
                    return it.cny_unit_price
                if it.price:
                    market = code.rsplit(".", 1)[1].upper() if "." in code else ""
                    return it.price * (fx.get(market) or config.FX_FALLBACK.get(market, 1.0))
    for p in ordered:
        if p is None:
            continue
        h = p.get(code)
        if h is not None and h.price:
            market = code.rsplit(".", 1)[1].upper() if "." in code else ""
            return h.price * (fx.get(market) or config.FX_FALLBACK.get(market, 1.0))
    return None


# ---------------------------------------------------------------------------
# 交易手数
# ---------------------------------------------------------------------------
def _looks_like_bond(bare: str, market: str) -> bool:
    """按代码前缀粗判债券/可转债（沪 110/111/113/118/120/122；深 12x/100/108）。"""
    if market == "SH":
        return bare[:3] in ("110", "111", "113", "118", "120", "122", "100", "101")
    if market == "SZ":
        return bare[:3] in ("123", "127", "128", "100", "108", "112", "114", "115")
    return False


def lot_rule(code: str, product: Optional[Product] = None) -> tuple[int, int]:
    """返回 (step, min_buy)：每笔买入须 ≥ min_buy，且按 step 递增。

    科创板 1 股递增/≥200；创业板·北交所 1 股递增/≥100；可转债 10 张；
    主板/ETF/基金 100 整数倍；港股按每手股数（默认 100）。
    """
    if code in config.LOT_OVERRIDES:
        lot = config.LOT_OVERRIDES[code]
        return lot, lot
    market = code.rsplit(".", 1)[1].upper() if "." in code else ""
    bare = code.split(".")[0]
    h = product.get(code) if product else None
    if (h is not None and h.category and "债" in h.category) or _looks_like_bond(bare, market):
        return config.BOND_LOT, config.BOND_LOT
    if market == "SH" and bare.startswith("688"):              # 科创板
        return 1, config.STAR_BOARD_MIN_BUY
    if market == "SZ" and bare[:3] in ("300", "301"):          # 创业板
        return 1, config.CHINEXT_MIN_BUY
    if market == "BJ":                                          # 北交所
        return 1, config.CHINEXT_MIN_BUY
    if market == "HK":
        return config.HK_DEFAULT_LOT, config.HK_DEFAULT_LOT
    return config.DEFAULT_LOT, config.DEFAULT_LOT              # 主板/ETF/基金


def lot_size(code: str, product: Optional[Product] = None) -> int:
    """递增步长（向后兼容旧调用）。"""
    return lot_rule(code, product)[0]


def round_buy(raw_qty: float, code: str, product: Optional[Product] = None) -> int:
    """买入数量按步长向下取整；不足最小买入量则不下单（如科创板<200、创业板<100）。"""
    step, min_buy = lot_rule(code, product)
    qty = int(math.floor(raw_qty / step + 1e-9) * step)   # +eps 抵消浮点误差
    return qty if qty >= min_buy else 0


def round_sell(raw_qty: float, current_qty: float, code: str, product: Optional[Product] = None) -> int:
    """卖出数量按步长向下取整，且不超过现有持仓。

    仅当「希望卖出量 ≈ 全部持仓」时才连零股一并卖出（清仓）；否则按步长向下取整，
    允许减仓后保留合法的小仓位/零股——绝不超卖。
    """
    step = lot_rule(code, product)[0]
    desired = min(raw_qty, current_qty)
    if desired <= 0:
        return 0
    if desired >= current_qty - 1e-6:          # 接近清仓 -> 全卖（含零股）
        return int(current_qty)                # 截断（不四舍五入），绝不超过持仓
    return int(math.floor(desired / step + 1e-9) * step)


def clamp_sell_to_holding(qty: float, current_qty: float, code: str, product: Optional[Product] = None) -> int:
    """把（手填的）卖出数量限制在持仓范围内，并按步长取整（清仓除外），绝不超卖。"""
    if qty <= 0:
        return 0
    if qty >= current_qty - 1e-6:              # 与 round_sell 一致的清仓阈值
        return int(current_qty)                # 截断，绝不超过持仓
    step = lot_rule(code, product)[0]
    return int(math.floor(qty / step + 1e-9) * step)


# ---------------------------------------------------------------------------
# 输入模型：交易组 + 股票项
# ---------------------------------------------------------------------------
@dataclass
class StockEntry:
    code: str
    name: str = ""
    price: Optional[float] = None      # 人民币单价（自动取自文件或手填）
    source: str = config.SOURCE_CURRENT
    shares: int = 0                    # 系统算出的建议股数（compute 时填充）
    adjust: Optional[int] = None       # 经理手填的调整股数（覆盖 shares）

    @property
    def final_qty(self) -> int:
        return int(self.adjust) if self.adjust is not None else int(self.shares)


@dataclass
class DirectionGroup:
    product: str
    direction: str                     # 买入 / 卖出
    amount: Optional[float]            # 组总金额（元）
    method: str                        # 等金额 / 当前持仓比例（必填）
    stocks: list[StockEntry] = field(default_factory=list)

    def label(self) -> str:
        return f"产品「{self.product}」{self.direction}组"


@dataclass
class RebalanceResult:
    orders: list[TradeOrder] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 同标的既买又卖（对倒/自成交）的 (产品, 代码) 列表；UI 导出前据此强制二次确认
    self_trades: list[tuple] = field(default_factory=list)

    def orders_for(self, product: str) -> list[TradeOrder]:
        return [o for o in self.orders if o.product == product]

    def products(self) -> list[str]:
        seen: list[str] = []
        for o in self.orders:
            if o.product not in seen:
                seen.append(o.product)
        return seen


# ---------------------------------------------------------------------------
# 计算
# ---------------------------------------------------------------------------
def _group_weights(group: DirectionGroup, method: str,
                   product: Optional[Product]) -> tuple[Optional[list[float]], list[str]]:
    """按方式给组内每只股票算权重（与 stocks 顺序一致）。返回 (weights 或 None, 警告)。"""
    warns: list[str] = []
    n = len(group.stocks)
    if n == 0:
        return None, [f"{group.label()}：未选择任何股票，已跳过"]
    if method == config.METHOD_HOLDING:
        mvs = []
        excluded = []
        zero_held = []
        unheld = []
        for s in group.stocks:
            h = product.get(s.code) if product else None
            mv = h.market_value if h else 0.0
            if h is None:                  # 未持有该标的 -> 无持仓基准，权重必为0、不会被交易
                unheld.append(s.code)
            if mv < 0:                 # 期货空头/浮亏的负市值不参与分配（否则污染分母、正股权重>1超买）
                excluded.append(s.code)
                mv = 0.0
            elif mv == 0 and h is not None and h.quantity:
                zero_held.append(s.code)   # 持有但市值为0（如当日价未回填）-> 权重0，会被静默跳过
            mvs.append(mv)
        if unheld:
            warns.append(
                f"{group.label()}：{len(unheld)} 只标的当前未持有（如 {unheld[0]}），"
                f"「当前持仓比例」下权重为 0、不会被交易；如需建仓请改用「等金额」")
        if excluded:
            warns.append(
                f"{group.label()}：{len(excluded)} 只标的当前市值为负（如 {excluded[0]}，"
                f"期货空头/浮亏），已不参与「当前持仓比例」分配（权重计 0）")
        if zero_held:
            warns.append(
                f"{group.label()}：{len(zero_held)} 只标的虽有持仓但当前市值为 0（如 {zero_held[0]}，"
                f"可能当日价未回填），「当前持仓比例」下权重为 0、不会被交易，请核对")
        total = sum(mvs)
        if total <= 0:
            warns.append(
                f"{group.label()}：方式为「当前持仓比例」但组内当前无正持仓市值，"
                f"无法分配，已跳过该组（如需建仓请改用「等金额」）")
            return None, warns
        weights = [mv / total for mv in mvs]
        assert abs(sum(weights) - 1.0) < 1e-6, "权重之和应为1"
        return weights, warns
    # 等金额
    return [1.0 / n] * n, warns


def compute_group_shares(group: DirectionGroup,
                         product: Optional[Product]) -> tuple[list[str], bool]:
    """计算组内每只股票的建议股数（写入 entry.shares）。返回 (提示, 该组是否有效)。

    供 UI「重算」与 build_orders 共用，保证显示与下单一致。
    无效组（方式/方向/金额非法、持仓比例无正市值）返回 ok=False，build_orders 据此整组跳过，
    避免组内某只手填 adjust 仍被下单。
    """
    warns: list[str] = []

    def invalid(msg):
        warns.append(f"{group.label()}：{msg}")
        for s in group.stocks:
            s.shares = 0
        return warns, False

    method = normalize_method(group.method)
    if method is None:
        return invalid("方式必填（等金额 / 当前持仓比例），已跳过该组")
    if normalize_direction(group.direction) is None:
        return invalid("方向无效（应为 买入/卖出），已跳过该组")
    if not group.amount or group.amount <= 0:
        return invalid("金额必须为正数，已跳过该组")

    weights, w_warns = _group_weights(group, method, product)
    warns.extend(w_warns)
    if weights is None:
        for s in group.stocks:
            s.shares = 0
        return warns, False

    is_buy = normalize_direction(group.direction) == config.DIR_BUY
    for s, w in zip(group.stocks, weights):
        if not s.price or s.price <= 0:
            s.shares = 0
            warns.append(f"{group.label()}：{s.code} 无有效价格，无法算股数（请填价格）")
            continue
        alloc = group.amount * w
        raw = alloc / s.price
        if is_buy:
            s.shares = round_buy(raw, s.code, product)
        else:
            cur = product.get(s.code).quantity if (product and product.get(s.code)) else 0.0
            if cur <= 0:
                s.shares = 0
                warns.append(f"{group.label()}：{s.code} 当前未持有，无法卖出")
                continue
            s.shares = round_sell(raw, cur, s.code, product)
    return warns, True


def build_orders(groups: list[DirectionGroup], products: list[Product],
                 merged: Optional[list[StockPoolItem]] = None) -> RebalanceResult:
    """根据交易组与各产品持仓，生成最终下单指令。"""
    result = RebalanceResult()
    products_by_name = {p.name: p for p in products}
    universe = {it.code: it for it in (merged or [])}

    def name_of(code: str, product: Optional[Product], entry_name: str) -> str:
        if entry_name:
            return entry_name
        if product is not None:
            h = product.get(code)
            if h and h.name:
                return h.name
        it = universe.get(code)
        return it.name if it else ""

    # (product, code, direction) -> TradeOrder（合并重复项）
    merged_orders: dict[tuple, TradeOrder] = {}
    order_seq: list[tuple] = []
    # (product, code) -> 已累计的卖出量；用于跨组/跨条目对「总卖出 ≤ 持仓」统一封顶，杜绝合并后超卖
    sold_so_far: dict[tuple, int] = {}
    # 同一 (产品,代码,买入) 来自多于一个组/条目时记一次，循环后告警（与卖出封顶/自成交告警对称）
    buy_merged: set[tuple] = set()

    for group in groups:
        product = products_by_name.get(group.product)
        if product is None and group.product:
            result.warnings.append(f"{group.label()}：找不到产品「{group.product}」，已跳过该组")
            continue

        warns, ok = compute_group_shares(group, product)
        result.warnings.extend(warns)
        if not ok:        # 无效组（方式/方向/金额非法、持仓比例无正市值）整组跳过，即使有手填 adjust
            continue
        direction = normalize_direction(group.direction)

        for s in group.stocks:
            raw = s.final_qty                       # 调整(若填) 否则 系统算的股数
            # 无有效价格时不下「0 价单」：即便手填了 adjust 也跳过，避免引擎一边告警算不出股数、
            # 一边照样产出 unit_price=0 的订单（请先在「新增」里补价格）。
            if raw > 0 and (not s.price or s.price <= 0):
                result.warnings.append(
                    f"{group.label()}：{s.code} 无有效价格，已跳过（不下 0 价单，请先填价格）")
                continue
            if direction == config.DIR_BUY:
                # 手填 adjust 也要按步长取整、遵守最小买入量（系统算的 shares 已合规，幂等）
                final = round_buy(raw, s.code, product)
                if s.adjust is not None and final != raw:
                    result.warnings.append(
                        f"{group.label()}：{s.code} 买入数量 {raw} 已按手取整为 {final}"
                        + ("（未达最小买入量，不下单）" if final == 0 and raw > 0 else ""))
            else:  # 卖出：按「剩余可卖 = 持仓 − 已累计卖出」封顶，跨组合并也绝不超卖
                cur = product.get(s.code).quantity if (product and product.get(s.code)) else 0.0
                already = sold_so_far.get((group.product, s.code), 0)
                remaining = max(0.0, cur - already)
                final = clamp_sell_to_holding(raw, remaining, s.code, product)
                if raw > remaining and remaining >= 0 and cur > 0:
                    result.warnings.append(
                        f"{group.label()}：{s.code} 本次拟卖 {raw}，但（含其他组）累计卖出不能超过持仓 "
                        f"{int(cur)}，已按剩余 {int(remaining)} 封顶为 {final}")
                elif s.adjust is not None and final != raw and raw <= remaining:
                    result.warnings.append(
                        f"{group.label()}：{s.code} 卖出数量 {raw} 已按手取整为 {final}")
                if final > 0:
                    sold_so_far[(group.product, s.code)] = already + final
            if final <= 0:
                continue
            nm = name_of(s.code, product, s.name)
            key = (group.product, s.code, direction)
            if key in merged_orders:
                o = merged_orders[key]
                if direction == config.DIR_BUY:
                    o.buy_qty += final
                    buy_merged.add((group.product, s.code))
                else:
                    o.sell_qty += final
            else:
                o = TradeOrder(
                    product=group.product, direction=direction, code=s.code, name=nm,
                    buy_qty=final if direction == config.DIR_BUY else 0,
                    sell_qty=final if direction == config.DIR_SELL else 0,
                    unit_price=s.price or 0.0,
                )
                merged_orders[key] = o
                order_seq.append(key)

    result.orders = [merged_orders[k] for k in order_seq]

    # 同一 (产品,代码) 的买入来自多个组/重复条目 -> 已累加，提示核对是否误重复（防静默翻倍超买）
    for (pname, code) in sorted(buy_merged):
        result.warnings.append(
            f"产品「{pname}」标的 {code} 的买入数量来自多个交易组/重复条目，已累加，请核对是否误重复")

    # 自成交检测：同一 (产品,代码) 既有买单又有卖单 -> 对倒/自成交，记录并告警（UI 导出前据此强制确认）
    bs = {}
    for o in result.orders:
        bs.setdefault((o.product, o.code), set()).add(o.direction)
    for (pname, code), dirs in bs.items():
        if config.DIR_BUY in dirs and config.DIR_SELL in dirs:
            result.self_trades.append((pname, code))
            result.warnings.append(
                f"产品「{pname}」标的 {code} 同时存在买单和卖单（自成交/对倒），请核对是否需要合并或删除其一")

    # 排序：每个产品内，卖出在前、买入在后
    dir_rank = {config.DIR_SELL: 0, config.DIR_BUY: 1}
    product_order: dict[str, int] = {}
    for o in result.orders:
        product_order.setdefault(o.product, len(product_order))
    result.orders.sort(key=lambda o: (
        product_order[o.product], dir_rank.get(o.direction, 9), o.code))
    return result
