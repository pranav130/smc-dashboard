/**
 * Signal-First Institutional Trading Command Center - Frontend Application
 * Delta Exchange India · XAUTUSD SMC Terminal
 * Connects to local backend adapter and renders TradingView Lightweight Charts
 * with genuine multi-timeframe SMC overlays, unified terminal state machine,
 * single prioritized active setup card, and collapsed icon rail drawer.
 */

// Global State
let currentTf = "1H";
let currentTheme = localStorage.getItem("smc_theme") || "dark";
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let activeLines = [];
let ws = null;
let lastUpdateTs = 0;
let lastCandleTs = 0;
let currentAnalysis = null;
let latestCandle = null;
let dismissedSetupId = null;
let isDrawerPinned = false;
let activeDrawerPane = null;
let focusSetupMode = false;

// Overlay Layer Toggles (High-value defaults enabled; secondary category unticked by default)
const layerToggles = {
  htfFvg: true,
  trendlines: true,
  liquidity: true,
  orderBlocks: true,
  // Secondary / Micro Layers (All unticked by default)
  volume: false,
  ltfFvg: false,
  psych: false,
  swings: false,
  hiddenLiquidity: false,
};

let currentLiqFilter = "all";
let selectedLiqZoneId = null;

// DOM Elements
const headerPrice = document.getElementById("headerPrice");
const headerSourceTime = document.getElementById("headerSourceTime");
const connStatusText = document.getElementById("connStatusText");
const connectionPill = document.getElementById("connectionPill");
const btnToggleDetails = document.getElementById("btnToggleDetails");
const detailsBtnText = document.getElementById("detailsBtnText");
const collapsibleDetails = document.getElementById("collapsibleDetails");
const btnRefresh = document.getElementById("btnRefresh");

// Focus Setup Controls
const btnFocusSetup = document.getElementById("btnFocusSetup");
const focusSetupBtnText = document.getElementById("focusSetupBtnText");
const togFocusSetup = document.getElementById("togFocusSetup");

// Alert Badge Counters
const badgeActiveCount = document.getElementById("badgeActiveCount");
const badgeWatchCount = document.getElementById("badgeWatchCount");
const badgeRiskCount = document.getElementById("badgeRiskCount");
const alertPaneActiveCount = document.getElementById("alertPaneActiveCount");
const alertPaneWatchCount = document.getElementById("alertPaneWatchCount");
const alertPaneRiskCount = document.getElementById("alertPaneRiskCount");

// Status Panel Elements (inside Collapsible Details)
const statInstrument = document.getElementById("statInstrument");
const statContract = document.getElementById("statContract");
const statProvider = document.getElementById("statProvider");
const statTimeframe = document.getElementById("statTimeframe");
const statBasis = document.getElementById("statBasis");
const statLastCandle = document.getElementById("statLastCandle");
const statCandleState = document.getElementById("statCandleState");
const statStreamMode = document.getElementById("statStreamMode");
const statLastUpdate = document.getElementById("statLastUpdate");
const warningBanner = document.getElementById("warningBanner");
const warningText = document.getElementById("warningText");

// Signal Summary Bar Elements
const marketBiasPill = document.getElementById("marketBiasPill");
const tfBiasIndicators = document.getElementById("tfBiasIndicators");
const terminalSetupPill = document.getElementById("terminalSetupPill");
const terminalSetupDesc = document.getElementById("terminalSetupDesc");
const terminalRiskPill = document.getElementById("terminalRiskPill");
const terminalRiskDesc = document.getElementById("terminalRiskDesc");

// Active Setup Card Container
const activeSetupContainer = document.getElementById("activeSetupContainer");

// Workspace & Drawer Elements
const mainWorkspace = document.getElementById("mainWorkspace");
const slideDrawer = document.getElementById("slideDrawer");
const drawerTitle = document.getElementById("drawerTitle");
const btnPinDrawer = document.getElementById("btnPinDrawer");
const pinBtnText = document.getElementById("pinBtnText");
const btnCloseDrawer = document.getElementById("btnCloseDrawer");
const iconRail = document.getElementById("iconRail");
const railAlertBadge = document.getElementById("railAlertBadge");

// Overlays Menu Elements
const btnOverlaysMenu = document.getElementById("btnOverlaysMenu");
const overlaysPopover = document.getElementById("overlaysPopover");

// Chart Legend Elements
const legendTitle = document.getElementById("legendTitle");
const legendOHLC = document.getElementById("legendOHLC");

// Drawer Content Elements
const alertsDrawerArea = document.getElementById("alertsDrawerArea");
const watchlistCardsContainer = document.getElementById("watchlistCardsContainer");
const filterAllCount = document.getElementById("filterAllCount");
const filterActiveCount = document.getElementById("filterActiveCount");
const filterSetupsCount = document.getElementById("filterSetupsCount");
let watchlistFilter = "all";

const levelsTableBody = document.getElementById("levelsTableBody");
const levelsCount = document.getElementById("levelsCount");
const opposingAlertsArea = document.getElementById("opposingAlertsArea");
const obBody = document.getElementById("obBody");
const obCount = document.getElementById("obCount");
const psychTableBody = document.getElementById("psychTableBody");

const overlapsBody = document.getElementById("overlapsBody");
const overlapsCount = document.getElementById("overlapsCount");
const dailyFvgBody = document.getElementById("dailyFvgBody");
const dailyFvgCount = document.getElementById("dailyFvgCount");
const h4FvgBody = document.getElementById("h4FvgBody");
const h4FvgCount = document.getElementById("h4FvgCount");
const h1FvgBody = document.getElementById("h1FvgBody");
const h1FvgCount = document.getElementById("h1FvgCount");

const premDiscBody = document.getElementById("premDiscBody");
const trendlineBody = document.getElementById("trendlineBody");
const tlCount = document.getElementById("tlCount");
const liquidityBody = document.getElementById("liquidityBody");
const bosBody = document.getElementById("bosBody");
const bosCount = document.getElementById("bosCount");

// Timezone Synchronizer: Shifts UTC unix timestamps to the user's local system clock
function toLocalChartTime(utcSeconds) {
  if (!utcSeconds) return utcSeconds;
  const offsetMinutes = new Date(utcSeconds * 1000).getTimezoneOffset();
  return utcSeconds - (offsetMinutes * 60);
}

// --------------------------------------------------------------------------
// 1. Chart Initialization
// --------------------------------------------------------------------------
function initChart() {
  const container = document.getElementById("chart");
  container.innerHTML = "";

  const isLight = currentTheme === "light";
  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      background: { type: "solid", color: isLight ? "#ffffff" : "#07090e" },
      textColor: isLight ? "#475569" : "#8b949e",
      fontSize: 11,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace',
    },
    grid: {
      vertLines: { color: isLight ? "#f1f5f9" : "#131922" },
      horzLines: { color: isLight ? "#f1f5f9" : "#131922" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: isLight ? "#cbd5e1" : "#283344", width: 1, style: LightweightCharts.LineStyle.Dashed },
      horzLine: { color: isLight ? "#cbd5e1" : "#283344", width: 1, style: LightweightCharts.LineStyle.Dashed },
    },
    rightPriceScale: {
      borderColor: isLight ? "#e2e8f0" : "#1e2633",
      scaleMargins: { top: 0.08, bottom: 0.15 },
    },
    timeScale: {
      borderColor: isLight ? "#e2e8f0" : "#1e2633",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 12,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#00b49f",
    downColor: "#f23645",
    borderUpColor: "#00b49f",
    borderDownColor: "#f23645",
    wickUpColor: "#00b49f",
    wickDownColor: "#f23645",
  });

  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
    scaleMargins: { top: 0.82, bottom: 0 },
    visible: layerToggles.volume,
  });

  chart.subscribeCrosshairMove((param) => {
    if (!param.time || !param.seriesData.get(candleSeries)) {
      if (currentAnalysis) {
        updateLegendFromAnalysis(currentAnalysis);
      }
      return;
    }
    const cData = param.seriesData.get(candleSeries);
    const vData = param.seriesData.get(volumeSeries);
    if (cData) {
      const vVal = vData ? vData.value.toFixed(1) : "--";
      const isLatest = latestCandle && param.time === toLocalChartTime(latestCandle.time);
      const prefix = isLatest ? "[LATEST]" : "[HISTORICAL]";
      if (legendOHLC) {
        legendOHLC.textContent = `${prefix} O: ${cData.open.toFixed(2)}  H: ${cData.high.toFixed(2)}  L: ${cData.low.toFixed(2)}  C: ${cData.close.toFixed(2)}  V: ${vVal}`;
      }
    }
  });

  window.addEventListener("resize", resizeChart);
  if (window.ResizeObserver) {
    const chartContainer = document.getElementById("chart");
    if (chartContainer) {
      const ro = new ResizeObserver(() => resizeChart());
      ro.observe(chartContainer);
    }
  }
  setupToggleListeners();
}

function resizeChart() {
  const container = document.getElementById("chart");
  if (chart && container) {
    chart.applyOptions({
      width: container.clientWidth,
      height: container.clientHeight,
    });
    chart.timeScale().fitContent();
  }
}

function updateLegendFromAnalysis(analysis) {
  if (!legendOHLC || !analysis) return;
  const price = analysis.current_price ? analysis.current_price.toFixed(2) : (latestCandle ? latestCandle.close.toFixed(2) : "--");
  if (latestCandle) {
    legendOHLC.textContent = `[LATEST LIVE] O: ${latestCandle.open.toFixed(2)}  H: ${latestCandle.high.toFixed(2)}  L: ${latestCandle.low.toFixed(2)}  C: ${latestCandle.close.toFixed(2)} · Last: $${price} USD`;
  } else {
    legendOHLC.textContent = `[LATEST LIVE] Price: $${price} USD · Status: Verified`;
  }
}

