# utils/metrics.py (המשך לקוד שלך)

class _Metrics:
    ...
    def render_prometheus(self) -> str:
        """
        החזרת metrics בפורמט Prometheus
        """
        now = int(time.time())
        lines = []
        with self._lock:
            # Counters
            lines.append(f'algogpt_uptime_seconds {now - self.boot_ts}')
            lines.append(f'algogpt_requests_total {self.total_requests}')
            lines.append(f'algogpt_errors_total {self.total_errors}')

            # לפי קוד סטטוס
            for sc, count in self.by_status.items():
                lines.append(f'algogpt_requests_status_total{{status="{sc}"}} {count}')

            # לפי method
            for m, count in getattr(self, "by_method", {}).items():
                lines.append(f'algogpt_requests_method_total{{method="{m}"}} {count}')

            # לפי path
            for p, count in getattr(self, "by_path", {}).items():
                lines.append(f'algogpt_requests_path_total{{path="{p}"}} {count}')

            # Latency
            lat_list = list(self.latencies)
            if lat_list:
                avg = sum(lat_list) / len(lat_list)
                lines.append(f'algogpt_latency_ms_avg {avg:.3f}')
                lines.append(f'algogpt_latency_ms_min {min(lat_list):.3f}')
                lines.append(f'algogpt_latency_ms_max {max(lat_list):.3f}')
                lines.append(f'algogpt_latency_ms_p50 {self._median(lat_list):.3f}')
                lines.append(f'algogpt_latency_ms_p95 {self._percentile(lat_list,95):.3f}')

            # RPS
            tlist = list(self.recent_ts)
            cutoff_5 = time.time() - 5
            cutoff_60 = time.time() - 60
            r5 = sum(1 for t in tlist if t >= cutoff_5) / 5.0 if tlist else 0.0
            r60 = sum(1 for t in tlist if t >= cutoff_60) / 60.0 if tlist else 0.0
            lines.append(f'algogpt_rps_5s {r5:.3f}')
            lines.append(f'algogpt_rps_60s {r60:.3f}')

        return "\n".join(lines) + "\n"



