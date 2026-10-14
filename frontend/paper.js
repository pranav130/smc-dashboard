/**
 * XAUTUSD Dedicated Paper Trading Dashboard Client
 * Real-time monitoring, institutional metrics, dual decoupled SMC models,
 * risk & discipline HUD, rejection inspector, strategy lab, and forensic trade replay.
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
  let activeReplayPosId = null;
  let activeUpdateStopPosId = null;

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

  // --- THEME MANAGEMENT ---
  function initTheme() {
    const savedTheme = localStorage.getItem("smc_theme") || "dark";
    if (savedTheme === "light") {
      document.body.classList.add("light-theme");
    } else {
      document.body.classList.remove("light-theme");
    }

    const btn = $("btnPaperThemeToggle");
    if (btn) {
      btn.onclick = () => {
        const isLight = document.body.classList.toggle("light-theme");
        localStorage.setItem("smc_theme", isLight ? "light" : "dark");
      };
    }
  }

  // --- RENDER PIPELINE ---

  function renderStatus(s, tickResult = null) {
    if (!s) return;
    paperState = s;
    const m = s.metrics || {};
    const md = s.market_data || {};
    const state = s.engine_state || "STOPPED";
    const isEmergency = Boolean(s.emergency_stop);
    const rm = s.risk_manager || {};
    const disc = rm.discipline || {};

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
    } else if (rm.circuit_breaker_active) {
      banner.className = "paper-banner danger";
      bannerIcon.textContent = "🛑";
      bannerText.textContent = `RISK CIRCUIT BREAKER TRIGGERED: ${rm.circuit_breaker_reason || "Loss limits exceeded"}. Entries locked.`;
    } else if (disc.active_cooldown) {
      banner.className = "paper-banner warning";
      bannerIcon.textContent = "⏳";
      const remMins = Math.ceil((disc.cooldown_remaining_sec || 0) / 60);
      bannerText.textContent = `DISCIPLINE COOLDOWN ACTIVE (${disc.cooldown_type}): Paused for ${remMins}m to prevent revenge trading.`;
    } else if (md.is_stale) {
      banner.className = "paper-banner warning";
      bannerIcon.textContent = "⚠️";
      bannerText.textContent = "MARKET DATA IS STALE OR DISCONNECTED. Simulated entries are halted until fresh prices arrive.";
    } else if (state === "RUNNING") {
      banner.className = "paper-banner";
      bannerIcon.textContent = "🟢";
      bannerText.textContent = "Paper engine running. Actively monitoring for confirmed ACTIVE setups in XAUTUSD across decoupled Model A & B.";
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

    // 3.5 INSTITUTIONAL RISK & DISCIPLINE HUD RENDERING
    renderRiskHud(rm, m, s);

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

    // 5. Dual SMC Strategy Panels
    renderDualStrategyPanels(tickResult, s);

    // 6. Open Positions Table
    renderPositions(s.open_positions || []);

    // 7. Active Tab Views
    if (activeTab === "trades") renderTrades(s.trades || []);
    if (activeTab === "orders") renderOrders(s.orders || []);
    if (activeTab === "events") renderEvents(s.events || []);
  }

  // --- 3.5 RISK HUD RENDERER ---
  function renderRiskHud(rm, m, s) {
    const dailyLossPct = Number(rm.daily_loss_pct || 0);
    const dailyLimitPct = Number(rm.daily_loss_limit_pct || 1.0);
    const ddPct = Number(rm.drawdown_pct || m.max_drawdown_pct || 0);
    const ddLimitPct = Number(rm.drawdown_limit_pct || 5.0);
    const disc = rm.discipline || {};

    // 1. Daily Loss Circuit Breaker
    $("hudDailyLossStat").textContent = `${dailyLossPct.toFixed(2)}% / ${dailyLimitPct.toFixed(2)}%`;
    const dailyRatio = Math.min(100, Math.max(0, (dailyLossPct / dailyLimitPct) * 100));
    const dailyFill = $("hudDailyLossFill");
    dailyFill.style.width = `${dailyRatio}%`;
    dailyFill.className = "hud-progress-fill " + (dailyRatio >= 100 ? "danger" : dailyRatio >= 70 ? "warn" : "");

    const startingEq = Number(m.starting_equity || (s.config && s.config.starting_equity) || 10000);
    const maxDailyLossDollars = (startingEq * dailyLimitPct) / 100;
    const currentDailyLossDollars = (startingEq * dailyLossPct) / 100;
    $("hudDailyLossDesc").textContent = `$${currentDailyLossDollars.toFixed(2)} loss of $${maxDailyLossDollars.toFixed(2)} max`;

    // 2. Drawdown Circuit Breaker
    $("hudDrawdownStat").textContent = `${ddPct.toFixed(2)}% / ${ddLimitPct.toFixed(2)}%`;
    const ddRatio = Math.min(100, Math.max(0, (ddPct / ddLimitPct) * 100));
    const ddFill = $("hudDrawdownFill");
    ddFill.style.width = `${ddRatio}%`;
    ddFill.className = "hud-progress-fill " + (ddRatio >= 100 ? "danger" : ddRatio >= 70 ? "warn" : "");

    const ddAmt = Number(m.max_drawdown_amount || 0);
    $("hudDrawdownDesc").textContent = `$${ddAmt.toFixed(2)} from peak`;
    const ddTag = $("hudDrawdownTag");
    if (ddRatio >= 100) {
      ddTag.textContent = "BREACHED (LOCKED)";
      ddTag.className = "hud-status-tag danger";
    } else if (ddRatio >= 70) {
      ddTag.textContent = "WARNING";
      ddTag.className = "hud-status-tag warn";
    } else {
      ddTag.textContent = "HEALTHY";
      ddTag.className = "hud-status-tag safe";
    }

    // 3. Anti-Revenge & Discipline Protocol
    const discTag = $("hudDisciplineTag");
    const cdVal = $("hudCooldownVal");
    const quotaVal = $("hudDailyQuotaVal");
    const consecVal = $("hudConsecLossesVal");

    quotaVal.textContent = `${disc.trades_today || 0} / ${disc.daily_quota_max || 3} Trades`;
    consecVal.textContent = String(disc.consecutive_losses || 0);

    if (disc.active_cooldown) {
      const remSec = disc.cooldown_remaining_sec || 0;
      const mLeft = Math.floor(remSec / 60);
      const sLeft = remSec % 60;
      cdVal.textContent = `${disc.cooldown_type} (${mLeft}m ${sLeft}s)`;
      cdVal.className = "disc-val text-bear";
      $("hudDisciplineStat").textContent = "PAUSED (COOLDOWN)";
      discTag.textContent = "PAUSED";
      discTag.className = "hud-status-tag warn";
    } else if ((disc.trades_today || 0) >= (disc.daily_quota_max || 3)) {
      cdVal.textContent = "Quota Exceeded";
      $("hudDisciplineStat").textContent = "QUOTA REACHED";
      discTag.textContent = "QUOTA LOCKED";
      discTag.className = "hud-status-tag warn";
    } else {
      cdVal.textContent = "None (Ready)";
      cdVal.className = "disc-val text-bull";
      $("hudDisciplineStat").textContent = "READY";
      discTag.textContent = "CLEAR";
      discTag.className = "hud-status-tag safe";
    }

    // Global HUD Badge
    const hudBadge = $("hudStatusBadge");
    const hudStatusText = $("hudStatusText");
    if (rm.circuit_breaker_active || isEmergency) {
      hudBadge.className = "hud-badge danger";
      hudStatusText.textContent = "CIRCUIT BREAKER ENGAGED";
    } else if (disc.active_cooldown) {
      hudBadge.className = "hud-badge";
      hudStatusText.textContent = "DISCIPLINE COOLDOWN ACTIVE";
    } else {
      hudBadge.className = "hud-badge";
      hudStatusText.textContent = "ALL SAFEGUARDS NORMAL";
    }
  }

  // --- 5. DUAL STRATEGY PANELS RENDERER ---
  function renderDualStrategyPanels(tickResult, s) {
    const modelA = tickResult ? tickResult.model_a_setup : null;
    const modelB = tickResult ? tickResult.model_b_setup : null;
    const activeSetup = tickResult ? tickResult.active_setup : null;
    const decision = tickResult ? tickResult.decision : null;

    // Helper to render checklist item
    const setChk = (id, passed) => {
      const el = $(id);
      if (!el) return;
      el.className = "checklist-item " + (passed ? "passed" : "failed");
      const icon = el.querySelector(".chk-icon");
      if (icon) icon.textContent = passed ? "✓" : "○";
    };

    // Render Model A
    const bA = $("modelAStatusBadge");
    if (modelA && modelA.id) {
      $("modelADirection").textContent = modelA.direction || "—";
      $("modelADirection").className = "field-value mono-val " + (modelA.direction === "LONG" ? "text-bull" : "text-bear");
      $("modelAEntry").textContent = modelA.price ? fmtMoney(modelA.price) : "—";
      $("modelAStop").textContent = modelA.invalidation_price ? fmtMoney(modelA.invalidation_price) : "—";
      $("modelATarget").textContent = modelA.target_price ? fmtMoney(modelA.target_price) : "—";
      $("modelARr").textContent = modelA.rr_ratio ? `${Number(modelA.rr_ratio).toFixed(2)} R:R` : "—";
      $("modelASetupId").textContent = modelA.id || "—";

      bA.textContent = modelA.state || "CANDIDATE";
      bA.className = "strat-status-badge " + (modelA.state === "ACTIVE" ? "active" : "candidate");

      const diag = modelA.diagnostics || {};
      setChk("chkADailyBias", diag.daily_bias_aligned !== false);
      setChk("chkA4hZone", diag.zone_aligned !== false);
      setChk("chkA1hSweep", diag.sweep_confirmed === true);
      setChk("chkAMss", diag.displacement_confirmed === true);
      setChk("chkARetrace", diag.retracement_valid === true);
    } else {
      $("modelADirection").textContent = "—";
      $("modelAEntry").textContent = "—";
      $("modelAStop").textContent = "—";
      $("modelATarget").textContent = "—";
      $("modelARr").textContent = "—";
      $("modelASetupId").textContent = "—";
      bA.textContent = "SCANNING";
      bA.className = "strat-status-badge";
      ["chkADailyBias", "chkA4hZone", "chkA1hSweep", "chkAMss", "chkARetrace"].forEach((id) => setChk(id, false));
    }

    // Render Model B
    const bB = $("modelBStatusBadge");
    if (modelB && modelB.id) {
      $("modelBDirection").textContent = modelB.direction || "—";
      $("modelBDirection").className = "field-value mono-val " + (modelB.direction === "LONG" ? "text-bull" : "text-bear");
      $("modelBEntry").textContent = modelB.price ? fmtMoney(modelB.price) : "—";
      $("modelBStop").textContent = modelB.invalidation_price ? fmtMoney(modelB.invalidation_price) : "—";
      $("modelBTarget").textContent = modelB.target_price ? fmtMoney(modelB.target_price) : "—";
      $("modelBRr").textContent = modelB.rr_ratio ? `${Number(modelB.rr_ratio).toFixed(2)} R:R` : "—";
      $("modelBSetupId").textContent = modelB.id || "—";

      bB.textContent = modelB.state || "CANDIDATE";
      bB.className = "strat-status-badge " + (modelB.state === "ACTIVE" ? "active" : "candidate");

      const diag = modelB.diagnostics || {};
      setChk("chkBMinTouches", (diag.touches_count || 0) >= 3);
      setChk("chkBGeometry", diag.geometry_valid !== false);
      setChk("chkBBreakout", diag.breakout_confirmed === true);
      setChk("chkBFoundation", diag.foundation_valid !== false);
      setChk("chkBRr", (modelB.rr_ratio || 0) >= 2.0);
    } else {
      $("modelBDirection").textContent = "—";
      $("modelBEntry").textContent = "—";
      $("modelBStop").textContent = "—";
      $("modelBTarget").textContent = "—";
      $("modelBRr").textContent = "—";
      $("modelBSetupId").textContent = "—";
      bB.textContent = "SCANNING";
      bB.className = "strat-status-badge";
      ["chkBMinTouches", "chkBGeometry", "chkBBreakout", "chkBFoundation", "chkBRr"].forEach((id) => setChk(id, false));
    }

    // Priority Router & Overall Diagnostic
    const tag = $("signalEligibilityTag");
    const diag = $("sigDiagnosticText");

    if (activeSetup && activeSetup.id) {
      if (decision && decision.accepted) {
        tag.textContent = "ACCEPTED & EXECUTED";
        tag.className = "eligibility-tag eligible";
        diag.textContent = `Setup ${activeSetup.id} (${activeSetup.name || "SMC"}) initiated simulated position #${decision.position_id}.`;
      } else if (decision && !decision.accepted) {
        tag.textContent = `REJECTED (${decision.reason || "RISK"})`;
        tag.className = "eligibility-tag rejected";
        diag.textContent = `Setup ${activeSetup.id} rejected: ${decision.message || decision.reason || "Risk control filter"}.`;
      } else {
        tag.textContent = "ACTIVE SETUP FOUND";
        tag.className = "eligibility-tag waiting";
        diag.textContent = `Monitoring active setup ${activeSetup.id} for price entry confirmation.`;
      }
    } else {
      tag.textContent = "SCANNING MARKET";
      tag.className = "eligibility-tag";
      diag.textContent = "Monitoring 1H market structure across decoupled Model A (Sweep) & Model B (Trendline). Only close-confirmed setups in ACTIVE state are routed for entry.";
    }
  }

  // --- 6. OPEN POSITIONS TABLE ---
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
        <td>
          <div style="display: flex; gap: 4px;">
            <button class="btn-table-action btn-update-sl" data-id="${pos.id}" data-dir="${pos.direction}" data-sl="${pos.stop_loss}" data-entry="${pos.entry_price}">Trail SL</button>
            <button class="btn-table-action btn-replay-trade" data-id="${pos.id}">Replay</button>
            <button class="btn-table-action btn-close-pos" data-id="${pos.id}">Close</button>
          </div>
        </td>
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

    tbody.querySelectorAll(".btn-update-sl").forEach((btn) => {
      btn.onclick = () => {
        activeUpdateStopPosId = btn.getAttribute("data-id");
        $("stopPosId").value = activeUpdateStopPosId;
        $("stopPosDir").value = btn.getAttribute("data-dir");
        $("stopCurrentVal").value = fmtMoney(btn.getAttribute("data-sl"));
        $("stopNewVal").value = "";
        $("stopErrorText").style.display = "none";
        $("modalUpdateStop").style.display = "flex";
      };
    });

    tbody.querySelectorAll(".btn-replay-trade").forEach((btn) => {
      btn.onclick = () => openTradeReplayModal(btn.getAttribute("data-id"));
    });
  }

  // --- 7. COMPLETED TRADES TABLE ---
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
      tbody.innerHTML = '<tr><td colspan="13" class="empty-state">No matching completed trades found.</td></tr>';
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
        <td><button class="btn-table-action btn-replay-trade" data-id="${t.id}">Replay 🔍</button></td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".btn-replay-trade").forEach((btn) => {
      btn.onclick = () => openTradeReplayModal(btn.getAttribute("data-id"));
    });
  }

  // --- ORDERS TABLE ---
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

  // --- AUDIT EVENTS TABLE ---
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

  // --- REJECTION INSPECTOR ---
  async function loadRejections() {
    const model = $("filterRejModel").value;
    const stage = $("filterRejStage").value;
    const url = `/api/paper/rejections?model=${encodeURIComponent(model)}&stage=${encodeURIComponent(stage)}&limit=100`;

    try {
      const data = await api(url, "GET");
      const rejections = data.rejections || [];
      const summary = data.summary || {};

      $("rejTotalCount").textContent = summary.total_rejections || 0;
      const topStage = Object.entries(summary.by_stage || {}).sort((a, b) => b[1] - a[1])[0];
      $("rejPrimaryStage").textContent = topStage ? `${topStage[0]} (${topStage[1]})` : "None";

      const tbody = $("tbodyRejections");
      tbody.innerHTML = "";
      if (rejections.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No rejected trade setups match the selected filter.</td></tr>';
        return;
      }

      rejections.forEach((r) => {
        const tr = document.createElement("tr");
        const reasonsStr = (r.reasons || []).join(" | ");
        tr.innerHTML = `
          <td>${fmtTime(r.timestamp)}</td>
          <td>${r.setup_id || "—"}</td>
          <td><span class="mono-code">${r.model}</span></td>
          <td><span class="mono-code text-bear">${r.stage_failed}</span></td>
          <td>${fmtMoney(r.evaluated_price)}</td>
          <td>${reasonsStr}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error("Failed to load rejections:", e);
    }
  }

  // --- STRATEGY LAB / BACKTEST ---
  async function runBacktest() {
    const btn = $("btnRunBacktest");
    const strategy = $("backtestModelSelect").value;
    btn.disabled = true;
    btn.textContent = "⏳ Running Chronological Simulation & Monte Carlo...";

    try {
      const res = await api("/api/paper/backtest", "POST", { strategy });
      if (!res.success) {
        alert("Backtest failed: " + res.message);
        return;
      }

      const results = res.results || {};
      const wf = results.walk_forward || {};
      const mc = results.monte_carlo || {};

      $("backtestResultsArea").style.display = "block";

      // Train Set
      const train = wf.train || {};
      $("trainTrades").textContent = train.trades_count || 0;
      $("trainWinRate").textContent = `${(train.win_rate || 0).toFixed(1)}%`;
      $("trainPf").textContent = train.profit_factor || "—";
      $("trainNetPnl").textContent = fmtSignedMoney(train.net_pnl || 0);
      $("trainMaxDd").textContent = `${(train.max_drawdown_pct || 0).toFixed(2)}%`;

      // Validation Set
      const val = wf.validation || {};
      $("valTrades").textContent = val.trades_count || 0;
      $("valWinRate").textContent = `${(val.win_rate || 0).toFixed(1)}%`;
      $("valPf").textContent = val.profit_factor || "—";
      $("valNetPnl").textContent = fmtSignedMoney(val.net_pnl || 0);
      $("valMaxDd").textContent = `${(val.max_drawdown_pct || 0).toFixed(2)}%`;

      // Out-of-Sample Test Set
      const test = wf.test || {};
      $("testTrades").textContent = test.trades_count || 0;
      $("testWinRate").textContent = `${(test.win_rate || 0).toFixed(1)}%`;
      $("testPf").textContent = test.profit_factor || "—";
      $("testNetPnl").textContent = fmtSignedMoney(test.net_pnl || 0);
      $("testMaxDd").textContent = `${(test.max_drawdown_pct || 0).toFixed(2)}%`;

      // Monte Carlo
      $("mcMaxDdP95").textContent = `${(mc.p95_max_drawdown_pct || 0).toFixed(2)}%`;
      $("mcMaxDdMedian").textContent = `${(mc.median_max_drawdown_pct || 0).toFixed(2)}%`;
      $("mcRuinProb").textContent = `${(mc.ruin_probability || 0).toFixed(2)}%`;
      $("mcMedianEquity").textContent = fmtMoney(mc.median_final_equity || 10000);
    } catch (e) {
      alert("Error executing backtest: " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Run Walk-Forward Validation (60/20/20)";
    }
  }

  // --- FORENSIC TRADE REPLAY MODAL ---
  async function openTradeReplayModal(posId) {
    activeReplayPosId = posId;
    $("modalTradeReplay").style.display = "flex";
    $("replayTimelineBody").innerHTML = '<tr><td colspan="3" class="empty-state">Loading reconstruction data...</td></tr>';

    try {
      const data = await api(`/api/paper/trade_replay/${posId}`, "GET");
      const pos = data.position || {};
      const metrics = data.metrics || {};
      const timeline = data.timeline || [];

      $("replayPosId").textContent = pos.id ? `${pos.id.slice(0, 8)}…` : "—";
      $("replaySetupId").textContent = pos.setup_id || "—";
      $("replayDir").textContent = pos.direction || "—";
      $("replayDir").className = pos.direction === "LONG" ? "text-bull" : "text-bear";
      $("replayEntry").textContent = fmtMoney(pos.entry_price);
      $("replayExit").textContent = pos.exit_price ? fmtMoney(pos.exit_price) : "Open";
      $("replayNetPnl").textContent = pos.net_pnl != null ? fmtSignedMoney(pos.net_pnl) : fmtSignedMoney(pos.unrealized_pnl);

      const mfe = Number(metrics.mfe || 0);
      const mae = Number(metrics.mae || 0);
      $("replayMfe").textContent = fmtSignedMoney(mfe);
      $("replayMae").textContent = fmtSignedMoney(mae);
      $("replayBeStatus").textContent = metrics.breakeven_triggered ? "TRIGGERED (+1R)" : "NOT TRIGGERED";
      $("replayBeStatus").className = "exc-val " + (metrics.breakeven_triggered ? "text-bull" : "");

      const sec = Math.round(metrics.holding_period_seconds || 0);
      const mins = Math.floor(sec / 60);
      $("replayDuration").textContent = `${mins}m ${sec % 60}s`;

      const tbody = $("replayTimelineBody");
      tbody.innerHTML = "";
      if (timeline.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No execution logs found for this position.</td></tr>';
      } else {
        timeline.forEach((ev) => {
          const tr = document.createElement("tr");
          let dStr = typeof ev.detail === "object" ? JSON.stringify(ev.detail) : String(ev.detail || "");
          tr.innerHTML = `
            <td>${fmtTime(ev.ts)}</td>
            <td><strong class="mono-code">${ev.kind}</strong></td>
            <td>${dStr}</td>
          `;
          tbody.appendChild(tr);
        });
      }
    } catch (e) {
      alert("Failed to load trade forensics: " + e.message);
      $("modalTradeReplay").style.display = "none";
    }
  }

  // --- MONOTONIC STOP LOSS ADJUSTMENT SUBMISSION ---
  async function submitMonotonicStop() {
    if (!activeUpdateStopPosId) return;
    const newVal = parseFloat($("stopNewVal").value);
    const errBox = $("stopErrorText");
    errBox.style.display = "none";

    if (isNaN(newVal) || newVal <= 0) {
      errBox.textContent = "Please enter a valid positive stop price.";
      errBox.style.display = "block";
      return;
    }

    try {
      const res = await api(`/api/paper/positions/${activeUpdateStopPosId}/update_stop`, "POST", { new_stop: newVal });
      if (!res.success) {
        errBox.textContent = `Monotonic Stop Violation: ${res.message || "Cannot widen stop loss"}`;
        errBox.style.display = "block";
      } else {
        $("modalUpdateStop").style.display = "none";
        await refresh(false);
      }
    } catch (e) {
      errBox.textContent = "Error: " + e.message;
      errBox.style.display = "block";
    }
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

  // Trade Replay Modal Controls
  $("btnCloseReplayModal").onclick = () => {
    $("modalTradeReplay").style.display = "none";
  };
  $("btnCloseReplayBtn").onclick = () => {
    $("modalTradeReplay").style.display = "none";
  };

  // Monotonic Stop Modal Controls
  $("btnCloseStopModal").onclick = () => {
    $("modalUpdateStop").style.display = "none";
  };
  $("btnCancelStopModal").onclick = () => {
    $("modalUpdateStop").style.display = "none";
  };
  $("btnSubmitStopUpdate").onclick = submitMonotonicStop;

  // Rejection Inspector Controls
  $("btnRefreshRejections").onclick = loadRejections;
  $("filterRejModel").onchange = loadRejections;
  $("filterRejStage").onchange = loadRejections;

  // Backtest Controls
  $("btnRunBacktest").onclick = runBacktest;

  // Tabs Switcher (5 Tabs)
  const tabMap = {
    trades: { btn: "tabBtnTrades", view: "viewTrades" },
    orders: { btn: "tabBtnOrders", view: "viewOrders" },
    rejections: { btn: "tabBtnRejections", view: "viewRejections" },
    backtest: { btn: "tabBtnBacktest", view: "viewBacktest" },
    events: { btn: "tabBtnEvents", view: "viewEvents" },
  };

  Object.entries(tabMap).forEach(([tabName, els]) => {
    const btn = $(els.btn);
    if (!btn) return;
    btn.onclick = () => {
      activeTab = tabName;
      Object.entries(tabMap).forEach(([name, target]) => {
        const isTarget = name === tabName;
        const b = $(target.btn);
        const v = $(target.view);
        if (b) b.className = isTarget ? "tab-btn active" : "tab-btn";
        if (v) v.style.display = isTarget ? "block" : "none";
      });

      // Filter controls visibility
      const flt = $("tradesFilterControls");
      if (flt) flt.style.display = (tabName === "trades" || tabName === "orders") ? "flex" : "none";

      if (tabName === "trades" && paperState) renderTrades(paperState.trades);
      if (tabName === "orders" && paperState) renderOrders(paperState.orders);
      if (tabName === "events" && paperState) renderEvents(paperState.events);
      if (tabName === "rejections") loadRejections();
    };
  });

  // Filters
  $("filterSearch").oninput = () => {
    if (activeTab === "trades") renderTrades(paperState ? paperState.trades : []);
    else if (activeTab === "orders") renderOrders(paperState ? paperState.orders : []);
  };
  $("filterDirection").onchange = () => {
    if (activeTab === "trades") renderTrades(paperState ? paperState.trades : []);
    else if (activeTab === "orders") renderOrders(paperState ? paperState.orders : []);
  };

  // Init
  initTheme();
  refresh(true);
  setInterval(() => refresh(true), 4000);
})();
