from __future__ import annotations
import pandas as pd, numpy as np

def squeeze_bb_kc(df, bb_len=20, bb_mult=2.0, kc_len=20, kc_mult=1.5):
    c = df["close"].astype(float)
    ma = c.rolling(bb_len).mean(); sd = c.rolling(bb_len).std(ddof=0)
    bb_up, bb_dn = ma + bb_mult*sd, ma - bb_mult*sd
    tr = (df["high"]-df["low"]).ewm(alpha=1/kc_len, adjust=False).mean()
    kc_up, kc_dn = ma + kc_mult*tr, ma - kc_mult*tr
    in_sq = (bb_up < kc_up) & (bb_dn > kc_dn)
    release = in_sq.shift(1).fillna(False) & (~in_sq)
    return {"series":{"bb_up":bb_up,"bb_dn":bb_dn,"kc_up":kc_up,"kc_dn":kc_dn}, "signals":[{"ts":df.index[-1],"side":"long","strength":8.0,"reason":{"sq":"release"}}] if bool(release.iloc[-1]) else [], "context":{}}

def donchian(df, length=20):
    up = df["high"].rolling(length).max()
    dn = df["low"].rolling(length).min()
    brk = (df["close"]>up.shift(1)) | (df["close"]<dn.shift(1))
    sig=[]
    if bool((df["close"].iloc[-1]>up.shift(1).iloc[-1])): sig.append({"ts":df.index[-1],"side":"long","strength":8.0,"reason":{"donchian":"breakout"}})
    if bool((df["close"].iloc[-1]<dn.shift(1).iloc[-1])): sig.append({"ts":df.index[-1],"side":"short","strength":8.0,"reason":{"donchian":"breakdown"}})
    return {"series":{"upper":up,"lower":dn},"signals":sig,"context":{}}

def avwap(df, anchor:str|None=None):
    tp = (df["high"]+df["low"]+df["close"])/3
    v  = df["volume"].replace(0,np.nan)
    vwap = (tp*v).cumsum()/v.cumsum()
    return {"series":{"avwap":vwap},"signals":[], "context":{"anchor":anchor}}

def chandelier(df, atr_len=22, mult=3.0):
    h,l,c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    tr = (h-l).ewm(alpha=1/atr_len, adjust=False).mean()
    ce_long  = h.rolling(1).max() - mult*tr
    ce_short = l.rolling(1).min() + mult*tr
    return {"series":{"ce_long":ce_long,"ce_short":ce_short},"signals":[],"context":{}}

def vol_regime(df, look=100):
    c = df["close"].astype(float)
    ret = c.pct_change().abs()
    p = ret.rolling(look).quantile([0.33,0.66]).unstack()
    lo, hi = p[0.33], p[0.66]
    state = (ret.rolling(10).mean())
    regime = state.apply(lambda x: "low" if x<=lo.iloc[-1] else ("high" if x>=hi.iloc[-1] else "med"))
    return {"series":{"state":state},"signals":[],"context":{"regime":regime.iloc[-1]}}
