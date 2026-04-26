from __future__ import annotations
from abc import ABC,abstractmethod
from dataclasses import dataclass
from datamodel import Order,OrderDepth,TradingState
from datamodel import OrderDepth
from typing import Any,Dict
from typing import Any,Dict,List,Optional,Set,Tuple
from typing import Any,Dict,List,Optional,Tuple
from typing import Any,Dict,List,Tuple
from typing import Any,Dict,Tuple
from typing import Any,Mapping
from typing import List,Sequence,Tuple,Optional
from typing import List,Tuple
import json,math
PriceLevel=Tuple[int,int]
@dataclass(frozen=True)
class BookSnapshot:symbol:str;bid_levels:List[PriceLevel];ask_levels:List[PriceLevel];best_bid:int|None;best_bid_volume:int;best_ask:int|None;best_ask_volume:int;mid_price:float|None;microprice:float|None;spread:int|None;imbalance:float|None
def _sorted_bid_levels(order_depth):return sorted(order_depth.buy_orders.items(),key=lambda item:item[0],reverse=True)
def _sorted_ask_levels(order_depth):return sorted(((price,-volume)for(price,volume)in order_depth.sell_orders.items()),key=lambda item:item[0])
def snapshot_from_order_depth(symbol,order_depth):
	bid_levels=_sorted_bid_levels(order_depth);ask_levels=_sorted_ask_levels(order_depth);best_bid=bid_levels[0][0]if bid_levels else None;best_bid_volume=bid_levels[0][1]if bid_levels else 0;best_ask=ask_levels[0][0]if ask_levels else None;best_ask_volume=ask_levels[0][1]if ask_levels else 0;mid_price=None;microprice=None;spread=None;imbalance=None
	if best_bid is not None and best_ask is not None:
		spread=best_ask-best_bid;mid_price=(best_bid+best_ask)/2.;total_top=best_bid_volume+best_ask_volume
		if total_top>0:microprice=(best_bid*best_ask_volume+best_ask*best_bid_volume)/total_top;imbalance=(best_bid_volume-best_ask_volume)/total_top
	return BookSnapshot(symbol=symbol,bid_levels=bid_levels,ask_levels=ask_levels,best_bid=best_bid,best_bid_volume=best_bid_volume,best_ask=best_ask,best_ask_volume=best_ask_volume,mid_price=mid_price,microprice=microprice,spread=spread,imbalance=imbalance)
def load_state(raw_state):
	if not raw_state:return{}
	try:loaded=json.loads(raw_state);return loaded if isinstance(loaded,dict)else{}
	except Exception:return{}
def dump_state(state):return json.dumps(state,separators=(',',':'))
class BaseStrategy(ABC):
	def __init__(self,product,params):self.product=product;self.params=params
	def on_tick(self,state,memory):
		self._memory=memory;order_depth=state.order_depths.get(self.product)
		if order_depth is None:return[],0
		position=state.position.get(self.product,0);book=snapshot_from_order_depth(self.product,order_depth);return self.compute_orders(state=state,book=book,order_depth=order_depth,position=position,memory=memory)
	@abstractmethod
	def compute_orders(self,state,book,order_depth,position,memory):...
	def _microprice(self,book):
		bid_total=sum(v for(_,v)in book.bid_levels);ask_total=sum(v for(_,v)in book.ask_levels);prev=self._memory.get('_microprice_last',.0)
		if bid_total==0 or ask_total==0:return float(prev)
		bid_vwap=sum(p*v for(p,v)in book.bid_levels)/bid_total;ask_vwap=sum(p*v for(p,v)in book.ask_levels)/ask_total;result=(bid_vwap*ask_total+ask_vwap*bid_total)/(bid_total+ask_total);self._memory['_microprice_last']=result;return result
	def _smooth_mid(self,mid,memory):
		window=int(self.params.get('mid_smooth_window',20))
		if window<=0:return mid
		half_life=float(self.params.get('mid_smooth_half_life',window/2.));buf=memory.setdefault('mid_smooth_buf',[]);buf.append(mid)
		if len(buf)>window:buf[:]=buf[-window:]
		if len(buf)<2:return mid
		alpha=1.-2.**(-1./half_life)if half_life>0 else 1.;smoothed=buf[0]
		for p in buf[1:]:smoothed=alpha*p+(1.-alpha)*smoothed
		memory['mid_smoothed']=smoothed;return smoothed
	def _update_volatility(self,mid,memory):
		window=int(self.params.get('sigma_window',50));prices=memory.setdefault('mid_history',[]);prices.append(mid)
		if len(prices)>window+1:prices[:]=prices[-(window+1):]
		if len(prices)<3:return float(self.params.get('sigma_default',1.))
		returns=[prices[i]-prices[i-1]for i in range(1,len(prices))];n=len(returns);mean_r=sum(returns)/n;var=sum((r-mean_r)**2 for r in returns)/max(n-1,1);sigma_raw=math.sqrt(var)if var>0 else float(self.params.get('sigma_default',1.));half_life=float(self.params.get('sigma_half_life',60));alpha=2./(half_life+1.);sigma_prev=memory.get('sigma_smoothed',sigma_raw);sigma_smoothed=alpha*sigma_raw+(1.-alpha)*sigma_prev;memory['sigma_smoothed']=sigma_smoothed;return max(sigma_smoothed,float(self.params.get('sigma_floor',.5)))
	def feature_prices(self,memory):return{}
	def runtime_trace_enabled(self):
		enabled=self.params.get('runtime_trace_enabled')
		if enabled is not None:return bool(enabled)
		return not bool(False)
	def log_quote_snapshot(self,*,state,memory,bid_price,ask_price,extras=None):
		if not self.params.get('quote_trace_enabled',False)or not self.runtime_trace_enabled():return
		row={'timestamp':int(state.timestamp),'bid_price':bid_price,'ask_price':ask_price}
		if extras:row.update(extras)
		columns=memory.setdefault('_quote_trace_columns',list(row.keys()))
		for key in row.keys():
			if key not in columns:columns.append(key)
		rows=memory.setdefault('_quote_trace_rows',[]);rows.append(row);flush_ts=int(self.params.get('log_flush_ts',10000));last_tick_ts=self.params.get('last_ts_value')
		if last_tick_ts is None:last_tick_ts=int(self.params.get('total_ticks',200000))-100
		else:last_tick_ts=int(last_tick_ts)
		end_of_sim=int(state.timestamp)>=last_tick_ts;checkpoint=flush_ts>0 and int(state.timestamp)%flush_ts==flush_ts-100
		if not(end_of_sim or checkpoint):return
		print(json.dumps({'product':self.product,'trace':'quote_trace','chunk_end':int(state.timestamp),'columns':columns,'log':[[row.get(column)for column in columns]for row in rows]}));memory['_quote_trace_rows']=[]
	def log_taker_fill(self,*,state,memory,side,price,quantity,gap_exploit=False):
		if not self.runtime_trace_enabled():return
		taker_log=memory.setdefault('_taker_log',[]);entry=[int(state.timestamp),side,price,quantity]
		if gap_exploit:entry.append(1)
		taker_log.append(entry);flush_ts=int(self.params.get('log_flush_ts',10000));ts_increment=int(self.params.get('ts_increment',100));last_ts=int(self.params.get('last_ts_value',199900));second_to_last=last_ts-ts_increment;is_quote_flush=flush_ts>0 and int(state.timestamp)%flush_ts==flush_ts-100;deferred=memory.get('_taker_flush_deferred',False)
		if len(taker_log)>=20 and is_quote_flush and not deferred:memory['_taker_flush_deferred']=True;return
		should_flush=deferred or int(state.timestamp)>=second_to_last or len(taker_log)>=20 and not is_quote_flush
		if not should_flush:return
		print(json.dumps({'product':self.product,'trace':'taker_fills','chunk_end':int(state.timestamp),'log':taker_log}));memory['_taker_log']=[];memory['_taker_flush_deferred']=False
	def position_limit(self):return self.params.get('position_limit',20)
	def buy_capacity(self,position):return max(0,self.position_limit()-position)
	def sell_capacity(self,position):return max(0,self.position_limit()+position)
DEFAULT_TIMESTAMP_UNITS_PER_DAY=1e6
DEFAULT_TS_INCREMENT=1e2
MIN_TTE_DAYS=.01
def timestamp_units_per_day_from_params(params):
	explicit=params.get('timestamp_units_per_day')
	if explicit is not None:return max(float(explicit),1.)
	ticks_per_day=float(params.get('ticks_per_day',DEFAULT_TIMESTAMP_UNITS_PER_DAY/DEFAULT_TS_INCREMENT));ts_increment=float(params.get('ts_increment',DEFAULT_TS_INCREMENT));return max(ticks_per_day*ts_increment,1.)
def time_to_expiry_days(timestamp,initial_tte_days,*,timestamp_units_per_day=DEFAULT_TIMESTAMP_UNITS_PER_DAY,min_tte_days=MIN_TTE_DAYS):elapsed_days=max(float(timestamp),.0)/max(float(timestamp_units_per_day),1.);return max(float(min_tte_days),float(initial_tte_days)-elapsed_days)
def resolve_initial_tte_days(trader_data,default_tte_days,historical_tte_by_day=None):
	if not historical_tte_by_day or not trader_data:return float(default_tte_days)
	try:loaded=json.loads(trader_data)
	except Exception:return float(default_tte_days)
	if not isinstance(loaded,dict):return float(default_tte_days)
	meta=loaded.get('_backtest')
	if not isinstance(meta,dict)or'day'not in meta:return float(default_tte_days)
	day=meta.get('day');candidate_keys=[day,str(day)]
	try:candidate_keys.append(int(day))
	except(TypeError,ValueError):pass
	for key in candidate_keys:
		if key in historical_tte_by_day:
			try:return float(historical_tte_by_day[key])
			except(TypeError,ValueError):return float(default_tte_days)
	return float(default_tte_days)
