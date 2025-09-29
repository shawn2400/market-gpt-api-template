# utils/indicators_ext.py
from __future__ import annotations
from typing import Dict, Any, List, Callable, Optional
import math, os
import pandas as pd
import numpy as np
import httpx

# שימוש בפונקציות המהירות שכבר יש לך:
from utils.indicators import ema, rsi, atr, bollinger_bands
from utils.get_klines import get_klines_sync as _get_klines
from utils.funding_bias import funding_bias as _funding_bias  # (יש לך קובץ)
# --- אם תרצה OI/Mark/Spot – תספק אותם מבחוץ דרך **feeds ---

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

# ===== עזר קיים ששמרתי (כדי לא לשבור API שהשתמשת בו) =====
def _safe_float(x) -> float:
    try: return float(x)
    except Exception: return math.nan

def compute_vwap(df: pd.DataFrame) -> float:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vwap = (tp * df["volume"]).sum() / max(1e-12, df["volume"].sum())
    return float(vwap)

def compute_obv(df: pd.DataFrame) -> float:
    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float, copy=False)
    vol   = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float, copy=False)
    obv = 0.0
    for i in range(1, len(close)):
        if close[i] > close[i-1]: obv += vol[i]
        elif close[i] < close[i-1]: obv -= vol[i]
    return float(obv)

def compute_cvd_from_trades(symbol: str, limit: int = 1000) -> float:
    symbol = symbol.upper().strip()
    with httpx.Client(timeout=6.0) as c:
        r = c.get(f"{_FAPI}/fapi/v1/aggTrades", params={"symbol": symbol, "limit": max(1, min(1000, limit))})
        r.raise_for_status()
        trades = r.json()
    cvd = 0.0
    for t in trades:
        q = _safe_float(t.get("q"))
        if t.get("m"):  # SELL aggression
            cvd -= q
        else:           # BUY aggression
            cvd += q
    return float(cvd)

def advanced_indicators(symbol: str, interval: str = "15m", limit: int = 200, market: str = "futures", with_cvd: bool = False) -> Dict[str, Any]:
    df = _get_klines(symbol, interval=interval, limit=max(50, min(1500, int(limit))), market_type=market)
    if df is None or len(df) < 10:
        return {"ok": False, "error": "klines_unavailable", "symbol": symbol.upper(), "interval": interval}
    vwap = compute_vwap(df)
    obv = compute_obv(df)
    out = {"ok": True, "symbol": symbol.upper(), "interval": interval, "limit": limit, "vwap": vwap, "obv": obv}
    if with_cvd:
        try:
            out["cvd"] = compute_cvd_from_trades(symbol)
        except Exception as e:
            out["cvd_error"] = str(e)
    return out

# ==========================
# 1) Market Cipher B (פתוח)
# ==========================
def mc_b_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    # WaveTrend פשוט (WT1/WT2)
    hlc3 = (df["high"]+df["low"]+df["close"]) / 3.0
    e1 = hlc3.ewm(span=9, adjust=False).mean()
    e2 = e1.ewm(span=12, adjust=False).mean()
    wt1 = e1 - e2
    wt2 = wt1.ewm(span=3, adjust=False).mean()
    # MFI-lite (zscore על tp)
    tp = hlc3
    mf = ((tp - tp.rolling(14).mean()) / (tp.rolling(14).std(ddof=0)+1e-9)).clip(-3,3)
    # VWAP מצטבר (על כל החלון הקיים)
    vwap = (tp*df["volume"]).cumsum() / (df["volume"].replace(0,np.nan)).cumsum()
    cross_up   = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    cross_down = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
    sig=[]
    if bool(cross_up.iloc[-1]):   sig.append({"ts":df.index[-1],"side":"long","strength":8.6,"reason":{"mc_b":"cross_up"}})
    if bool(cross_down.iloc[-1]): sig.append({"ts":df.index[-1],"side":"short","strength":8.6,"reason":{"mc_b":"cross_dn"}})
    return {"series":{"wt1":wt1,"wt2":wt2,"mf":mf,"vwap":vwap},"signals":sig,"context":{"tf":tf}}

