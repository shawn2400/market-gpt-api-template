import os, time, math
from typing import List
from binance.client import Client
from binance.exceptions import BinanceAPIException

# ===== ENV =====
K=os.getenv("BINANCE_API_KEY","").strip(); S=os.getenv("BINANCE_API_SECRET","").strip()
assert K and S, "BINANCE_API_KEY/SECRET missing"

SYM=os.getenv("SYMBOL","BTCUSDT").strip() or "BTCUSDT"

# BE / TP
BE_BPS=float(os.getenv("BE_BPS","5"))                        # 5bps=0.05%
TP_PCTS=[float(x) for x in (os.getenv("TP_PCTS","3,6,10,16")).split(",") if x.strip()]
TP_SPLITS=[float(x) for x in (os.getenv("TP_SPLITS","0.25,0.25,0.25,0.25")).split(",") if x.strip()]

# ATR/ADX trail
ATR_LEN=int(os.getenv("ATR_LEN","14"))
ADX_LEN=int(os.getenv("ADX_LEN","14"))
ADX_MIN=float(os.getenv("AUTO_TRAIL_ADX_MIN","14"))
ATR_MULT=float(os.getenv("TRAIL_ATR_MULT","1.6"))           # מרחק SL = ATR*mult
ATR_MAX_FRAC=float(os.getenv("AUTO_TRAIL_ATRPCT_MAX","0.015")) # ATR/Price cap
HYST_ATR_FRAC=float(os.getenv("HYSTERESIS_ATR_FRAC","0.2"))
SL_MIN_BPS=float(os.getenv("SL_MIN_STEP_BPS","3"))
POLL=float(os.getenv("POLL_SEC","5"))

cli=Client(K,S)

def _filters(sym):
    ex=cli.futures_exchange_info(); tick=0.1; step=0.001
    for s in ex.get("symbols",[]):
        if s.get("symbol")==sym:
            for f in s.get("filters",[]):
                if f.get("filterType")=="PRICE_FILTER": tick=float(f["tickSize"])
                if f.get("filterType")=="LOT_SIZE":     step=float(f["stepSize"])
            break
    return tick, step

def _fmt(v, step):
    s=f"{step:.10f}".rstrip("0"); d=len(s.split(".")[1]) if "." in s else 0
    return f"{v:.{d}f}"

def _rto(v, step, up):  # round to step
    q=v/step
    return (math.ceil(q)*step) if up else (math.floor(q)*step)

def _mark(sym):
    m=cli.futures_mark_price(symbol=sym)
    return float(m.get("markPrice") or m.get("price") or 0.0)

def _klines_close(sym, interval="15m", limit=200):
    kl=cli.futures_klines(symbol=sym, interval=interval, limit=limit)
    # [openTime,open,high,low,close,...]
    highs=[float(x[2]) for x in kl]; lows=[float(x[3]) for x in kl]; closes=[float(x[4]) for x in kl]
    return highs,lows,closes