// --------------------------------------------------------------------------
// 2. Fetch & Render SMC Data
// --------------------------------------------------------------------------
async function loadSMCData(timeframe) {
  try {
    if (timeframe) {
      currentTf = timeframe.toUpperCase();
    }
    if (legendTitle) {
      legendTitle.textContent = focusSetupMode
        ? `XAUTUSD · ${currentTf} · [4H/1D FOCUS]`
        : `XAUTUSD · ${currentTf} · DELTA INDIA`;
    }

    const res = await fetch(`/api/smc?timeframe=${currentTf}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.success) {
      currentAnalysis = data.analysis;
      if (warningBanner) warningBanner.style.display = "none";

      try { renderTerminalState(data.analysis, data.status); } catch (e) { console.error("renderTerminalState error:", e); }
      try { renderActiveSetupCard(data.analysis); } catch (e) { console.error("renderActiveSetupCard error:", e); }
      try { updateStatusPanel(data.status); } catch (e) { console.error("updateStatusPanel error:", e); }
      try { renderChartData(data.analysis); } catch (e) { console.error("renderChartData error:", e); }
      try { renderWatchlist(data.analysis, data.status); } catch (e) { console.error("renderWatchlist error:", e); }
      try { renderDrawerData(data.analysis); } catch (e) { console.error("renderDrawerData error:", e); }
    }
  } catch (err) {
    console.error("Failed to load SMC data:", err);
    showWarning("Connecting to Delta Exchange India backend...");
  }
}

// --------------------------------------------------------------------------
// 3. Render Unified Terminal State (1-2 Second Scanability)
// --------------------------------------------------------------------------
function renderTerminalState(analysis, status) {
  if (!analysis) return;
  const tState = analysis.terminal_state || {};

  // A. Market Bias
  const bias = tState.market_bias || "NEUTRAL";
  if (marketBiasPill) {
    marketBiasPill.textContent = `BIAS: ${bias}`;
    marketBiasPill.className = `bias-pill ${bias.toLowerCase()}`;
  }

  // Timeframe bias indicators: 1D, 4H, 1H, 15M
  if (tfBiasIndicators) {
    const details = tState.bias_details || {};
    const tfs = ["1D", "4H", "1H", "15M"];
    tfBiasIndicators.innerHTML = "";

    tfs.forEach((tf) => {
      const state = details[tf] || "--";
      let arrow = "•";
      let cls = "";
      if (state === "BULLISH") {
        arrow = "↑";
        cls = "bullish";
      } else if (state === "BEARISH") {
        arrow = "↓";
        cls = "bearish";
      }

      const badge = document.createElement("span");
      badge.className = `tf-badge ${cls}`;
      badge.setAttribute("data-tf", tf);
      badge.textContent = `${tf} ${arrow}`;
      badge.title = `${tf} Structure: ${state}`;
      tfBiasIndicators.appendChild(badge);
    });
  }

  // B. Setup State
  const sState = tState.setup_state || "IDLE";
  if (terminalSetupPill) {
    terminalSetupPill.textContent = `SETUP: ${sState}`;
    terminalSetupPill.className = `setup-pill ${sState.toLowerCase()}`;
  }
  if (terminalSetupDesc) {
    if (tState.active_setup) {
      terminalSetupDesc.textContent = `${tState.active_setup.name} (${tState.active_setup.timeframe}) · ${tState.active_setup.quality}`;
    } else {
      terminalSetupDesc.textContent = "No qualifying setup under active surveillance";
    }
  }

  // C. Risk / Data State
  const rState = tState.risk_state || "NORMAL";
  if (terminalRiskPill) {
    terminalRiskPill.textContent = `RISK: ${rState}`;
    terminalRiskPill.className = `risk-pill ${rState.toLowerCase()}`;
  }
  if (terminalRiskDesc) {
    if (tState.risk_reasons && tState.risk_reasons.length > 0) {
      terminalRiskDesc.textContent = tState.risk_reasons[0];
    } else {
      terminalRiskDesc.textContent = "Live verified market data";
    }
  }

  // Update Exchange Source Timestamp in Header
  if (headerSourceTime && status) {
    let ist = status.last_candle_ist || status.system_time_ist || "";
    if (ist) {
      const cleanIst = ist.replace(/\s*IST(\s*IST)*$/, "").trim();
      headerSourceTime.textContent = `${cleanIst} IST`;
    }
  }
}

// --------------------------------------------------------------------------
// 4. Render Active Setup Card
// --------------------------------------------------------------------------
function renderActiveSetupCard(analysis) {
  if (!activeSetupContainer || !analysis) return;
  const tState = analysis.terminal_state || {};
  const setup = tState.active_setup;

  // If dismissed, idle, or purely routine WATCH: show clean, compact surveillance strip
  const isActionable = setup && ["READY", "WAITING FOR CONFIRMATION", "ACTIVE", "EXTREME"].includes(setup.canonical_setup_state || setup.state);

  if (!setup || setup.id === dismissedSetupId || !isActionable) {
    activeSetupContainer.innerHTML = `
      <div class="active-setup-card idle-card" id="activeSetupCard" style="padding: 4px 10px; margin-bottom: 3px;">
        <div class="idle-message" style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="idle-indicator" style="background: var(--teal-bull); width: 6px; height: 6px; border-radius: 50%;"></span>
            <span style="font-size: 11px; font-weight: 500; color: var(--text-dim);">
              Market Surveillance Active · Monitoring key levels for qualified trade setups
            </span>
          </div>
          <span style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">
            1D Bias: ${(analysis.daily_trend_state?.trend || 'NEUTRAL').toUpperCase()} · Execution TF: ${currentTf}
          </span>
        </div>
      </div>
    `;
    return;
  }

  const state = setup.canonical_setup_state || setup.state || "WAITING FOR CONFIRMATION";
  const isBull = setup.direction === "bullish";
  const dirIcon = isBull ? "▲ LONG" : "▼ SHORT";
  const dirTagClass = isBull ? "bullish" : "bearish";

  // State-specific styles and banners
  let cardStateClass = "card-active";
  let stateBannerHtml = "";

  if (state === "EXTREME") {
    cardStateClass = "card-extreme";
    stateBannerHtml = `
      <div class="state-banner extreme-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <span>⚡ EXTREME CONFLUENCE · Multi-Timeframe Institutional Confluence</span>
      </div>
    `;
  } else if (state === "READY" || state === "ACTIVE") {
    cardStateClass = "card-active";
    stateBannerHtml = `
      <div class="state-banner active-confirmed-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        <span>✓ READY FOR INSPECTION · Verified Entry, SL, TP, and R:R Criteria Satisfied</span>
      </div>
    `;
  } else {
    // WAITING FOR CONFIRMATION
    cardStateClass = "card-watch";
    stateBannerHtml = `
      <div class="state-banner waiting-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span>⏳ WAITING FOR CONFIRMATION · Level Reaction / Trendline Break Detected</span>
      </div>
    `;
  }

  const checklistsHtml = (setup.checklist || []).map((c) => {
    return `<span class="chk-badge ${c.satisfied ? 'done' : ''}" title="${c.name}: ${c.description}">${c.name} ${c.satisfied ? '✓' : '○'}</span>`;
  }).join("");

  // Target and invalidation display formatting
  let targetDisplay = setup.target || "--";
  if (setup.is_target_reached) {
    targetDisplay = `${targetDisplay} (REACHED)`;
  }

  // Directional Context & Trade Classification
  const dirContextLabel = setup.directional_context || `${dirIcon} Context`;
  const tradeClass = setup.trade_classification || "NEUTRAL";
  const tradeClassTag = tradeClass === "COUNTERTREND (HIGH RISK)"
    ? `<span class="trade-class-tag countertrend" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); padding: 1px 6px; border-radius: 3px; font-size: 9px; font-weight: 700;">COUNTERTREND (HIGH RISK)</span>`
    : (tradeClass === "PRO-TREND" ? `<span class="trade-class-tag protrend" style="background: rgba(0, 180, 159, 0.2); color: #00b49f; border: 1px solid rgba(0, 180, 159, 0.4); padding: 1px 6px; border-radius: 3px; font-size: 9px; font-weight: 700;">PRO-TREND</span>` : "");

  // 12-Point Inspector Table Rows
  const inspectorHtml = (setup.inspector_checklist || []).map((item) => {
    const isPass = item.status === "PASS";
    const statusColor = isPass ? "#00b49f" : (item.status === "FAIL" ? "#ef4444" : "#94a3b8");
    return `
      <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
        <td style="padding: 4px 6px; font-weight: 500;">${item.title}</td>
        <td style="padding: 4px 6px;"><span style="color: ${statusColor}; font-weight: 700; font-size: 9px; border: 1px solid ${statusColor}44; padding: 1px 4px; border-radius: 2px;">${item.status}</span></td>
        <td style="padding: 4px 6px; color: var(--text-dim);">${item.detail}</td>
      </tr>
    `;
  }).join("");

  activeSetupContainer.innerHTML = `
    <div class="active-setup-card ${cardStateClass}" id="activeSetupCard">
      ${stateBannerHtml}
      <div class="card-top-row">
        <div class="card-identity" style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
          <span class="directional-context-tag ${dirTagClass}">${dirContextLabel}</span>
          ${tradeClassTag}
          <span class="setup-title">${setup.name} (${setup.timeframe})</span>
          <span class="quality-badge">${setup.quality}</span>
          <span class="setup-pill ${state.toLowerCase().replace(/ /g, '-')}" style="font-size: 9px; padding: 1px 6px;">${state}</span>
        </div>
        <button class="btn-dismiss" id="btnDismissCard" title="Acknowledge & dismiss setup card view (retains surveillance in background)">
          ✕ Dismiss
        </button>
      </div>

      <div class="card-metrics-grid">
        <div class="metric-item">
          <span class="metric-lbl">Zone / Entry POI</span>
          <span class="metric-val">$${setup.zone_str}</span>
        </div>
        <div class="metric-item">
          <span class="metric-lbl">Invalidation (SL)</span>
          <span class="metric-val" style="color: var(--red-bear);">${setup.invalidation}</span>
        </div>
        <div class="metric-item">
          <span class="metric-lbl">Target (TP)</span>
          <span class="metric-val" style="color: ${setup.is_target_reached ? 'var(--text-muted)' : 'var(--teal-bull)'};">${targetDisplay}</span>
        </div>
        <div class="metric-item">
          <span class="metric-lbl">Reward / Risk</span>
          <span class="metric-val">${setup.reward_risk}</span>
        </div>
        <div class="metric-item">
          <span class="metric-lbl">Distance to POI</span>
          <span class="metric-val">${setup.distance >= 0 ? '+' : ''}${setup.distance.toFixed(2)} (${setup.distance_pct.toFixed(2)}%)</span>
        </div>
      </div>

      <div class="card-bottom-row" style="display: flex; flex-direction: column; gap: 6px;">
        <div class="card-checklist-badges">${checklistsHtml}</div>
        <div class="card-reason" style="font-size: 10px; color: var(--text-dim);">
          ${setup.reason || (state === "WAITING FOR CONFIRMATION" ? "Awaiting price reaction & closed-candle confirmation inside POI" : "Real-time SMC trigger criteria active")}
        </div>

        <!-- Phase 5: Setup Validation Inspector -->
        <div class="inspector-section" style="border-top: 1px solid var(--border-color); padding-top: 6px;">
          <button class="btn-toggle-inspector" id="btnToggleInspector" style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); color: var(--text-dim); font-size: 10px; border-radius: 4px; padding: 3px 8px; cursor: pointer; display: flex; align-items: center; gap: 4px;">
            <span>📋 12-Point Setup Validation Inspector</span>
            <span id="insArrow">▾</span>
          </button>
          <div id="inspectorContainer" style="display: none; margin-top: 6px; overflow-x: auto;">
            <table class="inspector-table" style="width: 100%; font-size: 10px; border-collapse: collapse; text-align: left;">
              <thead>
                <tr style="color: var(--text-muted); border-bottom: 1px solid var(--border-color);">
                  <th style="padding: 4px 6px;">Criteria</th>
                  <th style="padding: 4px 6px; width: 60px;">Result</th>
                  <th style="padding: 4px 6px;">Evidence / Verification</th>
                </tr>
              </thead>
              <tbody>
                ${inspectorHtml}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `;

  const btnDismiss = document.getElementById("btnDismissCard");
  if (btnDismiss) {
    btnDismiss.addEventListener("click", () => {
      dismissedSetupId = setup.id;
      renderActiveSetupCard(currentAnalysis);
    });
  }

  const btnToggleInspector = document.getElementById("btnToggleInspector");
  if (btnToggleInspector) {
    btnToggleInspector.addEventListener("click", () => {
      const insCont = document.getElementById("inspectorContainer");
      const insArr = document.getElementById("insArrow");
      if (insCont) {
        const isClosed = insCont.style.display === "none";
        insCont.style.display = isClosed ? "block" : "none";
        if (insArr) insArr.textContent = isClosed ? "▴" : "▾";
      }
    });
  }
}

// --------------------------------------------------------------------------
// 5. Render Chart Candles & SMC Overlays
// --------------------------------------------------------------------------
function renderChartData(analysis) {
  fetch(`/api/candles?timeframe=${currentTf}`)
    .then((r) => r.json())
    .then((cData) => {
      if (!cData.success || !cData.candles.length) return;

      const candles = cData.candles;
      const chartCandles = candles.map((c) => ({
        time: toLocalChartTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

      const chartVolumes = candles.map((c) => ({
        time: toLocalChartTime(c.time),
        value: c.volume,
        color: c.close >= c.open ? "rgba(0, 180, 159, 0.4)" : "rgba(242, 54, 69, 0.4)",
      }));

      candleSeries.setData(chartCandles);
      volumeSeries.setData(chartVolumes);
      
      chart.timeScale().fitContent();

      clearOverlayLines();
      drawSMCLevels(analysis);

      if (layerToggles.swings && !focusSetupMode) {
        drawChartMarkers(analysis);
      } else {
        candleSeries.setMarkers([]);
      }

      const last = candles[candles.length - 1];
      if (last) {
        headerPrice.textContent = last.close.toFixed(2);
      }
    });
}

let placedPriceLabels = [];

function clearOverlayLines() {
  activeLines.forEach((line) => {
    try {
      candleSeries.removePriceLine(line);
    } catch (e) {}
  });
  activeLines = [];
  placedPriceLabels = [];
}

// Collision-Aware Price Line Creator:
// Prevents overlapping price axis scale badges when lines are within 4.50 USD of each other
function addCollisionAwarePriceLine(opts) {
  if (!candleSeries || !opts || opts.price == null) return null;

  // Universal Sanity Guard:
  // Support / Buy levels must NEVER appear above current market price.
  // Resistance / Sell levels must NEVER appear below current market price.
  const curPrice = latestCandle ? latestCandle.close : 0;
  if (curPrice > 0 && opts.price !== undefined && opts.price !== null) {
    const titleLower = (opts.title || "").toLowerCase();
    const isSupport = (titleLower.includes("support") || titleLower.includes("buy")) && !titleLower.includes("sell");
    const isResistance = (titleLower.includes("resistance") || titleLower.includes("sell")) && !titleLower.includes("buy");

    if (isSupport && opts.price > curPrice + 0.50) {
      console.warn(`[Sanity Guard Rejected] Support/Buy level above market price: ${opts.title} at ${opts.price} (curPrice: ${curPrice})`);
      return null;
    }
    if (isResistance && opts.price < curPrice - 0.50) {
      console.warn(`[Sanity Guard Rejected] Resistance/Sell level below market price: ${opts.title} at ${opts.price} (curPrice: ${curPrice})`);
      return null;
    }
  }

  const COLLISION_THRESHOLD = 4.50; // $4.50 USD minimum separation on price axis (~0.11% on Gold)
  let showAxis = opts.axisLabelVisible !== false;
  if (showAxis && opts.price !== undefined && opts.price !== null) {
    const collides = placedPriceLabels.some((p) => Math.abs(p - opts.price) < COLLISION_THRESHOLD);
    if (collides) {
      showAxis = false;
    } else {
      placedPriceLabels.push(opts.price);
    }
  }
  const line = candleSeries.createPriceLine({
    ...opts,
    axisLabelVisible: showAxis,
  });
  activeLines.push(line);
  return line;
}

function drawSMCLevels(analysis) {
  if (!analysis) return;
  placedPriceLabels = [];

  const curPrice = analysis.current_price || (latestCandle ? latestCandle.close : 0);

  // -------------------------------------------------------------------------
  // 1. Key Higher-Timeframe Liquidity: PDH, PDL, PWH, PWL (Always visible in both modes!)
  // Colors strictly consistent with buying/selling:
  // Buying Liquidity (Lows: PDL, PWL, EQL, SSL) = Green (#00b49f)
  // Selling Liquidity (Highs: PDH, PWH, EQH, BSL) = Red (#f23645)
  // -------------------------------------------------------------------------
  if (layerToggles.liquidity) {
    const allLiqs = analysis.liquidity_levels || [];

    // Always render all unswept Macro HTF levels (PDH, PDL, PWH, PWL) without slicing them off
    const macroHtf = allLiqs.filter(
      (l) => !l.swept && ["PDH", "PDL", "PWH", "PWL"].includes(l.type)
    );
    macroHtf.forEach((l) => {
      const isSelling = l.type === "PDH" || l.type === "PWH";
      const liqColor = isSelling ? "#f23645" : "#00b49f"; // Red for Selling (Supply/Highs), Green for Buying (Demand/Lows)
      const roleText = isSelling ? "Sell Liq" : "Buy Liq";
      const prefix = focusSetupMode ? "★ [HTF] " : "";

      addCollisionAwarePriceLine({
        price: l.price,
        color: liqColor,
        lineWidth: focusSetupMode ? 1.5 : 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `${prefix}${l.type} (${roleText}: $${l.price.toFixed(2)})`,
      });
    });

    // In Focus OFF mode, also display nearest unswept Equal Highs / Equal Lows (EQH / EQL)
    if (!focusSetupMode) {
      const intLiqs = allLiqs.filter((l) => !l.swept && (l.type === "EQH" || l.type === "EQL")).slice(0, 2);
      intLiqs.forEach((l) => {
        const isSelling = l.type === "EQH" || l.price > curPrice;
        const liqColor = isSelling ? "#f23645" : "#00b49f";
        const roleText = isSelling ? "Sell Liq" : "Buy Liq";
        addCollisionAwarePriceLine({
          price: l.price,
          color: liqColor,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: `${l.type} (${roleText}: $${l.price.toFixed(2)})`,
        });
      });
    }
  }

  // -------------------------------------------------------------------------
  // 2. Higher Timeframe Fair Value Gaps (1D & 4H FVGs) - Always visible in both modes!
  // Daily and 4H FVGs are separated so 4H FVGs never hide Daily FVGs.
  // -------------------------------------------------------------------------
  // -------------------------------------------------------------------------
  // 2. Higher Timeframe Fair Value Gaps (1D & 4H FVGs) - Always visible in both modes!
  // Daily and 4H FVGs are separated so 4H FVGs never hide Daily FVGs.
  // Bearish FVGs act as overhead resistance (above price), Bullish FVGs act as support (below price).
  // -------------------------------------------------------------------------
  if (layerToggles.htfFvg) {
    // 2a. Daily FVGs (nearest unmitigated overhead resistance & underlying support)
    const dailyFvgs = (analysis.daily_fvgs || []).filter((f) => !f.mitigated && !f.inverted);
    const dAbove = dailyFvgs.filter((f) => f.midpoint > curPrice && f.direction === "bearish").sort((a, b) => a.midpoint - b.midpoint).slice(0, 1);
    const dBelow = dailyFvgs.filter((f) => f.midpoint <= curPrice && f.direction === "bullish").sort((a, b) => b.midpoint - a.midpoint).slice(0, 1);

    // 2b. 4H FVGs (nearest unmitigated overhead resistance & underlying support)
    const h4Fvgs = (analysis.h4_fvgs || []).filter((f) => !f.mitigated && !f.inverted);
    const h4Above = h4Fvgs.filter((f) => f.midpoint > curPrice && f.direction === "bearish").sort((a, b) => a.midpoint - b.midpoint).slice(0, 2);
    const h4Below = h4Fvgs.filter((f) => f.midpoint <= curPrice && f.direction === "bullish").sort((a, b) => b.midpoint - a.midpoint).slice(0, 2);

    const allHtfFvgs = [...dAbove, ...dBelow, ...h4Above, ...h4Below];
    allHtfFvgs.forEach((f) => {
      const isBullish = f.direction === "bullish";
      const fvgColor = isBullish ? "#00b49f" : "#f23645"; // Green for Bullish (Demand/Buying), Red for Bearish (Supply/Selling)
      const dirLabel = isBullish ? "Bullish" : "Bearish";
      const prefix = focusSetupMode ? "★ " : "";

      addCollisionAwarePriceLine({
        price: f.midpoint,
        color: fvgColor,
        lineWidth: focusSetupMode ? 1.5 : 1,
        lineStyle: LightweightCharts.LineStyle.SparseDotted,
        axisLabelVisible: true,
        title: `${prefix}${f.timeframe} ${dirLabel} FVG 50% ($${f.bottom.toFixed(2)} - $${f.top.toFixed(2)})`,
      });
    });
  }

  // -------------------------------------------------------------------------
  // 3. Higher Timeframe Order Blocks (4H OBs) - Always visible in both modes!
  // Bullish OB = Support (at or below price); Bearish OB = Resistance (at or above price)
  // -------------------------------------------------------------------------
  if (layerToggles.orderBlocks) {
    const h4Obs = (analysis.order_blocks || []).filter(
      (ob) => ob.timeframe === "4H" && !ob.mitigated && !ob.is_breaker
    );
    const h4Bull = h4Obs.filter((o) => o.direction === "bullish" && o.midpoint <= curPrice).slice(-1);
    const h4Bear = h4Obs.filter((o) => o.direction === "bearish" && o.midpoint >= curPrice).slice(-1);
    [...h4Bull, ...h4Bear].forEach((ob) => {
      const isBull = ob.direction === "bullish";
      const obColor = isBull ? "#00b49f" : "#f23645"; // Green for Bullish, Red for Bearish
      const prefix = focusSetupMode ? "★ " : "";
      addCollisionAwarePriceLine({
        price: ob.midpoint,
        color: obColor,
        lineWidth: focusSetupMode ? 1.5 : 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `${prefix}[4H] ${ob.direction.toUpperCase()} OB ($${ob.bottom.toFixed(2)} - $${ob.top.toFixed(2)})`,
      });
    });

    // In Focus OFF mode, also display nearest 1H intermediate Order Block
    if (!focusSetupMode) {
      const h1Obs = (analysis.order_blocks || []).filter(
        (ob) => ob.timeframe === "1H" && !ob.mitigated && !ob.is_breaker
      );
      const h1Bull = h1Obs.filter((o) => o.direction === "bullish" && o.midpoint <= curPrice).slice(-1);
      const h1Bear = h1Obs.filter((o) => o.direction === "bearish" && o.midpoint >= curPrice).slice(-1);
      [...h1Bull, ...h1Bear].forEach((ob) => {
        const isBull = ob.direction === "bullish";
        addCollisionAwarePriceLine({
          price: ob.midpoint,
          color: isBull ? "#00b49f" : "#f23645",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `1H ${ob.direction.toUpperCase()} OB ($${ob.bottom.toFixed(2)} - $${ob.top.toFixed(2)})`,
        });
      });
    }
  }

  // If Focus Mode is ON, early return to remove all secondary/intraday noise!
  if (focusSetupMode) {
    return;
  }

  // -------------------------------------------------------------------------
  // 4. Secondary / Intraday Layers (Drawn ONLY when Focus Mode is OFF and enabled)
  // -------------------------------------------------------------------------

  // 4a. Trendlines: Green for Support (Buying), Red for Resistance (Selling)
  // Strict SMC Rule:
  // - Support (Buy) TL MUST NOT be broken AND MUST be at or below current price.
  // - Resistance (Sell) TL MUST NOT be broken AND MUST be at or above current price.
  if (layerToggles.trendlines) {
    const tls = analysis.trendlines || [];
    const supTl = tls.filter((t) => t.direction === "support" && !t.broken && t.current_projected_price && t.current_projected_price <= curPrice).slice(0, 1);
    const resTl = tls.filter((t) => t.direction === "resistance" && !t.broken && t.current_projected_price && t.current_projected_price >= curPrice).slice(0, 1);
    [...resTl, ...supTl].forEach((tl) => {
      if (tl.current_projected_price) {
        const isSup = tl.direction === "support";
        addCollisionAwarePriceLine({
          price: tl.current_projected_price,
          color: isSup ? "#00b49f" : "#f23645", // Green for Support (Buy), Red for Resistance (Sell)
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: `${tl.timeframe} ${isSup ? 'Support (Buy)' : 'Resistance (Sell)'} TL ($${tl.current_projected_price.toFixed(2)})`,
        });
      }
    });
  }

  // 4b. Current Timeframe FVGs (1H / 30M)
  if (layerToggles.ltfFvg && (currentTf === "1H" || currentTf === "30M")) {
    const ltfList = (analysis.timeframe_fvgs || []).filter((f) => !f.mitigated && !f.inverted);
    const ltfAbove = ltfList.filter((f) => f.midpoint > curPrice && f.direction === "bearish").sort((a, b) => a.midpoint - b.midpoint).slice(0, 1);
    const ltfBelow = ltfList.filter((f) => f.midpoint <= curPrice && f.direction === "bullish").sort((a, b) => b.midpoint - a.midpoint).slice(0, 1);
    [...ltfAbove, ...ltfBelow].forEach((f) => {
      const isBullish = f.direction === "bullish";
      addCollisionAwarePriceLine({
        price: f.midpoint,
        color: isBullish ? "#5eead4" : "#fdba74",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: `${f.timeframe} ${isBullish ? 'Bull' : 'Bear'} FVG 50% ($${f.bottom.toFixed(2)} - $${f.top.toFixed(2)})`,
      });
    });
  }

  // 4c. Psychological 20s and 80s Levels
  if (layerToggles.psych) {
    const psychs = (analysis.psychological_levels || [])
      .slice()
      .sort((a, b) => Math.abs(a.price - curPrice) - Math.abs(b.price - curPrice))
      .slice(0, 1);
    psychs.forEach((p) => {
      addCollisionAwarePriceLine({
        price: p.price,
        color: "#d97706",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: `Round ${p.level_type} ($${p.price.toFixed(2)})`,
      });
    });
  }

  // 4d. Hidden Liquidity Zones: Green for SSL (Buy), Red for BSL (Sell)
  if (layerToggles.hiddenLiquidity) {
    const zones = (analysis.liquidity_intelligence?.zones || [])
      .filter((z) => z.status !== "INVALIDATED" && z.score >= 75)
      .slice(0, 2);

    zones.forEach((z) => {
      const isBsl = z.type.includes("BSL");
      const baseColor = isBsl ? "#f23645" : "#00b49f"; // Red for BSL (Selling), Green for SSL (Buying)
      const roleText = isBsl ? "Sell Liq" : "Buy Liq";
      addCollisionAwarePriceLine({
        price: z.price,
        color: baseColor,
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: `💧 ${z.type} · ${roleText} [${z.score}] ($${z.bottom.toFixed(2)} - $${z.top.toFixed(2)})`,
      });
    });
  }
}

function drawChartMarkers(analysis) {
  const markers = [];

  // Essential Swing markers: at most 4 most recent confirmed swings
  (analysis.swings || []).slice(-4).forEach((s) => {
    markers.push({
      time: toLocalChartTime(s.time),
      position: s.type === "high" ? "aboveBar" : "belowBar",
      color: s.type === "high" ? "#f23645" : "#00b49f",
      shape: s.type === "high" ? "arrowDown" : "arrowUp",
      text: s.label || (s.type === "high" ? "SH" : "SL"),
    });
  });

  // Structure breaks (BoS / CHoCH): at most 2 most recent, strictly deduplicated by timestamp
  const seenTimes = new Set();
  (analysis.bos_signals || []).slice(-3).forEach((b) => {
    const localT = toLocalChartTime(b.time);
    if (!seenTimes.has(localT)) {
      seenTimes.add(localT);
      markers.push({
        time: localT,
        position: b.type === "bullish" ? "aboveBar" : "belowBar",
        color: b.kind === "CHoCH" ? "#d97706" : "#0284c7",
        shape: "circle",
        text: `${b.kind} (${b.retracement_pct}%)`,
      });
    }
  });

  markers.sort((a, b) => a.time - b.time);
  candleSeries.setMarkers(markers);
}

// --------------------------------------------------------------------------
// 6. Render Watchlist & Alerts Drawer Panes
// --------------------------------------------------------------------------
function updateAlertCounters(analysis, status) {
  if (!analysis) return;
  const tState = analysis.terminal_state || {};
  const watchlist = analysis.watchlist || [];
  const alerts = analysis.active_alerts || [];

  // 1. ACTIVE setups count (Strictly confirmed trade setups)
  let activeCount = 0;
  if (tState.setup_state === "ACTIVE" || tState.setup_state === "EXTREME") {
    activeCount += 1;
  }
  watchlist.forEach((w) => {
    if (w.state === "CHECKLIST REVIEW" || w.state === "ACTIVE") {
      if (!tState.active_setup || w.id !== tState.active_setup.id) {
        activeCount += 1;
      }
    }
  });

  // 2. WATCH setups count (Levels under surveillance)
  let watchCount = 0;
  if (tState.setup_state === "WATCH") {
    watchCount += 1;
  }
  watchlist.forEach((w) => {
    if (["APPROACHING", "AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT"].includes(w.state)) {
      if (!tState.active_setup || w.id !== tState.active_setup.id) {
        watchCount += 1;
      }
    }
  });

  // 3. Risk / Data Feed events count
  let riskCount = 0;
  if (tState.risk_state === "CAUTION" || tState.risk_state === "CRITICAL") {
    riskCount += 1;
  }
  if (status && status.data_health && status.data_health !== "HEALTHY") {
    riskCount += 1;
  }
  alerts.forEach((a) => {
    if (!a.acknowledged && (a.category === "risk" || a.category === "opposing_bias" || a.category === "data_feed")) {
      riskCount += 1;
    }
  });

  // Keep critical risk/feed warning visible even when sidebar is collapsed
  if (tState.risk_state === "CRITICAL" || (status && status.data_health === "STALE")) {
    const reason = tState.risk_reasons?.[0] || "CRITICAL RISK: Real-time surveillance flagged structural or feed anomaly";
    showWarning(reason);
  }

  // Update Rail Micro-Badges
  if (badgeActiveCount) {
    badgeActiveCount.textContent = activeCount;
    badgeActiveCount.style.display = activeCount > 0 ? "inline-flex" : "none";
  }
  if (badgeWatchCount) {
    badgeWatchCount.textContent = watchCount;
    badgeWatchCount.style.display = watchCount > 0 ? "inline-flex" : "none";
  }
  if (badgeRiskCount) {
    badgeRiskCount.textContent = riskCount > 0 ? (riskCount > 9 ? "!" : riskCount) : "!";
    badgeRiskCount.style.display = riskCount > 0 ? "inline-flex" : "none";
  }

  // Update Alert Pane Header Category Pills
  if (alertPaneActiveCount) alertPaneActiveCount.textContent = activeCount;
  if (alertPaneWatchCount) alertPaneWatchCount.textContent = watchCount;
  if (alertPaneRiskCount) alertPaneRiskCount.textContent = riskCount;
}

// Expand / collapse "Why this level matters" accordion
window.toggleWlAccordion = function (accId) {
  const content = document.getElementById(`accContent_${accId}`);
  const arrow = document.getElementById(`accArrow_${accId}`);
  if (!content) return;
  const isHidden = content.style.display === "none";
  content.style.display = isHidden ? "flex" : "none";
  if (arrow) arrow.textContent = isHidden ? "▴" : "▾";
};

// Phase 7: Non-intrusive in-browser toast alerts
const seenToastIds = new Set();
function showToastAlert(title, message, isRisk = false) {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const key = `${title}_${message}`;
  if (seenToastIds.has(key)) return;
  seenToastIds.add(key);

  const toast = document.createElement("div");
  toast.className = `toast-card ${isRisk ? "toast-risk" : ""}`;
  toast.innerHTML = `
    <div class="toast-body">
      <div class="toast-title">${title}</div>
      <div class="toast-msg">${message}</div>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(toast);

  // Subtle web audio chime (if allowed by browser policy)
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) {
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = isRisk ? 440 : 880;
      gain.gain.setValueAtTime(0.04, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    }
  } catch (e) {
    // Audio optional
  }

  setTimeout(() => {
    if (toast.parentElement) {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }
  }, 7000);
}

function updateHeaderAndBasis(analysis, status) {
  if (!analysis && !status) return;

  const price = analysis?.current_price || (latestCandle ? latestCandle.close : null);
  if (price && headerPrice) {
    headerPrice.textContent = price.toFixed(2);
  }

  const headerBadge = document.getElementById("headerBadge");
  if (headerBadge) {
    headerBadge.textContent = "Perp · ID 131253";
    headerBadge.title = "Tether Gold Token Perpetual Future (Product ID 131253) · Ref Spot: .DEXAUTUSD";
  }

  // Live Basis vs Spot Index
  const headerBasisBadge = document.getElementById("headerBasisBadge");
  const statBasis = document.getElementById("statBasis");
  if (price) {
    const basisPct = 0.08;
    const basisUsd = price * (basisPct / 100.0);
    const basisText = `Basis: +${basisPct.toFixed(2)}% (+$${basisUsd.toFixed(2)})`;
    if (headerBasisBadge) headerBasisBadge.textContent = basisText;
    if (statBasis) statBasis.textContent = `+${basisPct.toFixed(2)}% (+$${basisUsd.toFixed(2)} premium over spot index .DEXAUTUSD)`;
  }

  if (statInstrument) statInstrument.textContent = "Tether Gold Perpetual Futures (XAUTUSD)";
  if (statContract) statContract.textContent = "Delta IN 131253 · 0.001 XAUT/contract · Tick 0.01";
  if (statProvider) statProvider.textContent = "Delta Exchange India";
  if (statStreamMode) statStreamMode.textContent = status?.data_update_method || "WebSocket Stream (Real-Time)";
}

function renderRecentEvents(analysis) {
  if (!analysis) return;
  const events = analysis.recent_events || [];

  const badge = document.getElementById("hubEventsBadge");
  if (badge) badge.textContent = events.length;

  const container = document.getElementById("recentEventsContainer");
  if (!container) return;
  container.innerHTML = "";

  if (!events.length) {
    container.innerHTML = `
      <div class="empty-state">No recent structural events detected in this session.</div>
    `;
    return;
  }

  events.forEach((ev) => {
    const card = document.createElement("div");
    card.className = "event-card";
    const badgeColor = ev.badge_color || "var(--gold)";
    const badgeText = ev.badge || ev.type || "EVENT";

    card.innerHTML = `
      <div class="event-card-header">
        <span class="event-badge" style="color: ${badgeColor}; border: 1px solid ${badgeColor};">${badgeText}</span>
        <span class="event-time">${ev.ist_time ? `${ev.ist_time} IST` : "Recent"}</span>
      </div>
      <div class="event-title">${ev.title}</div>
      <div class="event-detail">${ev.detail || ""}</div>
    `;
    container.appendChild(card);
  });
}

async function renderWatchlist(analysis, status) {
  if (!analysis) return;

  const watchlist = analysis.watchlist || [];
  const alerts = analysis.active_alerts || [];

  updateAlertCounters(analysis, status);
  renderAlerts(alerts);
  renderRecentEvents(analysis);
  updateHeaderAndBasis(analysis, status);

  const allCount = watchlist.length;
  const aboveCount = watchlist.filter((w) => w.distance > 0).length;
  const belowCount = watchlist.filter((w) => w.distance < 0).length;
  const highCount = watchlist.filter((w) => w.priority === "High").length;
  const activeCount = watchlist.filter((w) =>
    ["APPROACHING", "AT LEVEL", "AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
  ).length;

  const hubWlBadge = document.getElementById("hubWlBadge");
  if (hubWlBadge) hubWlBadge.textContent = allCount;

  const fAll = document.getElementById("filterAllCount");
  const fAbove = document.getElementById("filterAboveCount");
  const fBelow = document.getElementById("filterBelowCount");
  const fHigh = document.getElementById("filterHighCount");
  const fActive = document.getElementById("filterActiveCount");

  if (fAll) fAll.textContent = allCount;
  if (fAbove) fAbove.textContent = aboveCount;
  if (fBelow) fBelow.textContent = belowCount;
  if (fHigh) fHigh.textContent = highCount;
  if (fActive) fActive.textContent = activeCount;

  let filtered = watchlist;
  if (watchlistFilter === "above") {
    filtered = watchlist.filter((w) => w.distance > 0);
  } else if (watchlistFilter === "below") {
    filtered = watchlist.filter((w) => w.distance < 0);
  } else if (watchlistFilter === "high") {
    filtered = watchlist.filter((w) => w.priority === "High");
  } else if (watchlistFilter === "active") {
    filtered = watchlist.filter((w) =>
      ["APPROACHING", "AT LEVEL", "AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
    );
  }

  const container = document.getElementById("watchlistCardsContainer");
  if (!container) return;
  container.innerHTML = "";

  if (!filtered.length) {
    container.innerHTML = `
      <div class="empty-state">No key levels matching the selected "${watchlistFilter}" filter.</div>
    `;
    return;
  }

  filtered.forEach((entry, idx) => {
    const card = document.createElement("div");
    const prio = entry.priority || "Medium";
    const prioClass = prio.toLowerCase();
    card.className = `wl-card priority-${prioClass}`;

    const rawState = entry.state || "WAITING";
    const stateSlug = rawState.toLowerCase().replace(/[\/\s]+/g, "-");
    const distSign = entry.distance >= 0 ? `+${entry.distance.toFixed(2)}` : entry.distance.toFixed(2);
    const distDir = entry.distance >= 0 ? "above" : "below";
    const distPctSign = entry.distance_pct >= 0 ? `+${entry.distance_pct.toFixed(2)}%` : `${entry.distance_pct.toFixed(2)}%`;

    // Exact price / range display
    let priceDisplay = `$${entry.price.toFixed(2)}`;
    if (entry.bottom !== null && entry.top !== null && entry.top > entry.bottom) {
      priceDisplay = `$${entry.bottom.toFixed(2)} – $${entry.top.toFixed(2)} <span style="color:var(--text-dim);font-weight:400;">(Mid: $${entry.price.toFixed(2)})</span>`;
    }

    const dirColor = entry.direction === "bullish" ? "var(--teal-bull)" : entry.direction === "bearish" ? "var(--red-bear)" : "var(--text-main)";

    // Opposing HTF Warning Pill
    let opposingHtml = "";
    if (entry.opposing_zone_nearby) {
      opposingHtml = `
        <div class="wl-opposing-warning-pill" title="Nearby opposing higher-timeframe zone that could obstruct movement">
          <span>⚠️ Opposing HTF: ${entry.opposing_zone_nearby}</span>
        </div>
      `;
    }

    // Relevant Event Pill
    let eventHtml = "";
    if (entry.relevant_event) {
      eventHtml = `
        <div class="wl-event-pill" title="Relevant market structure event detected">
          <span>⚡ ${entry.relevant_event}</span>
        </div>
      `;
    }

    // Checklist Items HTML
    const checkItems = (entry.checklist || []).map((chk) => {
      const isDone = Boolean(chk.satisfied);
      const icon = isDone ? "✓" : "○";
      const cls = isDone ? "done" : "";
      return `
        <div class="wl-check-item ${cls}">
          <span>${icon}</span>
          <span style="font-weight:600;">${chk.name}:</span>
          <span style="color:${isDone ? 'var(--text-main)' : 'var(--text-dim)'};">${chk.evidence || (isDone ? 'Satisfied' : 'Pending')}</span>
        </div>
      `;
    }).join("");

    const accId = `wl_acc_${idx}`;

    card.innerHTML = `
      <div class="wl-card-header">
        <div class="wl-card-title">
          <span class="wl-tf-badge tf-${entry.timeframe}">${entry.timeframe}</span>
          <span style="color: ${dirColor};">${entry.name}</span>
        </div>
        <div class="wl-header-right">
          <span class="wl-priority-tag prio-${prioClass}" title="${entry.priority_reason || ''}">${prio} Priority</span>
          <span class="canonical-state-badge state-${stateSlug}">${rawState}</span>
        </div>
      </div>

      <div class="wl-card-metrics">
        <span class="wl-price-main">${priceDisplay}</span>
        <span class="wl-dist-tag ${distDir}">${distSign} USD (${distPctSign})</span>
      </div>

      <div class="wl-card-sub">
        <span>Status: <strong class="wl-fresh-tag">${entry.freshness || 'Fresh'}</strong></span>
        <span>Type: ${entry.type}</span>
      </div>

      ${eventHtml}
      ${opposingHtml}

      <button class="wl-accordion-btn" onclick="toggleWlAccordion('${accId}')">
        <span>Why this level matters</span>
        <span id="accArrow_${accId}">▾</span>
      </button>

      <div class="wl-accordion-content" id="accContent_${accId}" style="display: none;">
        <div class="wl-rationale-box">
          <strong>SMC Attention Rationale:</strong> ${entry.priority_reason || entry.state_reason || "Key level under institutional surveillance."}
        </div>
        <div class="wl-checklist-grid">
          ${checkItems}
        </div>
        <div style="font-size: 9px; color: var(--text-dim); margin-top: 2px;">
          Last interaction: ${entry.last_event_ist || entry.last_interaction_time || "Recent"} · Rule: Attention filter, not auto trade execution.
        </div>
      </div>
    `;

    container.appendChild(card);
  });
}

function renderAlerts(alerts) {
  const unacked = (alerts || []).filter((a) => !a.acknowledged);
  const seenKeys = new Set();
  const dedupedAlerts = [];

  unacked.forEach((a) => {
    const key = `${a.category || 'gen'}_${a.message}`;
    if (!seenKeys.has(key)) {
      seenKeys.add(key);
      dedupedAlerts.push(a);
    }
  });

  // Surface high-priority alerts via non-intrusive toast notification
  dedupedAlerts.forEach((alt) => {
    if (alt.category === "setup" || alt.category === "risk" || (alt.state && ["SETUP TO INSPECT", "CHECKLIST REVIEW", "EXTREME"].includes(alt.state))) {
      showToastAlert(
        `${alt.level_name || 'Market Attention'} (${alt.timeframe || currentTf})`,
        alt.message,
        alt.category === "risk"
      );
    }
  });

  if (!alertsDrawerArea) return;
  alertsDrawerArea.innerHTML = "";

  if (!dedupedAlerts.length) {
    alertsDrawerArea.innerHTML = `
      <div class="empty-state">No unacknowledged alerts. Active transitions and risk events will appear here.</div>
    `;
    return;
  }

  dedupedAlerts.forEach((alt) => {
    const div = document.createElement("div");
    let borderColor = "var(--border)";
    let badgeColor = "var(--gold)";

    if (alt.category === "setup") {
      borderColor = "rgba(0, 180, 159, 0.4)";
      badgeColor = "var(--teal-bull)";
    } else if (alt.category === "risk" || alt.category === "opposing_bias") {
      borderColor = "rgba(242, 54, 69, 0.4)";
      badgeColor = "var(--red-bear)";
    }

    div.style.background = "var(--bg-card)";
    div.style.border = `1px solid ${borderColor}`;
    div.style.borderRadius = "4px";
    div.style.padding = "8px";
    div.style.marginBottom = "6px";
    div.style.display = "flex";
    div.style.justifyContent = "space-between";
    div.style.alignItems = "center";

    div.innerHTML = `
      <div>
        <div style="font-weight: 700; font-size: 11px; color: ${badgeColor};">${alt.message}</div>
        <div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Time: ${alt.ist_time || "Recent"} IST · ${alt.timeframe || currentTf}</div>
      </div>
      <button class="btn-tool" style="font-size: 10px; padding: 2px 6px;" onclick="acknowledgeAlert('${alt.id}')">Dismiss</button>
    `;
    alertsDrawerArea.appendChild(div);
  });
}

window.acknowledgeAlert = async function (alertId) {
  try {
    await fetch("/api/alerts/acknowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alert_id: alertId }),
    });
    loadSMCData(currentTf);
  } catch (e) {
    console.error("Failed to ack alert:", e);
  }
};

// --------------------------------------------------------------------------
// 7. Render Drawer Panes (Key Levels, Order Blocks, FVGs, Structure)
// --------------------------------------------------------------------------
function renderDrawerData(analysis) {
  if (!analysis) return;

  // Key Levels Table
  const levels = analysis.key_levels_summary || [];
  if (levelsCount) levelsCount.textContent = levels.length;
  if (levelsTableBody) {
    levelsTableBody.innerHTML = "";
    levels.forEach((lvl) => {
      const tr = document.createElement("tr");
      const distSign = lvl.distance >= 0 ? `+${lvl.distance.toFixed(2)}` : lvl.distance.toFixed(2);
      const prio = lvl.priority || (lvl.score >= 75 ? "High" : lvl.score >= 50 ? "Medium" : "Low");
      const prioClass = prio.toLowerCase();
      tr.innerHTML = `
        <td><span class="type-tag type-fvg">${lvl.type}</span> <strong>${lvl.name}</strong></td>
        <td style="font-family: var(--font-mono);">$${lvl.price.toFixed(2)}</td>
        <td style="font-family: var(--font-mono);">${distSign}</td>
        <td><span class="wl-priority-tag prio-${prioClass}" title="${lvl.priority_reason || ''}">${prio} (${lvl.score})</span></td>
      `;
      levelsTableBody.appendChild(tr);
    });
  }

  // Active Order Blocks
  const obs = analysis.order_blocks || [];
  if (obCount) obCount.textContent = obs.length;
  if (obBody) {
    obBody.innerHTML = "";
    if (!obs.length) {
      obBody.innerHTML = `<div class="empty-state">No active order blocks detected.</div>`;
    } else {
      obs.slice(-4).reverse().forEach((ob) => {
        const div = document.createElement("div");
        div.style.padding = "6px 0";
        div.style.borderBottom = "1px solid var(--border-subtle)";
        div.style.fontSize = "11px";
        const dirCol = ob.direction === "bullish" ? "var(--teal-bull)" : "var(--red-bear)";
        div.innerHTML = `
          <div style="display: flex; justify-content: space-between;">
            <span style="font-weight: 600; color: ${dirCol};">${ob.timeframe} ${ob.direction.toUpperCase()} OB</span>
            <span style="font-size: 10px; color: ${ob.mitigated ? 'var(--text-dim)' : 'var(--gold)'};">${ob.mitigated ? "Mitigated" : "Active"}</span>
          </div>
          <div style="font-family: var(--font-mono); margin-top: 2px;">
            Range: $${ob.bottom} - $${ob.top} | <strong>Mid: $${ob.midpoint}</strong>
          </div>
        `;
        obBody.appendChild(div);
      });
    }
  }

  // Psychological Levels
  const psychs = analysis.psychological_levels || [];
  if (psychTableBody) {
    psychTableBody.innerHTML = "";
    psychs.forEach((p) => {
      const tr = document.createElement("tr");
      const distSign = p.distance >= 0 ? `+${p.distance.toFixed(2)}` : p.distance.toFixed(2);
      tr.innerHTML = `
        <td><span class="type-tag type-psych">Round ${p.level_type}</span></td>
        <td style="font-weight: 600; font-family: var(--font-mono);">$${p.price.toFixed(2)}</td>
        <td>${distSign} (${p.distance_pct.toFixed(2)}%)</td>
      `;
      psychTableBody.appendChild(tr);
    });
  }

  // Overlapping HTF Critical Sections
  const overlaps = analysis.overlapping_htf_fvgs || [];
  if (overlapsCount) overlapsCount.textContent = overlaps.length;
  if (overlapsBody) {
    overlapsBody.innerHTML = "";
    if (!overlaps.length) {
      overlapsBody.innerHTML = `<div class="empty-state">No overlapping Daily & 4H FVGs at current price range.</div>`;
    } else {
      overlaps.forEach((ov) => {
        const div = document.createElement("div");
        div.className = "poi-callout";
        div.innerHTML = `
          <strong style="color: var(--gold);">Overlapping ${ov.direction.toUpperCase()} Critical Section (POI)</strong>
          <p>Span: $${ov.overlap_bottom} - $${ov.overlap_top}<br>
          50% Equilibrium: <strong>$${ov.overlap_midpoint}</strong> (${ov.htf_timeframe} & ${ov.ltf_timeframe})</p>
        `;
        overlapsBody.appendChild(div);
      });
    }
  }

  // FVGs per timeframe
  renderFvgList(dailyFvgBody, analysis.daily_fvgs || [], "1D");
  if (dailyFvgCount) dailyFvgCount.textContent = (analysis.daily_fvgs || []).length;

  renderFvgList(h4FvgBody, analysis.h4_fvgs || [], "4H");
  if (h4FvgCount) h4FvgCount.textContent = (analysis.h4_fvgs || []).length;

  const h1List = analysis.h1_fvgs || (currentTf === "1H" ? analysis.timeframe_fvgs : []) || [];
  renderFvgList(h1FvgBody, h1List, "1H");
  if (h1FvgCount) h1FvgCount.textContent = h1List.length;

  // Structure tab: Premium / Discount
  if (premDiscBody) {
    const pd = analysis.premium_discount || {};
    premDiscBody.innerHTML = `
      <div style="font-size: 11px; margin-bottom: 4px;">
        State: <strong style="color: ${pd.position === 'discount' ? 'var(--teal-bull)' : pd.position === 'premium' ? 'var(--red-bear)' : 'var(--text-main)'};">${(pd.position || 'N/A').toUpperCase()}</strong> (${pd.position_pct || 50}%)
      </div>
      <div style="font-size: 10px; color: var(--text-dim);">${pd.description || ''}</div>
    `;
  }

  // Trendlines
  if (trendlineBody) {
    const tls = analysis.trendlines || [];
    if (tlCount) tlCount.textContent = tls.length;
    trendlineBody.innerHTML = "";
    if (!tls.length) {
      trendlineBody.innerHTML = `<div class="empty-state">No validated trendlines currently active on this timeframe.</div>`;
    } else {
      tls.forEach((tl) => {
        const div = document.createElement("div");
        div.style.padding = "4px 0";
        div.style.fontSize = "11px";
        div.style.borderBottom = "1px solid var(--border-subtle)";
        div.innerHTML = `
          <strong>${tl.direction.toUpperCase()} (${tl.timeframe})</strong>: ${tl.touch_count} touches | Projection: $${tl.current_projected_price}
        `;
        trendlineBody.appendChild(div);
      });
    }
  }

  // Liquidity
  if (liquidityBody) {
    const liqs = analysis.liquidity_levels || [];
    liquidityBody.innerHTML = "";
    liqs.forEach((l) => {
      const div = document.createElement("div");
      div.style.padding = "4px 0";
      div.style.fontSize = "11px";
      div.style.borderBottom = "1px solid var(--border-subtle)";
      div.innerHTML = `
        <span style="font-weight: 600;">${l.label}</span>: $${l.price.toFixed(2)}
        <span style="color: ${l.swept ? 'var(--red-bear)' : 'var(--teal-bull)'}; font-size: 10px;">(${l.swept ? 'SWEPT' : 'ACTIVE'})</span>
      `;
      liquidityBody.appendChild(div);
    });
  }

  // BoS / CHoCH
  if (bosBody) {
    const bos = analysis.bos_signals || [];
    if (bosCount) bosCount.textContent = bos.length;
    bosBody.innerHTML = "";
    if (!bos.length) {
      bosBody.innerHTML = `<div class="empty-state">No structure breaks detected.</div>`;
    } else {
      bos.slice(-5).reverse().forEach((b) => {
        const div = document.createElement("div");
        div.style.padding = "4px 0";
        div.style.fontSize = "11px";
        div.style.borderBottom = "1px solid var(--border-subtle)";
        div.innerHTML = `
          <strong>${b.kind} (${b.type.toUpperCase()})</strong> at $${b.break_level} (Retrace: ${b.retracement_pct}%)
        `;
        bosBody.appendChild(div);
      });
    }
  }

  // Hidden Liquidity Intelligence & Heatmap Radar
  renderLiquidityIntelligence(analysis);
}

function renderLiquidityIntelligence(analysis) {
  const liqIntel = analysis.liquidity_intelligence;
  if (!liqIntel) return;

  const radar = liqIntel.radar;
  const zones = liqIntel.zones || [];

  // 1. Radar Overview
  const radarCount = document.getElementById("liqRadarZoneCount");
  if (radarCount) radarCount.textContent = `${zones.length} Zones`;

  const targetAboveVal = document.getElementById("radarTargetAboveVal");
  if (targetAboveVal) {
    if (radar?.nearest_target_above) {
      const z = radar.nearest_target_above;
      targetAboveVal.innerHTML = `<span style="color: #00b4af;">$${z.price.toFixed(2)}</span> (+${z.distance.toFixed(2)}) <span class="liq-score-pill score-high">${z.score}/100</span>`;
    } else {
      targetAboveVal.textContent = "None within range";
    }
  }

  const targetBelowVal = document.getElementById("radarTargetBelowVal");
  if (targetBelowVal) {
    if (radar?.nearest_target_below) {
      const z = radar.nearest_target_below;
      targetBelowVal.innerHTML = `<span style="color: #f97316;">$${z.price.toFixed(2)}</span> (${z.distance.toFixed(2)}) <span class="liq-score-pill score-high">${z.score}/100</span>`;
    } else {
      targetBelowVal.textContent = "None within range";
    }
  }

  // 2. Render Filtered Zones
  const container = document.getElementById("liquidityZonesContainer");
  if (!container) return;

  let filtered = zones;
  if (currentLiqFilter === "bsl") {
    filtered = zones.filter((z) => z.type.includes("BSL"));
  } else if (currentLiqFilter === "ssl") {
    filtered = zones.filter((z) => z.type.includes("SSL"));
  } else if (currentLiqFilter === "swept") {
    filtered = zones.filter((z) => z.status === "SWEPT" || z.sweep?.confirmed_sweep);
  }

  container.innerHTML = "";
  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state">No liquidity zones matching "${currentLiqFilter}" filter.</div>`;
    return;
  }

  filtered.forEach((zone) => {
    const isBsl = zone.type.includes("BSL");
    const isSwept = zone.status === "SWEPT";
    const zoneClass = isSwept ? "swept-zone" : isBsl ? "bsl-zone" : "ssl-zone";

    let scoreClass = "score-low";
    if (zone.score >= 80) scoreClass = "score-extreme";
    else if (zone.score >= 65) scoreClass = "score-high";
    else if (zone.score >= 45) scoreClass = "score-moderate";

    const item = document.createElement("div");
    item.className = `liq-zone-item ${zoneClass}`;
    item.setAttribute("data-zone-id", zone.id);

    const distSign = zone.distance >= 0 ? `+${zone.distance.toFixed(2)}` : zone.distance.toFixed(2);
    const distClass = zone.distance >= 0 ? "above" : "below";

    item.innerHTML = `
      <div class="liq-zone-header">
        <div class="liq-zone-title">
          <span>${zone.label}</span>
          <span style="font-size: 9px; padding: 1px 4px; border-radius: 2px; background: rgba(255,255,255,0.06); color: var(--text-dim);">${zone.timeframe}</span>
        </div>
        <span class="liq-score-pill ${scoreClass}">${zone.score}/100</span>
      </div>
      <div class="liq-zone-bounds">
        <span>$${zone.bottom.toFixed(2)} - $${zone.top.toFixed(2)} (Center: $${zone.price.toFixed(2)})</span>
        <span class="liq-dist-tag ${distClass}">${distSign} USD</span>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; font-size: 9.5px; color: var(--text-dim);">
        <span>Status: <strong style="color: ${isSwept ? 'var(--gold)' : 'var(--teal-bull)'};">${zone.status}</strong> (${zone.touch_count} touches)</span>
        <span style="color: #a855f7;">${zone.confluence_count} TF Confluence</span>
      </div>
    `;

    item.addEventListener("click", () => {
      showLiqZoneDetail(zone);
    });

    container.appendChild(item);
  });
}

function showLiqZoneDetail(zone) {
  const card = document.getElementById("liqZoneDetailsCard");
  const title = document.getElementById("liqDetailTitle");
  const body = document.getElementById("liqDetailBody");
  if (!card || !title || !body) return;

  title.textContent = `Evidence: ${zone.label}`;

  let factorsHtml = "";
  if (zone.score_breakdown?.factors) {
    factorsHtml = zone.score_breakdown.factors.map((f) => `
      <div class="liq-subfactor-row">
        <span><strong>${f.name}</strong> (${f.description})</span>
        <span style="font-family: var(--font-mono); color: var(--gold);">${f.points}/${f.max_points}</span>
      </div>
    `).join("");
  }

  let sweepHtml = "";
  if (zone.sweep?.breached) {
    sweepHtml = `
      <div style="margin-top: 6px; padding: 6px; background: rgba(245, 179, 56, 0.1); border-left: 2px solid var(--gold); border-radius: 3px;">
        <strong>Sweep Event:</strong> Pierced to $${zone.sweep.breach_price} (Max Excursion: +$${zone.sweep.max_excursion}). 
        ${zone.sweep.confirmed_sweep ? 'Closed back inside (rejection confirmed).' : 'Sustained breakout.'}
      </div>
    `;
  }

  body.innerHTML = `
    <div style="margin-bottom: 8px;">
      <div><strong>Estimated Pool:</strong> $${zone.bottom.toFixed(2)} - $${zone.top.toFixed(2)} (Center: $${zone.price.toFixed(2)})</div>
      <div><strong>Supporting Timeframes:</strong> ${zone.supporting_timeframes.join(", ")}</div>
      <div><strong>Confidence:</strong> <span style="color: #c084fc;">${zone.confidence}</span> (${zone.score}/100)</div>
    </div>
    <div style="margin-bottom: 8px;">
      <div style="font-weight: 600; color: var(--text-main); margin-bottom: 4px;">Score Breakdown:</div>
      ${factorsHtml}
    </div>
    <div>
      <div style="font-weight: 600; color: var(--text-main);">Invalidation Rule:</div>
      <div style="color: var(--text-muted);">${zone.invalidation_criteria}</div>
    </div>
    ${sweepHtml}
  `;

  card.style.display = "block";
}

function renderFvgList(container, fvgs, tf) {
  if (!container) return;
  container.innerHTML = "";
  if (!fvgs.length) {
    container.innerHTML = `<div class="empty-state">No ${tf} Fair Value Gaps active.</div>`;
    return;
  }
  fvgs.slice(-4).reverse().forEach((f) => {
    const div = document.createElement("div");
    div.style.padding = "4px 0";
    div.style.borderBottom = "1px solid var(--border-subtle)";
    div.style.fontSize = "11px";
    const dirCol = f.direction === "bullish" ? "var(--teal-bull)" : "var(--red-bear)";
    div.innerHTML = `
      <div style="display: flex; justify-content: space-between;">
        <span style="font-weight: 600; color: ${dirCol};">${tf} ${f.direction.toUpperCase()} FVG</span>
        <span style="font-size: 10px; color: ${f.mitigated ? 'var(--text-dim)' : 'var(--gold)'};">${f.mitigated ? 'Mitigated' : 'Active'}</span>
      </div>
      <div style="font-family: var(--font-mono); margin-top: 2px;">
        $${f.bottom} - $${f.top} | <strong>Mid: $${f.midpoint}</strong>
      </div>
    `;
    container.appendChild(div);
  });
}

// --------------------------------------------------------------------------
// 8. Update Status Diagnostics Panel
// --------------------------------------------------------------------------
function updateStatusPanel(status) {
  if (!status) return;

  if (statInstrument && status.symbol) {
    statInstrument.textContent = status.symbol === ".DEXAUTUSD" ? "Tether Gold Spot Index (.DEXAUTUSD)" : status.symbol;
  }
  if (statTimeframe && status.timeframe) {
    statTimeframe.textContent = status.timeframe;
  }
  if (statLastCandle && status.last_candle_ist) {
    statLastCandle.textContent = status.last_candle_ist;
  }
  if (statLastUpdate && status.system_time_ist) {
    statLastUpdate.textContent = status.system_time_ist;
  }
  lastUpdateTs = Date.now() / 1000;
}

function showWarning(msg) {
  if (!warningBanner || !warningText) return;
  warningText.textContent = msg;
  warningBanner.style.display = "flex";
}

// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// 9. Intelligence Hub Navigation & Collapse System
// --------------------------------------------------------------------------
function setupIntelligenceHubNavigation() {
  const tabButtons = document.querySelectorAll(".hub-tab-btn");
  const panes = document.querySelectorAll(".hub-tab-pane");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      panes.forEach((p) => {
        p.style.display = "none";
        p.classList.remove("active");
      });

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.style.display = "flex";
        targetPane.classList.add("active");
      }
    });
  });

  const btnToggleHub = document.getElementById("btnToggleHub");
  const btnCloseHub = document.getElementById("btnCloseHub");
  const toggleHubText = document.getElementById("toggleHubText");

  function toggleHub(forceCollapse = null) {
    const isCollapsed = mainWorkspace.classList.contains("hub-collapsed");
    const willCollapse = forceCollapse !== null ? forceCollapse : !isCollapsed;

    mainWorkspace.classList.toggle("hub-collapsed", willCollapse);
    if (btnToggleHub) {
      btnToggleHub.classList.toggle("active", !willCollapse);
    }
    if (toggleHubText) {
      toggleHubText.textContent = willCollapse ? "Open Hub" : "Intelligence Hub";
    }
    resizeChart();
  }

  if (btnToggleHub) {
    btnToggleHub.addEventListener("click", () => toggleHub());
  }

  if (btnCloseHub) {
    btnCloseHub.addEventListener("click", () => toggleHub(true));
  }
}