# ==========================
# 2) Market Cipher A (פתוח)
# ==========================
def mc_a_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    c = df["close"].astype(float)
    lens = (params or {}).get("ema_lens",[20,34,50,89])
    rib = {f"ema{n}": ema(c, n) for n in lens}
    a = atr(df, 14)
    vwap = (( (df["high"]+df["low"]+df["close"])/3 * df["volume"]).cumsum() / (df["volume"].replace(0,np.nan)).cumsum())
    rej = ( (c - vwap).abs() > 2.5*a ).astype(int)
    sig=[]
    if rej.iloc[-1]==1:
        side = "short" if c.iloc[-1]>vwap.iloc[-1] else "long"
        sig.append({"ts":df.index[-1],"side":side,"strength":8.2,"reason":{"mc_a":"rejection"}})
    return {"series":{**rib,"vwap":vwap,"atr":a},"signals":sig,"context":{"tf":tf}}

# =================================
# 3) AlphaTrend / Supertrend (פתוח)
# =================================
def supertrend_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    p = {"atr_len":14, "mult":3.0, "use_close":True}
    if params: p.update(params)
    h,l,c = [df[k].astype(float) for k in ("high","low","close")]
    a = atr(df, int(p["atr_len"]))
    mid = (h+l)/2.0
    bu = mid + p["mult"]*a
    bl = mid - p["mult"]*a
    fu, fl = bu.copy(), bl.copy()
    for i in range(1,len(df)):
        fu.iat[i] = bu.iat[i] if (bu.iat[i] < fu.iat[i-1] or c.iat[i-1] > fu.iat[i-1]) else fu.iat[i-1]
        fl.iat[i] = bl.iat[i] if (bl.iat[i] > fl.iat[i-1] or c.iat[i-1] < fl.iat[i-1]) else fl.iat[i-1]
    st = pd.Series(index=c.index, dtype=float)
    up = pd.Series(False, index=c.index)
    for i in range(len(df)):
        if i==0: st.iat[i]=fu.iat[i]; up.iat[i]=False; continue
        pst = st.iat[i-1]
        if pst==fu.iat[i-1]:
            st.iat[i] = fu.iat[i] if ((c.iat[i] if p["use_close"] else l.iat[i]) <= fu.iat[i]) else fl.iat[i]
        else:
            st.iat[i] = fl.iat[i] if ((c.iat[i] if p["use_close"] else h.iat[i]) >= fl.iat[i]) else fu.iat[i]
        up.iat[i] = (st.iat[i]==fl.iat[i])
    flip_long  = (~up.shift(1).fillna(False)) & (up)
    flip_short = (up.shift(1).fillna(False)) & (~up)
    sig=[]
    if bool(flip_long.iloc[-1]):  sig.append({"ts":df.index[-1],"side":"long","strength":8.8,"reason":{"alpha":"flip_long"}})
    if bool(flip_short.iloc[-1]): sig.append({"ts":df.index[-1],"side":"short","strength":8.8,"reason":{"alpha":"flip_short"}})
    return {"series":{"trail":st,"is_up":up.astype(int),"atr":a},"signals":sig,"context":{"tf":tf}}

# =================
# 4) QQE Mod (פתוח)
# =================
def qqe_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    length = int((params or {}).get("rsi_len",14))
    smooth = int((params or {}).get("smooth",5))
    c = df["close"].astype(float)
    r = rsi(c, length)
    r_s = r.ewm(alpha=1/float(max(1,smooth)), adjust=False).mean()
    base = r_s.rolling(5).mean()
    long_flag  = (r_s > base) & (r_s.shift(1) <= base.shift(1))
    short_flag = (r_s < base) & (r_s.shift(1) >= base.shift(1))
    sig=[]
    if bool(long_flag.iloc[-1]):  sig.append({"ts":df.index[-1],"side":"long","strength":8.3,"reason":{"qqe":"cross_up"}})
    if bool(short_flag.iloc[-1]): sig.append({"ts":df.index[-1],"side":"short","strength":8.3,"reason":{"qqe":"cross_dn"}})
    return {"series":{"rsi_s":r_s,"qqe_line":base},"signals":sig,"context":{"tf":tf}}

