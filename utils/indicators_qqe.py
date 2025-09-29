from __future__ import annotations
import pandas as pd, numpy as np

def rma(s: pd.Series, length:int)->pd.Series:
    return s.ewm(alpha=1/float(length), adjust=False).mean()

class qqe:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        c = df["close"].astype(float)
        length = (params or {}).get("rsi_len",14)
        delta = c.diff()
        up = (delta.clip(lower=0)).abs(); dn = (-delta.clip(upper=0)).abs()
        rs = rma(up,length)/rma(dn,length).replace(0,np.nan)
        rsi = 100 - (100/(1+rs))
        rsi_s = rma(rsi, (params or {}).get("smooth",5))
        # QQE line ~ רצועה על RSI_s
        dev = (rsi_s - rsi_s.rolling(14).mean()).abs().rolling(14).mean()
        qqe_line = rsi_s.rolling(5).mean()
        long_flag  = (rsi_s > qqe_line) & (rsi_s.shift(1) <= qqe_line.shift(1))
        short_flag = (rsi_s < qqe_line) & (rsi_s.shift(1) >= qqe_line.shift(1))
        signals=[]
        if bool(long_flag.iloc[-1]):  signals.append({"ts":df.index[-1],"side":"long","strength":8.3,"reason":{"qqe":"cross_up"}})
        if bool(short_flag.iloc[-1]): signals.append({"ts":df.index[-1],"side":"short","strength":8.3,"reason":{"qqe":"cross_dn"}})
        return {"series":{"rsi_s":rsi_s,"qqe_line":qqe_line,"dev":dev},
                "signals":signals,"context":{"tf":tf}}
