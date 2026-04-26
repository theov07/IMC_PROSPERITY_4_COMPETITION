"""velvet_strat_v30 — Four targeted option ideas untested in v29/v40-v48.

Each class is a thin wrapper that exists purely so config entries resolve to
a unique class name (makes compare/export safe).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IDEA 1 — VEV_4500: smile-calibrated GammaScalp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Inherits GammaScalpZGatedMixinStrategy (same as gamma_scalp_v28).
  Key change: fair_vol_mode="smile_iv" — uses LOO polynomial smile fit to
  predict the fair IV for K=4500 from the other strikes. Historical smile
  shows slightly-ITM strikes have higher IV than 0.0125 → BS fair value is
  higher → taker buys fire more often / at looser threshold.

  Previous v44 test used a fixed-fair passive ask overlay → no fills, neutral.
  This idea does NOT add an ask — it only changes how the fair value is
  computed for taker decisions. Separate, untested.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IDEA 2 — VEV_5100: gentle gamma+ask variant
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Previous v42 tested pure SymmetricOptionMM (true 2-sided MM) → catastrophic
  (-12.9k). That abandoned the accumulation bias entirely.
  This variant keeps full GammaScalp accumulation logic and only adds a
  very small passive ask (size=4) when position >= 80 AND market ask > BS fair.
  We are NOT doing 2-sided MM — just occasionally capturing a tick when the
  option spikes above fair after we've accumulated a position.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IDEA 3 — VEV_5200: smile-calibrated accumulator (replaces passive VEVOptionMMV28)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Current best: VEVOptionMMV28 (passive bid at best_bid+1, size 20, no fair
  value logic). Gets 11,882. Idea: replace with GammaScalp using smile_iv
  as fair vol and skip_when_expensive=False. For OTM K=5200, the smile
  predicts higher IV than 0.0125 → BS fair is higher → taker layer activates.
  Also still posts passive bid on every tick (edge_ticks=3 ensures ask ≤ fair
  is easier to satisfy even if smile estimate is slightly off).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IDEA 4 — VEV_4000: delta-one MM using VELVETFRUIT microprice
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  For K=4000, delta≈1: option tracks VELVETFRUIT tick-for-tick.
  Current GammaScalp uses BS(velvet_mid, 4000, T, 0.0125) for fair value.
  DeltaOneMMV30 uses VELVETFRUIT microprice (volume-weighted top-of-book)
  instead of mid. When order book is bid-heavy (microprice > mid), fair is
  higher → taker buys more aggressive. When ask-heavy (microprice < mid),
  fair is lower → conservative entry. Also scales passive bid size by
  imbalance to accumulate faster on dips and slower on spikes.

  Previous v29_vev4000_sym_mm used generic SymmetricOptionMM (fixed fair,
  no imbalance, 2-sided) → -21k on day-2 directional check. Entirely different.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

from prosperity.market import BookSnapshot
from prosperity.options.black_scholes import call_price
from prosperity.strategies.base.base import BaseStrategy
from prosperity.strategies.round_3.tibo.smile_iv_scalper import (
    GammaScalpZGatedMixinStrategy,
    _VelvetOptionMixin,
)
from prosperity.strategies.round_3.tibo.velvet_strat_v40 import GammaScalpWithAsk


# ══════════════════════════════════════════════════════════════════════════════
#  IDEA 1 — VEV_4500 smile-calibrated GammaScalp
# ══════════════════════════════════════════════════════════════════════════════


class GammaScalpSmileV30VEV4500(GammaScalpZGatedMixinStrategy):
    """VEV_4500 accumulator with smile-predicted IV as fair vol.

    Inherits all GammaScalp logic. Only difference from gamma_scalp_v28:
    the config sets fair_vol_mode="smile_iv" so _compute_fair_value() uses
    the LOO polynomial smile fit rather than implied_vol_prior=0.0125.
    """


# ══════════════════════════════════════════════════════════════════════════════
#  IDEA 2 — VEV_5100 gentle gamma + small passive ask
# ══════════════════════════════════════════════════════════════════════════════


class GammaScalpWithAskV30VEV5100(GammaScalpWithAsk):
    """VEV_5100 GammaScalp + tiny passive ask when position is large.

    Keeps full accumulation bias (same as gamma_scalp_v28 for VEV_5100).
    Adds a very small passive ask (size=4) only when:
      - position >= ask_min_position (default 80)
      - market best_ask > BS fair price (ask_only_above_fair=True)
    No taker sells. The ask fires at best_ask-1 and may occasionally fill
    when the option spikes above fair.

    v42 (pure SymmetricOptionMM) lost -12.9k. This is fundamentally different:
    we never abandon the accumulation bias.
    """


# ══════════════════════════════════════════════════════════════════════════════
#  IDEA 3 — VEV_5200 smile-calibrated accumulator
# ══════════════════════════════════════════════════════════════════════════════


class GammaScalpSmileV30VEV5200(GammaScalpZGatedMixinStrategy):
    """VEV_5200 accumulator with smile-predicted IV, no skip gate.

    Replaces VEVOptionMMV28 (pure passive bid-heavy) with GammaScalp that
    uses smile_iv as fair vol and skip_when_expensive=False.

    For OTM K=5200, smile typically predicts higher IV than 0.0125 → BS fair
    is higher → taker layer fires when market ask is still "cheap" vs smile.
    edge_ticks=3 relaxes the taker threshold further to ensure passive-like
    coverage even when smile estimate is uncertain.
    """


# ══════════════════════════════════════════════════════════════════════════════
#  IDEA 4 — VEV_4000 delta-one MM using VELVETFRUIT microprice
# ══════════════════════════════════════════════════════════════════════════════


class DeltaOneMMV30(_VelvetOptionMixin, BaseStrategy):
    """Delta-one accumulator for deep-ITM VEV_4000 using VELVETFRUIT microprice.

    For K=4000, delta≈1: fair value = call_price(microprice, 4000, T, sigma).
    Microprice = volume-weighted top-of-book VELVETFRUIT price:
        microprice = (bid * ask_vol + ask * bid_vol) / (bid_vol + ask_vol)

    When VELVETFRUIT order book is bid-heavy (microprice > mid):
      - fair value is higher → taker threshold is looser
      - passive bid size is boosted by imbalance_bid_boost factor

    When ask-heavy (microprice < mid):
      - fair value is lower → taker threshold is tighter
      - passive bid size is reduced by imbalance_bid_reduce factor

    No passive ask (consistent with all previous findings).
    Otherwise identical accumulation logic to GammaScalpZGatedMixinStrategy.
    """

    def _microprice_and_mid(
        self,
        state: TradingState,
        fallback_mid: float,
    ) -> Tuple[float, float]:
        underlying = str(self.params.get("underlying_symbol", "VELVETFRUIT_EXTRACT"))
        od = state.order_depths.get(underlying)
        if not od or not od.buy_orders or not od.sell_orders:
            return fallback_mid, fallback_mid
        bid = float(max(od.buy_orders))
        ask = float(min(od.sell_orders))
        bid_vol = float(abs(od.buy_orders[max(od.buy_orders)]))
        ask_vol = float(abs(od.sell_orders[min(od.sell_orders)]))
        total = bid_vol + ask_vol
        if total < 1e-9:
            micro = (bid + ask) * 0.5
        else:
            micro = (bid * ask_vol + ask * bid_vol) / total
        mid = (bid + ask) * 0.5
        return micro, mid

    def compute_orders(
        self,
        state: TradingState,
        book: BookSnapshot,
        order_depth: OrderDepth,
        position: int,
        memory: Dict[str, Any],
    ) -> Tuple[List[Order], int]:
        if book.best_bid is None or book.best_ask is None:
            return [], 0

        p = self.params
        ts = int(state.timestamp)
        _, T = self._resolve_tte(state)
        S = self._resolve_spot(state, memory, ts)
        if S is None:
            return [], 0

        microprice, velvet_mid = self._microprice_and_mid(state, S)

        K = float(p.get("strike", 4000))
        sigma = float(p.get("implied_vol_prior", 0.0125))
        fair = call_price(microprice, K, T, sigma)
        fair = max(max(0.0, microprice - K), fair)

        min_quote = float(p.get("min_quote_price", 2.0))
        if fair < min_quote:
            return [], 0

        target_qty = int(p.get("target_qty", 300))
        entry_size = int(p.get("entry_size", 30))
        base_passive_size = int(p.get("passive_bid_size", 24))
        edge_ticks = float(p.get("edge_ticks", 0.0))
        unwind_tte = float(p.get("unwind_tte_threshold", 1.5))

        # Scale passive bid size by order book imbalance signal
        # microprice > velvet_mid  → bid-heavy → accumulate faster
        # microprice < velvet_mid  → ask-heavy → slow down
        imb = microprice - velvet_mid  # typically ±0.5 to ±2 ticks
        imb_boost = float(p.get("imbalance_bid_boost", 1.5))
        imb_reduce = float(p.get("imbalance_bid_reduce", 0.5))
        imb_tick_threshold = float(p.get("imbalance_tick_threshold", 0.3))

        if imb > imb_tick_threshold:
            passive_bid_size = max(1, int(round(base_passive_size * imb_boost)))
        elif imb < -imb_tick_threshold:
            passive_bid_size = max(1, int(round(base_passive_size * imb_reduce)))
        else:
            passive_bid_size = base_passive_size

        orders: List[Order] = []
        buy_cap = self.buy_capacity(position)
        sell_cap = self.sell_capacity(position)

        # Unwind mode
        if T < unwind_tte or position >= target_qty:
            if sell_cap > 0 and position > 0:
                ask_px = book.best_ask - 1
                if ask_px <= book.best_bid:
                    ask_px = book.best_bid + 1
                qty = min(base_passive_size, sell_cap, position)
                if qty > 0:
                    orders.append(Order(self.product, ask_px, -qty))
            memory["_mode"] = "unwind"
            return orders, 0

        # Taker buy: option ask cheap vs microprice-anchored fair
        if buy_cap > 0 and position < target_qty:
            ask = book.best_ask
            if ask <= fair + edge_ticks:
                ask_qty = -order_depth.sell_orders.get(ask, 0)
                headroom = target_qty - position
                take_qty = min(ask_qty, buy_cap, entry_size, headroom)
                if take_qty > 0:
                    orders.append(Order(self.product, ask, take_qty))
                    buy_cap -= take_qty
                    position += take_qty

        # Passive bid (imbalance-scaled size)
        if buy_cap > 0 and position < target_qty:
            bid_px = book.best_bid + 1
            if bid_px < book.best_ask:
                qty = min(passive_bid_size, buy_cap, target_qty - position)
                if qty > 0:
                    orders.append(Order(self.product, bid_px, qty))

        memory["_mode"] = "accumulate"
        memory["_microprice"] = microprice
        memory["_velvet_mid"] = velvet_mid
        memory["_imbalance"] = imb
        memory["_fair"] = fair
        return orders, 0

    def feature_prices(self, memory: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if (v := memory.get("_microprice")) is not None:
            out["microprice"] = float(v)
        if (v := memory.get("_imbalance")) is not None:
            out["imbalance"] = float(v)
        if (v := memory.get("_fair")) is not None:
            out["fair"] = float(v)
        return out