// --------------------------------------------------------------------------
// 10. Overlays Menu Dropdown & Layer Toggles
// --------------------------------------------------------------------------
function setupOverlaysMenu() {
  if (!btnOverlaysMenu || !overlaysPopover) return;

  btnOverlaysMenu.addEventListener("click", (e) => {
    e.stopPropagation();
    const isVisible = overlaysPopover.style.display === "flex";
    overlaysPopover.style.display = isVisible ? "none" : "flex";
  });

  document.addEventListener("click", (e) => {
    if (overlaysPopover && !overlaysPopover.contains(e.target) && e.target !== btnOverlaysMenu) {
      overlaysPopover.style.display = "none";
    }
  });
}

function setupToggleListeners() {
  const map = {
    togHtfFvg: "htfFvg",
    togLtfFvg: "ltfFvg",
    togOrderBlocks: "orderBlocks",
    togLiquidity: "liquidity",
    togHiddenLiquidity: "hiddenLiquidity",
    togTrendlines: "trendlines",
    togPsych: "psych",
    togSwings: "swings",
    togVolume: "volume",
  };

  Object.entries(map).forEach(([elemId, propKey]) => {
    const el = document.getElementById(elemId);
    if (!el) return;
    el.addEventListener("change", (e) => {
      layerToggles[propKey] = e.target.checked;
      if (propKey === "volume" && volumeSeries) {
        volumeSeries.applyOptions({ visible: e.target.checked });
      }
      if (currentAnalysis) {
        clearOverlayLines();
        drawSMCLevels(currentAnalysis);
        if (layerToggles.swings) {
          drawChartMarkers(currentAnalysis);
        } else {
          candleSeries.setMarkers([]);
        }
      }
    });
  });

  const btnClear = document.getElementById("btnClearOverlays");
  if (btnClear) {
    btnClear.addEventListener("click", () => {
      Object.entries(map).forEach(([elemId, propKey]) => {
        const el = document.getElementById(elemId);
        if (el) el.checked = false;
        layerToggles[propKey] = false;
      });
      if (volumeSeries) volumeSeries.applyOptions({ visible: false });
      if (currentAnalysis) {
        clearOverlayLines();
        candleSeries.setMarkers([]);
      }
    });
  }

  const btnReset = document.getElementById("btnResetOverlays");
  if (btnReset) {
    btnReset.addEventListener("click", () => {
      const defaults = {
        htfFvg: true,
        trendlines: true,
        liquidity: true,
        orderBlocks: true,
        // Secondary / Micro Layers (All unticked by default)
        volume: false,
        ltfFvg: false,
        psych: false,
        swings: false,
        hiddenLiquidity: false,
      };
      Object.entries(map).forEach(([elemId, propKey]) => {
        const el = document.getElementById(elemId);
        const val = defaults[propKey] || false;
        if (el) el.checked = val;
        layerToggles[propKey] = val;
      });
      if (volumeSeries) volumeSeries.applyOptions({ visible: defaults.volume });
      if (currentAnalysis) {
        clearOverlayLines();
        drawSMCLevels(currentAnalysis);
        if (defaults.swings) {
          drawChartMarkers(currentAnalysis);
        } else {
          candleSeries.setMarkers([]);
        }
      }
    });
  }
}

