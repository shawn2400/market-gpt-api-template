export default async function handler(req, res) {
  try {
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/api\/proxy/, "");
    const target = "https://fapi.binance.com" + path + url.search;

    const r = await fetch(target, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        "User-Agent": "AlgoGPT-Proxy"
      }
    });

    const data = await r.text();

    res.status(r.status).send(data);
  } catch (err) {
    res.status(500).json({ error: "Proxy error", details: err.message });
  }
}
