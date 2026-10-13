/**
 * XAUTUSD Paper Trading Dashboard Frontend Controller
 * Connects to persistent backend endpoints and streams 24/7 market state.
 */

let selectedSide = "BUY";
let currentGoldPrice = 0.0;
let pollTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  setupSideSelector();
  setupOrderForm();
  setupActionButtons();
  
  // Initial fetch and start continuous polling (every 2.5 seconds)
  refreshAllData();
  pollTimer = setInterval(refreshAllData, 2500);

  // Initialize live WebSocket for instant tick streaming
  initWebSocket();
});

function setupSideSelector() {
  const buyBtn = document.querySelector(".btn-side.side-buy");
  const sellBtn = document.querySelector(".btn-side.side-sell");
  if (!buyBtn || !sellBtn) return;

  buyBtn.addEventListener("click", () => {
    selectedSide = "BUY";
    buyBtn.classList.add("active");
    sellBtn.classList.remove("active");
  });

  sellBtn.addEventListener("click", () => {
    selectedSide = "SELL";
    sellBtn.classList.add("active");
    buyBtn.classList.remove("active");
  });
}

function setupOrderForm() {
  const form = document.getElementById("orderForm");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const qty = parseFloat(document.getElementById("orderQty").value);
    const sl = parseFloat(document.getElementById("orderSL").value) || 0.0;
    const tp = parseFloat(document.getElementById("orderTP").value) || 0.0;
    const strategy = document.getElementById("orderStrategy").value.trim() || "Manual Paper Order";

    try {
      const resp = await fetch("/api/paper/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          direction: selectedSide,
          quantity: qty,
          stop_loss: sl,
          take_profit: tp,
          strategy: strategy
        })
      });
      const data = await resp.json();
      if (data.success) {
        alert("Paper order opened successfully!");
        refreshAllData();
      } else {
        alert("Order rejected: " + (data.message || "Unknown error"));
      }
    } catch (err) {
      alert("Error placing order: " + err.message);
    }
  });
}

function setupActionButtons() {
  const btnToggleAuto = document.getElementById("btnToggleAuto");
  if (btnToggleAuto) {
    btnToggleAuto.addEventListener("click", async () => {
      const isCurrentlyOn = btnToggleAuto.innerText.includes("ON");
      try {
        const resp = await fetch("/api/paper/toggle-auto", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: !isCurrentlyOn })
        });
        const data = await resp.json();
        updateAutoToggleBtn(data.auto_trading_enabled);
      } catch (err) {
        console.error("Failed to toggle auto trading:", err);
      }
    });
  }

  const btnReset = document.getElementById("btnResetAccount");
  if (btnReset) {
    btnReset.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to reset the simulated account balance to $10,000.00 USD? All open positions will be cleared.")) {
        return;
      }
      try {
        const resp = await fetch("/api/paper/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ balance: 10000.0 })
        });
        const data = await resp.json();
        if (data.success) {
          alert("Account reset successfully.");
          refreshAllData();
        } else {
          alert("Reset failed: " + (data.message || data.detail));
        }
      } catch (err) {
        alert("Reset failed: " + err.message);
      }
    });
  }
}

function updateAutoToggleBtn(enabled) {
  const btn = document.getElementById("btnToggleAuto");
  if (!btn) return;
  btn.innerHTML = `<span>Auto-Execute Signals: ${enabled ? "ON" : "OFF"}</span>`;
  if (enabled) {
    btn.style.color = "var(--teal-bull)";
    btn.style.borderColor = "rgba(38, 166, 154, 0.4)";
  } else {
    btn.style.color = "var(--text-dim)";
    btn.style.borderColor = "var(--border-subtle)";
  }
}

async function refreshAllData() {
  try {
    // 1. Fetch Summary
    const summaryResp = await fetch("/api/paper/summary");
    if (summaryResp.ok) {
      const json = await summaryResp.json();
      renderSummary(json.data);
    }

    // 2. Fetch Open Positions
    const posResp = await fetch("/api/paper/positions");
    if (posResp.ok) {
      const json = await posResp.json();
      renderPositions(json.positions || []);
    }

    // 3. Fetch Closed Trades
    const tradesResp = await fetch("/api/paper/trades?limit=50");
    if (tradesResp.ok) {
      const json = await tradesResp.json();
      renderTrades(json.trades || []);
    }

    // 4. Fetch Logs
    const logsResp = await fetch("/api/paper/logs?limit=30");
    if (logsResp.ok) {
      const json = await logsResp.json();
      renderLogs(json.logs || []);
    }

    const clock = document.getElementById("lastRefreshTime");
    if (clock) {
      const now = new Date();
      clock.innerText = `Updated at ${now.toLocaleTimeString()}`;
    }
  } catch (err) {
    console.warn("Paper dashboard data refresh error:", err);
  }
}

function renderSummary(s) {
  if (!s) return;
  document.getElementById("statBalance").innerText = formatCurrency(s.balance);
  document.getElementById("statEquity").innerText = formatCurrency(s.equity);

  const unPnl = document.getElementById("statUnrealizedPnl");
  unPnl.innerText = (s.total_unrealized_pnl >= 0 ? "+" : "") + formatCurrency(s.total_unrealized_pnl);
  unPnl.className = `kpi-value ${s.total_unrealized_pnl >= 0 ? "highlight" : "pnl-negative"}`;

  const rePnl = document.getElementById("statRealizedPnl");
  rePnl.innerText = (s.total_realized_pnl >= 0 ? "+" : "") + formatCurrency(s.total_realized_pnl);
  rePnl.className = `kpi-value ${s.total_realized_pnl >= 0 ? "highlight" : "pnl-negative"}`;

  document.getElementById("statTradesCount").innerText = `${s.total_trades} Trades Closed`;
  document.getElementById("statWinRate").innerText = `${s.win_rate_pct}%`;
  document.getElementById("statWinRatio").innerText = `${s.winning_trades}W / ${s.losing_trades}L (PF: ${s.profit_factor})`;

  if (s.last_evaluated_price > 0) {
    currentGoldPrice = s.last_evaluated_price;
    document.getElementById("statGoldPrice").innerText = formatCurrency(currentGoldPrice);
  }

  updateAutoToggleBtn(s.auto_trading_enabled);
}

