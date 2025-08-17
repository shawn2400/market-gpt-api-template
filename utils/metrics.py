# utils/metrics.py

from datetime import datetime
import time
import psutil
import platform
import os

# לוגיקה פנימית לניטור ביצועים
class MetricsTracker:
    def __init__(self):
        self.start_time = time.time()
        self.total_trades_executed = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.total_errors = 0

    def record_trade(self, pnl: float):
        self.total_trades_executed += 1
        if pnl >= 0:
            self.total_profit += pnl
        else:
            self.total_loss += abs(pnl)

    def record_error(self):
        self.total_errors += 1

    def get_metrics(self):
        uptime_sec = int(time.time() - self.start_time)
        process = psutil.Process(os.getpid())
        memory = process.memory_info().rss / 1024**2
        cpu = process.cpu_percent(interval=0.1)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_sec": uptime_sec,
            "total_trades_executed": self.total_trades_executed,
            "total_profit": round(self.total_profit, 2),
            "total_loss": round(self.total_loss, 2),
            "total_errors": self.total_errors,
            "cpu_usage_percent": round(cpu, 2),
            "memory_usage_mb": round(memory, 2),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        }


# מחזיר instance אחיד של המעקב
metrics_tracker = MetricsTracker()