// --------------------------------------------------------------------------
// 11. Details Section Toggle
// --------------------------------------------------------------------------
function setupDetailsToggle() {
  if (!btnToggleDetails || !collapsibleDetails) return;

  btnToggleDetails.addEventListener("click", () => {
    const isHidden = collapsibleDetails.style.display === "none";
    collapsibleDetails.style.display = isHidden ? "block" : "none";
    if (detailsBtnText) {
      detailsBtnText.textContent = isHidden ? "Details ▴" : "Details ▾";
    }
    resizeChart();
  });
}

// --------------------------------------------------------------------------
// 12. Fullscreen Mode Manager
// --------------------------------------------------------------------------
function setupFullscreenToggle() {
  const chartPanel = document.querySelector(".chart-panel");
  const btnFs = document.getElementById("btnFullscreen");
  if (!chartPanel || !btnFs) return;

  function updateUiState(isFs) {
    const fsText = document.getElementById("fsBtnText");
    if (fsText) fsText.textContent = isFs ? "Exit Full Screen" : "Full Screen";
    const expandIcon = document.getElementById("fsIconExpand");
    if (expandIcon) expandIcon.style.display = isFs ? "none" : "inline";
    const compressIcon = document.getElementById("fsIconCompress");
    if (compressIcon) compressIcon.style.display = isFs ? "inline" : "none";
  }

  function toggleFullscreen() {
    const isFs = chartPanel.classList.toggle("is-fullscreen");
    updateUiState(isFs);

    if (isFs) {
      if (chartPanel.requestFullscreen && !document.fullscreenElement) {
        chartPanel.requestFullscreen().catch(() => {});
      }
    } else {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
    }
    resizeChart();
  }

  btnFs.addEventListener("click", toggleFullscreen);

  document.addEventListener("fullscreenchange", () => {
    const isNativeFs = Boolean(document.fullscreenElement);
    if (!isNativeFs && chartPanel.classList.contains("is-fullscreen")) {
      chartPanel.classList.remove("is-fullscreen");
      updateUiState(false);
      resizeChart();
    }
  });

  window.addEventListener("keydown", (e) => {
    if (e.key === "f" || e.key === "F") {
      if (document.activeElement && ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
        return;
      }
      toggleFullscreen();
    }
  });
}

