/**
 * XAUTUSD Dedicated Paper Trading Dashboard Client
 * Real-time monitoring, institutional metrics, and isolated execution controls
 */

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // Formatting helpers
  const fmtMoney = (n) =>
    "$" + Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtSignedMoney = (n) => {
    const val = Number(n || 0);
    const sign = val > 0 ? "+" : val < 0 ? "-" : "";
    return sign + "$" + Math.abs(val).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const fmtQty = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: 6 }));

  const fmtTime = (ts) => {
    if (!ts) return "—";
    const d = new Date(Number(ts) * 1000);
    return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString("en-US", { hour12: false }) + " (" + d.toLocaleDateString() + ")";
  };

  // State
  let paperState = null;
  let activeTab = "trades";
  let isPolling = false;

  async function api(url, method = "GET", data = null) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (data && (method === "POST" || method === "PUT")) {
      opts.body = JSON.stringify(data);
    }
    const res = await fetch(url, opts);
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }
    return res.json();
  }

  // --- RENDER PIPELINE ---

  function renderStatus(s, tickResult = null) {
    if (!s) return;
    paperState = s;
    const m = s.metrics || {};
    const md = s.market_data || {};
    const state = s.engine_state || "STOPPED";
    const isEmergency = Boolean(s.emergency_stop);

    // 1. Header market pills
    $("hdrPrice").textContent = md.last_price ? fmtMoney(md.last_price) : "—";
    const feedStatus = md.status || "DISCONNECTED";
    $("hdrFeedStatus").textContent = feedStatus;
    $("hdrFeedStatus").className = "status-indicator " + feedStatus.toLowerCase();
    $("hdrLastUpdate").textContent = md.last_price_ts ? fmtTime(md.last_price_ts) : "—";

    // Header summary
    $("hdrEquity").textContent = fmtMoney(m.current_equity || s.equity);
    const uPnl = Number(m.unrealized_pnl || 0);
    const rPnl = Number(m.realized_pnl || 0);
    const dPnl = Number(m.daily_pnl || 0);

    $("hdrUnrealized").textContent = fmtSignedMoney(uPnl);
    $("hdrUnrealized").className = "mono-val " + (uPnl > 0 ? "text-bull" : uPnl < 0 ? "text-bear" : "");

    $("hdrRealized").textContent = fmtSignedMoney(rPnl);
    $("hdrRealized").className = "mono-val " + (rPnl > 0 ? "text-bull" : rPnl < 0 ? "text-bear" : "");

    $("hdrDaily").textContent = fmtSignedMoney(dPnl);
    $("hdrDaily").className = "mono-val " + (dPnl > 0 ? "text-bull" : dPnl < 0 ? "text-bear" : "");

    // Engine badge
    const badge = $("engineStatusBadge");
    if (isEmergency) {
      badge.textContent = "KILL SWITCH ACTIVE";
      badge.className = "badge-engine killed";
    } else if (state === "RUNNING") {
      badge.textContent = "RUNNING";
      badge.className = "badge-engine running";
    } else if (state === "PAUSED") {
      badge.textContent = "PAUSED";
      badge.className = "badge-engine paused";
    } else {
      badge.textContent = "STOPPED";
      badge.className = "badge-engine stopped";
    }

    // 2. Banner Notification
    const banner = $("paperBanner");
    const bannerText = $("bannerText");
    const bannerIcon = $("bannerIcon");
    if (isEmergency) {
      banner.className = "paper-banner danger";
      bannerIcon.textContent = "🚨";
      bannerText.textContent = "EMERGENCY STOP IS ACTIVE. All new simulated entries are locked. Clear Stop Lock to reset.";
    } else if (md.is_stale) {
      banner.className = "paper-banner warning";
      bannerIcon.textContent = "⚠️";
      bannerText.textContent = "MARKET DATA IS STALE OR DISCONNECTED. Simulated entries are halted until fresh prices arrive.";
    } else if (state === "RUNNING") {
      banner.className = "paper-banner";
      bannerIcon.textContent = "🟢";
      bannerText.textContent = "Paper engine running. Actively monitoring for confirmed ACTIVE setups in XAUTUSD.";
    } else if (state === "PAUSED") {
      banner.className = "paper-banner warning";
      bannerIcon.textContent = "⏸️";
      bannerText.textContent = "Engine paused: new entries are blocked. Existing open positions continue to monitor SL/TP.";
    } else {
      banner.className = "paper-banner";
      bannerIcon.textContent = "⏹️";
      bannerText.textContent = "Paper engine stopped. Press 'Start Paper Engine' to activate automated simulation.";
    }

    // 3. Controls button state
    $("btnStart").disabled = isEmergency || state === "RUNNING";
    $("btnStop").disabled = state === "STOPPED" && !isEmergency;
    $("btnEmergencyStop").disabled = isEmergency;

    if (state === "PAUSED") {
      $("btnPause").style.display = "none";
      $("btnResume").style.display = "inline-block";
      $("btnResume").disabled = isEmergency;
    } else {
      $("btnPause").style.display = "inline-block";
      $("btnPause").disabled = isEmergency || state !== "RUNNING";
      $("btnResume").style.display = "none";
    }

    $("btnResetStop").style.display = isEmergency ? "inline-block" : "none";
    $("btnCloseAll").disabled = !s.open_positions || s.open_positions.length === 0;

    // 4. Account Overview Cards
    $("cardStartBalance").textContent = fmtMoney(m.starting_equity || (s.config && s.config.starting_equity) || 10000);
    $("cardCurrentEquity").textContent = fmtMoney(m.current_equity || s.equity);
    $("cardAvailableBalance").textContent = fmtMoney(m.available_balance != null ? m.available_balance : s.equity);

    $("cardUnrealizedPnl").textContent = fmtSignedMoney(uPnl);
    $("cardUnrealizedPnl").className = "stat-value " + (uPnl > 0 ? "text-bull" : uPnl < 0 ? "text-bear" : "");

    $("cardRealizedPnl").textContent = fmtSignedMoney(rPnl);
    $("cardRealizedPnl").className = "stat-value " + (rPnl > 0 ? "text-bull" : rPnl < 0 ? "text-bear" : "");

    $("cardDailyPnl").textContent = fmtSignedMoney(dPnl);
    $("cardDailyPnl").className = "stat-value " + (dPnl > 0 ? "text-bull" : dPnl < 0 ? "text-bear" : "");
    $("cardDailyPnlPct").textContent = (m.daily_pnl_pct >= 0 ? "+" : "") + Number(m.daily_pnl_pct || 0).toFixed(2) + "% today";

    $("cardOpenCount").textContent = s.counts ? s.counts.open : 0;
    $("openPosBadge").textContent = (s.counts ? s.counts.open : 0) + " Active";
    $("cardMaxPosLimit").textContent = `Max ${s.config ? s.config.max_positions : 1} allowed`;

    const completedCount = s.counts ? s.counts.completed : (s.trades ? s.trades.length : 0);
    $("cardCompletedCount").textContent = completedCount;

    $("cardWinRate").textContent = (m.win_rate || 0).toFixed(1) + "%";
    const wins = s.trades ? s.trades.filter((t) => Number(t.net_pnl || 0) > 0).length : 0;
    $("cardWinLoss").textContent = `${wins} wins / ${completedCount} trades`;

    $("cardProfitFactor").textContent = m.profit_factor || "—";
    $("cardMaxDrawdown").textContent = (m.max_drawdown_pct || 0).toFixed(2) + "%";
    $("cardMaxDrawdownAmt").textContent = fmtMoney(m.max_drawdown_amount || 0) + " from peak";

    // 5. Confirmed Signal Panel
    renderSignalPanel(tickResult, s);

    // 6. Open Positions Table
    renderPositions(s.open_positions || []);

    // 7. Trades & Orders
    renderTrades(s.trades || []);
    renderOrders(s.orders || []);

    // 8. Events
    renderEvents(s.events || []);
    $("eventCountBadge").textContent = (s.events ? s.events.length : 0) + " Events";
  }

  function renderSignalPanel(tickResult, s) {
    const setup = tickResult ? tickResult.active_setup : null;
    const terminal = tickResult ? tickResult.terminal_state : null;
    const decision = tickResult ? tickResult.decision : null;

    if (!setup || Object.keys(setup).length === 0) {
      $("sigSetupId").textContent = "—";
      $("sigDirection").textContent = "—";
      $("sigState").textContent = terminal && terminal.setup_state ? terminal.setup_state : "IDLE";
      $("sigEntryZone").textContent = "—";
      $("sigEntryPrice").textContent = "—";
      $("sigStopLoss").textContent = "—";
      $("sigTakeProfit").textContent = "—";
      $("sigRrRatio").textContent = "—";
      $("sigActivationTime").textContent = "—";

      $("signalEligibilityTag").textContent = "NO ACTIVE SETUP";
      $("signalEligibilityTag").className = "eligibility-tag";
      $("sigDiagnosticText").textContent =
        "SMC engine currently reports no active setup. Only signals confirmed strictly with state ACTIVE are eligible for paper entry.";
      return;
    }

    $("sigSetupId").textContent = setup.id || "—";
    const dir = String(setup.direction || "").toUpperCase();
    $("sigDirection").textContent = dir === "BULLISH" ? "LONG (Bullish)" : dir === "BEARISH" ? "SHORT (Bearish)" : dir;
    $("sigDirection").className = "field-value " + (dir === "BULLISH" ? "text-bull" : "text-bear");

    const st = setup.state || (terminal ? terminal.setup_state : "—");
    $("sigState").textContent = st;
    $("sigState").className = "field-value " + (st === "ACTIVE" ? "text-bull" : "text-bear");

    const top = setup.top ? fmtMoney(setup.top) : "—";
    const btm = setup.bottom ? fmtMoney(setup.bottom) : "—";
    $("sigEntryZone").textContent = `${btm} – ${top}`;

    $("sigEntryPrice").textContent = setup.price ? fmtMoney(setup.price) : "—";
    $("sigStopLoss").textContent = setup.invalidation_price ? fmtMoney(setup.invalidation_price) : "—";
    $("sigTakeProfit").textContent = setup.target_price ? fmtMoney(setup.target_price) : "—";
    $("sigRrRatio").textContent = setup.rr_ratio ? Number(setup.rr_ratio).toFixed(2) + " R:R" : "—";
    $("sigActivationTime").textContent = setup.activation_time ? fmtTime(setup.activation_time) : fmtTime(setup.timestamp);

    // Diagnostic & Eligibility evaluation
    const tag = $("signalEligibilityTag");
    const diag = $("sigDiagnosticText");

    if (decision && decision.accepted) {
      tag.textContent = "ACCEPTED & EXECUTED";
      tag.className = "eligibility-tag eligible";
      diag.textContent = `Setup ${setup.id} successfully initiated paper position #${decision.position_id}.`;
    } else if (decision && !decision.accepted) {
      const reason = decision.reason || "REJECTED";
      if (reason === "DUPLICATE_SETUP") {
        tag.textContent = "ALREADY POSITIONED";
        tag.className = "eligibility-tag";
        diag.textContent = `Setup ${setup.id} has already been executed. Duplicate entry prevented.`;
      } else if (reason.includes("NOT_ACTIVE")) {
        tag.textContent = "INELIGIBLE (NOT ACTIVE)";
        tag.className = "eligibility-tag rejected";
        diag.textContent = `Setup status is ${st}. Only setups confirmed strictly as ACTIVE are eligible.`;
      } else if (reason === "PRICE_OUTSIDE_ENTRY_ZONE") {
        tag.textContent = "WAITING FOR ZONE";
        tag.className = "eligibility-tag waiting";
        diag.textContent = `Current market price is outside entry zone [${btm} – ${top}]. Entry deferred.`;
      } else if (reason === "ENGINE_STOPPED") {
        tag.textContent = "ENGINE STOPPED";
        tag.className = "eligibility-tag";
        diag.textContent = "Paper engine is currently stopped. Start engine to allow automated entries.";
      } else if (reason === "ENGINE_PAUSED") {
        tag.textContent = "ENGINE PAUSED";
        tag.className = "eligibility-tag waiting";
        diag.textContent = "Engine is paused. New simulated entries are temporarily blocked.";
      } else if (reason === "MAX_POSITIONS") {
        tag.textContent = "MAX POSITIONS REACHED";
        tag.className = "eligibility-tag rejected";
        diag.textContent = "Maximum concurrent positions limit reached. Blocked from opening additional trades.";
      } else {
        tag.textContent = "REJECTED";
        tag.className = "eligibility-tag rejected";
        diag.textContent = `Entry rejected by risk management: ${reason}`;
      }
    } else {
      tag.textContent = "EVALUATING";
      tag.className = "eligibility-tag";
      diag.textContent = `Monitoring setup ${setup.id} in ${st} state.`;
    }
  }

  function renderPositions(positions) {
    const tbody = $("tbodyPositions");
    tbody.innerHTML = "";

    if (!positions || positions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="13" class="empty-state">No open simulated positions.</td></tr>';
      return;
    }

    positions.forEach((pos) => {
      const tr = document.createElement("tr");
      const uPnl = Number(pos.unrealized_pnl || 0);
      const uPnlPct = Number(pos.unrealized_pnl_pct || 0);
      const pnlCls = uPnl > 0 ? "text-bull" : uPnl < 0 ? "text-bear" : "";

      tr.innerHTML = `
        <td title="${pos.id}">${pos.id.slice(0, 8)}…</td>
        <td>${pos.setup_id}</td>
        <td class="${pos.direction === "LONG" ? "text-bull" : "text-bear"}">${pos.direction}</td>
        <td>${fmtMoney(pos.entry_price)}</td>
        <td>${fmtMoney(pos.current_price)}</td>
        <td>${fmtQty(pos.quantity)}</td>
        <td>${fmtMoney(pos.notional)}</td>
        <td class="text-bear">${fmtMoney(pos.stop_loss)}</td>
        <td class="text-bull">${fmtMoney(pos.take_profit)}</td>
        <td class="${pnlCls}">${fmtSignedMoney(uPnl)} (${uPnlPct >= 0 ? "+" : ""}${uPnlPct.toFixed(2)}%)</td>
        <td>${fmtMoney(pos.entry_fee)}</td>
        <td>${fmtTime(pos.created_at)}</td>
        <td><button class="btn-table-action btn-close-pos" data-id="${pos.id}">Close</button></td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".btn-close-pos").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-id");
        if (confirm("Close this simulated position at current market price?")) {
          try {
            await api(`/api/paper/positions/${id}/close`, "POST");
            await refresh(false);
          } catch (e) {
            alert("Failed to close position: " + e.message);
          }
        }
      };
    });
  }

  function renderTrades(trades) {
    const tbody = $("tbodyTrades");
    tbody.innerHTML = "";

    const filterText = ($("filterSearch").value || "").trim().toLowerCase();
    const filterDir = $("filterDirection").value;

    const filtered = (trades || []).filter((t) => {
      if (filterDir !== "ALL" && t.direction !== filterDir) return false;
      if (filterText && !t.setup_id.toLowerCase().includes(filterText) && !t.id.toLowerCase().includes(filterText)) {
        return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="12" class="empty-state">No matching completed trades found.</td></tr>';
      return;
    }

    filtered.forEach((t) => {
      const tr = document.createElement("tr");
      const net = Number(t.net_pnl || 0);
      const gross = Number(t.gross_pnl || 0);
      const fees = Number(t.entry_fee || 0) + Number(t.exit_fee || 0);
      const pnlCls = net > 0 ? "text-bull" : net < 0 ? "text-bear" : "";

      tr.innerHTML = `
        <td title="${t.id}">${t.id.slice(0, 8)}…</td>
        <td>${t.setup_id}</td>
        <td class="${t.direction === "LONG" ? "text-bull" : "text-bear"}">${t.direction}</td>
        <td>${fmtMoney(t.entry_price)}</td>
        <td>${fmtMoney(t.exit_price)}</td>
        <td>${fmtQty(t.quantity)}</td>
        <td>${fmtSignedMoney(gross)}</td>
        <td>${fmtMoney(fees)}</td>
        <td class="${pnlCls}">${fmtSignedMoney(net)}</td>
        <td><span class="mono-code">${t.exit_reason || "CLOSED"}</span></td>
        <td>${fmtTime(t.created_at)}</td>
        <td>${fmtTime(t.closed_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderOrders(orders) {
    const tbody = $("tbodyOrders");
    tbody.innerHTML = "";

    const filterText = ($("filterSearch").value || "").trim().toLowerCase();
    const filterDir = $("filterDirection").value;

    const filtered = (orders || []).filter((o) => {
      const dirMatch = filterDir === "ALL" || (filterDir === "LONG" ? o.side === "BUY" : o.side === "SELL");
      if (!dirMatch) return false;
      if (filterText && !o.setup_id.toLowerCase().includes(filterText) && !o.id.toLowerCase().includes(filterText)) {
        return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No matching simulated orders found.</td></tr>';
      return;
    }

    filtered.forEach((o) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td title="${o.id}">${o.id.slice(0, 8)}…</td>
        <td>${o.setup_id}</td>
        <td class="${o.side === "BUY" ? "text-bull" : "text-bear"}">${o.side}</td>
        <td>${o.order_type}</td>
        <td>${fmtMoney(o.requested_price)}</td>
        <td>${fmtMoney(o.fill_price)}</td>
        <td>${fmtQty(o.quantity)}</td>
        <td><span class="mono-code">${o.status}</span></td>
        <td>${fmtMoney(o.fee)}</td>
        <td>${fmtTime(o.created_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderEvents(events) {
    const tbody = $("tbodyEvents");
    tbody.innerHTML = "";

    if (!events || events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No execution events recorded.</td></tr>';
      return;
    }

    events.slice(0, 100).forEach((e) => {
      const tr = document.createElement("tr");
      let detailStr = "";
      if (typeof e.detail === "object") {
        detailStr = Object.entries(e.detail)
          .map(([k, v]) => `${k}: ${typeof v === "number" ? Number(v).toFixed(4) : v}`)
          .join(" · ");
      } else {
        detailStr = String(e.detail);
      }

      tr.innerHTML = `
        <td>${fmtTime(e.ts)}</td>
        <td><strong class="mono-code">${e.kind}</strong></td>
        <td>${e.setup_id || "—"}</td>
        <td>${detailStr}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // --- REFRESH & TICK LOOP ---

  async function refresh(runTick = true) {
    if (isPolling) return;
    isPolling = true;
    try {
      if (runTick) {
        const tickData = await api("/api/paper/tick", "POST");
        renderStatus(tickData.status, tickData);
      } else {
        const statusData = await api("/api/paper/status", "GET");
        renderStatus(statusData);
      }
    } catch (err) {
      console.warn("Paper poll error:", err.message);
      $("bannerText").textContent = "API connection error: " + err.message;
      $("paperBanner").className = "paper-banner danger";
    } finally {
      isPolling = false;
    }
  }

  // Controls helper
  async function sendControl(action, payload = null) {
    try {
      const res = await api(`/api/paper/control/${action}`, "POST", payload);
      if (!res.success) {
        alert("Action failed: " + res.message);
      }
      await refresh(false);
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  // --- EVENT HANDLERS ---

  $("btnStart").onclick = () => sendControl("start");
  $("btnPause").onclick = () => sendControl("pause");
  $("btnResume").onclick = () => sendControl("resume");
  $("btnStop").onclick = () => sendControl("stop");
  $("btnManualTick").onclick = () => refresh(true);

  $("btnDemoTrade").onclick = async () => {
    try {
      const res = await api("/api/paper/simulate-demo-trade", "POST");
      if (res.decision && res.decision.accepted) {
        alert("Demo trade executed! Position opened at $" + Number(res.decision.entry_price).toFixed(2));
      } else {
        alert("Could not open demo trade: " + (res.decision ? res.decision.reason : "unknown"));
      }
      await refresh(false);
    } catch (e) {
      alert("Error: " + e.message);
    }
  };

  $("btnEmergencyStop").onclick = () => {
    if (confirm("EMERGENCY STOP:\n\nImmediately halt all new paper entries and engage the kill switch?\nExisting open positions will remain open unless closed separately.")) {
      sendControl("emergency-stop");
    }
  };

  $("btnResetStop").onclick = () => {
    if (confirm("Clear emergency stop lock? The engine will remain STOPPED until manually started.")) {
      sendControl("reset-stop");
    }
  };

  $("btnCloseAll").onclick = () => {
    if (confirm("Close ALL open simulated positions at current market price?")) {
      sendControl("close-all");
    }
  };

  // Reset Modal
  $("btnResetAccount").onclick = () => {
    $("modalResetConfirm").style.display = "flex";
  };
  $("btnCloseResetModal").onclick = () => {
    $("modalResetConfirm").style.display = "none";
  };
  $("btnCancelReset").onclick = () => {
    $("modalResetConfirm").style.display = "none";
  };
  $("btnConfirmReset").onclick = async () => {
    $("modalResetConfirm").style.display = "none";
    await sendControl("reset", { confirm: true });
  };

  // Config Modal
  $("btnOpenConfig").onclick = async () => {
    try {
      const cfg = await api("/api/paper/config", "GET");
      $("cfgStartingEquity").value = cfg.starting_equity || 10000;
      $("cfgRiskFraction").value = cfg.risk_fraction || 0.0025;
      $("cfgDailyLossFraction").value = cfg.daily_loss_fraction || 0.01;
      $("cfgMaxPositions").value = cfg.max_positions || 1;
      $("cfgMaxNotional").value = cfg.max_notional || 2500;
      $("cfgFeeRate").value = cfg.fee_rate || 0.0005;
      $("cfgSlippageBps").value = cfg.slippage_bps || 5;
      $("modalConfig").style.display = "flex";
    } catch (e) {
      alert("Failed to load config: " + e.message);
    }
  };
  $("btnCloseConfigModal").onclick = () => {
    $("modalConfig").style.display = "none";
  };
  $("btnCancelConfig").onclick = () => {
    $("modalConfig").style.display = "none";
  };
  $("btnSaveConfig").onclick = async () => {
    const payload = {
      starting_equity: parseFloat($("cfgStartingEquity").value),
      risk_fraction: parseFloat($("cfgRiskFraction").value),
      daily_loss_fraction: parseFloat($("cfgDailyLossFraction").value),
      max_positions: parseInt($("cfgMaxPositions").value, 10),
      max_notional: parseFloat($("cfgMaxNotional").value),
      fee_rate: parseFloat($("cfgFeeRate").value),
      slippage_bps: parseFloat($("cfgSlippageBps").value),
    };
    try {
      const res = await api("/api/paper/config", "POST", payload);
      if (res.success) {
        $("modalConfig").style.display = "none";
        await refresh(false);
      } else {
        alert("Config error: " + res.message);
      }
    } catch (e) {
      alert("Error saving config: " + e.message);
    }
  };

  // Tabs
  $("tabBtnTrades").onclick = () => {
    activeTab = "trades";
    $("tabBtnTrades").className = "tab-btn active";
    $("tabBtnOrders").className = "tab-btn";
    $("viewTrades").style.display = "block";
    $("viewOrders").style.display = "none";
    if (paperState) renderTrades(paperState.trades);
  };

  $("tabBtnOrders").onclick = () => {
    activeTab = "orders";
    $("tabBtnTrades").className = "tab-btn";
    $("tabBtnOrders").className = "tab-btn active";
    $("viewTrades").style.display = "none";
    $("viewOrders").style.display = "block";
    if (paperState) renderOrders(paperState.orders);
  };

  // Filters
  $("filterSearch").oninput = () => {
    if (activeTab === "trades") renderTrades(paperState ? paperState.trades : []);
    else renderOrders(paperState ? paperState.orders : []);
  };
  $("filterDirection").onchange = () => {
    if (activeTab === "trades") renderTrades(paperState ? paperState.trades : []);
    else renderOrders(paperState ? paperState.orders : []);
  };

  $("btnClearAuditFilter").onclick = () => {
    if (paperState) renderEvents(paperState.events);
  };

  // Initial load & 4-second poll loop
  refresh(true);
  setInterval(() => refresh(true), 4000);
})();
