// api/proxy.js
/**
 * Binance REST + WebSocket Proxy
 * Deploys on Vercel Edge (Workers runtime)
 */

export default {
  async fetch(req) {
    try {
      const url = new URL(req.url);

      // --- אם זה WebSocket ---
      if (url.pathname.startsWith("/api/proxy/ws")) {
        const target = url.searchParams.get("target");
        if (!target || !target.startsWith("wss://")) {
          return new Response("Missing ?target=wss://...", { status: 400 });
        }

        const upgradeHeader = req.headers.get("upgrade") || "";
        if (upgradeHeader.toLowerCase() !== "websocket") {
          return new Response("Expected WebSocket", { status: 426 });
        }

        const { 0: client, 1: server } = Object.values(new WebSocketPair());

        // חיבור ל־Binance
        const upstream = new WebSocket(target, {
          headers: { "User-Agent": "AlgoGPT-Proxy" },
        });

        upstream.addEventListener("message", (msg) => server.send(msg.data));
        upstream.addEventListener("close", () => server.close());
        upstream.addEventListener("error", (err) => {
          console.error("WS Proxy error:", err);
          server.close();
        });

        server.addEventListener("message", (msg) => upstream.send(msg.data));
        server.accept();

        return new Response(null, { status: 101, webSocket: client });
      }

      // --- REST Proxy ---
      const targetBase = url.pathname.startsWith("/api/proxy/fapi")
        ? "https://fapi.binance.com"
        : "https://api.binance.com";

      const targetUrl = targetBase + url.pathname.replace("/api/proxy", "") + url.search;

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
      return new Response(
        JSON.stringify({ error: "Proxy error", detail: String(err) }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    }
  },
};


