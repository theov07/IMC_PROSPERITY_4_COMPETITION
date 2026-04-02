import json
from math import ceil, floor, sqrt, log, exp, erfc, pi

from datamodel import Order, TradingState


# ── Configuration ────────────────────────────────────────────────────
PRODUCTS = {'EMERALDS': {'anchor_price': 10000.0,
              'anchor_weight': 0.92,
              'ema_alpha': 0.08,
              'fair_mode': 'anchored_microprice',
              'improve_ticks': 1,
              'inventory_aversion': 1.2,
              'join_best': True,
              'maker_size': 18,
              'max_inventory_bias_ticks': 4,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm',
              'take_edge': 1.0,
              'tighten_ticks': 1},
 'TOMATOES': {'anchor_price': None,
              'anchor_weight': 0.0,
              'ema_alpha': 0.18,
              'fair_mode': 'microprice_ema',
              'improve_ticks': 1,
              'inventory_aversion': 1.5,
              'join_best': True,
              'maker_size': 10,
              'max_inventory_bias_ticks': 5,
              'position_limit': 80,
              'quote_half_spread': 2,
              'strategy': 'naive_tight_mm',
              'take_edge': 1.0,
              'tighten_ticks': 1}}


# ── Persistence ──────────────────────────────────────────────────────
def load_state(raw):
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def dump_state(state):
    return json.dumps(state, separators=(",", ":"))


# ── Market helpers ───────────────────────────────────────────────────
def snapshot(order_depth):
    bids = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
    asks = sorted(((p, -v) for p, v in order_depth.sell_orders.items()), key=lambda x: x[0])
    bb = bids[0][0] if bids else None
    bbv = bids[0][1] if bids else 0
    ba = asks[0][0] if asks else None
    bav = asks[0][1] if asks else 0
    mid = (bb + ba) / 2.0 if bb is not None and ba is not None else None
    micro = None
    imb = None
    if bb is not None and ba is not None:
        t = bbv + bav
        if t > 0:
            micro = (bb * bav + ba * bbv) / t
            imb = (bbv - bav) / t
    return {"bids": bids, "asks": asks, "bb": bb, "bbv": bbv, "ba": ba, "bav": bav,
            "mid": mid, "micro": micro, "spread": (ba - bb) if bb is not None and ba is not None else None, "imb": imb}


def ewma(prev, cur, alpha):
    return cur if prev is None else alpha * cur + (1.0 - alpha) * prev


def norm_cdf(x):
    return 0.5 * erfc(-x / sqrt(2.0))


# ── Strategy implementations ────────────────────────────────────────

