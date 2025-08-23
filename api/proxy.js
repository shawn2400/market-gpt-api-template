// api/proxy.js

export default {
  async fetch(request) {
    try {
      const url = new URL(request.url);

      // נחפש אם זה קריאה ל־REST של Binance
      if (url.pathname.startsWith("/api/proxy/")) {
        const target = url.pathname.replace("/api/proxy", "");
        const fullUrl = `https://fapi.binance.com${target}${url.search}`;

        const resp = await fetch(fullUrl, {
          method: request.method,
          headers: { "User-Agent": "AlgoGPT-Proxy" }
        });

        return new Response(resp.body, {
          status: resp.status,
          headers: { "content-type": resp.headers.get("content-type") || "application/json" }
        });
      }

      // WebSocket proxy
      if (url.pathname === "/api/proxy/ws") {
        const target = url.searchParams.get("target");
        if (!target) {
          return new Response(JSON.stringify({ error: "Missing target" }), { status: 400 });
        }
        return fetch(target, request); // pass-through upgrade
      }

      return new Response(JSON.stringify({ error: "Not found" }), { status: 404 });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
    }
  }
};