def _atr_adx(sym)->tuple[float,float,float]:
    try:
        import pandas as pd
    except Exception:
        return float("nan"), float("nan"), float("nan")
    highs,lows,closes=_klines_close(sym, os.getenv("DEFAULT_INTERVAL","15m"), 200)
    if len(closes)<max(ATR_LEN,ADX_LEN)+2: return float("nan"), float("nan"), float("nan")
    import pandas as pd
    df=pd.DataFrame({"high":highs,"low":lows,"close":closes})
    # ATR
    tr = pd.concat([
        (df["high"]-df["low"]).abs(),
        (df["high"]-df["close"].shift(1)).abs(),
        (df["low"] -df["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_LEN).mean().iloc[-1]
    # ADX (פשטני, מספיק לשער)
    up_move=df["high"].diff(); dn_move=(-df["low"].diff())
    plus_dm = ((up_move>dn_move)&(up_move>0))*up_move
    minus_dm=((dn_move>up_move)&(dn_move>0))*dn_move
    tr14 = tr.rolling(ADX_LEN).mean()
    pdi=100*(plus_dm.rolling(ADX_LEN).mean()/tr14).iloc[-1]
    mdi=100*(minus_dm.rolling(ADX_LEN).mean()/tr14).iloc[-1]
    dx = 100*abs(pdi-mdi)/max(pdi+mdi,1e-9)
    adx = pd.Series(dx).rolling(ADX_LEN).mean().iloc[-1] if hasattr(dx,'rolling') else dx
    return float(closes[-1]), float(atr), float(adx)

def _position(sym):
    for p in cli.futures_position_information(symbol=sym):
        amt=float(p.get("positionAmt") or 0.0)
        if abs(amt)>1e-12:
            return amt, float(p.get("entryPrice") or 0.0)
    return 0.0,0.0

def _cancel_reduce_only(sym):
    try:
        for od in cli.futures_get_open_orders(symbol=sym):
            if str(od.get("reduceOnly")).lower()=="true":
                try: cli.futures_cancel_order(symbol=sym, orderId=od["orderId"])
                except: pass
    except: pass

def _current_be_sl(sym):
    try:
        for o in cli.futures_get_open_orders(symbol=sym):
            t=str(o.get("type","")).upper()
            if t in ("STOP","STOP_MARKET") and str(o.get("closePosition","false")).lower()=="true":
                return float(o.get("stopPrice") or 0.0)
    except: pass
    return None

def _place_be(sym, long, entry, tick):
    mult=1.0+(BE_BPS/10000.0)
    be_raw=entry*(mult if long else 1.0/mult)
    m=_mark(sym)
    be=_rto(be_raw, tick, up=long)
    # clamp נגד -2021
    if long and be>=m:    be=_rto(m - tick, tick, up=False)
    if (not long) and be<=m: be=_rto(m + tick, tick, up=True)
    try:
        # החלפת SL closePosition ישן
        for o in cli.futures_get_open_orders(symbol=sym):
            if str(o.get("type","")).upper() in ("STOP","STOP_MARKET") and str(o.get("closePosition","false")).lower()=="true":
                try: cli.futures_cancel_order(symbol=sym, orderId=o["orderId"])
                except: pass
        cli.futures_create_order(
            symbol=sym, side=("SELL" if long else "BUY"),
            type="STOP_MARKET", stopPrice=f"{be:.1f}",
            closePosition=True, workingType="MARK_PRICE")
        print(f"BE OK @ {be:.1f}")
        return be
    except BinanceAPIException as e:
        print("BE ERROR:", e); return None

def _tp_ladder(sym,long,entry,tick,step,qty_abs,pcts:List[float],splits:List[float]):
    if len(splits)!=len(pcts):
        n=len(pcts); splits=[1.0/n]*n
    _cancel_reduce_only(sym)
    rem=qty_abs
    for i,(pct,w) in enumerate(zip(pcts,splits),start=1):
        q=max(0.0, math.floor((qty_abs*w)/step)*step)
        q=min(q, math.floor(rem/step)*step)
        if q<=0: continue
        rem=max(0.0, rem-q)
        trg = entry*(1.0 + pct/100.0) if long else entry*(1.0 - pct/100.0)
        trg = _rto(trg, tick, up=long)
        try:
            cli.futures_create_order(
                symbol=sym, side=("SELL" if long else "BUY"),
                type="TAKE_PROFIT_MARKET", stopPrice=_fmt(trg,tick),
                quantity=_fmt(q,step), reduceOnly=True, workingType="MARK_PRICE",
                newClientOrderId=f"TP{i}"
            )
            print(f"TP{i} OK @ {trg:.1f} qty={q}")
        except BinanceAPIException as e:
            print(f"TP{i} ERROR:", e)

def _hyst_ok(prev,new,atr_abs,ref,side):
    if prev is None: return True
    # SL לא נסוג לאחור
    if side=="BUY" and new<prev: return False
    if side=="SELL" and new>prev: return False
    step_abs=max(HYST_ATR_FRAC*max(atr_abs,0.0), (SL_MIN_BPS/10000.0)*max(ref,1e-9))
    return abs(new - prev) >= step_abs

def main():
    amt, entry = _position(SYM)
    if amt==0.0: print("no_open_position"); return
    long = amt>0
    side = "BUY" if long else "SELL"
    tick, step = _filters(SYM)
    qty_abs=abs(amt)

    # 1) BE (אם עוד לא קיים/חסר)
    cur=_current_be_sl(SYM)
    if cur is None:
        cur=_place_be(SYM,long,entry,tick)

    # 2) TP ladder פעם אחת
    _tp_ladder(SYM,long,entry,tick,step,qty_abs,TP_PCTS,TP_SPLITS)

    last_sl=cur
    armed = cur is not None
    while True:
        try:
            px, atr_abs, adx = _atr_adx(SYM)
            if not (math.isfinite(px) and math.isfinite(atr_abs) and math.isfinite(adx)):
                time.sleep(POLL); continue
            if atr_abs<=0: time.sleep(POLL); continue

            # gate: ATR סביר יחסית למחיר + ADX מינימלי
            if (atr_abs/px)<=ATR_MAX_FRAC and adx>=ADX_MIN and armed:
                # טרייל ATR*mult
                target = px - ATR_MULT*atr_abs if long else px + ATR_MULT*atr_abs
                # לא מתחת ל-BE בלונג / לא מעל BE בשורט
                be_floor = entry*(1.0 + (BE_BPS/10000.0)*(1 if long else -1))
                target = max(target, be_floor) if long else min(target, be_floor)

                m=_mark(SYM)
                # צביטה נגד -2021
                if long and target>=m:    target=_rto(m - tick, tick, up=False)
                if (not long) and target<=m: target=_rto(m + tick, tick, up=True)

                if _hyst_ok(last_sl, target, atr_abs, px, side):
                    # החלפה ל-SL חדש כ-closePosition
                    try:
                        for o in cli.futures_get_open_orders(symbol=SYM):
                            if str(o.get("type","")).upper() in ("STOP","STOP_MARKET") and str(o.get("closePosition","false")).lower()=="true":
                                try: cli.futures_cancel_order(symbol=SYM, orderId=o["orderId"])
                                except: pass
                        cli.futures_create_order(
                            symbol=SYM, side=("SELL" if long else "BUY"),
                            type="STOP_MARKET", stopPrice=f"{target:.1f}",
                            closePosition=True, workingType="MARK_PRICE"
                        )
                        print(f"[trail] SL -> {target:.1f} (px={px:.1f}, ATR={atr_abs:.1f}, ADX={adx:.1f})")
                        last_sl=target
                    except BinanceAPIException as e:
                        print("trail place error:", e)
        except Exception as e:
            print("loop err:", e)
        time.sleep(POLL)

if __name__=="__main__":
    main()