_SQRT_2PI=math.sqrt(2.*math.pi)
def _norm_pdf(x):return math.exp(-.5*x*x)/_SQRT_2PI
def _norm_cdf(x):return .5*(1.+math.erf(x/math.sqrt(2.)))
def _d1_d2(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0 or S<=.0 or K<=.0:return None,None
	sqrtT=math.sqrt(T);d1=(math.log(S/K)+(r-q+.5*sigma*sigma)*T)/(sigma*sqrtT);d2=d1-sigma*sqrtT;return d1,d2
def call_price(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0:return max(.0,S-K)
	d1,d2=_d1_d2(S,K,T,sigma,r,q)
	if d1 is None:return max(.0,S-K)
	return S*math.exp(-q*T)*_norm_cdf(d1)-K*math.exp(-r*T)*_norm_cdf(d2)
def call_delta(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0:return 1. if S>K else .0 if S<K else .5
	d1,_=_d1_d2(S,K,T,sigma,r,q)
	if d1 is None:return .5
	return math.exp(-q*T)*_norm_cdf(d1)
def call_gamma(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0 or S<=.0:return .0
	d1,_=_d1_d2(S,K,T,sigma,r,q)
	if d1 is None:return .0
	return math.exp(-q*T)*_norm_pdf(d1)/(S*sigma*math.sqrt(T))
def call_vega(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0:return .0
	d1,_=_d1_d2(S,K,T,sigma,r,q)
	if d1 is None:return .0
	return S*math.exp(-q*T)*_norm_pdf(d1)*math.sqrt(T)
def call_theta(S,K,T,sigma,r=.0,q=.0):
	if T<=.0 or sigma<=.0:return .0
	d1,d2=_d1_d2(S,K,T,sigma,r,q)
	if d1 is None:return .0
	term1=-S*_norm_pdf(d1)*sigma*math.exp(-q*T)/(2.*math.sqrt(T));term2=-r*K*math.exp(-r*T)*_norm_cdf(d2);term3=q*S*math.exp(-q*T)*_norm_cdf(d1);return term1+term2+term3
def put_price(S,K,T,sigma,r=.0,q=.0):c=call_price(S,K,T,sigma,r,q);return c-S*math.exp(-q*T)+K*math.exp(-r*T)
def put_delta(S,K,T,sigma,r=.0,q=.0):return call_delta(S,K,T,sigma,r,q)-math.exp(-q*T)
def call_implied_vol(target_price,S,K,T,r=.0,q=.0,*,sigma_init=.02,tol=1e-05,max_iter=30,sigma_min=1e-05,sigma_max=5.):
	import math
	if T<=.0 or S<=.0 or K<=.0:return
	lower_bound=max(S*math.exp(-q*T)-K*math.exp(-r*T),.0);upper_bound=S*math.exp(-q*T)
	if target_price<lower_bound-1e-06 or target_price>upper_bound+1e-06:return
	sigma=sigma_init
	for _ in range(max_iter):
		price=call_price(S,K,T,sigma,r,q);diff=price-target_price
		if abs(diff)<tol:return sigma
		vega=call_vega(S,K,T,sigma,r,q)
		if vega<1e-10:break
		sigma-=diff/vega
		if sigma<sigma_min or sigma>sigma_max:break
	lo,hi=sigma_min,sigma_max;p_lo=call_price(S,K,T,lo,r,q);p_hi=call_price(S,K,T,hi,r,q)
	if p_lo>target_price or p_hi<target_price:return
	for _ in range(max_iter*2):
		mid=.5*(lo+hi);p_mid=call_price(S,K,T,mid,r,q)
		if abs(p_mid-target_price)<tol:return mid
		if p_mid<target_price:lo=mid
		else:hi=mid
	return .5*(lo+hi)
def put_implied_vol(target_price,S,K,T,r=.0,q=.0,**kwargs):import math;call_target=target_price+S*math.exp(-q*T)-K*math.exp(-r*T);return call_implied_vol(call_target,S,K,T,r,q,**kwargs)
def _solve_normal_eqs(X_cols,y):
	n=len(y);d=len(X_cols)
	if n<d:return
	XtX=[[.0]*d for _ in range(d)];Xty=[.0]*d
	for i in range(d):
		for j in range(d):
			s=.0
			for k in range(n):s+=X_cols[i][k]*X_cols[j][k]
			XtX[i][j]=s
		s=.0
		for k in range(n):s+=X_cols[i][k]*y[k]
		Xty[i]=s
	M=[row[:]+[Xty[i]]for(i,row)in enumerate(XtX)]
	for i in range(d):
		max_row=i
		for r in range(i+1,d):
			if abs(M[r][i])>abs(M[max_row][i]):max_row=r
		M[i],M[max_row]=M[max_row],M[i]
		if abs(M[i][i])<1e-12:return
		pivot=M[i][i]
		for c in range(d+1):M[i][c]/=pivot
		for r in range(d):
			if r!=i:
				factor=M[r][i]
				for c in range(d+1):M[r][c]-=factor*M[i][c]
	return[M[i][d]for i in range(d)]
def fit_smile_poly(strikes,vols,S,T,r=.0,q=.0,*,degree=2,min_points=3):
	F=S*math.exp((r-q)*T);ms=[];sigs=[]
	for(K,v)in zip(strikes,vols):
		if v is None or v<=.0 or K<=.0:continue
		ms.append(math.log(K/F));sigs.append(float(v))
	if len(ms)<max(min_points,degree+1):return
	cols=[]
	for d in range(degree+1):cols.append([m**d for m in ms])
	return _solve_normal_eqs(cols,sigs)
def smile_predict(K,coeffs,S,T,r=.0,q=.0):
	F=S*math.exp((r-q)*T);m=math.log(K/F);sig=.0
	for(i,a)in enumerate(coeffs):sig+=a*m**i
	return max(1e-05,sig)
def average_vol(vols):
	valid=[v for v in vols if v is not None and v>.0]
	if not valid:return
	return sum(valid)/len(valid)
DEFAULT_VEV_STRIKES=[4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]
class _VelvetOptionMixin:
	def _shared(self,memory):
		shared=memory.get('_shared')
		if not isinstance(shared,dict):shared={};memory['_shared']=shared
		return shared
	def _option_strike(self,symbol=None):
		raw=symbol or self.product
		if not raw.startswith('VEV_'):return
		try:return int(raw.replace('VEV_',''))
		except ValueError:return
	def _resolve_tte(self,state):params=self.params;tte0=resolve_initial_tte_days(state.traderData,float(params.get('tte_days_initial',5.)),params.get('historical_tte_by_day'));ts_per_day=timestamp_units_per_day_from_params(params);T=time_to_expiry_days(int(state.timestamp),tte0,timestamp_units_per_day=ts_per_day);return tte0,max(.01,T)
	def _resolve_spot(self,state,memory,ts):
		shared=self._shared(memory)
		if shared.get('velvet_spot_ts')==ts:return shared.get('velvet_spot')
		underlying=str(self.params.get('underlying_symbol','VELVETFRUIT_EXTRACT'));od=state.order_depths.get(underlying)
		if not od or not od.buy_orders or not od.sell_orders:return
		spot=.5*(max(od.buy_orders)+min(od.sell_orders));shared['velvet_spot_ts']=ts;shared['velvet_spot']=spot;return spot
	def _build_chain_snapshot(self,state,memory,S,T,ts):
		shared=self._shared(memory)
		if shared.get('vev_chain_ts')==ts:
			cached=shared.get('vev_chain')
			if isinstance(cached,dict):return cached
		prior=float(self.params.get('prior_vol',self.params.get('implied_vol_prior',.0125)));sigma_floor=float(self.params.get('sigma_floor',.005));sigma_cap=float(self.params.get('sigma_cap',.1));chain={}
		for(symbol,od)in state.order_depths.items():
			strike=self._option_strike(symbol)
			if strike is None or not od.buy_orders or not od.sell_orders:continue
			best_bid=max(od.buy_orders);best_ask=min(od.sell_orders);mid=.5*(best_bid+best_ask);iv=call_implied_vol(mid,S,float(strike),T,sigma_init=prior);iv_valid=float(iv)if iv is not None and sigma_floor<=iv<=sigma_cap else None;chain[strike]={'best_bid':float(best_bid),'best_ask':float(best_ask),'mid':float(mid),'iv':iv_valid}
		shared['vev_chain_ts']=ts;shared['vev_chain']=chain;shared['vev_chain_loo_ts']=None;shared['vev_chain_loo']={};return chain
	def _fit_leave_one_out_iv(self,memory,*,strike,chain,S,T,ts):
		shared=self._shared(memory)
		if shared.get('vev_chain_loo_ts')!=ts:shared['vev_chain_loo_ts']=ts;shared['vev_chain_loo']={}
		cache=shared.setdefault('vev_chain_loo',{})
		if strike in cache:return cache[strike]
		smile_degree=int(self.params.get('smile_degree',2));min_points=int(self.params.get('smile_min_points',4));prior=float(self.params.get('prior_vol',self.params.get('implied_vol_prior',.0125)));sigma_floor=float(self.params.get('sigma_floor',.005));sigma_cap=float(self.params.get('sigma_cap',.1));strikes=[];vols=[]
		for(other_strike,row)in chain.items():
			if other_strike==strike:continue
			iv=row.get('iv')
			if iv is None:continue
			strikes.append(float(other_strike));vols.append(float(iv))
		fair_iv=None
		if len(strikes)>=max(min_points,smile_degree+1):
			coeffs=fit_smile_poly(strikes,vols,S,T,degree=smile_degree,min_points=min_points)
			if coeffs is not None:fair_iv=smile_predict(float(strike),coeffs,S,T)
		if fair_iv is None:own_iv=chain.get(strike,{}).get('iv');fair_iv=float(own_iv)if own_iv is not None else prior
		fair_iv=max(sigma_floor,min(sigma_cap,float(fair_iv)));cache[strike]=fair_iv;return fair_iv
	def _active_rank(self,*,strike,chain,S):
		if strike not in chain:return False,0,None
		ordered=sorted(chain.keys(),key=lambda k:(abs(k-S),k));reference=float(self.params.get('active_reference_spot',525e1));expand_every=float(self.params.get('active_expand_every',12e1));base_count=int(self.params.get('active_base_count',4));max_extra=int(self.params.get('active_max_extra_count',2))
		if expand_every>0:extra=min(max_extra,int(abs(S-reference)//expand_every))
		else:extra=max_extra
		active_count=min(len(ordered),max(0,base_count+extra));rank=ordered.index(strike)+1;return rank<=active_count,active_count,rank
class GammaScalpZGatedStrategy(_VelvetOptionMixin,BaseStrategy):
	def compute_orders(self,state,book,order_depth,position,memory):
		if book.best_bid is None or book.best_ask is None:return[],0
		p=self._read_params(state);ts=int(state.timestamp);S=self._resolve_spot(state,memory,ts)
		if S is None:return[],0
		z=self._update_zscore(S,memory,p);fair=call_price(S,p['K'],p['T'],p['implied_vol_prior']);gamma=call_gamma(S,p['K'],p['T'],p['implied_vol_prior']);delta=call_delta(S,p['K'],p['T'],p['implied_vol_prior']);memory['_velvet_z']=z;memory['_gamma']=gamma;memory['_delta']=delta;memory['_fair_iv']=fair;memory['_spot']=S;memory['_T']=p['T']
		if fair<p['min_quote_price']:return[],0
		orders=[];buy_cap=self.buy_capacity(position);sell_cap=self.sell_capacity(position)
		if p['T']<p['unwind_tte_threshold']or position>=p['target_qty']:
			if sell_cap>0 and position>0:
				ask_px=book.best_ask-1
				if ask_px<=book.best_bid:ask_px=book.best_bid+1
				qty=min(p['passive_bid_size'],sell_cap,position)
				if qty>0:orders.append(Order(self.product,ask_px,-qty))
			memory['_mode']='unwind';return orders,0
		if p['sell_when_very_expensive']and z is not None and z>p['zscore_sell_threshold']and position>0 and sell_cap>0:
			ask_px=book.best_ask-1
			if ask_px<=book.best_bid:ask_px=book.best_bid+1
			sell_qty=max(1,int(round(position*p['sell_size_pct'])));qty=min(sell_qty,sell_cap,position,p['passive_bid_size'])
			if qty>0:orders.append(Order(self.product,ask_px,-qty))
			memory['_mode']='z_profit_take';return orders,0
		if p['skip_when_expensive']and z is not None and z>p['zscore_skip_threshold']:memory['_mode']='z_skipped_expensive';return orders,0
		size_mult=1.;memory['_mode']='accumulate'
		if p['boost_when_cheap']and z is not None and z<-p['zscore_boost_threshold']:size_mult=p['entry_size_boost'];memory['_mode']='z_boost_cheap'
		eff_entry_size=max(1,int(round(p['entry_size']*size_mult)));eff_passive_size=max(1,int(round(p['passive_bid_size']*size_mult)))
		if buy_cap>0 and position<p['target_qty']:
			ask=book.best_ask
			if ask is not None and ask<=fair+p['edge_ticks']:
				ask_qty=-order_depth.sell_orders.get(ask,0);headroom=p['target_qty']-position;take_qty=min(ask_qty,buy_cap,eff_entry_size,headroom)
				if take_qty>0:orders.append(Order(self.product,ask,take_qty));buy_cap-=take_qty;position+=take_qty
		if buy_cap>0 and position<p['target_qty']:
			bid_px=book.best_bid+1
			if bid_px<book.best_ask:
				qty=min(eff_passive_size,buy_cap,p['target_qty']-position)
				if qty>0:orders.append(Order(self.product,bid_px,qty))
		return orders,0
	def _update_zscore(self,S,memory,params):
		window=params['zscore_window'];buf=memory.setdefault('_velvet_buf',[]);buf.append(S)
		if len(buf)>window:buf[:]=buf[-window:]
		if len(buf)<max(3,window//4):return
		mean=sum(buf)/len(buf);var=sum((x-mean)**2 for x in buf)/max(len(buf)-1,1);std=math.sqrt(var)
		if std<1e-09:return
		return(S-mean)/std
	def _read_params(self,state):_,T=self._resolve_tte(state);params=self.params;return{'K':float(params['strike']),'T':T,'implied_vol_prior':float(params.get('implied_vol_prior',.0125)),'edge_ticks':float(params.get('edge_ticks',.0)),'target_qty':int(params.get('target_qty',100)),'entry_size':int(params.get('entry_size',10)),'passive_bid_size':int(params.get('passive_bid_size',10)),'unwind_tte_threshold':float(params.get('unwind_tte_threshold',1.5)),'min_quote_price':float(params.get('min_quote_price',2.)),'zscore_window':int(params.get('zscore_window',500)),'zscore_skip_threshold':float(params.get('zscore_skip_threshold',1.)),'zscore_boost_threshold':float(params.get('zscore_boost_threshold',1.)),'skip_when_expensive':bool(params.get('skip_when_expensive',True)),'boost_when_cheap':bool(params.get('boost_when_cheap',False)),'entry_size_boost':float(params.get('entry_size_boost',1.5)),'sell_when_very_expensive':bool(params.get('sell_when_very_expensive',False)),'zscore_sell_threshold':float(params.get('zscore_sell_threshold',1.5)),'sell_size_pct':float(params.get('sell_size_pct',.1))}
	def feature_prices(self,memory):
		out={}
		if(gamma:=memory.get('_gamma'))is not None:out['gamma']=float(gamma)
		if(delta:=memory.get('_delta'))is not None:out['delta']=float(delta)
		if(fair:=memory.get('_fair_iv'))is not None:out['fair_iv']=float(fair)
		if(z:=memory.get('_velvet_z'))is not None:out['velvet_z']=float(z)
		if(mode:=memory.get('_mode'))is not None:out['mode']={'accumulate':1.,'unwind':.0,'z_skipped_expensive':-1.,'z_boost_cheap':2.,'z_profit_take':.5}.get(str(mode),.5)
		return out
class SmileIVScalperStrategy(_VelvetOptionMixin,BaseStrategy):
	def compute_orders(self,state,book,order_depth,position,memory):
		if book.best_bid is None or book.best_ask is None:return[],0
		strike=self._option_strike()
		if strike is None:return[],0
		ts=int(state.timestamp);_,T=self._resolve_tte(state);S=self._resolve_spot(state,memory,ts)
		if S is None:return[],0
		chain=self._build_chain_snapshot(state,memory,S,T,ts);row=chain.get(strike);market_iv=None if row is None else row.get('iv')
		if row is None or market_iv is None:return[],0
		fair_iv=self._fit_leave_one_out_iv(memory,strike=strike,chain=chain,S=S,T=T,ts=ts)
		if fair_iv is None:return[],0
		active,active_count,active_rank=self._active_rank(strike=strike,chain=chain,S=S);residual=float(market_iv)-float(fair_iv);baseline_mean,baseline_std,resid_z,obs=self._residual_signal(memory,residual);reference_iv=self._clamp_sigma(float(fair_iv)+baseline_mean);reference_px=call_price(S,float(strike),T,reference_iv);orders=[];buy_cap=self.buy_capacity(position);sell_cap=self.sell_capacity(position);soft_limit=int(self.params.get('soft_position_limit',60));take_size=int(self.params.get('take_size',6));maker_size=max(0,int(self.params.get('maker_size',4)));maker_edge=float(self.params.get('maker_edge',1.5));take_edge=float(self.params.get('take_price_edge',2.));reduce_edge=float(self.params.get('reduce_price_edge',1.));take_z=float(self.params.get('take_zscore',.9));reduce_z=float(self.params.get('reduce_zscore',.6));cheap_reset_z=float(self.params.get('cheap_reset_z',.35));inventory_skew=float(self.params.get('inventory_skew',4.));min_quote_price=float(self.params.get('min_quote_price',1.));warmup_ticks=int(self.params.get('resid_warmup_ticks',60));maker_join=bool(self.params.get('maker_join_best',True));inactive_unwind_bias=int(self.params.get('inactive_unwind_bias',1));entry_position_cap=int(self.params.get('entry_position_cap',0));take_cooldown_ts=int(self.params.get('take_cooldown_ts',0));headroom=max(0,soft_limit-position);edge_buy=reference_px-book.best_ask;edge_sell=book.best_bid-reference_px;warmed=obs>=warmup_ticks
		if resid_z>=-cheap_reset_z:memory['_cheap_regime']=False
		last_take_ts=memory.get('_last_take_ts');cooled=last_take_ts is None or take_cooldown_ts<=0 or ts-int(last_take_ts)>=take_cooldown_ts;cheap_cross=resid_z<=-take_z and not bool(memory.get('_cheap_regime',False))
		if active and warmed and reference_px>=min_quote_price and buy_cap>0 and headroom>0 and position<=entry_position_cap:
			if edge_buy>=take_edge and cheap_cross and cooled:
				scale=1+int(edge_buy//max(take_edge,1.));qty=min(take_size*scale,buy_cap,headroom,max(1,book.best_ask_volume))
				if qty>0:orders.append(Order(self.product,book.best_ask,qty));position+=qty;buy_cap-=qty;sell_cap=self.sell_capacity(position);headroom=max(0,soft_limit-position);memory['_cheap_regime']=True;memory['_last_take_ts']=ts
		if position>0 and sell_cap>0:
			should_reduce=edge_sell>=reduce_edge or resid_z>=reduce_z
			if not active and book.best_bid>=max(1,int(round(reference_px))-inactive_unwind_bias):should_reduce=True
			if should_reduce:
				qty=min(position,sell_cap,max(1,book.best_bid_volume),take_size)
				if qty>0:orders.append(Order(self.product,book.best_bid,-qty));position-=qty;sell_cap-=qty;buy_cap=self.buy_capacity(position);headroom=max(0,soft_limit-position)
		bid_px=None;ask_px=None
		if active and warmed and maker_size>0 and reference_px>=min_quote_price and buy_cap>0 and headroom>0:
			raw_bid=int(round(reference_px-maker_edge-inventory_skew*max(position,0)/max(soft_limit,1)));join_bid=book.best_bid+(1 if maker_join and(book.spread or 0)>=2 else 0);bid_px=max(1,min(book.best_ask-1,max(join_bid,raw_bid)))
			if bid_px<book.best_ask:
				qty=min(maker_size,buy_cap,headroom)
				if qty>0:orders.append(Order(self.product,bid_px,qty))
		if position>0 and sell_cap>0 and maker_size>0:
			raw_ask=int(round(reference_px+maker_edge-inventory_skew*position/max(soft_limit,1)))
			if active:join_ask=book.best_ask-(1 if maker_join and(book.spread or 0)>=2 else 0);ask_px=max(book.best_bid+1,min(join_ask,raw_ask))
			else:ask_px=max(book.best_bid+1,min(book.best_ask-inactive_unwind_bias,raw_ask))
			if ask_px>book.best_bid:
				qty=min(maker_size,sell_cap,position)
				if qty>0:orders.append(Order(self.product,ask_px,-qty))
		self._update_residual_baseline(memory,residual);memory['_fair_iv_smile']=fair_iv;memory['_residual_iv']=residual;memory['_residual_z']=resid_z;memory['_residual_mean']=baseline_mean;memory['_residual_std']=baseline_std;memory['_reference_iv']=reference_iv;memory['_reference_px']=reference_px;memory['_active_rank']=float(active_rank or 0);memory['_active_count']=float(active_count);memory['_active_flag']=1. if active else .0;return orders,0
	def _clamp_sigma(self,sigma):floor=float(self.params.get('sigma_floor',.005));cap=float(self.params.get('sigma_cap',.1));return max(floor,min(cap,sigma))
	def _residual_signal(self,memory,residual):
		mean_prev=memory.get('_resid_mean_ewma')
		if mean_prev is None:init_std=float(self.params.get('resid_std_init',.0015));return float(residual),max(init_std,1e-06),.0,0
		var_prev=float(memory.get('_resid_var_ewma',float(self.params.get('resid_std_init',.0015))**2));std_prev=max(float(self.params.get('resid_std_floor',.0005)),math.sqrt(max(var_prev,.0)));resid_z=(residual-float(mean_prev))/std_prev;return float(mean_prev),std_prev,resid_z,int(memory.get('_resid_obs',0))
	def _update_residual_baseline(self,memory,residual):
		alpha=float(self.params.get('resid_ewma_alpha',.03))
		if'_resid_mean_ewma'not in memory:memory['_resid_mean_ewma']=float(residual);memory['_resid_var_ewma']=float(self.params.get('resid_std_init',.0015))**2;memory['_resid_obs']=1;return
		mean_prev=float(memory['_resid_mean_ewma']);var_prev=float(memory.get('_resid_var_ewma',float(self.params.get('resid_std_init',.0015))**2));delta=residual-mean_prev;mean_new=mean_prev+alpha*delta;var_new=(1.-alpha)*var_prev+alpha*delta**2;memory['_resid_mean_ewma']=mean_new;memory['_resid_var_ewma']=max(var_new,float(self.params.get('resid_std_floor',.0005))**2);memory['_resid_obs']=int(memory.get('_resid_obs',0))+1
	def feature_prices(self,memory):
		out={}
		if(fair_iv:=memory.get('_fair_iv_smile'))is not None:out['smile_fair_iv_pct']=float(fair_iv)*1e2
		if(reference_iv:=memory.get('_reference_iv'))is not None:out['reference_iv_pct']=float(reference_iv)*1e2
		if(reference_px:=memory.get('_reference_px'))is not None:out['reference_px']=float(reference_px)
		if(residual:=memory.get('_residual_iv'))is not None:out['iv_resid_bps']=float(residual)*1e4
		if(resid_z:=memory.get('_residual_z'))is not None:out['iv_resid_z']=float(resid_z)
		if(active:=memory.get('_active_flag'))is not None:out['active']=float(active)
		if(active_rank:=memory.get('_active_rank'))is not None:out['active_rank']=float(active_rank)
		return out
class MMFirstV4ComboStrategy(BaseStrategy):
	def _compute_quote_prices(self,book,inventory_ratio,mid_smooth):bid_price=book.best_bid+1 if book.best_bid is not None else None;ask_price=book.best_ask-1 if book.best_ask is not None else None;return bid_price,ask_price,'L1'
	def _compute_zscore(self,mid,memory):
		window=int(self.params.get('zscore_window',50));buf=memory.setdefault('_zscore_buf',[]);buf.append(mid)
		if len(buf)>window:buf[:]=buf[-window:]
		if len(buf)<max(3,window//4):memory['zscore']=None;return
		n=len(buf);mean=sum(buf)/n;var=sum((x-mean)**2 for x in buf)/max(n-1,1);std=var**.5
		if std<1e-09:memory['zscore']=None;return
		z=(mid-mean)/std;memory['zscore']=z;memory['_zs_mean']=mean;memory['_zs_std']=std;return z
	def _zscore_size_factors(self,memory):
		z=memory.get('zscore')
		if z is None:return 1.,1.
		threshold=float(self.params.get('zscore_threshold',1.));size_scale=float(self.params.get('zscore_size_scale',.5));max_scale=float(self.params.get('zscore_max_scale',3.));excess=max(.0,abs(z)-threshold);scale=min(max_scale,1.+size_scale*excess)
		if z>threshold:return 1./scale,scale
		if z<-threshold:return scale,1./scale
		return 1.,1.
	def _compute_sizes(self,position,limit):base=float(self.params.get('maker_size_base_pct',.2))*limit;bid_size=base*(1.-position/limit);ask_size=base*(1.+position/limit);return bid_size,ask_size
	def _dynamic_take_edge(self,memory):
		lo=self.params.get('take_edge_lo');hi=self.params.get('take_edge_hi')
		if lo is None or hi is None:return float(self.params.get('take_edge',1.))
		sigma=memory.get('sigma_smoothed')
		if sigma is None:return float(lo)
		vol_lo=float(self.params.get('take_edge_vol_lo',2.));vol_hi=float(self.params.get('take_edge_vol_hi',5.))
		if sigma<=vol_lo:return float(lo)
		if sigma>=vol_hi:return float(hi)
		t=(sigma-vol_lo)/(vol_hi-vol_lo);return float(lo)+t*(float(hi)-float(lo))
	def _compute_anchor_signal(self,mid,book,mid_smooth,memory):
		anchor_price=self.params.get('anchor_price')
		if anchor_price is None:return mid_smooth
		anchor_fixed=float(anchor_price);anchor_alpha=float(self.params.get('anchor_alpha',.0))
		if anchor_alpha>.0:
			ema=memory.get('_anchor_ema',anchor_fixed);ema=anchor_alpha*mid+(1.-anchor_alpha)*ema;drift_bound=float(self.params.get('anchor_drift_bound',.0))
			if drift_bound>0:ema=max(anchor_fixed-drift_bound,min(anchor_fixed+drift_bound,ema))
			memory['_anchor_ema']=ema;anchor_value=ema
		else:anchor_value=anchor_fixed
		ar_gain=float(self.params.get('ar_gain',.0));ar_shift=.0
		if ar_gain>.0:
			source=str(self.params.get('ar_shift_source','mid'))
			if source=='microprice':current=self._microprice(book)
			elif source=='mid_smooth':current=mid_smooth
			else:current=mid
			prev=memory.get('_ar_prev_signal')
			if prev is not None:ar_shift=-ar_gain*(current-prev)
			memory['_ar_prev_signal']=current
		return anchor_value+ar_shift
	def _compute_asym_take_edges(self,base_edge,position,memory):
		unwind=float(self.params.get('unwind_take_edge',.0))
		if unwind<=0:return base_edge,base_edge
		limit=self.position_limit();pressure=abs(position)/max(1.,float(limit))
		if position>0:sell_edge=max(.0,base_edge-unwind*pressure);buy_edge=base_edge+unwind*pressure
		elif position<0:buy_edge=max(.0,base_edge-unwind*pressure);sell_edge=base_edge+unwind*pressure
		else:return base_edge,base_edge
		return buy_edge,sell_edge
	def _fire_takers(self,order_depth,fair_value,bid_size,ask_size,buy_cap,sell_cap,buy_edge,sell_edge):
		taker_buy_threshold=self.params.get('taker_buy_threshold');taker_sell_threshold=self.params.get('taker_sell_threshold');orders=[];taker_buy_px=set();taker_sell_px=set()
		for ask_p in sorted(order_depth.sell_orders):
			available=-order_depth.sell_orders[ask_p];mid_signal=ask_p<=fair_value-buy_edge;abs_signal=taker_buy_threshold is not None and ask_p<=taker_buy_threshold
			if not(mid_signal or abs_signal)or buy_cap<=0:break
			qty=min(available,buy_cap,int(bid_size*.3))
			if qty>0:orders.append(Order(self.product,ask_p,qty));taker_buy_px.add(ask_p);buy_cap-=qty
		for bid_p in sorted(order_depth.buy_orders,reverse=True):
			volume=order_depth.buy_orders[bid_p];mid_signal=bid_p>=fair_value+sell_edge;abs_signal=taker_sell_threshold is not None and bid_p>=taker_sell_threshold
			if not(mid_signal or abs_signal)or sell_cap<=0:break
			qty=min(volume,sell_cap,int(ask_size*.3))
			if qty>0:orders.append(Order(self.product,bid_p,-qty));taker_sell_px.add(bid_p);sell_cap-=qty
		return orders,buy_cap,sell_cap,taker_buy_px,taker_sell_px
	def _gap_exploit(self,order_depth,memory,limit,bid_size,ask_size,bid_price,ask_price,buy_cap,sell_cap,taker_buy_px,taker_sell_px):
		gap_min=float(self.params.get('gap_trigger_min',10));shift=float(self.params.get('OB_cleared_shift',10));gap_vol_pct=float(self.params.get('gap_trigger_max_vol_pct',.1));gap_max_vol=int(gap_vol_pct*limit)if limit else 0;gap_confirm=int(self.params.get('gap_trigger_confirm_ticks',1));z=memory.get('zscore');gap_gate=float(self.params.get('zscore_gap_gate',self.params.get('zscore_threshold',1.)));bid_z_ok=z is None or z>=-gap_gate;ask_z_ok=z is None or z<=gap_gate;orders=[];memory['_gap_buy_px']=[];memory['_gap_sell_px']=[];all_bids=sorted(order_depth.buy_orders.keys(),reverse=True);all_asks=sorted(order_depth.sell_orders.keys())
		if all_bids:memory['_last_best_bid']=all_bids[0]
		if all_asks:memory['_last_best_ask']=all_asks[0]
		last_best_bid=memory.get('_last_best_bid');last_best_ask=memory.get('_last_best_ask');remaining_bids=[p for p in all_bids if p not in taker_sell_px];remaining_asks=[p for p in all_asks if p not in taker_buy_px];gap_swept_bids=set();gap_swept_asks=set()
		if gap_min>0 and gap_max_vol>0:
			bid_gap_ok=False;bid1=bid2=bid1_vol=None
			if len(remaining_bids)>=2:bid1,bid2=remaining_bids[0],remaining_bids[1];bid1_vol=order_depth.buy_orders[bid1];bid_gap_ok=bid1-bid2>=gap_min and bid1_vol<=gap_max_vol
			bid_streak=memory.get('_gap_bid_streak',0);bid_streak=bid_streak+1 if bid_gap_ok else 0;memory['_gap_bid_streak']=bid_streak
			if bid_streak>=gap_confirm and bid_gap_ok and sell_cap>0 and bid_z_ok:
				qty=min(bid1_vol,sell_cap,int(ask_size))
				if qty>0:
					orders.append(Order(self.product,bid1,-qty));sell_cap-=qty;memory['_gap_sell_px'].append(bid1)
					if qty>=bid1_vol:gap_swept_bids.add(bid1)
			ask_gap_ok=False;ask1=ask2=ask1_vol=None
			if len(remaining_asks)>=2:ask1,ask2=remaining_asks[0],remaining_asks[1];ask1_vol=-order_depth.sell_orders[ask1];ask_gap_ok=ask2-ask1>=gap_min and ask1_vol<=gap_max_vol
			ask_streak=memory.get('_gap_ask_streak',0);ask_streak=ask_streak+1 if ask_gap_ok else 0;memory['_gap_ask_streak']=ask_streak
			if ask_streak>=gap_confirm and ask_gap_ok and buy_cap>0 and ask_z_ok:
				qty=min(ask1_vol,buy_cap,int(bid_size))
				if qty>0:
					orders.append(Order(self.product,ask1,qty));buy_cap-=qty;memory['_gap_buy_px'].append(ask1)
					if qty>=ask1_vol:gap_swept_asks.add(ask1)
		final_remaining_bids=[p for p in remaining_bids if p not in gap_swept_bids];final_remaining_asks=[p for p in remaining_asks if p not in gap_swept_asks]
		if final_remaining_asks:ask_price=final_remaining_asks[0]-1
		elif last_best_ask is not None:ask_price=last_best_ask+int(shift)
		if final_remaining_bids:bid_price=final_remaining_bids[0]+1
		elif last_best_bid is not None:bid_price=last_best_bid-int(shift)
		return orders,buy_cap,sell_cap,bid_price,ask_price
	def _apply_toxic_flow(self,state,memory,buy_size,sell_size):
		toxic_threshold=float(self.params.get('toxic_threshold',.0))
		if toxic_threshold<=0:return buy_size,sell_size
		toxic_window=int(self.params.get('toxic_window',6));toxic_size_frac=float(self.params.get('toxic_size_frac',.75));flow_history=memory.setdefault('_flow_history',[]);prev_best_bid=memory.get('_prev_best_bid');prev_best_ask=memory.get('_prev_best_ask');trades=state.market_trades.get(self.product,[])
		if toxic_window>0 and prev_best_bid is not None and prev_best_ask is not None:
			for trade in trades:
				if trade.price>=prev_best_ask:flow_history.append(trade.quantity)
				elif trade.price<=prev_best_bid:flow_history.append(-trade.quantity)
			if len(flow_history)>toxic_window:del flow_history[:-toxic_window]
		flow_score=.0
		if flow_history:
			signed=sum(flow_history);total=sum(abs(x)for x in flow_history)
			if total>0:flow_score=signed/total
		memory['_flow_score']=flow_score
		if flow_score>toxic_threshold and sell_size>0:sell_size=max(1.,sell_size*toxic_size_frac)
		elif flow_score<-toxic_threshold and buy_size>0:buy_size=max(1.,buy_size*toxic_size_frac)
		return buy_size,sell_size
	def _apply_jump_filter(self,book,memory,buy_size,sell_size):
		threshold=float(self.params.get('trend_jump_threshold',.0))
		if threshold<=0:return buy_size,sell_size
		jump_size_frac=float(self.params.get('jump_size_frac',.5));prev_best_bid=memory.get('_prev_best_bid');prev_best_ask=memory.get('_prev_best_ask');bid_jumped=prev_best_bid is not None and book.best_bid==prev_best_bid+1;ask_jumped=prev_best_ask is not None and book.best_ask==prev_best_ask-1
		if bid_jumped and sell_size>0:sell_size=max(1.,sell_size*jump_size_frac)
		if ask_jumped and buy_size>0:buy_size=max(1.,buy_size*jump_size_frac)
		return buy_size,sell_size
	def _compute_base_mid(self,raw_mid,book):
		vol_filter=int(self.params.get('mid_vol_filter',0))
		if vol_filter<=0:return raw_mid
		wall_bid=None
		for(p,v)in book.bid_levels:
			if v>=vol_filter:wall_bid=p;break
		wall_ask=None
		for(p,v)in book.ask_levels:
			if v>=vol_filter:wall_ask=p;break
		if wall_bid is None or wall_ask is None:return raw_mid
		return(wall_bid+wall_ask)/2.
	def _taker_cooldown_active(self,state,memory):
		cooldown=int(self.params.get('taker_cooldown_ticks',0))
		if cooldown<=0:return False,False
		now=int(state.timestamp);ts_increment=int(self.params.get('ts_increment',100));last_buy=memory.get('_last_taker_buy_ts');last_sell=memory.get('_last_taker_sell_ts');buy_blocked=last_buy is not None and now-last_buy<cooldown*ts_increment;sell_blocked=last_sell is not None and now-last_sell<cooldown*ts_increment;return buy_blocked,sell_blocked
	def _update_taker_cooldown(self,state,memory,taker_buy_px,taker_sell_px):
		now=int(state.timestamp)
		if taker_buy_px:memory['_last_taker_buy_ts']=now
		if taker_sell_px:memory['_last_taker_sell_ts']=now
	def _apply_inventory_bias(self,fair_value,position,memory):
		gamma=float(self.params.get('inventory_aversion_gamma',.0))
		if gamma<=0 or position==0:return fair_value
		sigma=memory.get('sigma_smoothed',1.);return fair_value-gamma*position*sigma**2
	def _microprice_size_tilt(self,book,raw_mid,bid_size,ask_size):
		gain=float(self.params.get('microprice_size_gain',.0))
		if gain<=0:return bid_size,ask_size
		threshold=float(self.params.get('microprice_size_threshold',.2));micro=self._microprice(book);delta=micro-raw_mid
		if abs(delta)<threshold:return bid_size,ask_size
		scale=1.+gain*(abs(delta)-threshold)
		if delta>0:return bid_size/scale,ask_size*scale
		else:return bid_size*scale,ask_size/scale
	def _apply_spread_widening(self,bid_price,ask_price,book,memory):
		threshold=float(self.params.get('spread_widen_vol_threshold',.0))
		if threshold<=0 or bid_price is None or ask_price is None:return bid_price,ask_price
		if book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		sigma=memory.get('sigma_smoothed',.0)
		if sigma<threshold:return bid_price,ask_price
		extra=int(self.params.get('spread_widen_extra_ticks',1));new_bid=max(1,bid_price-extra);new_ask=ask_price+extra
		if book.best_ask is not None:new_bid=min(new_bid,book.best_ask-1)
		if book.best_bid is not None:new_ask=max(new_ask,book.best_bid+1)
		return new_bid,new_ask
	def _effective_position(self,position):target=int(self.params.get('inventory_target',0));return position-target
	def _apply_fill_rate_toxicity(self,state,memory,bid_size,ask_size):
		window=int(self.params.get('fill_toxicity_window',0))
		if window<=0:return bid_size,ask_size
		history=memory.setdefault('_fill_history',[])
		for trade in state.own_trades.get(self.product,[]):
			qty=float(trade.quantity)
			if trade.buyer=='SUBMISSION':history.append(qty)
			elif trade.seller=='SUBMISSION':history.append(-qty)
		if len(history)>window:del history[:-window]
		if not history:return bid_size,ask_size
		signed=sum(history);total=sum(abs(x)for x in history)
		if total<=0:return bid_size,ask_size
		imbalance=signed/total;threshold=float(self.params.get('fill_toxicity_threshold',.7));frac=float(self.params.get('fill_toxicity_frac',.5))
		if imbalance>threshold and bid_size>0:bid_size=max(1.,bid_size*frac)
		elif imbalance<-threshold and ask_size>0:ask_size=max(1.,ask_size*frac)
		return bid_size,ask_size
	def _apply_spread_zscore_skew(self,bid_price,ask_price,book,memory):
		window=int(self.params.get('spread_zscore_window',0))
		if window<=0 or bid_price is None or ask_price is None:return bid_price,ask_price
		if book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		spread=book.best_ask-book.best_bid;buf=memory.setdefault('_spread_buf',[]);buf.append(spread)
		if len(buf)>window:del buf[:-window]
		if len(buf)<max(10,window//4):return bid_price,ask_price
		mean=sum(buf)/len(buf);var=sum((x-mean)**2 for x in buf)/max(len(buf)-1,1);std=var**.5
		if std<1e-09:return bid_price,ask_price
		z=(spread-mean)/std;threshold=float(self.params.get('spread_zscore_threshold',1.5))
		if z<threshold:return bid_price,ask_price
		shift=int(self.params.get('spread_zscore_shift',1));new_bid=min(book.best_ask-1,bid_price+shift);new_ask=max(book.best_bid+1,ask_price-shift)
		if new_bid>=new_ask:new_ask=new_bid+1
		return new_bid,new_ask
	def _probe_tick0(self,book,state,memory,buy_cap,sell_cap):
		distances=self.params.get('probe_t0_distances')
		if not distances or book.best_bid is None or book.best_ask is None:return[],buy_cap,sell_cap
		max_ts=int(self.params.get('probe_t0_max_ts',500));now=int(state.timestamp)
		if now>max_ts:return[],buy_cap,sell_cap
		if memory.get('_probe_t0_fired',False):return[],buy_cap,sell_cap
		qty=int(self.params.get('probe_t0_qty',1));orders=[]
		for dist in distances:
			d=int(dist)
			if d<=0:continue
			b_qty=min(qty,buy_cap);a_qty=min(qty,sell_cap)
			if b_qty>0:orders.append(Order(self.product,book.best_bid-d,b_qty));buy_cap-=b_qty
			if a_qty>0:orders.append(Order(self.product,book.best_ask+d,-a_qty));sell_cap-=a_qty
		if orders:memory['_probe_t0_fired']=True
		return orders,buy_cap,sell_cap
	def _apply_momentum_follower(self,state,order_depth,memory,buy_cap,sell_cap):
		window=int(self.params.get('momentum_window',0))
		if window<=0:return[],buy_cap,sell_cap
		history=memory.setdefault('_momentum_history',[]);prev_bid=memory.get('_prev_best_bid');prev_ask=memory.get('_prev_best_ask')
		for trade in state.market_trades.get(self.product,[]):
			qty=float(trade.quantity)
			if prev_ask is not None and trade.price>=prev_ask:history.append(qty)
			elif prev_bid is not None and trade.price<=prev_bid:history.append(-qty)
		if len(history)>window:del history[:-window]
		if not history:return[],buy_cap,sell_cap
		signed=sum(history);total=sum(abs(x)for x in history)
		if total<=0:return[],buy_cap,sell_cap
		flow=signed/total;threshold=float(self.params.get('momentum_threshold',.8));qty=int(self.params.get('momentum_qty',3));orders=[]
		if flow>threshold and buy_cap>0:
			asks=sorted(order_depth.sell_orders.keys())
			if asks:
				ask_p=asks[0];available=-order_depth.sell_orders[ask_p];q=min(qty,buy_cap,available)
				if q>0:orders.append(Order(self.product,ask_p,q));buy_cap-=q
		elif flow<-threshold and sell_cap>0:
			bids=sorted(order_depth.buy_orders.keys(),reverse=True)
			if bids:
				bid_p=bids[0];volume=order_depth.buy_orders[bid_p];q=min(qty,sell_cap,volume)
				if q>0:orders.append(Order(self.product,bid_p,-q));sell_cap-=q
		return orders,buy_cap,sell_cap
	def _probe_quotes(self,book,state,memory,position,buy_cap,sell_cap):
		probe_dist=int(self.params.get('probe_distance',0))
		if probe_dist<=0 or book.best_bid is None or book.best_ask is None:return[],buy_cap,sell_cap
		probe_qty=int(self.params.get('probe_qty',1));probe_interval=int(self.params.get('probe_interval_ticks',100));ts_increment=int(self.params.get('ts_increment',100));now=int(state.timestamp);last_probe=memory.get('_last_probe_ts',-10**9)
		if now-last_probe<probe_interval*ts_increment:return[],buy_cap,sell_cap
		orders=[];actual_bid_qty=min(probe_qty,buy_cap);actual_ask_qty=min(probe_qty,sell_cap)
		if actual_bid_qty>0:probe_bid=book.best_bid-probe_dist;orders.append(Order(self.product,probe_bid,actual_bid_qty));buy_cap-=actual_bid_qty
		if actual_ask_qty>0:probe_ask=book.best_ask+probe_dist;orders.append(Order(self.product,probe_ask,-actual_ask_qty));sell_cap-=actual_ask_qty
		if orders:memory['_last_probe_ts']=now
		return orders,buy_cap,sell_cap
	def _asym_passive_skew(self,bid_price,ask_price,position,book):
		skew_max=int(self.params.get('passive_unwind_skew_ticks',0))
		if skew_max<=0 or bid_price is None or ask_price is None:return bid_price,ask_price
		if book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		trigger=float(self.params.get('passive_unwind_trigger',.3));limit=self.position_limit();pressure=abs(position)/max(1.,float(limit))
		if pressure<trigger:return bid_price,ask_price
		scaled=(pressure-trigger)/max(1e-09,1.-trigger);skew=int(round(skew_max*scaled))
		if skew<=0:return bid_price,ask_price
		if position>0:ask_price=max(book.best_bid+1,ask_price-skew)
		elif position<0:bid_price=min(book.best_ask-1,bid_price+skew)
		return bid_price,ask_price
	def _apply_eod_flatten(self,state,order_depth,position):
		eod_ts=int(self.params.get('eod_flatten_ts',0))
		if eod_ts<=0 or state.timestamp<eod_ts or position==0:return
		orders=[]
		if position>0:
			for bid_price in sorted(order_depth.buy_orders,reverse=True):
				vol=order_depth.buy_orders[bid_price];qty=min(vol,position)
				if qty<=0:break
				orders.append(Order(self.product,bid_price,-qty));position-=qty
				if position==0:break
		else:
			need=-position
			for ask_price in sorted(order_depth.sell_orders):
				vol=-order_depth.sell_orders[ask_price];qty=min(vol,need)
				if qty<=0:break
				orders.append(Order(self.product,ask_price,qty));need-=qty
				if need==0:break
		return orders
	def _passive_quotes(self,bid_price,ask_price,bid_size,ask_size,buy_cap,sell_cap,position,limit):
		quote_buy=min(buy_cap,int(bid_size));quote_sell=min(sell_cap,int(ask_size));inv_abs=abs(position)/float(limit)if limit else .0;hard_stop_thr=1.-float(self.params.get('pct_kept_for_takers',.2))
		if inv_abs>=hard_stop_thr:
			if position>0:quote_buy=0
			elif position<0:quote_sell=0
		orders=[]
		if quote_buy>0 and bid_price is not None:orders.append(Order(self.product,bid_price,quote_buy))
		if quote_sell>0 and ask_price is not None:orders.append(Order(self.product,ask_price,-quote_sell))
		return orders,buy_cap-quote_buy,sell_cap-quote_sell
	def _log_taker_fills(self,state,memory,this_taker_buy_px,this_taker_sell_px):
		prev_taker_buy_px=set(memory.get('_taker_buy_px',[]));prev_taker_sell_px=set(memory.get('_taker_sell_px',[]));prev_gap_buy_px=set(memory.get('_gap_buy_px_prev',[]));prev_gap_sell_px=set(memory.get('_gap_sell_px_prev',[]));memory['_taker_buy_px']=list(this_taker_buy_px);memory['_taker_sell_px']=list(this_taker_sell_px);memory['_gap_buy_px_prev']=list(memory.get('_gap_buy_px',[]));memory['_gap_sell_px_prev']=list(memory.get('_gap_sell_px',[]))
		for trade in state.own_trades.get(self.product,[]):
			if trade.buyer=='SUBMISSION':side,is_taker='BUY',trade.price in prev_taker_buy_px
			else:side,is_taker='SELL',trade.price in prev_taker_sell_px
			if is_taker:is_gap=side=='BUY'and trade.price in prev_gap_buy_px or side=='SELL'and trade.price in prev_gap_sell_px;self.log_taker_fill(state=state,memory=memory,side=side,price=trade.price,quantity=trade.quantity,gap_exploit=is_gap)
	def compute_orders(self,state,book,order_depth,position,memory):
		if order_depth.buy_orders and order_depth.sell_orders:
			eod_orders=self._apply_eod_flatten(state,order_depth,position)
			if eod_orders is not None:return eod_orders,0
		if book.best_bid is None and book.best_ask is None:
			if memory.get('_last_mid')is None:return[],0
		raw_mid=book.mid_price
		if raw_mid is None and book.best_bid is not None:raw_mid=float(book.best_bid)
		if raw_mid is None and book.best_ask is not None:raw_mid=float(book.best_ask)
		mid=raw_mid if raw_mid is not None else memory['_last_mid']
		if raw_mid is not None:memory['_last_mid']=raw_mid
		if self.params.get('use_microprice_as_fair',False):micro=self._microprice(book);base_mid=micro if micro else mid
		else:base_mid=self._compute_base_mid(mid,book)
		mid_smooth=self._smooth_mid(base_mid,memory);self._compute_zscore(base_mid,memory);sigma=self._update_volatility(base_mid,memory);fair_value=self._compute_anchor_signal(base_mid,book,mid_smooth,memory);eff_position=self._effective_position(position);fair_value=self._apply_inventory_bias(fair_value,eff_position,memory);limit=self.position_limit();inventory_ratio=position/float(limit)if limit else .0;bid_price,ask_price,_=self._compute_quote_prices(book,inventory_ratio,fair_value);buy_cap=self.buy_capacity(position);sell_cap=self.sell_capacity(position);bid_size,ask_size=self._compute_sizes(position,limit);bid_factor,ask_factor=self._zscore_size_factors(memory);bid_size=max(.0,bid_size*bid_factor);ask_size=max(.0,ask_size*ask_factor);bid_size,ask_size=self._microprice_size_tilt(book,mid,bid_size,ask_size);base_edge=self._dynamic_take_edge(memory);buy_edge,sell_edge=self._compute_asym_take_edges(base_edge,eff_position,memory);buy_blocked,sell_blocked=self._taker_cooldown_active(state,memory)
		if buy_blocked:buy_edge=1e6
		if sell_blocked:sell_edge=1e6
		taker_orders,buy_cap,sell_cap,taker_buy_px,taker_sell_px=self._fire_takers(order_depth,fair_value,bid_size,ask_size,buy_cap,sell_cap,buy_edge=buy_edge,sell_edge=sell_edge);self._update_taker_cooldown(state,memory,taker_buy_px,taker_sell_px);gap_orders,buy_cap,sell_cap,bid_price,ask_price=self._gap_exploit(order_depth,memory,limit,bid_size,ask_size,bid_price,ask_price,buy_cap,sell_cap,taker_buy_px,taker_sell_px);bid_price,ask_price=self._asym_passive_skew(bid_price,ask_price,eff_position,book);bid_price,ask_price=self._apply_spread_widening(bid_price,ask_price,book,memory);bid_price,ask_price=self._apply_spread_zscore_skew(bid_price,ask_price,book,memory);bid_size,ask_size=self._apply_toxic_flow(state,memory,bid_size,ask_size);bid_size,ask_size=self._apply_jump_filter(book,memory,bid_size,ask_size);bid_size,ask_size=self._apply_fill_rate_toxicity(state,memory,bid_size,ask_size);passive_orders,buy_cap,sell_cap=self._passive_quotes(bid_price,ask_price,bid_size,ask_size,buy_cap,sell_cap,position,limit);probe_orders,buy_cap,sell_cap=self._probe_quotes(book,state,memory,position,buy_cap,sell_cap);passive_orders.extend(probe_orders);probe_t0_orders,buy_cap,sell_cap=self._probe_tick0(book,state,memory,buy_cap,sell_cap);passive_orders.extend(probe_t0_orders);momentum_orders,buy_cap,sell_cap=self._apply_momentum_follower(state,order_depth,memory,buy_cap,sell_cap);taker_orders.extend(momentum_orders)
		if book.best_bid is not None:memory['_prev_best_bid']=book.best_bid
		if book.best_ask is not None:memory['_prev_best_ask']=book.best_ask
		self._log_taker_fills(state,memory,taker_buy_px,taker_sell_px);z=memory.get('zscore');self.log_quote_snapshot(state=state,memory=memory,bid_price=bid_price,ask_price=ask_price,extras={'position':position,'fair':round(fair_value,2),'buy_edge':round(buy_edge,2),'sell_edge':round(sell_edge,2),'bid_size':int(bid_size),'ask_size':int(ask_size),'zscore':round(z,4)if z is not None else None,'sigma':round(sigma,4),'flow_score':round(memory.get('_flow_score',.0),3)});return taker_orders+gap_orders+passive_orders,0
	def feature_prices(self,memory):
		out={}
		if(m:=memory.get('mid_smoothed'))is not None:out['MidSmooth']=m
		if(a:=memory.get('_anchor_ema'))is not None:out['AnchorEMA']=a
		z=memory.get('zscore')
		if z is not None:out['Z']=float(z)
		return out
class R3GuardedAnchorMMStrategy(MMFirstV4ComboStrategy):
	def compute_orders(self,state,book,order_depth,position,memory):
		mid=book.mid_price;anchor=self.params.get('anchor_price')
		if mid is None or anchor is None:return super().compute_orders(state,book,order_depth,position,memory)
		use_anchor=self._use_anchor(float(mid),float(anchor),position,memory);memory['_guard_use_anchor']=int(use_anchor)
		if use_anchor:return super().compute_orders(state,book,order_depth,position,memory)
		old_anchor=self.params.get('anchor_price');old_ar=self.params.get('ar_gain');old_take_lo=self.params.get('take_edge_lo');old_take_hi=self.params.get('take_edge_hi')
		try:self.params['anchor_price']=None;self.params['ar_gain']=.0;self.params['take_edge_lo']=1e6;self.params['take_edge_hi']=1e6;return super().compute_orders(state,book,order_depth,position,memory)
		finally:self.params['anchor_price']=old_anchor;self.params['ar_gain']=old_ar;self.params['take_edge_lo']=old_take_lo;self.params['take_edge_hi']=old_take_hi
	def _use_anchor(self,mid,anchor,position,memory):prev_mid=memory.get('_guard_prev_mid');memory['_guard_prev_mid']=mid;raw_trend=.0 if prev_mid is None else mid-float(prev_mid);alpha=float(self.params.get('guard_trend_alpha',.3));trend=float(memory.get('_guard_trend_ema',raw_trend));trend=alpha*raw_trend+(1.-alpha)*trend;memory['_guard_trend_ema']=trend;dist=mid-anchor;memory['_guard_dist']=dist;memory['_guard_trend']=trend;near_band=float(self.params.get('guard_near_band',.0));min_dist=float(self.params.get('guard_min_dist',.0));max_dist=float(self.params.get('guard_max_dist',8e1));threshold=float(self.params.get('guard_reversion_threshold',.0));inventory_dist=float(self.params.get('guard_inventory_dist',4e1));near_anchor=abs(dist)<=near_band;reverting=min_dist<=abs(dist)<=max_dist and dist*trend<=-threshold;wrong_way_inventory=position>0 and dist<-inventory_dist or position<0 and dist>inventory_dist;return(near_anchor or reverting)and not wrong_way_inventory
	def feature_prices(self,memory):
		out=super().feature_prices(memory)
		if(dist:=memory.get('_guard_dist'))is not None:out['GuardDist']=float(dist)
		if(trend:=memory.get('_guard_trend'))is not None:out['GuardTrend']=float(trend)
		if(use_anchor:=memory.get('_guard_use_anchor'))is not None:out['GuardOn']=float(use_anchor)
		return out
class R3HydroReversionMMStrategy(BaseStrategy):
	def compute_orders(self,state,book,order_depth,position,memory):
		if book.best_bid is None or book.best_ask is None or book.mid_price is None:return[],0
		if self.params.get('use_target_inventory_model'):return self._compute_target_inventory_orders(state=state,book=book,position=position,memory=memory)
		mid=float(book.mid_price);ema,fast_ema=self._update_emas(mid,memory);deviation=mid-ema;trend=fast_ema-ema;prev_trend=float(memory.get('prev_trend',trend));trend_change=trend-prev_trend;realized,unrealized=self._update_inventory_pnl(state,mid,position,memory);risk=self._risk_context(int(state.timestamp),mid,position,trend,trend_change,realized,unrealized,memory);midcap=self._mid_session_cap_context(int(state.timestamp),mid,position,realized,unrealized,memory);trailcap=self._trailcap_context(int(state.timestamp),mid,position,trend_change,memory);eod=self._eod_context(int(state.timestamp));buy_cap=self.buy_capacity(position);sell_cap=self.sell_capacity(position);orders=[];bid_price,ask_price=self._quote_prices(book);bid_price,ask_price=self._apply_risk_quote_prices(position,bid_price,ask_price,book,risk);bid_price,ask_price=self._apply_midcap_quote_prices(position,bid_price,ask_price,book,midcap);bid_price,ask_price=self._apply_trailcap_quote_prices(position,bid_price,ask_price,book,trailcap);bid_size,ask_size=self._quote_sizes(position,deviation,trend);bid_size,ask_size=self._apply_risk_quote_controls(position,bid_size,ask_size,risk);bid_size,ask_size=self._apply_midcap_quote_controls(position,bid_size,ask_size,midcap);bid_size,ask_size=self._apply_trailcap_quote_controls(position,bid_size,ask_size,trailcap);bid_size,ask_size=self._apply_eod_quote_controls(position,bid_size,ask_size,eod)
		if bid_size>0 and buy_cap>0:qty=min(bid_size,buy_cap);orders.append(Order(self.product,bid_price,qty));buy_cap-=qty
		if ask_size>0 and sell_cap>0:qty=min(ask_size,sell_cap);orders.append(Order(self.product,ask_price,-qty));sell_cap-=qty
		take_order=self._take_order(state,book,position,deviation,trend,memory,buy_cap,sell_cap,risk,midcap,trailcap)
		if take_order is not None:orders.append(take_order)
		self.log_quote_snapshot(state=state,memory=memory,bid_price=bid_price if bid_size>0 else None,ask_price=ask_price if ask_size>0 else None,extras={'ema':round(ema,2),'dev':round(deviation,2),'trend':round(trend,2),'trend_change':round(trend_change,2),'realized':round(realized,2),'unrealized':round(unrealized,2),'risk':int(risk is not None),'risk_cap':risk['target_position']if risk is not None else None,'risk_rebound':round(float(risk['rebound_ticks']),2)if risk is not None else None,'midcap':midcap['position_cap']if midcap is not None else None,'midcap_rebound':round(float(midcap['rebound_ticks']),2)if midcap is not None else None,'trailcap':trailcap['position_cap']if trailcap is not None else None,'trailcap_rebound':round(float(trailcap['rebound_ticks']),2)if trailcap is not None else None,'trailcap_stale':trailcap['stale_ts']if trailcap is not None else None,'eod_cap':eod['position_cap']if eod is not None else None,'bid_size':bid_size,'ask_size':ask_size});memory['dev']=deviation;memory['prev_trend']=trend;return orders,0
	def _compute_target_inventory_orders(self,state,book,position,memory):
		mid=float(book.mid_price);ema,fast_ema=self._update_emas(mid,memory);deviation=mid-ema;trend=fast_ema-ema;prev_trend=float(memory.get('prev_trend',trend));trend_change=trend-prev_trend;realized,unrealized=self._update_inventory_pnl(state,mid,position,memory);eod=self._eod_context(int(state.timestamp));target_ctx=self._target_inventory_context(timestamp=int(state.timestamp),mid=mid,position=position,deviation=deviation,trend=trend,trend_change=trend_change,eod=eod,memory=memory);bid_price,ask_price=self._quote_prices(book);bid_price,ask_price=self._target_quote_prices(book=book,position=position,target_position=int(target_ctx['target_position']),bid_price=bid_price,ask_price=ask_price);bid_size,ask_size=self._target_quote_sizes(position=position,target_position=int(target_ctx['target_position']));buy_cap=self.buy_capacity(position);sell_cap=self.sell_capacity(position);orders=[]
		if bid_size>0 and buy_cap>0:qty=min(bid_size,buy_cap);orders.append(Order(self.product,bid_price,qty));buy_cap-=qty
		if ask_size>0 and sell_cap>0:qty=min(ask_size,sell_cap);orders.append(Order(self.product,ask_price,-qty));sell_cap-=qty
		take_order=self._target_take_order(state=state,book=book,position=position,memory=memory,buy_cap=buy_cap,sell_cap=sell_cap,target_ctx=target_ctx,eod=eod)
		if take_order is not None:orders.append(take_order)
		self.log_quote_snapshot(state=state,memory=memory,bid_price=bid_price if bid_size>0 else None,ask_price=ask_price if ask_size>0 else None,extras={'ema':round(ema,2),'dev':round(deviation,2),'trend':round(trend,2),'trend_change':round(trend_change,2),'target':int(target_ctx['target_position']),'delta_to_target':int(target_ctx['delta_to_target']),'short_signal':round(float(target_ctx['short_signal']),2),'relief':round(float(target_ctx['relief']),2),'rebound':round(float(target_ctx['rebound_ticks']),2),'realized':round(realized,2),'unrealized':round(unrealized,2),'eod_cap':eod['position_cap']if eod is not None else None,'bid_size':bid_size,'ask_size':ask_size});memory['dev']=deviation;memory['prev_trend']=trend;return orders,0
	def _update_emas(self,mid,memory):slow_alpha=float(self.params.get('ema_alpha',.008));fast_alpha=float(self.params.get('fast_ema_alpha',.03));ema=memory.get('ema');fast_ema=memory.get('fast_ema');ema=mid if ema is None else slow_alpha*mid+(1.-slow_alpha)*float(ema);fast_ema=mid if fast_ema is None else fast_alpha*mid+(1.-fast_alpha)*float(fast_ema);memory['ema']=ema;memory['fast_ema']=fast_ema;return ema,fast_ema
	def _quote_prices(self,book):
		tighten=int(self.params.get('tighten_ticks',1));bid=int(book.best_bid);ask=int(book.best_ask)
		if book.spread is not None and book.spread>=2:bid=min(int(book.best_bid)+tighten,int(book.best_ask)-1);ask=max(int(book.best_ask)-tighten,int(book.best_bid)+1)
		return bid,ask
	def _apply_risk_quote_prices(self,position,bid_price,ask_price,book,risk):
		if risk is None or book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		tighten=int(self.params.get('risk_unwind_tighten_ticks',4));leave_gap=int(self.params.get('risk_unwind_leave_gap_ticks',1))
		if position<0:
			bid_ceiling=int(book.best_ask)-leave_gap
			if bid_ceiling<int(book.best_bid):bid_ceiling=int(book.best_bid)
			bid_price=min(int(book.best_bid)+tighten,bid_ceiling)
		elif position>0:
			ask_floor=int(book.best_bid)+leave_gap
			if ask_floor>int(book.best_ask):ask_floor=int(book.best_ask)
			ask_price=max(int(book.best_ask)-tighten,ask_floor)
		return bid_price,ask_price
	def _apply_midcap_quote_prices(self,position,bid_price,ask_price,book,midcap):
		if midcap is None or book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		tighten=int(self.params.get('midcap_unwind_tighten_ticks',3));leave_gap=int(self.params.get('midcap_unwind_leave_gap_ticks',1))
		if position<0:
			bid_ceiling=int(book.best_ask)-leave_gap
			if bid_ceiling<int(book.best_bid):bid_ceiling=int(book.best_bid)
			bid_price=min(int(book.best_bid)+tighten,bid_ceiling)
		elif position>0:
			ask_floor=int(book.best_bid)+leave_gap
			if ask_floor>int(book.best_ask):ask_floor=int(book.best_ask)
			ask_price=max(int(book.best_ask)-tighten,ask_floor)
		return bid_price,ask_price
	def _quote_sizes(self,position,deviation,trend):
		maker=int(self.params.get('maker_size',24));min_size=int(self.params.get('min_maker_size',3));quote_threshold=float(self.params.get('quote_threshold',6.));signal_boost=int(self.params.get('max_signal_size_boost',12));trend_guard=float(self.params.get('trend_guard',8.));pos_gate=int(self.params.get('signal_pos_gate',12));reduce_per_unit=float(self.params.get('inventory_reduce_per_unit',.4));unwind_per_unit=float(self.params.get('inventory_unwind_per_unit',.3));unwind_boost=int(self.params.get('max_unwind_boost',20));bid_size=maker;ask_size=maker
		if abs(trend)<trend_guard:
			if deviation>quote_threshold and position>-pos_gate:bid_size=0;ask_size=maker+min(signal_boost,int(abs(deviation)//4))
			elif deviation<-quote_threshold and position<pos_gate:ask_size=0;bid_size=maker+min(signal_boost,int(abs(deviation)//4))
		if position>0:bid_size=max(0,bid_size-int(position*reduce_per_unit));ask_size+=min(unwind_boost,int(position*unwind_per_unit))
		elif position<0:ask_size=max(0,ask_size-int(-position*reduce_per_unit));bid_size+=min(unwind_boost,int(-position*unwind_per_unit))
		if 0<bid_size<min_size:bid_size=min_size
		if 0<ask_size<min_size:ask_size=min_size
		return max(0,bid_size),max(0,ask_size)
	def _update_inventory_pnl(self,state,mid,position,memory):
		tracked_pos=int(memory.get('tracked_pos',0));avg_cost=float(memory.get('avg_cost',.0));realized=float(memory.get('realized_pnl',.0))
		for trade in state.own_trades.get(self.product,[]):
			qty=int(trade.quantity);price=float(trade.price)
			if trade.buyer=='SUBMISSION':
				if tracked_pos>=0:new_pos=tracked_pos+qty;avg_cost=(avg_cost*tracked_pos+price*qty)/new_pos if new_pos else .0;tracked_pos=new_pos
				else:
					cover=min(qty,-tracked_pos);realized+=(avg_cost-price)*cover;tracked_pos+=cover;remainder=qty-cover
					if tracked_pos==0:avg_cost=.0
					if remainder>0:tracked_pos=remainder;avg_cost=price
			elif trade.seller=='SUBMISSION':
				if tracked_pos<=0:new_abs_pos=-tracked_pos+qty;avg_cost=(avg_cost*-tracked_pos+price*qty)/new_abs_pos if new_abs_pos else .0;tracked_pos-=qty
				else:
					close=min(qty,tracked_pos);realized+=(price-avg_cost)*close;tracked_pos-=close;remainder=qty-close
					if tracked_pos==0:avg_cost=.0
					if remainder>0:tracked_pos=-remainder;avg_cost=price
		if tracked_pos!=position:
			tracked_pos=position
			if tracked_pos==0:avg_cost=.0
			elif avg_cost==.0:avg_cost=mid
		if tracked_pos>0:unrealized=(mid-avg_cost)*tracked_pos
		elif tracked_pos<0:unrealized=(avg_cost-mid)*-tracked_pos
		else:unrealized=.0
		memory['tracked_pos']=tracked_pos;memory['avg_cost']=avg_cost;memory['realized_pnl']=realized;memory['unrealized_pnl']=unrealized;return realized,unrealized
	def _target_inventory_context(self,timestamp,mid,position,deviation,trend,trend_change,eod,memory):
		trend_entry=float(self.params.get('target_trend_entry',3.));trend_full=float(self.params.get('target_trend_full',12.));max_short=int(self.params.get('target_max_short',28));reset_trend=float(self.params.get('target_regime_reset_trend',1.));short_signal=.0
		if trend<-trend_entry:denom=max(1e-09,trend_full-trend_entry);short_signal=min(1.,max(.0,(-trend-trend_entry)/denom))
		regime_side=int(memory.get('target_regime_side',0));regime_low=float(memory.get('target_regime_low',mid));regime_low_ts=int(memory.get('target_regime_low_ts',timestamp))
		if short_signal<=.0 or trend>-reset_trend:regime_side=0;regime_low=mid;regime_low_ts=timestamp
		else:
			if regime_side!=-1:regime_low=mid;regime_low_ts=timestamp
			elif mid<regime_low:regime_low=mid;regime_low_ts=timestamp
			regime_side=-1
		memory['target_regime_side']=regime_side;memory['target_regime_low']=regime_low;memory['target_regime_low_ts']=regime_low_ts;rebound_ticks=max(.0,mid-regime_low)if regime_side==-1 else .0;oversold_start=float(self.params.get('target_oversold_start',1e1));oversold_full=float(self.params.get('target_oversold_full',28.));rebound_start=float(self.params.get('target_rebound_start',8.));rebound_full=float(self.params.get('target_rebound_full',22.));turn_start=float(self.params.get('target_turn_start',.8));turn_full=float(self.params.get('target_turn_full',2.8));oversold_relief=.0
		if deviation<-oversold_start:oversold_relief=min(1.,max(.0,(-deviation-oversold_start)/max(1e-09,oversold_full-oversold_start)))
		rebound_relief=.0
		if rebound_ticks>rebound_start:rebound_relief=min(1.,max(.0,(rebound_ticks-rebound_start)/max(1e-09,rebound_full-rebound_start)))
		turn_relief=.0
		if trend_change>turn_start:turn_relief=min(1.,max(.0,(trend_change-turn_start)/max(1e-09,turn_full-turn_start)))
		relief=max(float(self.params.get('target_oversold_relief_weight',.8))*oversold_relief,float(self.params.get('target_rebound_relief_weight',1.))*rebound_relief,float(self.params.get('target_turn_relief_weight',.8))*turn_relief);relief=min(1.,max(.0,relief));raw_target=-int(round(max_short*short_signal*max(.0,1.-relief)))
		if abs(raw_target)<int(self.params.get('target_min_active_position',4)):raw_target=0
		if eod is not None:cap=int(eod['position_cap']);raw_target=-min(abs(raw_target),cap)
		return{'target_position':float(raw_target),'delta_to_target':float(raw_target-position),'short_signal':short_signal,'oversold_relief':oversold_relief,'rebound_relief':rebound_relief,'turn_relief':turn_relief,'relief':relief,'rebound_ticks':rebound_ticks}
	def _target_quote_prices(self,book,position,target_position,bid_price,ask_price):
		if book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		delta=target_position-position;hold_band=int(self.params.get('target_hold_band',2));base_tighten=int(self.params.get('target_base_tighten_ticks',1));gap_step=int(self.params.get('target_gap_per_tighten_step',6));max_tighten=int(self.params.get('target_max_tighten_ticks',5));same_side_leave_gap=int(self.params.get('target_leave_gap_ticks',1));tighten=min(max_tighten,base_tighten+abs(delta)//max(1,gap_step));bid_ceiling=int(book.best_ask)-same_side_leave_gap;ask_floor=int(book.best_bid)+same_side_leave_gap
		if delta>hold_band:bid_price=min(int(book.best_bid)+tighten,max(int(book.best_bid),bid_ceiling));ask_price=int(book.best_ask)
		elif delta<-hold_band:ask_price=max(int(book.best_ask)-tighten,min(int(book.best_ask),ask_floor));bid_price=int(book.best_bid)
		return bid_price,ask_price
	def _target_quote_sizes(self,position,target_position):
		delta=target_position-position;hold_band=int(self.params.get('target_hold_band',2));neutral_size=int(self.params.get('target_neutral_maker_size',4));same_side_size=int(self.params.get('target_same_side_size',0));max_size=int(self.params.get('target_max_quote_size',20));gap_gain=float(self.params.get('target_size_gain_per_unit',.8))
		if delta>hold_band:bid_size=min(max_size,neutral_size+int(round(abs(delta)*gap_gain)));ask_size=same_side_size
		elif delta<-hold_band:ask_size=min(max_size,neutral_size+int(round(abs(delta)*gap_gain)));bid_size=same_side_size
		else:bid_size=neutral_size;ask_size=neutral_size
		return max(0,bid_size),max(0,ask_size)
	def _target_take_order(self,state,book,position,memory,buy_cap,sell_cap,target_ctx,eod):
		delta=int(round(target_ctx['delta_to_target']))
		if delta>0:
			take_size=int(self.params.get('target_cover_take_size',1))
			if take_size<=0:return
			gap_threshold=int(self.params.get('target_cover_take_gap_threshold',8));rebound_threshold=float(self.params.get('target_cover_take_rebound_threshold',12.));last_take_ts=int(memory.get('last_target_take_ts',-10**9));cooldown_ts=int(self.params.get('target_cover_take_cooldown_ts',1000))
			if int(state.timestamp)-last_take_ts<cooldown_ts:return
			eod_force=eod is not None and abs(position)>int(eod['position_cap']);rebound_force=float(target_ctx['rebound_ticks'])>=rebound_threshold
			if delta>=gap_threshold and(rebound_force or eod_force)and buy_cap>0:
				qty=min(take_size,buy_cap,delta)
				if qty>0:memory['last_target_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
		if delta<0:
			take_size=int(self.params.get('target_entry_take_size',0))
			if take_size<=0:return
			gap_threshold=int(self.params.get('target_entry_take_gap_threshold',12));trend_threshold=float(self.params.get('target_entry_take_trend_threshold',8.));short_signal_threshold=float(self.params.get('target_entry_take_short_signal_threshold',.75));relief_cap=float(self.params.get('target_entry_take_relief_cap',.35));last_take_ts=int(memory.get('last_target_entry_take_ts',-10**9));cooldown_ts=int(self.params.get('target_entry_take_cooldown_ts',1600))
			if int(state.timestamp)-last_take_ts<cooldown_ts:return
			if-delta>=gap_threshold and float(target_ctx['short_signal'])>=short_signal_threshold and float(target_ctx['relief'])<=relief_cap and float(memory.get('fast_ema',.0))-float(memory.get('ema',.0))<=-trend_threshold and sell_cap>0:
				qty=min(take_size,sell_cap,-delta)
				if qty>0:memory['last_target_entry_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
	def _risk_context(self,timestamp,mid,position,trend,trend_change,realized,unrealized,memory):
		threshold=self.params.get('risk_abs_position_threshold')
		if threshold is None:return
		high_pos=int(threshold)
		if abs(position)<high_pos:memory['risk_peak_side']=0;memory['risk_peak_unrealized']=max(.0,unrealized);memory['risk_peak_unrealized_ts']=timestamp;memory['risk_rebound_side']=0;memory['risk_rebound_ref_mid']=mid;memory['risk_rebound_ref_ts']=timestamp;return
		progress_threshold=float(self.params.get('risk_realized_progress_threshold',8.));anchor=float(memory.get('risk_realized_anchor',realized));anchor_ts=int(memory.get('risk_realized_anchor_ts',timestamp))
		if realized>=anchor+progress_threshold:anchor=realized;anchor_ts=timestamp
		memory['risk_realized_anchor']=anchor;memory['risk_realized_anchor_ts']=anchor_ts;side=1 if position>0 else-1;peak_side=int(memory.get('risk_peak_side',0));peak_unrealized=float(memory.get('risk_peak_unrealized',max(.0,unrealized)));peak_ts=int(memory.get('risk_peak_unrealized_ts',timestamp))
		if side!=peak_side:peak_unrealized=max(.0,unrealized);peak_ts=timestamp;peak_side=side
		elif unrealized>peak_unrealized:peak_unrealized=unrealized;peak_ts=timestamp
		memory['risk_peak_side']=peak_side;memory['risk_peak_unrealized']=peak_unrealized;memory['risk_peak_unrealized_ts']=peak_ts;rebound_side=int(memory.get('risk_rebound_side',0));ref_mid=float(memory.get('risk_rebound_ref_mid',mid));ref_ts=int(memory.get('risk_rebound_ref_ts',timestamp))
		if side!=rebound_side:ref_mid=mid;ref_ts=timestamp
		elif side<0 and mid<ref_mid:ref_mid=mid;ref_ts=timestamp
		elif side>0 and mid>ref_mid:ref_mid=mid;ref_ts=timestamp
		memory['risk_rebound_side']=side;memory['risk_rebound_ref_mid']=ref_mid;memory['risk_rebound_ref_ts']=ref_ts;rebound_ticks=mid-ref_mid if side<0 else ref_mid-mid;active_until=int(memory.get('risk_active_until_ts',-10**9));target_position=int(self.params.get('risk_target_position',max(1,high_pos//2)))
		if timestamp<=active_until and abs(position)>target_position:return{'target_position':target_position,'giveback':max(.0,peak_unrealized-unrealized),'rebound_ticks':rebound_ticks}
		stall_ts=int(self.params.get('risk_realized_stall_ts',4000));peak_min=float(self.params.get('risk_unrealized_peak_min',15e1));giveback_threshold=float(self.params.get('risk_unrealized_giveback_threshold',18e1));giveback_window_ts=int(self.params.get('risk_giveback_window_ts',15000));adverse_trend_threshold=float(self.params.get('risk_adverse_trend_threshold',2.));trend_turn_threshold=float(self.params.get('risk_trend_turn_threshold',1.2));force_giveback_threshold=float(self.params.get('risk_force_giveback_threshold',3e2));rebound_ticks_threshold=float(self.params.get('risk_rebound_ticks_threshold',12.));rebound_window_ts=int(self.params.get('risk_rebound_window_ts',12000));hold_ts=int(self.params.get('risk_hold_ts',6000));realized_stalled=timestamp-anchor_ts>=stall_ts;giveback=peak_unrealized-unrealized;quick_giveback=peak_unrealized>=peak_min and giveback>=giveback_threshold and timestamp-peak_ts<=giveback_window_ts;adverse_trend=trend>=adverse_trend_threshold if position<0 else trend<=-adverse_trend_threshold;adverse_turn=trend_change>=trend_turn_threshold if position<0 else trend_change<=-trend_turn_threshold;rebound_active=rebound_ticks>=rebound_ticks_threshold and timestamp-ref_ts<=rebound_window_ts
		if realized_stalled and quick_giveback and(rebound_active or adverse_turn or adverse_trend or giveback>=force_giveback_threshold):memory['risk_active_until_ts']=timestamp+hold_ts;memory['risk_last_trigger_ts']=timestamp;return{'target_position':target_position,'giveback':giveback,'rebound_ticks':rebound_ticks}
	def _apply_risk_quote_controls(self,position,bid_size,ask_size,risk):
		if risk is None:return bid_size,ask_size
		bonus=int(self.params.get('risk_unwind_size_bonus',14));same_side_cap=int(self.params.get('risk_same_side_size_cap',0))
		if position<0:bid_size+=bonus;ask_size=min(ask_size,same_side_cap)
		elif position>0:ask_size+=bonus;bid_size=min(bid_size,same_side_cap)
		return max(0,bid_size),max(0,ask_size)
	def _mid_session_cap_context(self,timestamp,mid,position,realized,unrealized,memory):
		activation=self.params.get('midcap_activation_position')
		if activation is None:return
		activation_pos=int(activation)
		if abs(position)<activation_pos:memory['midcap_side']=0;memory['midcap_best_mid']=mid;memory['midcap_best_mid_ts']=timestamp;return
		side=1 if position>0 else-1;saved_side=int(memory.get('midcap_side',0));best_mid=float(memory.get('midcap_best_mid',mid));best_mid_ts=int(memory.get('midcap_best_mid_ts',timestamp))
		if side!=saved_side:best_mid=mid;best_mid_ts=timestamp
		elif side<0 and mid<best_mid:best_mid=mid;best_mid_ts=timestamp
		elif side>0 and mid>best_mid:best_mid=mid;best_mid_ts=timestamp
		memory['midcap_side']=side;memory['midcap_best_mid']=best_mid;memory['midcap_best_mid_ts']=best_mid_ts;avg_cost=float(memory.get('avg_cost',mid));captured_ticks=avg_cost-best_mid if side<0 else best_mid-avg_cost;rebound_ticks=mid-best_mid if side<0 else best_mid-mid;capture_threshold=float(self.params.get('midcap_capture_ticks_threshold',2e1));rebound_start=float(self.params.get('midcap_rebound_start_ticks',8.));rebound_full=float(self.params.get('midcap_rebound_full_ticks',rebound_start+12.));rebound_window_ts=int(self.params.get('midcap_rebound_window_ts',12000));realized_floor=float(self.params.get('midcap_realized_floor',.0));unrealized_floor=float(self.params.get('midcap_unrealized_floor',.0))
		if captured_ticks<capture_threshold:return
		if rebound_ticks<rebound_start:return
		if timestamp-best_mid_ts>rebound_window_ts:return
		if realized<realized_floor and unrealized<unrealized_floor:return
		base_cap=int(self.params.get('midcap_base_position_cap',self.params.get('signal_pos_gate',activation_pos)));min_cap=int(self.params.get('midcap_min_position_cap',max(1,activation_pos//2)))
		if rebound_full<=rebound_start:progress=1.
		else:progress=min(1.,max(.0,(rebound_ticks-rebound_start)/float(rebound_full-rebound_start)))
		cap=int(round(base_cap+(min_cap-base_cap)*progress));return{'position_cap':max(min_cap,min(base_cap,cap)),'progress':progress,'captured_ticks':captured_ticks,'rebound_ticks':rebound_ticks}
	def _apply_midcap_quote_controls(self,position,bid_size,ask_size,midcap):
		if midcap is None:return bid_size,ask_size
		cap=int(midcap['position_cap']);progress=float(midcap['progress']);unwind_bonus=int(round(float(self.params.get('midcap_unwind_size_bonus',8))*max(.5,progress)));same_side_cap=int(self.params.get('midcap_same_side_size_cap',0))
		if position<0:
			bid_size+=unwind_bonus
			if-position>=cap:ask_size=min(ask_size,same_side_cap)
			else:room=max(0,cap+position);scale=room/max(1,cap);ask_size=min(ask_size,max(same_side_cap,int(round(ask_size*scale))))
		elif position>0:
			ask_size+=unwind_bonus
			if position>=cap:bid_size=min(bid_size,same_side_cap)
			else:room=max(0,cap-position);scale=room/max(1,cap);bid_size=min(bid_size,max(same_side_cap,int(round(bid_size*scale))))
		return max(0,bid_size),max(0,ask_size)
	def _trailcap_context(self,timestamp,mid,position,trend_change,memory):
		activation=self.params.get('trailcap_activation_position')
		if activation is None:return
		activation_pos=int(activation);side=1 if position>0 else-1 if position<0 else 0
		if side==0 or abs(position)<activation_pos:memory['trailcap_side']=0;memory['trailcap_best_mid']=mid;memory['trailcap_best_mid_ts']=timestamp;return
		saved_side=int(memory.get('trailcap_side',0));best_mid=float(memory.get('trailcap_best_mid',mid));best_mid_ts=int(memory.get('trailcap_best_mid_ts',timestamp))
		if side!=saved_side:best_mid=mid;best_mid_ts=timestamp
		elif side<0 and mid<best_mid:best_mid=mid;best_mid_ts=timestamp
		elif side>0 and mid>best_mid:best_mid=mid;best_mid_ts=timestamp
		memory['trailcap_side']=side;memory['trailcap_best_mid']=best_mid;memory['trailcap_best_mid_ts']=best_mid_ts;avg_cost=float(memory.get('avg_cost',mid));capture_ticks=avg_cost-best_mid if side<0 else best_mid-avg_cost;rebound_ticks=mid-best_mid if side<0 else best_mid-mid;capture_ticks=max(.0,capture_ticks);rebound_ticks=max(.0,rebound_ticks);stale_ts=max(0,timestamp-best_mid_ts);capture_start=float(self.params.get('trailcap_capture_start',12.))
		if capture_ticks<capture_start:return
		rebound_start=float(self.params.get('trailcap_rebound_start',8.));rebound_full=float(self.params.get('trailcap_rebound_full',22.));stale_start_ts=int(self.params.get('trailcap_stale_start_ts',3000));stale_full_ts=int(self.params.get('trailcap_stale_full_ts',12000));turn_start=float(self.params.get('trailcap_turn_start',.8));turn_full=float(self.params.get('trailcap_turn_full',2.));base_cap=int(self.params.get('trailcap_base_position_cap',self.params.get('signal_pos_gate',activation_pos)));min_cap=int(self.params.get('trailcap_min_position_cap',max(1,activation_pos//2)));rebound_progress=.0
		if rebound_ticks>rebound_start:rebound_progress=min(1.,max(.0,(rebound_ticks-rebound_start)/max(1e-09,rebound_full-rebound_start)))
		stale_progress=.0
		if stale_ts>stale_start_ts:stale_progress=min(1.,max(.0,(stale_ts-stale_start_ts)/max(1.,stale_full_ts-stale_start_ts)))
		adverse_turn=trend_change if side<0 else-trend_change;turn_progress=.0
		if adverse_turn>turn_start:turn_progress=min(1.,max(.0,(adverse_turn-turn_start)/max(1e-09,turn_full-turn_start)))
		progress=max(rebound_progress,float(self.params.get('trailcap_stale_weight',.7))*stale_progress,float(self.params.get('trailcap_turn_weight',.8))*turn_progress);progress=min(1.,max(.0,progress))
		if progress<=.0:return
		cap=int(round(base_cap+(min_cap-base_cap)*progress));return{'position_cap':max(min_cap,min(base_cap,cap)),'progress':progress,'capture_ticks':capture_ticks,'rebound_ticks':rebound_ticks,'stale_ts':stale_ts}
	def _apply_trailcap_quote_prices(self,position,bid_price,ask_price,book,trailcap):
		if trailcap is None or book.best_bid is None or book.best_ask is None:return bid_price,ask_price
		tighten=int(self.params.get('trailcap_unwind_tighten_ticks',3));leave_gap=int(self.params.get('trailcap_unwind_leave_gap_ticks',1))
		if position<0:
			bid_ceiling=int(book.best_ask)-leave_gap
			if bid_ceiling<int(book.best_bid):bid_ceiling=int(book.best_bid)
			bid_price=min(int(book.best_bid)+tighten,bid_ceiling)
		elif position>0:
			ask_floor=int(book.best_bid)+leave_gap
			if ask_floor>int(book.best_ask):ask_floor=int(book.best_ask)
			ask_price=max(int(book.best_ask)-tighten,ask_floor)
		return bid_price,ask_price
	def _apply_trailcap_quote_controls(self,position,bid_size,ask_size,trailcap):
		if trailcap is None:return bid_size,ask_size
		cap=int(trailcap['position_cap']);progress=float(trailcap['progress']);unwind_bonus=int(round(float(self.params.get('trailcap_unwind_size_bonus',10))*max(.5,progress)));same_side_cap=int(self.params.get('trailcap_same_side_size_cap',0))
		if position<0:
			bid_size+=unwind_bonus
			if-position>=cap:ask_size=min(ask_size,same_side_cap)
			else:room=max(0,cap+position);scale=room/max(1,cap);ask_size=min(ask_size,max(same_side_cap,int(round(ask_size*scale))))
		elif position>0:
			ask_size+=unwind_bonus
			if position>=cap:bid_size=min(bid_size,same_side_cap)
			else:room=max(0,cap-position);scale=room/max(1,cap);bid_size=min(bid_size,max(same_side_cap,int(round(bid_size*scale))))
		return max(0,bid_size),max(0,ask_size)
	def _eod_context(self,timestamp):
		start_ts=self.params.get('eod_start_ts')
		if start_ts is None:return
		start=int(start_ts);end=int(self.params.get('eod_end_ts',start))
		if timestamp<start:return
		if end<=start:progress=1.
		else:progress=min(1.,max(.0,(timestamp-start)/float(end-start)))
		start_cap=int(self.params.get('eod_start_pos_limit',self.params.get('signal_pos_gate',12)));end_cap=int(self.params.get('eod_end_pos_limit',0));cap=int(round(start_cap+(end_cap-start_cap)*progress));return{'progress':progress,'position_cap':max(0,cap)}
	def _apply_eod_quote_controls(self,position,bid_size,ask_size,eod):
		if eod is None:return bid_size,ask_size
		progress=float(eod['progress']);cap=int(eod['position_cap']);bonus=int(round(progress*float(self.params.get('eod_unwind_size_bonus',12))))
		if position<0:
			bid_size+=bonus;ask_size=int(round(ask_size*max(.0,1.-progress)))
			if-position>=cap:ask_size=0
		elif position>0:
			ask_size+=bonus;bid_size=int(round(bid_size*max(.0,1.-progress)))
			if position>=cap:bid_size=0
		return max(0,bid_size),max(0,ask_size)
	def _take_order(self,state,book,position,deviation,trend,memory,buy_cap,sell_cap,risk,midcap,trailcap):
		eod=self._eod_context(int(state.timestamp))
		if eod is not None:
			eod_take=self._eod_take_order(state=state,book=book,position=position,memory=memory,buy_cap=buy_cap,sell_cap=sell_cap,eod=eod)
			if eod_take is not None:return eod_take
		if midcap is not None:
			midcap_take=self._midcap_take_order(state=state,book=book,position=position,memory=memory,buy_cap=buy_cap,sell_cap=sell_cap,midcap=midcap)
			if midcap_take is not None:return midcap_take
		if trailcap is not None:
			trailcap_take=self._trailcap_take_order(state=state,book=book,position=position,memory=memory,buy_cap=buy_cap,sell_cap=sell_cap,trailcap=trailcap)
			if trailcap_take is not None:return trailcap_take
		if risk is not None:
			risk_take=self._risk_take_order(state=state,book=book,position=position,memory=memory,buy_cap=buy_cap,sell_cap=sell_cap,risk=risk)
			if risk_take is not None:return risk_take
		if midcap is not None and abs(position)>=int(midcap['position_cap']):return
		if trailcap is not None and abs(position)>=int(trailcap['position_cap']):return
		threshold=float(self.params.get('take_threshold',12.));trend_guard=float(self.params.get('trend_guard',8.));pos_gate=int(self.params.get('signal_pos_gate',12));cooldown_ts=int(self.params.get('take_cooldown_ts',2000));take_size=int(self.params.get('take_size',1));last_take_ts=int(memory.get('last_take_ts',-10**9))
		if int(state.timestamp)-last_take_ts<cooldown_ts:return
		if abs(trend)<trend_guard:
			if deviation>threshold and position>-pos_gate and sell_cap>0:
				qty=min(take_size,sell_cap,pos_gate+position)
				if qty>0:memory['last_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
			if deviation<-threshold and position<pos_gate and buy_cap>0:
				qty=min(take_size,buy_cap,pos_gate-position)
				if qty>0:memory['last_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
	def _trailcap_take_order(self,state,book,position,memory,buy_cap,sell_cap,trailcap):
		cap=int(trailcap['position_cap']);cooldown_ts=int(self.params.get('trailcap_take_cooldown_ts',1200));take_size=int(self.params.get('trailcap_take_size',1))
		if take_size<=0:return
		last_take_ts=int(memory.get('last_trailcap_take_ts',-10**9))
		if int(state.timestamp)-last_take_ts<cooldown_ts:return
		if position<-cap and buy_cap>0:
			qty=min(take_size,buy_cap,-position-cap)
			if qty>0:memory['last_trailcap_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
		if position>cap and sell_cap>0:
			qty=min(take_size,sell_cap,position-cap)
			if qty>0:memory['last_trailcap_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
	def _midcap_take_order(self,state,book,position,memory,buy_cap,sell_cap,midcap):
		cap=int(midcap['position_cap']);cooldown_ts=int(self.params.get('midcap_take_cooldown_ts',1200));take_size=int(self.params.get('midcap_take_size',1))
		if take_size<=0:return
		last_take_ts=int(memory.get('last_midcap_take_ts',-10**9))
		if int(state.timestamp)-last_take_ts<cooldown_ts:return
		if position<-cap and buy_cap>0:
			qty=min(take_size,buy_cap,-position-cap)
			if qty>0:memory['last_midcap_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
		if position>cap and sell_cap>0:
			qty=min(take_size,sell_cap,position-cap)
			if qty>0:memory['last_midcap_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
	def _risk_take_order(self,state,book,position,memory,buy_cap,sell_cap,risk):
		take_size=int(self.params.get('risk_take_size',0))
		if take_size<=0:return
		target_position=int(risk['target_position']);cooldown_ts=int(self.params.get('risk_take_cooldown_ts',800));last_take_ts=int(memory.get('last_risk_take_ts',-10**9))
		if int(state.timestamp)-last_take_ts<cooldown_ts:return
		if position<-target_position and buy_cap>0:
			qty=min(take_size,buy_cap,-position-target_position)
			if qty>0:memory['last_risk_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
		if position>target_position and sell_cap>0:
			qty=min(take_size,sell_cap,position-target_position)
			if qty>0:memory['last_risk_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
	def _eod_take_order(self,state,book,position,memory,buy_cap,sell_cap,eod):
		cap=int(eod['position_cap'])
		if cap<0:return
		cooldown_ts=int(self.params.get('eod_take_cooldown_ts',1000));take_size=int(self.params.get('eod_take_size',1));excess_threshold=int(self.params.get('eod_take_excess_threshold',0));last_take_ts=int(memory.get('last_eod_take_ts',-10**9))
		if int(state.timestamp)-last_take_ts<cooldown_ts:return
		if position<-(cap+excess_threshold)and buy_cap>0:
			qty=min(take_size,buy_cap,-position-cap)
			if qty>0:memory['last_eod_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_ask),qty)
		if position>cap+excess_threshold and sell_cap>0:
			qty=min(take_size,sell_cap,position-cap)
			if qty>0:memory['last_eod_take_ts']=int(state.timestamp);return Order(self.product,int(book.best_bid),-qty)
	def feature_prices(self,memory):
		out={}
		if'ema'in memory:out['HydroEMA']=float(memory['ema'])
		if'fast_ema'in memory:out['HydroFastEMA']=float(memory['fast_ema'])
		if'dev'in memory:out['HydroDev']=float(memory['dev'])
		return out
PRODUCTS={'HYDROGEL_PACK':{'ema_alpha':.008,'fast_ema_alpha':.03,'inventory_reduce_per_unit':.4,'inventory_unwind_per_unit':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_size':24,'max_signal_size_boost':12,'max_unwind_boost':20,'min_maker_size':3,'position_limit':200,'quote_threshold':6.,'signal_pos_gate':12,'strategy':'r3_hydro_reversion_mm','take_cooldown_ts':2000,'take_size':1,'take_threshold':12.,'tighten_ticks':1,'trend_guard':8.,'ts_increment':100},'VELVETFRUIT_EXTRACT':{'anchor_alpha':.02,'anchor_drift_bound':2.,'anchor_price':525e1,'ar_gain':.3,'ar_shift_source':'mid_smooth','full_capacity_on_empty':True,'guard_inventory_dist':4e1,'guard_max_dist':8e1,'guard_min_dist':.0,'guard_near_band':.0,'guard_reversion_threshold':7.5,'guard_trend_alpha':.45,'inventory_aversion_gamma':.001,'last_ts_value':999900,'log_flush_ts':1000,'maker_size':30,'maker_size_base_pct':.31,'passive_unwind_skew_ticks':1,'passive_unwind_trigger':.38,'pct_kept_for_takers':.005,'position_limit':200,'strategy':'r3_guarded_anchor_mm','take_edge_hi':1.2,'take_edge_lo':.6,'tighten_ticks':1,'toxic_size_frac':.68,'toxic_threshold':.6,'toxic_window':8,'ts_increment':100,'unwind_take_edge':3.},'VEV_4000':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':4000,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':1.5,'zscore_window':500},'VEV_4500':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':4500,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':2.,'zscore_window':500},'VEV_5000':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5000,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':1.,'zscore_window':500},'VEV_5100':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5100,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':.5,'zscore_window':500},'VEV_5200':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5200,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':2.,'zscore_window':500},'VEV_5300':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5300,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':2.,'zscore_window':500},'VEV_5400':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5400,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':1.,'zscore_window':500},'VEV_5500':{'boost_when_cheap':False,'edge_ticks':.0,'enable_takers':False,'entry_size':30,'entry_size_boost':1.5,'implied_vol_prior':.0125,'inv_bias_per_unit':.02,'iv_ewma_alpha':.3,'last_ts_value':999900,'log_flush_ts':1000,'maker_edge':2,'maker_size':20,'min_quote_price':2.,'passive_bid_size':24,'penny_improve_around_mkt':True,'position_limit':300,'prior_vol':.0125,'sigma_cap':.1,'sigma_floor':.005,'skip_when_expensive':True,'strategy':'r3_gamma_scalp_zgated','strike':5500,'take_edge':3.,'take_size':40,'target_qty':300,'timestamp_units_per_day':1000000,'ts_increment':100,'tte_days_initial':5.,'underlying_symbol':'VELVETFRUIT_EXTRACT','unwind_tte_threshold':1.5,'use_smile':True,'zscore_boost_threshold':1.,'zscore_skip_threshold':.5,'zscore_window':500}}
STRATEGY_CLASSES={'r3_gamma_scalp_zgated':GammaScalpZGatedStrategy,'r3_guarded_anchor_mm':R3GuardedAnchorMMStrategy,'r3_hydro_reversion_mm':R3HydroReversionMMStrategy}
class Trader:
	def __init__(self):
		self.strategies={}
		for(symbol,cfg)in PRODUCTS.items():strat_name=cfg['strategy'];params={k:v for(k,v)in cfg.items()if k!='strategy'};cls=STRATEGY_CLASSES[strat_name];self.strategies[symbol]=cls(product=symbol,params=params)
	def bid(self):return 15
	def run(self,state):
		saved=load_state(state.traderData);product_memories=saved.setdefault('products',{});shared={'timestamp':state.timestamp};result={};total_conversions=0
		for(product,strategy)in self.strategies.items():
			if product not in state.order_depths:continue
			memory=product_memories.setdefault(product,{});memory['_shared']=shared;orders,conversions=strategy.on_tick(state,memory);result[product]=orders;total_conversions+=conversions
		for memory in product_memories.values():
			if isinstance(memory,dict):memory.pop('_shared',None)
		saved['last_timestamp']=state.timestamp;return result,total_conversions,dump_state(saved)