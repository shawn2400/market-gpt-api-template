from __future__ import annotations
import pandas as pd, numpy as np

class mc_b:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        c = df["close"].astype(float)
        # WaveTrend (גרסה בסיסית; נרחיב בהמשך)
        hlc3 = (df["high"]+df["low"]+df["close"])/3
        ema1 = hlc3.ewm(span=9, adjust=False).mean()
        ema2 = ema1.ewm(span=12, adjust=False).mean()
        wt1  = ema1 - ema2
        wt2  = wt1.ewm(span=3, adjust=False).mean()
        # Money Flow (MFI-lite)
        tp = hlc3; vr = df["volume"].rolling(14).sum().replace(0,np.nan)
        mf = ((tp - tp.rolling(14).mean()) / (tp.rolling(14).std(ddof=0)+1e-9)).clip(-3,3)
        # VWAP יומי (פשוט)
        vwap = (tp*df["volume"]).cumsum() / (df["volume"].replace(0,np.nan)).cumsum()
        # אותות פשוטים (קרוס)
        cross_up   = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
        cross_down = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
        signals=[]
        if bool(cross_up.iloc[-1]):   signals.append({"ts":df.index[-1], "side":"long",  "strength":8.6, "reason":{"mc_b":"cross_up"}})
        if bool(cross_down.iloc[-1]): signals.append({"ts":df.index[-1], "side":"short", "strength":8.6, "reason":{"mc_b":"cross_dn"}})
        return {"series":{"wt1":wt1,"wt2":wt2,"mf":mf,"vwap":vwap},"signals":signals,"context":{"tf":tf}}

class mc_a:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        c = df["close"].astype(float)
        # ריבון EMA
        ema_lens = params.get("ema_lens",[20,34,50,89]) if params else [20,34,50,89]
        ribbon = {f"ema{n}": c.ewm(span=n, adjust=False).mean() for n in ema_lens}
        # Rejection dots (סטיית ATR מול VWAP/EMA)
        atr = (df["high"]-df["low"]).ewm(alpha=1/14, adjust=False).mean()
        vwap = ((c*df["volume"]).cumsum()/(df["volume"].replace(0,np.nan)).cumsum())
        rej = ( (c - vwap).abs() > 2.5*atr ).astype(int)
        signals=[]
        if rej.iloc[-1]==1:
            side = "short" if c.iloc[-1]>vwap.iloc[-1] else "long"
            signals.append({"ts":df.index[-1], "side":side, "strength":8.2, "reason":{"mc_a":"rejection"}})
        return {"series":{**ribbon,"vwap":vwap,"atr":atr},"signals":signals,"context":{"tf":tf}}
