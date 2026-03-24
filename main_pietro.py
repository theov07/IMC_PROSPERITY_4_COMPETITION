from datamodel import OrderDepth, TradingState, Order
from typing import List

class Trader:
    POSITION_LIMIT = 80

    # Tomatoes
    TOM_HALF_SPREAD = 3     # ticks each side from THEO
    TOM_THETA       = 0.15  # inventory skew sensitivity

    # Emeralds
    EME_THEO        = 10000
    EME_HALF_SPREAD = 6     # ticks each side from THEO (inside 8-tick market half-spread)


    def run(self, state: TradingState):
        results = {}

        if "TOMATOES" in state.order_depths:
            results["TOMATOES"] = self.trade_tomatoes(state)

        if "EMERALDS" in state.order_depths:
            results["EMERALDS"] = self.trade_emeralds(state)
        
        return results, 0, ""
    

    def compute_tomatoe_theo(self, order_depth: OrderDepth):
        bids = sorted(order_depth.buy_orders.items(), reverse=True)
        asks = sorted(order_depth.sell_orders.items())

        # Need at least L1 on both sides
        if not bids or not asks:
            return None
        
        #If we have at least two levels  else fall back to just one level
        if len(bids) >= 2 and len(asks) >= 2:
            bp1, bv1 = bids[0];  bp2, bv2 = bids[1]
            ap1, av1 = asks[0];  ap2, av2 = asks[1]
            av1, av2 = abs(av1), abs(av2)   # sell volumes are negative in datamodel

            total_bid = bv1 + bv2
            total_ask = av1 + av2
            bid_vwap  = (bp1 * bv1 + bp2 * bv2) / total_bid
            ask_vwap  = (ap1 * av1 + ap2 * av2) / total_ask

        else:
            bp1, bv1  = bids[0]
            ap1, av1  = asks[0]
            av1       = abs(av1)
            total_bid, total_ask = bv1, av1
            bid_vwap,  ask_vwap  = bp1, ap1
        
        theo = (ask_vwap * total_bid + bid_vwap * total_ask) / (total_bid + total_ask)
        return theo
    
    def trade_tomatoes(self, state: TradingState):
        orders      = []
        od          = state.order_depths["TOMATOES"]
        position    = state.position.get("TOMATOES", 0)

        theo = self.compute_tomatoe_theo(od)
        #This just measn we have no orders for tomatoes
        if theo is None:
            return orders
        
        buy_cap  = self.POSITION_LIMIT - position   # how much more we can buy
        sell_cap = self.POSITION_LIMIT + position   # how much more we can sell

        #Active Taking
        orders, sell_cap, buy_cap = self._active_taking(theo, od, orders, 'TOMATOES', buy_cap, sell_cap)

        #Passive Orders
        DANGER_ZONE = 60  # ~75% of position limit

        if abs(position) >= DANGER_ZONE:
            #Priorotize getting flat
            if position > 0:
                bid_quote = None
                ask_quote = round(theo+1)
            else:
                bid_quote = round(theo-1)
                ask_quote = None
        else:
            utilization = abs(position) / DANGER_ZONE
            dynamic_theta = self.TOM_THETA * (1 + utilization)
            skew = dynamic_theta * position
            bid_quote = round(theo - self.TOM_HALF_SPREAD - skew)
            ask_quote = round(theo + self.TOM_HALF_SPREAD - skew)
            
        if buy_cap > 0 and bid_quote is not None:
            orders.append(Order("TOMATOES", bid_quote, buy_cap))
        if sell_cap > 0 and ask_quote is not None:
            orders.append(Order("TOMATOES", ask_quote, -sell_cap))

        return orders
    

    def trade_emeralds(self, state: TradingState):
        orders      = []
        od          = state.order_depths["EMERALDS"]
        position    = state.position.get("EMERALDS", 0)
        theo = self.EME_THEO

        buy_cap  = self.POSITION_LIMIT - position
        sell_cap = self.POSITION_LIMIT + position

        #Active Taking
        orders, sell_cap, buy_cap = self._active_taking(theo, od, orders, 'EMERALDS', buy_cap, sell_cap)

        #Passive Orders
        #We quote inside the market to attract bot flow
        bid_quote = theo - self.EME_HALF_SPREAD   # 9996
        ask_quote = theo + self.EME_HALF_SPREAD   # 10004

        if buy_cap > 0:
            orders.append(Order("EMERALDS", bid_quote,  buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", ask_quote, -sell_cap))

        return orders

    def _active_taking(self, theo, od, orders, product, buy_cap, sell_cap):
        #If Buy bot sell orders that are below THEO instant edge
        for ask_px, ask_vol in sorted(od.sell_orders.items()):
            if ask_px < theo and buy_cap > 0:
                qty = min(abs(ask_vol), buy_cap)
                orders.append(Order(product, ask_px, qty))
                buy_cap -= qty

        for bid_px, bid_vol in sorted(od.buy_orders.items(), reverse=True):
            if bid_px > theo and sell_cap > 0:
                qty = min(bid_vol, sell_cap)
                orders.append(Order(product, bid_px, -qty))
                sell_cap -= qty
        return orders, sell_cap, buy_cap

