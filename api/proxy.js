// api/proxy.js
export default {
  async fetch(request) {
    try {
      const url = new URL(request.url);

      // ניתוב כל מה שבא אחרי /api/proxy/
      if (url.pathname.startsWith("/api/proxy/")) {
        const targetPath = url.pathname.replace("/api/proxy", "");
        const fullUrl = `https://fapi.binance.com${targetPath}${url.search}`;

        const resp = await fetch(fullUrl, {
          method: request.method,
          headers: { "User-Agent": "AlgoGPT-Proxy" }
        });

        return new Response(resp.body, {
          status: resp.status,
          headers: {
            "content-type": resp.headers.get("content-type") || "application/json"
          }
        });
      }

      return new Response(JSON.stringify({ error: "Not found" }), { status: 404 });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err) }), { status: 500 });
    }
  }
};