def run_market_maker(product, od, book, pos, mem, p):
    orders = []
    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)

    # Fair value
    prev_fair = mem.get("fair")
    ref = book["micro"] or book["mid"] or p.get("anchor_price") or prev_fair or 0.0
    mode = p.get("fair_mode", "microprice_ema")
    alpha = p.get("ema_alpha", 0.15)
    if mode == "fixed":
        fair = p.get("anchor_price") or ref
    elif mode == "anchored_microprice":
        anchor = p.get("anchor_price") or ref
        w = p.get("anchor_weight", 0.9)
        fair = ewma(prev_fair, w * anchor + (1 - w) * ref, alpha)
    elif mode == "mid_ema":
        fair = ewma(prev_fair, book["mid"] if book["mid"] is not None else ref, alpha)
    else:
        fair = ewma(prev_fair, ref, alpha)
    mem["fair"] = fair

    # Take
    edge = p.get("take_edge", 1.0)
    for ap in sorted(od.sell_orders):
        av = -od.sell_orders[ap]
        if ap > fair - edge or buy_cap <= 0:
            break
        q = min(av, buy_cap)
        if q > 0:
            orders.append(Order(product, ap, q))
            buy_cap -= q
    for bp in sorted(od.buy_orders, reverse=True):
        bv = od.buy_orders[bp]
        if bp < fair + edge or sell_cap <= 0:
            break
        q = min(bv, sell_cap)
        if q > 0:
            orders.append(Order(product, bp, -q))
            sell_cap -= q

    # Quote
    aversion = p.get("inventory_aversion", 1.0)
    max_ticks = p.get("max_inventory_bias_ticks", 3)
    bias = int(round(max(-max_ticks, min(max_ticks, (pos / float(lim)) * aversion * max_ticks)))) if lim > 0 else 0
    adj = fair - bias
    hs = p.get("quote_half_spread", 2)
    tb = floor(adj - hs)
    ta = ceil(adj + hs)
    if p.get("join_best", True) and book["bb"] is not None and book["ba"] is not None:
        imp = p.get("improve_ticks", 1)
        tb = max(tb, min(book["bb"] + imp, book["ba"] - 1))
        ta = min(ta, max(book["ba"] - imp, book["bb"] + 1))
    if book["ba"] is not None:
        tb = min(tb, book["ba"] - 1)
    if book["bb"] is not None:
        ta = max(ta, book["bb"] + 1)
    if ta <= tb:
        ta = tb + 1
    ms = p.get("maker_size", 12)
    qb = min(buy_cap, ms)
    qs = min(sell_cap, ms)
    ir = abs(pos) / float(lim) if lim else 0.0
    if ir >= 0.85:
        qb = max(1, qb // 2)
        qs = max(1, qs // 2)
    if pos > 0:
        qs = min(sell_cap, max(qs, min(ms * 2, abs(pos) // 4 + 1)))
    elif pos < 0:
        qb = min(buy_cap, max(qb, min(ms * 2, abs(pos) // 4 + 1)))
    if ir >= 0.75:
        if pos > 0: qb = 0
        elif pos < 0: qs = 0
    if qb > 0:
        orders.append(Order(product, tb, qb))
    if qs > 0:
        orders.append(Order(product, ta, -qs))
    return orders, 0


def run_naive_tight_mm(product, od, book, pos, mem, p):
    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)
    ms = p.get("maker_size", 10)
    tighten = p.get("tighten_ticks", 1)
    orders = []

    bid_price = book["bb"]
    ask_price = book["ba"]

    if book["bb"] is not None and book["ba"] is not None:
        spread = book["ba"] - book["bb"]
        if spread >= 2:
            bid_price = min(book["bb"] + tighten, book["ba"] - 1)
            ask_price = max(book["ba"] - tighten, book["bb"] + 1)

    if bid_price is not None and buy_cap > 0:
        orders.append(Order(product, bid_price, min(ms, buy_cap)))
    if ask_price is not None and sell_cap > 0:
        orders.append(Order(product, ask_price, -min(ms, sell_cap)))

    mem["last_bid_price"] = bid_price
    mem["last_ask_price"] = ask_price
    mem["last_spread"] = book["spread"]
    return orders, 0


def run_avellaneda_stoikov(product, od, book, pos, mem, p):
    if book["mid"] is None:
        return [], 0
    mid = book["mid"]
    orders = []
    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)

    # Vol estimation
    window = p.get("sigma_window", 50)
    prices = mem.setdefault("mid_history", [])
    prices.append(mid)
    if len(prices) > window + 1:
        prices[:] = prices[-(window + 1):]
    if len(prices) < 3:
        sigma = p.get("sigma_default", 1.0)
    else:
        rets = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        n = len(rets)
        mr = sum(rets) / n
        var = sum((r - mr)**2 for r in rets) / max(n - 1, 1)
        sigma = max(sqrt(var) if var > 0 else p.get("sigma_default", 1.0), p.get("sigma_floor", 0.5))

    gamma = p.get("gamma", 0.1)
    kappa = p.get("kappa", 1.5)
    total = p.get("total_ticks", 10000)
    tick = mem.get("tc", 0)
    mem["tc"] = tick + 1
    tau = max((total - tick) / total, 0.001)

    reservation = mid - pos * gamma * sigma * sigma * tau
    hs = max((gamma * sigma * sigma * tau) / 2 + log(1 + gamma / kappa) / gamma, p.get("min_half_spread", 1.0))

    bp = floor(reservation - hs)
    ap = ceil(reservation + hs)
    if book["ba"] is not None: bp = min(bp, book["ba"] - 1)
    if book["bb"] is not None: ap = max(ap, book["bb"] + 1)
    if ap <= bp: ap = bp + 1

    # Take
    te = p.get("take_edge", 0.5)
    for ask_p in sorted(od.sell_orders):
        av = -od.sell_orders[ask_p]
        if ask_p > reservation - te or buy_cap <= 0: break
        q = min(av, buy_cap)
        if q > 0: orders.append(Order(product, ask_p, q)); buy_cap -= q
    for bid_p in sorted(od.buy_orders, reverse=True):
        bv = od.buy_orders[bid_p]
        if bid_p < reservation + te or sell_cap <= 0: break
        q = min(bv, sell_cap)
        if q > 0: orders.append(Order(product, bid_p, -q)); sell_cap -= q

    ms = p.get("maker_size", 10)
    qb = min(buy_cap, ms)
    qs = min(sell_cap, ms)
    ir = abs(pos) / float(lim) if lim else 0.0
    if ir >= 0.75:
        if pos > 0: qb = 0
        elif pos < 0: qs = 0
    if qb > 0: orders.append(Order(product, bp, qb))
    if qs > 0: orders.append(Order(product, ap, -qs))
    mem["reservation"] = reservation
    mem["sigma"] = sigma
    return orders, 0


def run_stat_arb(product, state, book, pos, mem, p):
    if book["mid"] is None:
        return [], 0
    components = p.get("components", {})
    synthetic = 0.0
    for sym, w in components.items():
        cod = state.order_depths.get(sym)
        if cod is None: return [], 0
        cb = snapshot(cod)
        if cb["mid"] is None: return [], 0
        synthetic += cb["mid"] * w
    synthetic += p.get("basket_offset", 0.0)

    spread = book["mid"] - synthetic
    hist = mem.setdefault("sh", [])
    hist.append(spread)
    win = p.get("window", 100)
    if len(hist) > win: hist[:] = hist[-win:]
    n = len(hist)
    if n < 5: return [], 0
    m = sum(hist) / n
    std = sqrt(sum((x - m)**2 for x in hist) / max(n - 1, 1))
    z = (spread - m) / std if std > 0 else 0.0

    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)
    ms = p.get("maker_size", 10)
    ez = p.get("entry_z", 2.0)
    xz = p.get("exit_z", 0.5)
    orders = []
    if z > ez and sell_cap > 0 and book["bb"] is not None:
        orders.append(Order(product, book["bb"], -min(ms, sell_cap)))
    elif z < -ez and buy_cap > 0 and book["ba"] is not None:
        orders.append(Order(product, book["ba"], min(ms, buy_cap)))
    elif abs(z) < xz:
        if pos > 0 and book["bb"] is not None:
            orders.append(Order(product, book["bb"], -min(pos, sell_cap)))
        elif pos < 0 and book["ba"] is not None:
            orders.append(Order(product, book["ba"], min(-pos, buy_cap)))
    return orders, 0


def run_black_scholes(product, state, book, pos, mem, p):
    if book["mid"] is None: return [], 0
    underlying = p.get("underlying")
    if not underlying: return [], 0
    uod = state.order_depths.get(underlying)
    if uod is None: return [], 0
    ub = snapshot(uod)
    if ub["mid"] is None: return [], 0
    S = ub["mid"]
    K = p.get("strike", S)
    r = p.get("risk_free_rate", 0.0)
    tpy = p.get("ticks_per_year", 2520000)
    total = p.get("total_ticks", 10000)
    tick = mem.get("tc", 0)
    mem["tc"] = tick + 1
    T = max((total - tick) / tpy, 1e-6)

    # Vol
    win = p.get("vol_window", 100)
    uh = mem.setdefault("uh", [])
    uh.append(S)
    if len(uh) > win + 1: uh[:] = uh[-(win + 1):]
    if len(uh) < 5:
        sigma = p.get("vol_default", 0.2)
    else:
        rets = [log(uh[i] / uh[i-1]) for i in range(1, len(uh)) if uh[i-1] > 0]
        if len(rets) < 2: sigma = p.get("vol_default", 0.2)
        else:
            n = len(rets)
            mr = sum(rets) / n
            var = sum((x - mr)**2 for x in rets) / max(n - 1, 1)
            sigma = max(sqrt(var * tpy) if var > 0 else p.get("vol_default", 0.2), 0.05)

    is_call = p.get("is_call", True)
    if T > 0 and sigma > 0:
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)
        if is_call:
            theo = S * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
        else:
            theo = K * exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    else:
        theo = max(S - K, 0.0) if is_call else max(K - S, 0.0)

    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)
    ms = p.get("maker_size", 5)
    eth = p.get("edge_threshold", 1.0)
    orders = []
    if book["ba"] is not None and book["ba"] < theo - eth and buy_cap > 0:
        orders.append(Order(product, book["ba"], min(ms, buy_cap)))
    if book["bb"] is not None and book["bb"] > theo + eth and sell_cap > 0:
        orders.append(Order(product, book["bb"], -min(ms, sell_cap)))
    return orders, 0


def run_conversion_arb(product, state, book, pos, mem, p):
    orders = []
    convs = 0
    obs = state.observations
    if obs is None: return orders, 0
    conv_obs = getattr(obs, "conversionObservations", {})
    key = p.get("observation_key", product)
    if not isinstance(conv_obs, dict) or key not in conv_obs: return orders, 0
    co = conv_obs[key]
    fb, fa = co.bidPrice, co.askPrice
    tr, ex, im_ = co.transportFees, co.exportTariff, co.importTariff
    me = p.get("min_edge", 1.0)
    ms = p.get("maker_size", 10)
    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)
    if book["ba"] is not None and (fb - tr - ex) - book["ba"] > me and buy_cap > 0:
        orders.append(Order(product, book["ba"], min(ms, buy_cap)))
    if book["bb"] is not None and book["bb"] - (fa + tr + im_) > me and sell_cap > 0:
        orders.append(Order(product, book["bb"], -min(ms, sell_cap)))
    if pos > 0: convs = pos
    elif pos < 0: convs = pos
    return orders, convs


def run_signal_trader(product, state, book, pos, mem, p):
    tick = mem.get("tc", 0)
    mem["tc"] = tick + 1
    tracked = set(p.get("tracked_bots", []))
    window = p.get("signal_window", 5)
    signals = mem.setdefault("sigs", [])
    for t in state.market_trades.get(product, []):
        if (t.buyer or "") in tracked:
            signals.append({"d": 1, "q": t.quantity, "t": tick})
        if (t.seller or "") in tracked:
            signals.append({"d": -1, "q": t.quantity, "t": tick})
    signals[:] = [s for s in signals if s["t"] >= tick - window]
    strength = p.get("signal_strength", 1.0)
    total = sum(s["d"] * s["q"] * strength for s in signals)
    lim = p["position_limit"]
    buy_cap = max(0, lim - pos)
    sell_cap = max(0, lim + pos)
    ms = p.get("maker_size", 8)
    orders = []
    if total > 0 and buy_cap > 0 and book["ba"] is not None:
        orders.append(Order(product, book["ba"], min(ms, buy_cap)))
    elif total < 0 and sell_cap > 0 and book["bb"] is not None:
        orders.append(Order(product, book["bb"], -min(ms, sell_cap)))
    elif total == 0 and abs(pos) > 0:
        if pos > 0 and book["bb"] is not None:
            q = min(max(1, abs(pos) // 4), sell_cap)
            if q > 0: orders.append(Order(product, book["bb"], -q))
        elif pos < 0 and book["ba"] is not None:
            q = min(max(1, abs(pos) // 4), buy_cap)
            if q > 0: orders.append(Order(product, book["ba"], q))
    return orders, 0


STRATEGY_DISPATCH = {
    "market_maker": lambda prod, state, od, book, pos, mem, p: run_market_maker(prod, od, book, pos, mem, p),
    "naive_tight_mm": lambda prod, state, od, book, pos, mem, p: run_naive_tight_mm(prod, od, book, pos, mem, p),
    "avellaneda_stoikov": lambda prod, state, od, book, pos, mem, p: run_avellaneda_stoikov(prod, od, book, pos, mem, p),
    "stat_arb": lambda prod, state, od, book, pos, mem, p: run_stat_arb(prod, state, book, pos, mem, p),
    "black_scholes": lambda prod, state, od, book, pos, mem, p: run_black_scholes(prod, state, book, pos, mem, p),
    "conversion_arb": lambda prod, state, od, book, pos, mem, p: run_conversion_arb(prod, state, book, pos, mem, p),
    "signal_trader": lambda prod, state, od, book, pos, mem, p: run_signal_trader(prod, state, book, pos, mem, p),
}


class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        saved = load_state(state.traderData)
        product_state = saved.setdefault("products", {})
        result = {}
        total_conversions = 0

        for product, config in PRODUCTS.items():
            od = state.order_depths.get(product)
            if od is None:
                continue
            pos = state.position.get(product, 0)
            book = snapshot(od)
            mem = product_state.setdefault(product, {})
            strat = config.get("strategy", "market_maker")
            fn = STRATEGY_DISPATCH.get(strat)
            if fn is None:
                continue
            orders, convs = fn(product, state, od, book, pos, mem, config)
            result[product] = orders
            total_conversions += convs

        saved["last_timestamp"] = state.timestamp
        return result, total_conversions, dump_state(saved)