from __future__ import annotations
import pandas as pd, numpy as np

class smc:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        h,l,c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
        atr = (h-l).ewm(alpha=1/14, adjust=False).mean()
        # FVG (n=3): gap בין high של נר 1 ל-low של נר 3
        fvg_up = (h.shift(2) < l).astype(int)
        fvg_dn = (l.shift(2) > h).astype(int)
        zones = {
          "fvg_up": [{"start":i, "high":float(h.iloc[i-2]), "low":float(l.iloc[i])} for i in range(2,len(df)) if fvg_up.iloc[i]],
          "fvg_dn": [{"start":i, "high":float(h.iloc[i]),   "low":float(l.iloc[i-2])} for i in range(2,len(df)) if fvg_dn.iloc[i]],
        }
        # Sweep (SFP): שבירת swing high/low וחזרה פנימה באותו/הנר הבא
        swing_h = (h.shift(1)<h) & (h.shift(-1)<h)
        swing_l = (l.shift(1)>l) & (l.shift(-1)>l)
        sweep_up = (h > h.shift(1).where(swing_h).ffill()) & (c < h.shift(1).where(swing_h).ffill())
        sweep_dn = (l < l.shift(1).where(swing_l).ffill()) & (c > l.shift(1).where(swing_l).ffill())
        events = {"sweep_up": list(df.index[sweep_up.fillna(False)]), "sweep_dn": list(df.index[sweep_dn.fillna(False)])}
        signals=[]
        if bool(sweep_up.iloc[-1]): signals.append({"ts":df.index[-1],"side":"short","strength":8.7,"reason":{"smc":"sweep_up"}})
        if bool(sweep_dn.iloc[-1]): signals.append({"ts":df.index[-1],"side":"long","strength":8.7,"reason":{"smc":"sweep_dn"}})
        return {"series":{"atr":atr}, "signals":signals, "zones":zones, "events":events, "context":{"tf":tf}}