# ============================
# 5) SMC-Lite: FVG/Sweep/BOS
# ============================
def smc_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    h,l,c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    a = atr(df, 14)
    # FVG (n=3)
    fvg_up = (h.shift(2) < l).fillna(False)
    fvg_dn = (l.shift(2) > h).fillna(False)
    zones = {
        "fvg_up": [{"start":int(i), "high":float(h.iloc[i-2]), "low":float(l.iloc[i])} for i in range(2,len(df)) if fvg_up.iloc[i]],
        "fvg_dn": [{"start":int(i), "high":float(h.iloc[i]),   "low":float(l.iloc[i-2])} for i in range(2,len(df)) if fvg_dn.iloc[i]],
    }
    # Sweep (SFP) לוגיקה פשוטה
    swing_h = (h.shift(1)<h) & (h.shift(-1)<h)
    swing_l = (l.shift(1)>l) & (l.shift(-1)>l)
    sh = h.shift(1).where(swing_h).ffill()
    sl = l.shift(1).where(swing_l).ffill()
    sweep_up = (h > sh) & (c < sh)
    sweep_dn = (l < sl) & (c > sl)
    sig=[]
    if bool(sweep_up.fillna(False).iloc[-1]): sig.append({"ts":df.index[-1],"side":"short","strength":8.7,"reason":{"smc":"sweep_up"}})
    if bool(sweep_dn.fillna(False).iloc[-1]): sig.append({"ts":df.index[-1],"side":"long","strength":8.7,"reason":{"smc":"sweep_dn"}})
    return {"series":{"atr":a},"signals":sig,"zones":zones,"context":{"tf":tf}}

# ======================
# 7) BB-KC Squeeze (פתוח)
# ======================
def squeeze_bb_kc_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    bb_len = int((params or {}).get("bb_len",20)); bb_mult = float((params or {}).get("bb_mult",2.0))
    kc_len = int((params or {}).get("kc_len",20)); kc_mult = float((params or {}).get("kc_mult",1.5))
    mid, bb_up, bb_dn = bollinger_bands(df["close"], bb_len, bb_mult)
    tr = (df["high"]-df["low"]).ewm(alpha=1/float(kc_len), adjust=False).mean()
    kc_up, kc_dn = mid + kc_mult*tr, mid - kc_mult*tr
    in_sq = (bb_up < kc_up) & (bb_dn > kc_dn)
    release = in_sq.shift(1).fillna(False) & (~in_sq)
    sig=[]
    if bool(release.iloc[-1]): sig.append({"ts":df.index[-1],"side":"long","strength":8.0,"reason":{"squeeze":"release"}})
    return {"series":{"bb_up":bb_up,"bb_dn":bb_dn,"kc_up":kc_up,"kc_dn":kc_dn},"signals":sig,"context":{"tf":tf}}

# =========================
# 8) Donchian (Breakouts)
# =========================
def donchian_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    length = int((params or {}).get("length",20))
    up = df["high"].rolling(length).max()
    dn = df["low"].rolling(length).min()
    sig=[]
    if bool(df["close"].iloc[-1] > up.shift(1).iloc[-1]): sig.append({"ts":df.index[-1],"side":"long","strength":8.0,"reason":{"donchian":"breakout"}})
    if bool(df["close"].iloc[-1] < dn.shift(1).iloc[-1]): sig.append({"ts":df.index[-1],"side":"short","strength":8.0,"reason":{"donchian":"breakdown"}})
    return {"series":{"upper":up,"lower":dn},"signals":sig,"context":{"tf":tf}}

# ======================
# 9) Anchored VWAP (פשוט)
# ======================
def avwap_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    tp = (df["high"]+df["low"]+df["close"])/3.0
    v  = df["volume"].replace(0,np.nan)
    vwap = (tp*v).cumsum()/v.cumsum()
    return {"series":{"avwap":vwap},"signals":[],"context":{"tf":tf}}

# ==========================
# 10) Chandelier Exit (SL)
# ==========================
def chandelier_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    atr_len = int((params or {}).get("atr_len",22)); mult = float((params or {}).get("mult",3.0))
    a = atr(df, atr_len)
    ce_long  = df["high"].rolling(1).max() - mult*a
    ce_short = df["low"].rolling(1).min()  + mult*a
    return {"series":{"ce_long":ce_long,"ce_short":ce_short},"signals":[],"context":{"tf":tf}}