function renderPositions(positions) {
  const tbody = document.getElementById("positionsTbody");
  const countEl = document.getElementById("openCount");
  if (countEl) countEl.innerText = positions.length;

  if (!positions.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No open positions currently. Monitoring market 24/7 for SMC setups.</td></tr>`;
    return;
  }

  tbody.innerHTML = positions.map(p => {
    const isPnlPositive = p.unrealized_pnl >= 0;
    const pnlClass = isPnlPositive ? "pnl-positive" : "pnl-negative";
    const sign = isPnlPositive ? "+" : "";

    return `
      <tr>
        <td><strong>${p.symbol}</strong></td>
        <td><span class="badge-side ${p.direction}">${p.direction}</span></td>
        <td>${p.quantity} oz</td>
        <td>$${p.entry_price.toFixed(2)}</td>
        <td>$${p.current_price.toFixed(2)}</td>
        <td>${p.stop_loss > 0 ? '$' + p.stop_loss.toFixed(2) : '--'}</td>
        <td>${p.take_profit > 0 ? '$' + p.take_profit.toFixed(2) : '--'}</td>
        <td class="${pnlClass}">${sign}$${p.unrealized_pnl.toFixed(2)} (${sign}${p.unrealized_pnl_pct.toFixed(2)}%)</td>
        <td title="${p.strategy}">${p.strategy.length > 25 ? p.strategy.substring(0, 25) + '...' : p.strategy}</td>
        <td>
          <button class="btn-close-pos" onclick="closePosition('${p.id}')">Close</button>
        </td>
      </tr>
    `;
  }).join("");
}

function renderTrades(trades) {
  const tbody = document.getElementById("tradesTbody");
  if (!trades.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty-state">No closed trade records yet. Completed trades will persist here across server restarts.</td></tr>`;
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const isWin = t.net_pnl >= 0;
    const pnlClass = isWin ? "pnl-positive" : "pnl-negative";
    const sign = isWin ? "+" : "";
    const durationMin = Math.round(t.duration_seconds / 60);

    return `
      <tr>
        <td><code>${t.id.substring(0, 10)}</code></td>
        <td><span class="badge-side ${t.direction}">${t.direction}</span></td>
        <td>${t.quantity} oz</td>
        <td>$${t.entry_price.toFixed(2)}</td>
        <td>$${t.exit_price.toFixed(2)}</td>
        <td class="${pnlClass}">${sign}$${t.net_pnl.toFixed(2)}</td>
        <td class="${pnlClass}">${sign}${t.realized_pnl_pct.toFixed(2)}%</td>
        <td>${durationMin} min</td>
        <td><span class="badge-lock" style="background: rgba(255,255,255,0.05); color: #cbd5e1; border-color: #334155;">${t.exit_reason}</span></td>
        <td>${t.exit_time_ist}</td>
        <td title="${t.strategy}">${t.strategy.length > 25 ? t.strategy.substring(0, 25) + '...' : t.strategy}</td>
      </tr>
    `;
  }).join("");
}

function renderLogs(logs) {
  const stream = document.getElementById("logStream");
  if (!logs.length) return;

  stream.innerHTML = logs.map(l => {
    return `<div class="log-line ${l.level.toLowerCase()}">[${l.timestamp_ist}] [${l.category}] ${l.message}</div>`;
  }).join("");
}

async function closePosition(posId) {
  if (!confirm(`Close paper position ${posId} at market price?`)) return;
  try {
    const resp = await fetch("/api/paper/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_id: posId })
    });
    const data = await resp.json();
    if (data.success) {
      refreshAllData();
    } else {
      alert("Error: " + data.message);
    }
  } catch (err) {
    alert("Error closing position: " + err.message);
  }
}

function initWebSocket() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${proto}//${window.location.host}/ws`;

  try {
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.event === "candle_update" && msg.candle) {
          currentGoldPrice = msg.candle.close;
          const goldPriceEl = document.getElementById("statGoldPrice");
          if (goldPriceEl) goldPriceEl.innerText = formatCurrency(currentGoldPrice);

          // Update default SL & TP inputs in order form if empty
          const slInput = document.getElementById("orderSL");
          const tpInput = document.getElementById("orderTP");
          if (slInput && !slInput.value) {
            slInput.value = (currentGoldPrice * (selectedSide === "BUY" ? 0.995 : 1.005)).toFixed(2);
          }
          if (tpInput && !tpInput.value) {
            tpInput.value = (currentGoldPrice * (selectedSide === "BUY" ? 1.01 : 0.99)).toFixed(2);
          }
        }
      } catch (err) {}
    };
    ws.onclose = () => {
      setTimeout(initWebSocket, 5000);
    };
  } catch (e) {
    console.warn("WebSocket init error:", e);
  }
}

function formatCurrency(val) {
  if (val === undefined || val === null || isNaN(val)) return "$0.00";
  return "$" + Number(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
