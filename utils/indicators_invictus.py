from __future__ import annotations
import pandas as pd, numpy as np

class invictus:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        c,v = df["close"].astype(float), df["volume"].astype(float)
        ema_fast = c.ewm(span=21, adjust=False).mean()
        ema_slow = c.ewm(span=50, adjust=False).mean()
        trend = (ema_fast > ema_slow).astype(int)
        obv = (np.sign(c.diff().fillna(0))*v).cumsum()
        obv_ma = obv.ewm(span=20, adjust=False).mean()
        strength = 7.0 + 1.5*float((trend.iloc[-1])) + 0.5*float(obv.iloc[-1] > obv_ma.iloc[-1])
        side = "long" if (trend.iloc[-1]==1 and obv.iloc[-1]>obv_ma.iloc[-1]) else ("short" if trend.iloc[-1]==0 and obv.iloc[-1]<obv_ma.iloc[-1] else None)
        signals = [{"ts":df.index[-1],"side":side,"strength":strength,"reason":{"invictus":"composite"}}] if side else []
        return {"series":{"ema21":ema_fast,"ema50":ema_slow,"obv":obv,"obv_ma":obv_ma},
                "signals":signals,"context":{"tf":tf,"trend":int(trend.iloc[-1])}}
