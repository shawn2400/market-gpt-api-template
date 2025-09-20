import React, { useEffect, useState } from "react";

const API_BASE = (window.API_BASE || "").replace(/\/+$/,"") || "";

function authHeaders() {
  const tok = window.API_TOKEN || "";
  return {
    "X-API-Key": tok,
    "Authorization": "Bearer " + tok,
  };
}

async function jget(path) {
  const r = await fetch(API_BASE + path, { headers: authHeaders() });
  return r.json();
}

export default function App() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [activeGrids, setActiveGrids] = useState([]);
  const [trades, setTrades] = useState([]);
  const [pnl, setPnl] = useState(null);

  useEffect(() => {
    jget("/ui/grid/accounts")
      .then(data => {
        if (data.ok) {
          setAccounts(data.accounts || []);
          if (data.accounts?.length) setAccountId(data.accounts[0]);
        }
      })
      .catch(console.error);
  }, []);

  const loadData = () => {
    if (!accountId) return;
    jget(`/ui/grid/active?account_id=${encodeURIComponent(accountId)}`)
      .then(d => setActiveGrids(d.active || []))
      .catch(console.error);

    jget(`/ui/grid/trades?account_id=${encodeURIComponent(accountId)}`)
      .then(d => setTrades(d.trades || []))
      .catch(console.error);

    jget(`/ui/grid/pnl?account_id=${encodeURIComponent(accountId)}`)
      .then(d => setPnl(d.summary || null))
      .catch(console.error);
  };

  useEffect(() => { loadData(); }, [accountId]);

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <h1 className="text-2xl font-bold mb-4">AlgoGPT Grid Dashboard</h1>

      <div className="mb-6">
        <label className="mr-2">בחר חשבון:</label>
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          className="bg-gray-800 border border-gray-600 p-2 rounded"
        >
          {accounts.map((acc) => (
            <option key={acc} value={acc}>{acc}</option>
          ))}
        </select>
        <button
          onClick={loadData}
          className="ml-4 bg-blue-600 px-3 py-1 rounded hover:bg-blue-500"
        >
          רענן
        </button>
      </div>

      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-2">גרידים פעילים</h2>
        {activeGrids.length === 0 ? (
          <p>אין גרידים פעילים.</p>
        ) : (
          <table className="w-full border-collapse border border-gray-700">
            <thead>
              <tr className="bg-gray-800">
                <th className="p-2 border border-gray-700">Symbol</th>
                <th className="p-2 border border-gray-700">Orders</th>
              </tr>
            </thead>
            <tbody>
              {activeGrids.map((g, i) => (
                <tr key={i} className="hover:bg-gray-800">
                  <td className="p-2 border border-gray-700">{g.symbol}</td>
                  <td className="p-2 border border-gray-700">{g.orders ? g.orders.length : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-2">טריידים</h2>
        {trades.length === 0 ? (
          <p>אין טריידים להצגה.</p>
        ) : (
          <table className="w-full border-collapse border border-gray-700 text-sm">
            <thead>
              <tr className="bg-gray-800">
                <th className="p-2 border border-gray-700">ID</th>
                <th className="p-2 border border-gray-700">Symbol</th>
                <th className="p-2 border border-gray-700">Side</th>
                <th className="p-2 border border-gray-700">Entry</th>
                <th className="p-2 border border-gray-700">SL</th>
                <th className="p-2 border border-gray-700">TP</th>
                <th className="p-2 border border-gray-700">PNL</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i} className="hover:bg-gray-800">
                  <td className="p-2 border border-gray-700">{t.trade_id}</td>
                  <td className="p-2 border border-gray-700">{t.symbol}</td>
                  <td className="p-2 border border-gray-700">{t.side}</td>
                  <td className="p-2 border border-gray-700">{t.entry_price}</td>
                  <td className="p-2 border border-gray-700">{t.stop_price}</td>
                  <td className="p-2 border border-gray-700">{t.tp_prices?.join(", ")}</td>
                  <td className="p-2 border border-gray-700">{t.realized_pnl}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-2">סיכום PnL</h2>
        {!pnl ? (
          <p>אין נתונים.</p>
        ) : (
          <pre className="bg-gray-800 p-4 rounded">{JSON.stringify(pnl, null, 2)}</pre>
        )}
      </div>
    </div>
  );
}