# ==============================
# 11) Volatility Regime (Classifier)
# ==============================
def vol_regime_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    look = int((params or {}).get("look",100))
    c = df["close"].astype(float)
    ret = c.pct_change().abs()
    # ספי percentiles (33/66) על חלון look
    p = ret.rolling(look).quantile([0.33,0.66]).unstack()
    lo, hi = p[0.33], p[0.66]
    state = ret.rolling(10).mean()
    cur = state.iloc[-1]
    regime = "low" if cur<=lo.iloc[-1] else ("high" if cur>=hi.iloc[-1] else "med")
    return {"series":{"state":state},"signals":[],"context":{"tf":tf,"regime":regime}}

# ======================
# 12) CVD / Delta Bars
# ======================
def cvd_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    """
    feeds יכול להכיל: delta_per_bar: pd.Series (אם כבר אגרת aggTrades בעצמך)
    אם לא – נבצע fallback גס (לא מומלץ לייצור) על 1000 aggTrades אחרונים.
    """
    delta = feeds.get("delta_per_bar")
    if isinstance(delta, pd.Series) and len(delta)==len(df):
        cvd_s = delta.cumsum()
        last = float(delta.iloc[-1])
    else:
        # Fallback: משתמש ב-aggTrades live אחרונים (גס)
        last = 0.0
        try:
            last = compute_cvd_from_trades(feeds.get("symbol","BTCUSDT"))
        except Exception:
            pass
        cvd_s = pd.Series(np.nan, index=df.index)
    sig=[]
    if last>0: sig.append({"ts":df.index[-1],"side":"long","strength":8.1,"reason":{"cvd":"buying_pressure"}})
    if last<0: sig.append({"ts":df.index[-1],"side":"short","strength":8.1,"reason":{"cvd":"selling_pressure"}})
    return {"series":{"cvd":cvd_s}, "signals":sig, "context":{"tf":tf}}

# =========================
# 13) OI Impulse / Divergence
# =========================
def oi_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    """
    צפה ל-feeds['oi_df'] עם עמודה 'oi' מסונכרנת (אותו index או reindex).
    """
    oi_df: Optional[pd.DataFrame] = feeds.get("oi_df")
    if oi_df is None or "oi" not in oi_df.columns:
        return {"series":{}, "signals":[], "context":{"note":"supply oi_df"}}
    oi = pd.to_numeric(oi_df["oi"], errors="coerce").astype(float).reindex(df.index).ffill()
    c  = pd.to_numeric(df["close"], errors="coerce").astype(float)
    z = (oi - oi.rolling(20).mean())/(oi.rolling(20).std(ddof=0)+1e-9)
    impulse = (z.abs()>2.0)
    div = ((c.diff()>0) & (oi.diff()<0)) | ((c.diff()<0)&(oi.diff()>0))
    sig=[]
    if bool(impulse.iloc[-1]): sig.append({"ts":df.index[-1],"side":"long" if c.iloc[-1]>c.iloc[-2] else "short","strength":8.2,"reason":{"oi":"impulse"}})
    if bool(div.fillna(False).iloc[-1]): sig.append({"ts":df.index[-1],"side":"neutral","strength":7.5,"reason":{"oi":"divergence"}})
    return {"series":{"z_oi":z},"signals":sig,"context":{"tf":tf}}

# ======================
# 14) Funding Bias (יש לך)
# ======================
async def funding_bias_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    symbol = str(feeds.get("symbol","BTCUSDT")).upper()
    side = feeds.get("side")  # אופציונלי
    data = await _funding_bias(symbol, side)
    sig=[]
    # דוגמת סיגנל: קיצון מימון => משקל קונטרה
    if abs(float(data.get("factor",0.0))) >= float(data.get("max_bias",0.25))*0.8:
        s = "short" if data["direction"]=="SHORT" else ("long" if data["direction"]=="LONG" else None)
        if s: sig.append({"ts":df.index[-1],"side":s,"strength":7.8,"reason":{"funding":"extreme_bias"}})
    return {"series":{"funding_rate": data.get("rate",0.0)}, "signals":sig, "context":data}

