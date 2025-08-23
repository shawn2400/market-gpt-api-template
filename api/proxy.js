// api/proxy.js
/**
 * Binance Proxy for REST + WebSocket
 * Deploys on Vercel Worker runtime
 */

export default {
  async fetch(req) {
    try {
      const url = new URL(req.url);

      // בסיס Binance
      const targetBase = url.pathname.startsWith("/api/proxy/fapi")
        ? "https://fapi.binance.com"
        : "https://api.binance.com";

      // מסלול חדש ל־Binance
      const targetUrl = targetBase + url.pathname.replace("/api/proxy", "") + url.search;

      // מעביר את הבקשה כמו שהיא
      const resp = await fetch(targetUrl, {
        method: req.method,
        headers: {
          "User-Agent": "AlgoGPT-Proxy",
          "Content-Type": "application/json",
        },
        body: req.method !== "GET" ? await req.text() : undefined,
      });

      return new Response(resp.body, {
        status: resp.status,
        headers: {
          "Content-Type": resp.headers.get("content-type") || "application/json",
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: "Proxy error", detail: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};