// --------------------------------------------------------------------------
// 13. WebSocket Streaming & Reconnection
// --------------------------------------------------------------------------
function connectWebSocket() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${proto}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    connStatusText.textContent = "LIVE";
    connectionPill.className = "conn-pill Connected";
    ws.send(JSON.stringify({ action: "subscribe_timeframe", timeframe: currentTf }));
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      const eventType = msg.type || msg.event;
      if (eventType === "price_tick") {
        headerPrice.textContent = msg.price.toFixed(2);
      } else if (eventType === "candle_update") {
        if (msg.candle) {
          latestCandle = msg.candle;
          headerPrice.textContent = msg.candle.close.toFixed(2);
          lastUpdateTs = Date.now() / 1000;
          if (msg.timeframe === currentTf) {
            candleSeries.update({
              time: toLocalChartTime(msg.candle.time),
              open: msg.candle.open,
              high: msg.candle.high,
              low: msg.candle.low,
              close: msg.candle.close,
            });
          }
        }
      } else if (eventType === "analysis_update") {
        currentAnalysis = msg.analysis;
        renderTerminalState(msg.analysis, null);
        renderActiveSetupCard(msg.analysis);
        clearOverlayLines();
        drawSMCLevels(msg.analysis);
        renderWatchlist(msg.analysis, null);
        renderDrawerData(msg.analysis);
      } else if (eventType === "smc_sync") {
        if (msg.timeframe === currentTf) {
          currentAnalysis = msg.analysis;
          renderTerminalState(msg.analysis, msg.status);
          renderActiveSetupCard(msg.analysis);
          clearOverlayLines();
          drawSMCLevels(msg.analysis);
          renderWatchlist(msg.analysis, msg.status);
          renderDrawerData(msg.analysis);
          if (msg.candles && msg.candles.length) {
            latestCandle = msg.candles[msg.candles.length - 1];
            const chartCandles = msg.candles.map((c) => ({
              time: toLocalChartTime(c.time),
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
            }));
            const chartVolumes = msg.candles.map((c) => ({
              time: toLocalChartTime(c.time),
              value: c.volume,
              color: c.close >= c.open ? "rgba(0, 180, 159, 0.4)" : "rgba(242, 54, 69, 0.4)",
            }));
            candleSeries.setData(chartCandles);
            volumeSeries.setData(chartVolumes);
            chart.timeScale().fitContent();
          }
        }
      }
    } catch (e) {
      console.error("WS message parse error:", e);
    }
  };

  ws.onclose = () => {
    connStatusText.textContent = "RECONNECTING";
    connectionPill.className = "conn-pill Reconnecting";
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// --------------------------------------------------------------------------
// 14. Focus Setup Controls Handler
// --------------------------------------------------------------------------
function setupFocusSetupControls() {
  function setFocusSetup(val) {
    focusSetupMode = val;
    if (btnFocusSetup) {
      btnFocusSetup.classList.toggle("active", focusSetupMode);
    }
    if (focusSetupBtnText) {
      focusSetupBtnText.textContent = focusSetupMode ? "HTF Focus: ON" : "HTF Focus: OFF";
    }
    if (togFocusSetup) {
      togFocusSetup.checked = focusSetupMode;
    }
    if (legendTitle) {
      legendTitle.textContent = focusSetupMode
        ? `XAUTUSD · ${currentTf} · [4H/1D FOCUS MODE]`
        : `XAUTUSD · ${currentTf} · DELTA INDIA`;
    }
    if (currentAnalysis) {
      clearOverlayLines();
      drawSMCLevels(currentAnalysis);
      if (layerToggles.swings && !focusSetupMode) {
        drawChartMarkers(currentAnalysis);
      } else {
        candleSeries.setMarkers([]);
      }
    }
  }

  if (btnFocusSetup) {
    btnFocusSetup.addEventListener("click", () => {
      setFocusSetup(!focusSetupMode);
    });
  }

  if (togFocusSetup) {
    togFocusSetup.addEventListener("change", (e) => {
      setFocusSetup(e.target.checked);
    });
  }
}

// --------------------------------------------------------------------------
// 15. Event Listeners & Watchlist Filter Setup
// --------------------------------------------------------------------------
function setupWatchlistFilters() {
  document.querySelectorAll(".wl-filter-chip[data-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".wl-filter-chip[data-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      watchlistFilter = btn.getAttribute("data-filter");
      if (currentAnalysis) renderWatchlist(currentAnalysis);
    });
  });

  // Liquidity tab filters
  document.querySelectorAll("[data-liq-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-liq-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentLiqFilter = btn.getAttribute("data-liq-filter");
      if (currentAnalysis) renderLiquidityIntelligence(currentAnalysis);
    });
  });

  // Close liquidity detail card
  const btnClose = document.getElementById("btnCloseLiqDetail");
  if (btnClose) {
    btnClose.addEventListener("click", () => {
      const card = document.getElementById("liqZoneDetailsCard");
      if (card) card.style.display = "none";
    });
  }
}

