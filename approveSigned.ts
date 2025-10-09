// approveSigned.ts
import crypto from "crypto";

// קריאת env: אפשר להשתמש באחד מהם
const HOST = process.env.PUBLIC_HOST ?? "https://algogpt-docker.onrender.com";
const HMAC_SECRET = process.env.OPS_SIGN_SECRET || process.env.WEBHOOK_HMAC_SECRET; // חובה

// עוזר: חתימת HMAC-SHA256 (מפתח יכול להיות hex או טקסט)
function signHex(secret: string, timestamp: string, nonce: string, body: Buffer): string {
  const key = secret.length === 64 && /^[0-9a-fA-F]+$/.test(secret)
    ? Buffer.from(secret, "hex")
    : Buffer.from(secret, "utf8");
  const h = crypto.createHmac("sha256", key);
  h.update(Buffer.from(`${timestamp}.${nonce}.`, "utf8"));
  h.update(body);
  return h.digest("hex");
}

function randNonce(bytes = 8) {
  return crypto.randomBytes(bytes).toString("hex");
}

export type ApproveTicket = {
  ticket_id?: string;
  symbol: string;              // לדוגמה: "BTCUSDT"
  side: "BUY" | "SELL";
  qty?: number;                // אופציונלי — השרת יבצע sizing אוטומטי אם מוגדר
  leverage?: number;           // אופציונלי — מומלץ לספק
  position_side?: "LONG" | "SHORT" | "BOTH";
  tp1?: number; tp2?: number; tp3?: number;
  sl?: number;
  tp_splits?: number[];        // לדוגמה: [0.4,0.35,0.25]
  note?: string;               // אפשר לכלול [mode: HYBRID] / [mode: MARKET] וכו'
  expiry_ts?: number;          // יוניקס (שניות) — אם יש
  // שדות נוספים לפי הצורך…
};

export async function approveSigned(ticket: ApproveTicket, opts?: { timeoutMs?: number }) {
  if (!HMAC_SECRET) throw new Error("Missing OPS_SIGN_SECRET/WEBHOOK_HMAC_SECRET");
  const url = `${HOST}/ops/approve/signed`;
  const ts = Math.floor(Date.now() / 1000).toString();
  const nonce = randNonce(8);
  const bodyBuf = Buffer.from(JSON.stringify(ticket), "utf8");
  const sig = signHex(HMAC_SECRET, ts, nonce, bodyBuf);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts?.timeoutMs ?? 15000);

  try {
    const res = await fetch(url, {
      method: "POST",
      body: bodyBuf,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sig,
      },
    });

    const text = await res.text();
    let json: any = null;
    try { json = JSON.parse(text); } catch {}

    // טיפול שיטתי בשגיאות נפוצות
    if (res.status === 409) throw new Error("Replay detected (nonce reuse). Try again with a new nonce.");
    if (res.status === 401) throw new Error("Signature rejected (check secret, timestamp skew, or body).");
    if (res.status === 400) throw new Error(`Bad request: ${text}`);
    if (res.status >= 500) throw new Error(`Server error ${res.status}: ${text}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text}`);

    return json ?? text;
  } finally {
    clearTimeout(timeout);
  }
}

// דוגמה לשימוש
(async () => {
  const ticket: ApproveTicket = {
    ticket_id: "T_demo_123",
    symbol: "BTCUSDT",
    side: "BUY",
    qty: 0,                // אפשר 0 — השרת יבצע sizing אוטומטי אם מוגדר
    leverage: 5,
    tp1: 1.8, tp2: 3.2, tp3: 5.5,
    sl: 1.2,
    tp_splits: [0.4, 0.35, 0.25],
    note: "[mode: HYBRID] auto from bot",
  };
  const res = await approveSigned(ticket);
  console.log("Approve response:", res);
})();
