from __future__ import annotations
import pandas as pd, numpy as np

def oi_impulse_div(df_oi: pd.DataFrame|None=None, df_price: pd.DataFrame|None=None, *, tf:str="", params:dict|None=None)->dict:
    # צפה לקבל df_oi מבחוץ (API Binance), df_price = df של הסימבול
    if df_oi is None or df_price is None:
        return {"series":{}, "signals":[], "context":{"note":"supply df_oi & df_price"}}
    oi = df_oi["oi"].astype(float)
    c  = df_price["close"].astype(float)
    d_oi = (oi - oi.rolling(20).mean())/ (oi.rolling(20).std(ddof=0)+1e-9)
    impulse = (d_oi.abs()>2.0).astype(int)
    div = ((c.diff()>0) & (oi.diff()<0)) | ((c.diff()<0)&(oi.diff()>0))
    sig=[]
    if bool(impulse.iloc[-1]): sig.append({"ts":df_price.index[-1],"side":"long" if c.iloc[-1]>c.iloc[-2] else "short","strength":8.2,"reason":{"oi":"impulse"}})
    if bool(div.iloc[-1]):     sig.append({"ts":df_price.index[-1],"side":"neutral","strength":7.5,"reason":{"oi":"divergence"}})
    return {"series":{"d_oi":d_oi},"signals":sig,"context":{}}