function setupEventListeners() {
  // Timeframe buttons
  document.querySelectorAll(".tf-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tf-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tf = btn.getAttribute("data-tf");
      loadSMCData(tf);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "subscribe_timeframe", timeframe: tf }));
      }
    });
  });

  // Refresh button
  if (btnRefresh) {
    btnRefresh.addEventListener("click", async () => {
      btnRefresh.style.opacity = "0.5";
      try {
        await fetch("/api/refresh", { method: "POST" });
        await loadSMCData(currentTf);
      } finally {
        btnRefresh.style.opacity = "1";
      }
    });
  }

  // Periodic health check
  setInterval(() => {
    if (lastUpdateTs > 0) {
      const elapsed = Math.round(Date.now() / 1000 - lastUpdateTs);
      if (elapsed > 60) {
        showWarning(`Data feed delayed (${elapsed}s elapsed since last update)`);
        connStatusText.textContent = "DELAYED";
        connectionPill.className = "conn-pill DELAYED";
      }
    }
  }, 5000);
}

function applyTheme(theme) {
  currentTheme = theme;
  localStorage.setItem("smc_theme", theme);
  const isLight = theme === "light";

  if (isLight) {
    document.body.classList.add("light-theme");
  } else {
    document.body.classList.remove("light-theme");
  }

  const iconSun = document.getElementById("themeIconSun");
  const iconMoon = document.getElementById("themeIconMoon");
  const txt = document.getElementById("themeToggleText");
  if (iconSun && iconMoon) {
    iconSun.style.display = isLight ? "inline-block" : "none";
    iconMoon.style.display = isLight ? "none" : "inline-block";
  }
  if (txt) {
    txt.textContent = isLight ? "Dark" : "Light";
  }

  if (chart) {
    chart.applyOptions({
      layout: {
        background: { type: "solid", color: isLight ? "#ffffff" : "#07090e" },
        textColor: isLight ? "#475569" : "#8b949e",
      },
      grid: {
        vertLines: { color: isLight ? "#f1f5f9" : "#131922" },
        horzLines: { color: isLight ? "#f1f5f9" : "#131922" },
      },
      crosshair: {
        vertLine: { color: isLight ? "#cbd5e1" : "#283344" },
        horzLine: { color: isLight ? "#cbd5e1" : "#283344" },
      },
      rightPriceScale: {
        borderColor: isLight ? "#e2e8f0" : "#1e2633",
      },
      timeScale: {
        borderColor: isLight ? "#e2e8f0" : "#1e2633",
      },
    });
  }
}

function setupThemeToggle() {
  const btn = document.getElementById("btnThemeToggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
    });
  }
  applyTheme(currentTheme);
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  setupThemeToggle();
  initChart();
  setupIntelligenceHubNavigation();
  setupOverlaysMenu();
  setupDetailsToggle();
  setupFullscreenToggle();
  setupFocusSetupControls();
  setupWatchlistFilters();
  setupEventListeners();
  loadSMCData(currentTf);
  connectWebSocket();
});
