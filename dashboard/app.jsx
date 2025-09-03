import React, { useEffect, useState } from "react";

export default function App() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [activeGrids, setActiveGrids] = useState([]);
  const [trades, setTrades] = useState([]);
  const [pnl, setPnl] = useState(null);

  // טעינת חשבונות בהתחלה
  useEffect(() => {
    fetch("/ui/grid/accounts", {
      headers: { "Authorization": "Bearer " + (window.API_TOKEN || "") }
    })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          setAccounts(data.accounts || []);
          if (data.accounts && data.accounts.length > 0) {
            setAccountId(data.accounts[0]);
          }
        }
      })
      .catch(console.error);
  }, []);

  // טוען מידע לפי account_id
  const loadData = () => {
    if (!accountId) return;

    fetch(`/ui/grid/active?account_id=${accountId}`, {
      headers: { "Authorization": "Bearer " + (window.API_TOKEN || "") }
    })
      .then(r => r.json())
      .then(d => setActiveGrids(d.active || []))
      .catch(console.error);

    fetch(`/ui/grid/trades?account_id=${accountId}`, {
      headers: { "Authorization": "Bearer " + (window.API_TOKEN || "") }
    })
      .then(r => r.json())
      .then(d => setTrades(d.trades || []))
      .catch(console.error);

    fetch(`/ui/grid/pnl?account_id=${accountId}`, {
      headers: { "Authorization": "Bearer " + (window.API_TOKEN || "") }
    })
      .then(r => r.json())
      .then(d => setPnl(d.summary || null))
      .catch(console.error);
  };

  useEffect(() => {
    loadData();
  }, [accountId]);

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <h1 className="text-2xl font-bold mb-4">AlgoGPT Grid Dashboard</h1>

      {/* בחירת חשבון */}
      <div className="mb-6">
        <label className="mr-2">בחר חשבון:</label>
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value)}
          className="bg-gray-800 border border-gray-600 p-2 rounded"
        >
          {accounts.map((acc) => (
            <option key={acc} value={acc}>
              {acc}
            </option>
          ))}
        </select>
        <button
          onClick={loadData}
          className="ml-4 bg-blue-600 px-3 py-1 rounded hover:bg-blue-500"
        >
          רענן
        </button>
      </div>

      {/* גרידים פעילים */}
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
                  <td className="p-2 border border-gray-700">
                    {g.orders ? g.orders.length : 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* טריידים */}
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

      {/* סיכום PnL */}
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


