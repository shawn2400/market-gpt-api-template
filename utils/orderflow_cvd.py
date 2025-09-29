from __future__ import annotations
import pandas as pd, numpy as np

class cvd:
    @staticmethod
    def compute(df: pd.DataFrame, *, tf:str, params:dict|None=None) -> dict:
        # צפה לקבל DF נרות + df_trades חיצוני (נדרש באגגרגטור שלך)
        # כאן טמפלט בלבד — חבר לאגרגציה שלך של aggTrades -> delta per bar
        delta = pd.Series(0.0, index=df.index)   # TODO: החלף ב-Δ אמיתי
        cvd_s = delta.cumsum()
        sig=[]
        if float(delta.iloc[-1])>0: sig.append({"ts":df.index[-1],"side":"long","strength":8.1,"reason":{"cvd":"buying_pressure"}})
        if float(delta.iloc[-1])<0: sig.append({"ts":df.index[-1],"side":"short","strength":8.1,"reason":{"cvd":"selling_pressure"}})
        return {"series":{"delta":delta,"cvd":cvd_s},"signals":sig,"context":{}}
