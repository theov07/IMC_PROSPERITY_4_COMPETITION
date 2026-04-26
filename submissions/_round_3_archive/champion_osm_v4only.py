from prosperity.config import get_round_config
from prosperity.persistence import dump_state, load_state
from prosperity.strategies import build_strategy

class Trader:
    def __init__(self):
        cfg = get_round_config(2, "champion_osm_v4only")
        self.strategies = {}
        for sym, pc in cfg.items():
            merged = {"position_limit": pc.position_limit, **pc.params}
            self.strategies[sym] = build_strategy(pc.strategy, sym, merged)
    def bid(self): return 2951
    def run(self, state):
        saved = load_state(state.traderData)
        mems = saved.setdefault("products", {})
        result = {}; convs = 0
        for p, s in self.strategies.items():
            if p not in state.order_depths: continue
            m = mems.setdefault(p, {})
            orders, c = s.on_tick(state, m)
            result[p] = orders; convs += c
        saved["last_timestamp"] = state.timestamp
        return result, convs, dump_state(saved)
