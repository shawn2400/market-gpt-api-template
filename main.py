# main.py (excerpt – החלף את בלוק טענת הראוטרים וההוספה ל-app)
from routes.ai import router as ai_router
from routes.trade import router as trade_router

def _try_import(name: str, attr: str = "router"):
    try:
        module = __import__(name, fromlist=[attr])
        return getattr(module, attr)
    except Exception as exc:
        logger.warning("%s not loaded: %s", name, exc)
        return None

backtest_router   = _try_import("routes.backtest")
scan_router       = _try_import("routes.scan")
ai_analyze_router = _try_import("routes.ai_analyze")
ai_health_router  = _try_import("routes.ai_health")
health_router     = _try_import("routes.health_full") or _try_import("routes.health")
dashboard_router  = _try_import("routes.dashboard")
price_router      = _try_import("routes.price")
indicators_router = _try_import("routes.routes_indicators")
market_router     = _try_import("routes.market")       # /symbols/top-volume
analytics_router  = _try_import("routes.analytics")    # /analytics/*, /sentiment/*, /eta/*
news_router       = _try_import("routes.news")         # /news/*
decision_router   = _try_import("routes.decision")     # /decision/*

app = FastAPI(
    title="AlgoGPT API",
    description="AlgoGPT — מסחר אלגוריתמי בזמן אמת ל־Binance Futures",
    version=APP_VERSION,
)

# ... CORS, static, middlewares & handlers כמו אצלך ...

@app.get("/", operation_id="getRootStatus", tags=["Config"])
def root():
    return {"status": "ok", "version": app.version}

@app.get("/metrics", operation_id="getBasicMetrics", tags=["Config"])
async def get_metrics():
    return metrics_tracker.get_metrics()

# חובה
app.include_router(ai_router,    prefix="/ai",    tags=["AI"])
app.include_router(trade_router, prefix="/trade", tags=["Trades"])

# אופציונליים
for r in [
    ai_analyze_router, ai_health_router, scan_router, backtest_router,
    dashboard_router, health_router, price_router, indicators_router,
    market_router, analytics_router, news_router, decision_router
]:
    if r: app.include_router(r)































































































































































































































































































