# utils/indicators.py
from __future__ import annotations
import os
from typing import Optional
import numpy as np
import pandas as pd
import requests

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 indicators", "Accept": "application/json"})

# --- TA helpers ---
def _ema(s: pd.Series, n: int) -> pd.Series: return s.ewm(span=max(1,int(n)), adjust=False).mean()
def _rma(s: pd.Series, n: int) -> pd.Series: return s.ewm(alpha=1.0/max(1,int(n)), adjust=False).mean()
def _atr(h,l,c,n=14):
    prev=c.shift(1); tr=pd.concat([h-l,(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    return _rma(tr,n)
def _adx(h,l,c,n=14):
    up=h.diff(); dn=-l.diff()
    plus_dm  = pd.Series(np.where((up>dn)&(up>0),up,0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn>up)&(dn>0),dn,0.0), index=h.index)
    atrv=_atr(h,l,c,n).replace(0,np.nan)
    plus_di=100*_rma(plus_dm,n)/atrv; minus_di=100*_rma(minus_dm,n)/atrv
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    return _rma(dx.fillna(0.0),n).fillna(0.0)
def _stoch(h,l,c,win=14,smooth=3):
    ll=l.rolling(win, min_periods=1).min(); hh=h.rolling(win, min_periods=1).max()
    k=100*((c-ll)/(hh-ll).replace(0,np.nan)); d=k.rolling(smooth, min_periods=1).mean()
    return k.fillna(0.0), d.fillna(0.0)
def _supertrend(h,l,c,period=10,factor=3.0):
    atr=_atr(h,l,c,period); hl2=(h+l)/2.0; upper=hl2+factor*atr; lower=hl2-factor*atr
    fu=upper.copy(); fl=lower.copy(); st=pd.Series(index=c.index, dtype="float64")
    fu.iloc[0]=upper.iloc[0]; fl.iloc[0]=lower.iloc[0]; st.iloc[0]=upper.iloc[0]
    for i in range(1,len(c)):
        fu.iloc[i]=upper.iloc[i] if (upper.iloc[i]<fu.iloc[i-1] or c.iloc[i-1]>fu.iloc[i-1]) else fu.iloc[i-1]
        fl.iloc[i]=lower.iloc[i] if (lower.iloc[i]>fl.iloc[i-1] or c.iloc[i-1]<fl.iloc[i-1]) else fl.iloc[i-1]
        st.iloc[i]= fu.iloc[i] if st.iloc[i-1]==fu.iloc[i-1] and c.iloc[i]<=fu.iloc[i] else \
                    (fl.iloc[i] if st.iloc[i-1]!=fu.iloc[i-1] and c.iloc[i]>=fl.iloc[i] else fu.iloc[i])
    return st
def _ich_state(h,l,c,conv=9,base=26,span_b=52):
    conv_l=(h.rolling(conv).max()+l.rolling(conv).min())/2.0
    base_l=(h.rolling(base).max()+l.rolling(base).min())/2.0
    span_a=(conv_l+base_l)/2.0; span_b_s=(h.rolling(span_b).max()+l.rolling(span_b).min())/2.0
    top=np.maximum(span_a, span_b_s); bot=np.minimum(span_a, span_b_s)
    s=np.where(c>top,"BULLISH", np.where(c<bot,"BEARISH","NEUTRAL"))
    return pd.Series(s, index=c.index)

# --- Public API expected by routes.routes_indicators ---
def add_indicators(df: pd.DataFrame,
                   ema_fast: int = 21, ema_slow: int = 50, adx_len: int = 14,
                   st_period: int = 10, st_factor: float = 3.0,
                   ichimoku_conv: int = 9, ichimoku_base: int = 26, ichimoku_span_b: int = 52,
                   **_) -> pd.DataFrame:
    d=df.copy(); c,h,l=d["close"],d["high"],d["low"]
    d["ema_fast"]=_ema(c,ema_fast); d["ema_slow"]=_ema(c,ema_slow); d["adx"]=_adx(h,l,c,adx_len)
    k,dv=_stoch(h,l,c,14,3); d["stoch_k"],d["stoch_d"]=k,dv
    d["atr"]=_atr(h,l,c,max(14,st_period)); d["supertrend"]=_supertrend(h,l,c,st_period,float(st_factor))
    d["ichimoku_state"]=_ich_state(h,l,c,ichimoku_conv,ichimoku_base,ichimoku_span_b)
    d["trend_dir"]=np.where(d["ema_fast"]>d["ema_slow"],"UP", np.where(d["ema_fast"]<d["ema_slow"],"DOWN","FLAT"))
    d["trending"]=(d["adx"]>=20.0) & (d["trend_dir"]!="FLAT")
    return d

def compute_indicators(df: pd.DataFrame, **kw) -> pd.DataFrame:
    return add_indicators(df, **kw)

def _fetch_klines(symbol: str, interval: str, limit: int, market: str = "futures") -> Optional[pd.DataFrame]:
    base = FUTURES_BASE if market=="futures" else SPOT_BASE
    path = "fapi/v1/klines" if market=="futures" else "api/v3/klines"
    try:
        r=_S.get(f"{base}/{path}", params={"symbol":symbol,"interval":interval,"limit":int(limit)}, timeout=8)
        if r.status_code!=200: return None
        data=r.json()
        if not data: return None
        df=pd.DataFrame(data, columns=["openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"])
        for c in ("open","high","low","close","volume"): df[c]=pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["open","high","low","close"], inplace=True)
        df["timestamp"]=pd.to_datetime(df["openTime"], unit="ms", utc=True)
        return df[["timestamp","open","high","low","close","volume"]]
    except Exception:
        return None

def prepare_indicators_for_backtest(symbol: str, timeframe: str = "15m", limit: int = 200, market: str = "futures") -> pd.DataFrame:
    df=_fetch_klines(symbol, timeframe, limit, market) or pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])
    if df.empty: return df
    return add_indicators(df)


































