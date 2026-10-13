/**
 * Signal-First Institutional Trading Command Center - Frontend Application
 * Delta Exchange India · XAUTUSD SMC Terminal
 * Connects to local backend adapter and renders TradingView Lightweight Charts
 * with genuine multi-timeframe SMC overlays, unified terminal state machine,
 * single prioritized active setup card, and collapsed icon rail drawer.
 */

// Global State
let currentTf = "1H";
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

// Overlay Layer Toggles
const layerToggles = {
  htfFvg: true,
  ltfFvg: true,
  orderBlocks: true,
  liquidity: true,
  trendlines: true,
  psych: true,
  swings: true,
  volume: true,
};

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

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      background: { type: "solid", color: "#07090e" },
      textColor: "#8b949e",
      fontSize: 11,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace',
    },
    grid: {
      vertLines: { color: "#131922" },
      horzLines: { color: "#131922" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: "#283344", width: 1, style: LightweightCharts.LineStyle.Dashed },
      horzLine: { color: "#283344", width: 1, style: LightweightCharts.LineStyle.Dashed },
    },
    rightPriceScale: {
      borderColor: "#1e2633",
      scaleMargins: { top: 0.08, bottom: 0.15 },
    },
    timeScale: {
      borderColor: "#1e2633",
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
      legendTitle.textContent = `XAUTUSD · ${currentTf} · DELTA INDIA`;
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
    const ist = status.last_candle_ist || status.system_time_ist || "";
    if (ist) {
      headerSourceTime.textContent = `${ist} IST`;
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

  // If dismissed or no qualifying setup exists: show quiet neutral state
  if (!setup || setup.id === dismissedSetupId || tState.setup_state === "IDLE") {
    activeSetupContainer.innerHTML = `
      <div class="active-setup-card idle-card" id="activeSetupCard">
        <div class="idle-message">
          <span class="idle-indicator"></span>
          <span>Market surveillance idle — monitoring SMC structural key levels for qualified trade setups</span>
        </div>
      </div>
    `;
    return;
  }

  const state = setup.state || "WATCH";
  const isBull = setup.direction === "bullish";
  const dirIcon = isBull ? "▲ LONG" : "▼ SHORT";
  const dirTagClass = isBull ? "bullish" : "bearish";

  // State-specific styles and banners
  let cardStateClass = "card-watch";
  let stateBannerHtml = "";

  if (state === "EXTREME") {
    cardStateClass = "card-extreme";
    stateBannerHtml = `
      <div class="state-banner extreme-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
        <span>⚡ EXTREME CONFLUENCE · Multi-Timeframe Institutional Confluence</span>
      </div>
    `;
  } else if (state === "ACTIVE") {
    cardStateClass = "card-active";
    stateBannerHtml = `
      <div class="state-banner active-confirmed-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        <span>✓ ACTIVE SETUP CONFIRMED · Strict Entry & Rejection Criteria Satisfied</span>
      </div>
    `;
  } else if (state === "INVALIDATED") {
    cardStateClass = "card-invalidated";
    const invalReason = setup.reason || (setup.is_target_reached ? "Target already reached. Setup expired." : "Structural invalidation triggered");
    stateBannerHtml = `
      <div class="state-banner invalidated-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        <span>✕ SETUP INVALIDATED / EXPIRED · ${invalReason}</span>
      </div>
    `;
  } else {
    // WATCH is default
    cardStateClass = "card-watch";
    stateBannerHtml = `
      <div class="state-banner waiting-banner">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span>⏳ WAITING FOR CONFIRMATION · Pending closed-candle rejection & trigger rule</span>
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

  // Directional Context (framing as context, not execution instruction)
  const dirContextLabel = setup.directional_context || `${dirIcon} Bias`;

  activeSetupContainer.innerHTML = `
    <div class="active-setup-card ${cardStateClass}" id="activeSetupCard">
      ${stateBannerHtml}
      <div class="card-top-row">
        <div class="card-identity">
          <span class="directional-context-tag ${dirTagClass}">${dirContextLabel}</span>
          <span class="setup-title">${setup.name} (${setup.timeframe})</span>
          <span class="quality-badge">${setup.quality}</span>
          <span class="setup-pill ${state.toLowerCase()}" style="font-size: 9px; padding: 1px 6px;">${state}</span>
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

      <div class="card-bottom-row">
        <div class="card-checklist-badges">${checklistsHtml}</div>
        <div class="card-reason" style="font-size: 10px; color: var(--text-dim);">
          ${setup.reason || (state === "WATCH" ? "Awaiting price reaction & closed-candle confirmation inside POI" : "Real-time SMC trigger criteria active")}
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

      if (layerToggles.swings) {
        drawChartMarkers(analysis);
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
// Prevents overlapping price axis scale badges when lines are within 1.20 USD of each other
function addCollisionAwarePriceLine(opts) {
  const COLLISION_THRESHOLD = 1.20; // 1.20 USD minimum separation on price axis
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

  const setup = analysis.terminal_state?.active_setup;

  // -------------------------------------------------------------------------
  // Priority 1: Focus Setup Mode POI, Target & Invalidation (Highest Priority)
  // -------------------------------------------------------------------------
  if (focusSetupMode && setup && setup.state !== "IDLE") {
    const isBull = setup.direction === "bullish";
    const setupColor = isBull ? "#00b49f" : "#f97316";

    // Setup Target (TP)
    if (setup.target_price) {
      addCollisionAwarePriceLine({
        price: setup.target_price,
        color: "#00b49f",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `★ FOCUS TARGET (TP): $${setup.target_price.toFixed(2)}`,
      });
    }

    // Setup Invalidation (SL)
    if (setup.invalidation_price) {
      addCollisionAwarePriceLine({
        price: setup.invalidation_price,
        color: "#f23645",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `★ FOCUS INVALIDATION (SL): $${setup.invalidation_price.toFixed(2)}`,
      });
    }
  }

  // -------------------------------------------------------------------------
  // 1. Liquidity Levels (PDH, PDL, PWH, PWL)
  // -------------------------------------------------------------------------
  if (layerToggles.liquidity) {
    const liqs = analysis.liquidity_levels || [];
    liqs.forEach((l) => {
      const isFaded = focusSetupMode;
      if (l.type === "PDH" || l.type === "PDL") {
        addCollisionAwarePriceLine({
          price: l.price,
          color: isFaded ? "rgba(41, 182, 246, 0.4)" : (l.type === "PDH" ? "#29b6f6" : "#0288d1"),
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: !isFaded,
          title: `${l.type} ($${l.price.toFixed(2)}) [${l.swept ? "SWEPT" : "ACTIVE"}]`,
        });
      } else if (l.type === "PWH" || l.type === "PWL") {
        addCollisionAwarePriceLine({
          price: l.price,
          color: isFaded ? "rgba(38, 198, 218, 0.3)" : "#26c6da",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: !isFaded,
          title: `${l.type} ($${l.price.toFixed(2)})`,
        });
      }
    });
  }

  // -------------------------------------------------------------------------
  // 2. Higher Timeframe FVGs (1D & 4H)
  // -------------------------------------------------------------------------
  if (layerToggles.htfFvg) {
    const htfFvgs = [...(analysis.daily_fvgs || []), ...(analysis.h4_fvgs || [])];
    htfFvgs.forEach((f) => {
      if (!f.mitigated && !f.inverted) {
        const isBullish = f.direction === "bullish";
        const isFocusPOI = focusSetupMode && setup && Math.abs(setup.distance) < 50 && f.timeframe === setup.timeframe;
        
        let fvgColor = isBullish ? "#00b49f" : "#f97316";
        let boundColor = isBullish ? "rgba(0, 180, 159, 0.45)" : "rgba(249, 115, 22, 0.45)";
        let lineWidth = isFocusPOI ? 3 : 2;

        if (focusSetupMode && !isFocusPOI) {
          fvgColor = isBullish ? "rgba(0, 180, 159, 0.25)" : "rgba(249, 115, 22, 0.25)";
          boundColor = "rgba(100, 116, 139, 0.15)";
          lineWidth = 1;
        }

        const dirLabel = isBullish ? "Bullish" : "Bearish";
        const prefix = isFocusPOI ? "★ FOCUS POI: " : "";

        // 50% Midpoint POI line
        addCollisionAwarePriceLine({
          price: f.midpoint,
          color: fvgColor,
          lineWidth: lineWidth,
          lineStyle: isFocusPOI ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.SparseDotted,
          axisLabelVisible: !focusSetupMode || isFocusPOI,
          title: `${prefix}${f.timeframe} ${dirLabel} FVG 50% ($${f.bottom.toFixed(2)} - $${f.top.toFixed(2)})`,
        });

        // Boundary lines
        addCollisionAwarePriceLine({
          price: f.top,
          color: boundColor,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: false,
          title: `${f.timeframe} Top: $${f.top.toFixed(2)}`,
        });
        addCollisionAwarePriceLine({
          price: f.bottom,
          color: boundColor,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: false,
          title: `${f.timeframe} Bot: $${f.bottom.toFixed(2)}`,
        });
      }
    });
  }

  // -------------------------------------------------------------------------
  // 3. Current Timeframe FVGs (Controlled by Current TF FVGs toggle)
  // -------------------------------------------------------------------------
  if (layerToggles.ltfFvg) {
    if (currentTf === "1H") {
      // 1H FVGs ONLY appear on 1H timeframe: Lighter mint / peach tint
      const h1List = analysis.timeframe_fvgs || analysis.h1_fvgs || [];
      h1List.slice(-4).forEach((f) => {
        if (!f.mitigated && !f.inverted) {
          const isBullish = f.direction === "bullish";
          let fvgColor = isBullish ? "#5eead4" : "#fdba74";
          let boundColor = isBullish ? "rgba(94, 234, 212, 0.35)" : "rgba(253, 186, 116, 0.35)";

          if (focusSetupMode) {
            fvgColor = isBullish ? "rgba(94, 234, 212, 0.2)" : "rgba(253, 186, 116, 0.2)";
            boundColor = "rgba(100, 116, 139, 0.12)";
          }

          const dirLabel = isBullish ? "Bullish" : "Bearish";

          addCollisionAwarePriceLine({
            price: f.midpoint,
            color: fvgColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: !focusSetupMode,
            title: `1H ${dirLabel} FVG 50% ($${f.bottom.toFixed(2)} - $${f.top.toFixed(2)})`,
          });

          addCollisionAwarePriceLine({
            price: f.top,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
          addCollisionAwarePriceLine({
            price: f.bottom,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
        }
      });
    } else if (currentTf !== "1D" && currentTf !== "4H") {
      // Sub-Hourly Timeframes (30M, 15M, 5M, 1M): Only render that timeframe's own FVGs (never 1H FVGs)
      (analysis.timeframe_fvgs || []).slice(-4).forEach((f) => {
        if (!f.mitigated && !f.inverted) {
          const isBullish = f.direction === "bullish";
          let fvgColor = isBullish ? "#29b6f6" : "#e91e63";
          let boundColor = isBullish ? "rgba(41, 182, 246, 0.35)" : "rgba(233, 30, 99, 0.35)";

          if (focusSetupMode) {
            fvgColor = isBullish ? "rgba(41, 182, 246, 0.2)" : "rgba(233, 30, 99, 0.2)";
            boundColor = "rgba(100, 116, 139, 0.12)";
          }

          const dirLabel = isBullish ? "Bullish" : "Bearish";

          addCollisionAwarePriceLine({
            price: f.midpoint,
            color: fvgColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: !focusSetupMode,
            title: `${f.timeframe} ${dirLabel} FVG 50% ($${f.bottom.toFixed(2)} - $${f.top.toFixed(2)})`,
          });

          addCollisionAwarePriceLine({
            price: f.top,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
          addCollisionAwarePriceLine({
            price: f.bottom,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
        }
      });
    }
  }

  // -------------------------------------------------------------------------
  // 4. Order Blocks
  // -------------------------------------------------------------------------
  if (layerToggles.orderBlocks) {
    const obs = analysis.order_blocks || [];
    obs.slice(-4).forEach((ob) => {
      if (!ob.mitigated) {
        const isFaded = focusSetupMode;
        addCollisionAwarePriceLine({
          price: ob.midpoint,
          color: isFaded ? "rgba(38, 166, 154, 0.25)" : (ob.direction === "bullish" ? "#26a69a" : "#ab47bc"),
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: !isFaded,
          title: `${ob.timeframe} ${ob.direction.toUpperCase()} OB 50% ($${ob.bottom.toFixed(2)} - $${ob.top.toFixed(2)})`,
        });
      }
    });
  }

  // -------------------------------------------------------------------------
  // 5. Psychological 20s and 80s Levels
  // -------------------------------------------------------------------------
  if (layerToggles.psych && !focusSetupMode) {
    const psychs = analysis.psychological_levels || [];
    psychs.slice(0, 3).forEach((p) => {
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

  // -------------------------------------------------------------------------
  // 6. Trendlines
  // -------------------------------------------------------------------------
  if (layerToggles.trendlines && !focusSetupMode) {
    const tls = analysis.trendlines || [];
    tls.forEach((tl) => {
      if (tl.current_projected_price) {
        addCollisionAwarePriceLine({
          price: tl.current_projected_price,
          color: tl.direction === "resistance" ? "#ef5350" : "#26a69a",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: `${tl.timeframe} TL (${tl.touch_count}T: $${tl.current_projected_price.toFixed(2)})`,
        });
      }
    });
  }
}

function drawChartMarkers(analysis) {
  const markers = [];

  // Swing markers
  (analysis.swings || []).slice(-8).forEach((s) => {
    markers.push({
      time: toLocalChartTime(s.time),
      position: s.type === "high" ? "aboveBar" : "belowBar",
      color: s.type === "high" ? "#f23645" : "#00b49f",
      shape: s.type === "high" ? "arrowDown" : "arrowUp",
      text: s.label || (s.type === "high" ? "SH" : "SL"),
    });
  });

  // Structure breaks (BoS / CHoCH)
  (analysis.bos_signals || []).slice(-4).forEach((b) => {
    markers.push({
      time: toLocalChartTime(b.time),
      position: b.type === "bullish" ? "aboveBar" : "belowBar",
      color: b.kind === "CHoCH" ? "#d97706" : "#0284c7",
      shape: "circle",
      text: `${b.kind} (${b.retracement_pct}%)`,
    });
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

async function renderWatchlist(analysis, status) {
  if (!analysis) return;

  let watchlist = analysis.watchlist || [];
  let alerts = analysis.active_alerts || [];

  updateAlertCounters(analysis, status);
  renderAlerts(alerts);

  const allCount = watchlist.length;
  const activeCount = watchlist.filter(
    (w) => ["APPROACHING", "AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
  ).length;
  const setupsCount = watchlist.filter(
    (w) => ["SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
  ).length;

  if (filterAllCount) filterAllCount.textContent = allCount;
  if (filterActiveCount) filterActiveCount.textContent = activeCount;
  if (filterSetupsCount) filterSetupsCount.textContent = setupsCount;

  let filtered = watchlist;
  if (watchlistFilter === "active") {
    filtered = watchlist.filter((w) =>
      ["APPROACHING", "AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
    );
  } else if (watchlistFilter === "setups") {
    filtered = watchlist.filter((w) =>
      ["SETUP TO INSPECT", "CHECKLIST REVIEW"].includes(w.state)
    );
  }

  if (!watchlistCardsContainer) return;
  watchlistCardsContainer.innerHTML = "";

  if (!filtered.length) {
    watchlistCardsContainer.innerHTML = `
      <div class="empty-state">No key levels matching the selected filter.</div>
    `;
    return;
  }

  filtered.forEach((entry) => {
    const card = document.createElement("div");
    let stateClass = "state-watch";
    if (entry.state === "CHECKLIST REVIEW") stateClass = "state-active";
    if (entry.score >= 85) stateClass = "state-extreme";

    card.className = `surveillance-card ${stateClass}`;
    const distSign = entry.distance >= 0 ? `+${entry.distance.toFixed(2)}` : entry.distance.toFixed(2);
    const dirCol = entry.direction === "bullish" ? "var(--teal-bull)" : entry.direction === "bearish" ? "var(--red-bear)" : "var(--text-main)";

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: baseline;">
        <span style="font-weight: 700; color: ${dirCol}; font-size: 11px;">${entry.name} (${entry.timeframe})</span>
        <span style="font-size: 9px; font-weight: 700; color: var(--gold);">${entry.state}</span>
      </div>
      <div style="font-family: var(--font-mono); font-size: 11px; margin-top: 3px; display: flex; justify-content: space-between;">
        <span>$${entry.price.toFixed(2)}</span>
        <span style="color: var(--text-muted);">${distSign} (${entry.distance_pct.toFixed(2)}%)</span>
      </div>
      <div style="font-size: 10px; color: var(--text-dim); margin-top: 4px;">
        ${entry.state_reason}
      </div>
    `;
    watchlistCardsContainer.appendChild(card);
  });
}

function renderAlerts(alerts) {
  // Deduplicate unacknowledged alerts to avoid spam
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
      tr.innerHTML = `
        <td><span class="type-tag type-fvg">${lvl.type}</span> <strong>${lvl.name}</strong></td>
        <td style="font-family: var(--font-mono);">$${lvl.price.toFixed(2)}</td>
        <td style="font-family: var(--font-mono);">${distSign}</td>
        <td><strong style="color: var(--gold);">${lvl.score}</strong></td>
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
// 9. Drawer Navigation & Pinning System
// --------------------------------------------------------------------------
function setupDrawerNavigation() {
  const railButtons = document.querySelectorAll(".rail-btn");
  const panes = document.querySelectorAll(".drawer-pane");

  const paneTitles = {
    "pane-alerts": "Active Alerts",
    "pane-setups": "Trade-Readiness Watchlist",
    "pane-levels": "SMC Key Levels & Order Blocks",
    "pane-fvg": "Fair Value Gaps & Overlaps",
    "pane-structure": "Market Structure & Swings",
    "pane-strategy": "Strategy Playbook & Rules",
  };

  function openPane(paneId) {
    panes.forEach((p) => (p.style.display = "none"));
    railButtons.forEach((b) => b.classList.remove("active"));

    const targetPane = document.getElementById(paneId);
    if (targetPane) targetPane.style.display = "flex";

    const targetBtn = document.querySelector(`.rail-btn[data-pane="${paneId}"]`);
    if (targetBtn) targetBtn.classList.add("active");

    if (drawerTitle) drawerTitle.textContent = paneTitles[paneId] || "Intelligence Drawer";
    slideDrawer.style.display = "flex";
    activeDrawerPane = paneId;

    if (isDrawerPinned) {
      mainWorkspace.classList.add("drawer-pinned");
      resizeChart();
    }
  }

  function closeDrawer() {
    slideDrawer.style.display = "none";
    railButtons.forEach((b) => b.classList.remove("active"));
    activeDrawerPane = null;
    mainWorkspace.classList.remove("drawer-pinned");
    resizeChart();
  }

  railButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const paneId = btn.getAttribute("data-pane");
      if (slideDrawer.style.display === "flex" && activeDrawerPane === paneId) {
        closeDrawer();
      } else {
        openPane(paneId);
      }
    });
  });

  if (btnCloseDrawer) {
    btnCloseDrawer.addEventListener("click", closeDrawer);
  }

  if (btnPinDrawer) {
    btnPinDrawer.addEventListener("click", () => {
      isDrawerPinned = !isDrawerPinned;
      btnPinDrawer.classList.toggle("pinned", isDrawerPinned);
      if (pinBtnText) pinBtnText.textContent = isDrawerPinned ? "Pinned" : "Pin";
      mainWorkspace.classList.toggle("drawer-pinned", isDrawerPinned);
      resizeChart();
    });
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
      focusSetupBtnText.textContent = focusSetupMode ? "Focus: ON" : "Focus: OFF";
    }
    if (togFocusSetup) {
      togFocusSetup.checked = focusSetupMode;
    }
    if (currentAnalysis) {
      clearOverlayLines();
      drawSMCLevels(currentAnalysis);
      if (layerToggles.swings) {
        drawChartMarkers(currentAnalysis);
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
  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      watchlistFilter = btn.getAttribute("data-filter");
      if (currentAnalysis) renderWatchlist(currentAnalysis);
    });
  });
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

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  setupDrawerNavigation();
  setupOverlaysMenu();
  setupDetailsToggle();
  setupFullscreenToggle();
  setupFocusSetupControls();
  setupWatchlistFilters();
  setupEventListeners();
  loadSMCData(currentTf);
  connectWebSocket();
});
