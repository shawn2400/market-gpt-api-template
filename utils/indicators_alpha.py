# utils/indicators_alpha.py
from __future__ import annotations
import pandas as pd
from utils.indicators import atr

class alpha:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf: str, params: dict | None = None, **feeds) -> dict:
        p = {"atr_len": 14, "mult": 3.0, "use_close": True}
        if params: p.update(params)

        h = df["high"].astype(float); l = df["low"].astype(float); c = df["close"].astype(float)
        a = atr(df, int(p["atr_len"]))
        mid = (h + l) / 2.0
        bu = mid + p["mult"] * a
        bl = mid - p["mult"] * a

        fu, fl = bu.copy(), bl.copy()
        for i in range(1, len(df)):
            fu.iat[i] = bu.iat[i] if (bu.iat[i] < fu.iat[i-1] or c.iat[i-1] > fu.iat[i-1]) else fu.iat[i-1]
            fl.iat[i] = bl.iat[i] if (bl.iat[i] > fl.iat[i-1] or c.iat[i-1] < fl.iat[i-1]) else fl.iat[i-1]

        st = c.copy()*0.0
        up = c.copy().astype(bool)
        for i in range(len(df)):
            if i == 0:
                st.iat[i] = fu.iat[i]; up.iat[i] = False; continue
            pst = st.iat[i-1]
            if pst == fu.iat[i-1]:
                st.iat[i] = fu.iat[i] if ((c.iat[i] if p["use_close"] else l.iat[i]) <= fu.iat[i]) else fl.iat[i]
            else:
                st.iat[i] = fl.iat[i] if ((c.iat[i] if p["use_close"] else h.iat[i]) >= fl.iat[i]) else fu.iat[i]
            up.iat[i] = (st.iat[i] == fl.iat[i])

        flip_long  = (~up.shift(1).fillna(False)) & (up)
        flip_short = (up.shift(1).fillna(False)) & (~up)
        sig = []
        if bool(flip_long.iloc[-1]):  sig.append({"ts": df.index[-1], "side": "long",  "strength": 8.8, "reason": {"alpha": "flip_long"}})
        if bool(flip_short.iloc[-1]): sig.append({"ts": df.index[-1], "side": "short", "strength": 8.8, "reason": {"alpha": "flip_short"}})

        return {"series": {"trail": st, "is_up": up.astype(int), "atr": a},
                "signals": sig,
                "context": {"tf": tf}}