# ============================
# 15) Perp–Spot Basis (Premium)
# ============================
def basis_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    """
    feeds: df_spot['price'], df_mark['markPrice'] – מסונכרנים (reindex לפי df.index)
    """
    spot = feeds.get("df_spot"); mark = feeds.get("df_mark")
    if spot is None or mark is None or "price" not in spot.columns or "markPrice" not in mark.columns:
        return {"series":{}, "signals":[], "context":{"note":"supply df_spot & df_mark"}}
    s = pd.to_numeric(spot["price"], errors="coerce").astype(float).reindex(df.index).ffill()
    m = pd.to_numeric(mark["markPrice"], errors="coerce").astype(float).reindex(df.index).ffill()
    bp = (m - s) / s * 100.0
    z = (bp - bp.rolling(96).mean())/(bp.rolling(96).std(ddof=0)+1e-9)
    sig=[]
    if abs(float(z.iloc[-1]))>2.0:
        side = "short" if z.iloc[-1]>0 else "long"
        sig.append({"ts":df.index[-1],"side":side,"strength":7.9,"reason":{"basis":"extreme"}})
    return {"series":{"basis_pct":bp,"zscore":z},"signals":sig,"context":{"tf":tf}}

# =========================
# 6) Invictus-like Composite
# =========================
def invictus_compute(df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    c = pd.to_numeric(df["close"], errors="coerce").astype(float)
    v = pd.to_numeric(df["volume"], errors="coerce").astype(float)
    e21, e50 = ema(c,21), ema(c,50)
    trend = (e21 > e50).astype(int)
    obv = (np.sign(c.diff().fillna(0))*v).cumsum()
    obv_ma = obv.ewm(span=20, adjust=False).mean()
    strength = 7.0 + 1.5*float(trend.iloc[-1]) + 0.5*float(obv.iloc[-1] > obv_ma.iloc[-1])
    side = "long" if (trend.iloc[-1]==1 and obv.iloc[-1]>obv_ma.iloc[-1]) else ("short" if trend.iloc[-1]==0 and obv.iloc[-1]<obv_ma.iloc[-1] else None)
    sig = [{"ts":df.index[-1],"side":side,"strength":strength,"reason":{"invictus":"composite"}}] if side else []
    return {"series":{"ema21":e21,"ema50":e50,"obv":obv,"obv_ma":obv_ma}, "signals":sig, "context":{"tf":tf,"trend":int(trend.iloc[-1])}}

# ============
# REGISTRY API
# ============
_REGISTRY: Dict[str, Callable[..., dict]] = {
    "mc_b": mc_b_compute,           # 1
    "mc_a": mc_a_compute,           # 2
    "alpha": supertrend_compute,    # 3
    "qqe": qqe_compute,             # 4
    "smc": smc_compute,             # 5
    "invictus": invictus_compute,   # 6
    "squeeze": squeeze_bb_kc_compute,# 7
    "donchian": donchian_compute,   # 8
    "avwap": avwap_compute,         # 9
    "chandelier": chandelier_compute,# 10
    "vol_regime": vol_regime_compute,# 11
    "cvd": cvd_compute,             # 12
    "oi": oi_compute,               # 13
    "funding": None,                # 14 (async)
    "basis": basis_compute,         # 15
}

def list_indicators() -> List[str]:
    return list(_REGISTRY.keys())

def run_indicator(name: str, df: pd.DataFrame, *, tf:str, params:dict|None=None, **feeds) -> dict:
    if name == "funding":
        # עטיפה אסינכרונית לשימוש חיצוני (await)
        raise RuntimeError("funding is async – use run_funding_async()")
    fn = _REGISTRY.get(name)
    if not callable(fn):
        raise KeyError(f"indicator not found: {name}")
    return fn(df, tf=tf, params=params or {}, **feeds)

async def run_funding_async(df: pd.DataFrame, *, tf:str, symbol:str, side:str|None=None, params:dict|None=None) -> dict:
    return await funding_bias_compute(df, tf=tf, params=params or {}, symbol=symbol, side=side)

def run_all(df: pd.DataFrame, *, tf:str, feeds:dict|None=None, subset:List[str]|None=None) -> Dict[str, dict]:
    names = subset or list_indicators()
    out: Dict[str, dict] = {}
    feeds = feeds or {}
    for n in names:
        if n == "funding":
            # השאר ל-callers אסינכרוני
            continue
        try:
            out[n] = run_indicator(n, df, tf=tf, **feeds)
        except Exception as e:
            out[n] = {"error": str(e)}
    return out









