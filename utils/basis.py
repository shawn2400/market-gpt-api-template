from __future__ import annotations
import pandas as pd, numpy as np

def perp_spot_basis(df_spot: pd.DataFrame|None=None, df_mark: pd.DataFrame|None=None)->dict:
    if df_spot is None or df_mark is None:
        return {"series":{}, "signals":[], "context":{"note":"supply spot & mark"}}
    s = df_spot["price"].astype(float)
    m = df_mark["markPrice"].astype(float)
    bp = (m - s) / s * 100.0
    z = (bp - bp.rolling(96).mean())/(bp.rolling(96).std(ddof=0)+1e-9)
    sig=[]
    if abs(float(z.iloc[-1]))>2.0:
        side = "short" if z.iloc[-1]>0 else "long"
        sig.append({"ts":df_spot.index[-1],"side":side,"strength":7.9,"reason":{"basis":"extreme"}})
    return {"series":{"basis_pct":bp,"zscore":z},"signals":sig,"context":{}}
