/**
 * SMC Key-Level Intelligence Dashboard - Frontend Application
 * Connects to Delta Exchange India via local backend adapter and renders
 * TradingView Lightweight Charts with genuine multi-timeframe SMC overlays.
 */

// State
let currentTf = "1H";
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let activeLines = [];
let activeMarkers = [];
let ws = null;
let lastUpdateTs = 0;
let lastCandleTs = 0;
let currentAnalysis = null;

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

// Elements
const headerPrice = document.getElementById("headerPrice");
const connStatusText = document.getElementById("connStatusText");
const connectionPill = document.getElementById("connectionPill");
const statTimeframe = document.getElementById("statTimeframe");
const statLastCandle = document.getElementById("statLastCandle");
const statCandleState = document.getElementById("statCandleState");
const statLastUpdate = document.getElementById("statLastUpdate");
const statStreamMode = document.getElementById("statStreamMode");
const warningBanner = document.getElementById("warningBanner");
const warningText = document.getElementById("warningText");
const legendTitle = document.getElementById("legendTitle");
const legendOHLC = document.getElementById("legendOHLC");
const levelsTableBody = document.getElementById("levelsTableBody");
const levelsCount = document.getElementById("levelsCount");
const psychTableBody = document.getElementById("psychTableBody");
const overlapsBody = document.getElementById("overlapsBody");
const overlapsCount = document.getElementById("overlapsCount");
const dailyFvgBody = document.getElementById("dailyFvgBody");
const dailyFvgCount = document.getElementById("dailyFvgCount");
const h4FvgBody = document.getElementById("h4FvgBody");
const h4FvgCount = document.getElementById("h4FvgCount");
const h1FvgBody = document.getElementById("h1FvgBody");
const h1FvgCount = document.getElementById("h1FvgCount");
const liquidityBody = document.getElementById("liquidityBody");
const bosBody = document.getElementById("bosBody");
const bosCount = document.getElementById("bosCount");
const obBody = document.getElementById("obBody");
const obCount = document.getElementById("obCount");
const premDiscBody = document.getElementById("premDiscBody");
const trendlineBody = document.getElementById("trendlineBody");
const tlCount = document.getElementById("tlCount");
const opposingAlertsArea = document.getElementById("opposingAlertsArea");

// Market Overview Bar elements
const ovDailyTrend = document.getElementById("ovDailyTrend");
const ovH4Trend = document.getElementById("ovH4Trend");
const ovDealingRange = document.getElementById("ovDealingRange");
const ovNearestAbove = document.getElementById("ovNearestAbove");
const ovNearestBelow = document.getElementById("ovNearestBelow");
const ovOteStatus = document.getElementById("ovOteStatus");

// Watchlist & Alerts elements
const watchlistAlertBadge = document.getElementById("watchlistAlertBadge");
const alertsDrawerArea = document.getElementById("alertsDrawerArea");
const watchlistCardsContainer = document.getElementById("watchlistCardsContainer");
const filterAllCount = document.getElementById("filterAllCount");
const filterActiveCount = document.getElementById("filterActiveCount");
const filterSetupsCount = document.getElementById("filterSetupsCount");
let watchlistFilter = "all";

// Timezone Synchronizer: Shifts UTC unix timestamps to the user's local system clock
function toLocalChartTime(utcSeconds) {
  if (!utcSeconds) return utcSeconds;
  const offsetMinutes = new Date(utcSeconds * 1000).getTimezoneOffset();
  return utcSeconds - (offsetMinutes * 60);
}

// 1. Initialize Lightweight Chart
function initChart() {
  const container = document.getElementById("chart");
  container.innerHTML = "";

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      background: {
        type: "solid",
        color: "#090c10",
      },
      textColor: "#b2b5be",
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { visible: false },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {
        color: "#2a3447",
        width: 1,
        style: LightweightCharts.LineStyle ? LightweightCharts.LineStyle.Dashed : 2,
        visible: true,
        labelVisible: true,
      },
      horzLine: {
        color: "#2a3447",
        width: 1,
        style: LightweightCharts.LineStyle ? LightweightCharts.LineStyle.Dashed : 2,
        visible: true,
        labelVisible: true,
      },
    },
    rightPriceScale: {
      borderColor: "#222a36",
      autoScale: true,
      scaleMargins: { top: 0.08, bottom: 0.18 },
    },
    timeScale: {
      borderColor: "#222a36",
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time, tickMarkType, locale) => {
        const d = new Date(time * 1000);
        if (tickMarkType === 0) return d.getUTCFullYear().toString();
        if (tickMarkType === 1) return d.toLocaleDateString(locale, { month: "short", timeZone: "UTC" });
        if (tickMarkType === 2) return d.getUTCDate().toString();
        const hh = String(d.getUTCHours()).padStart(2, "0");
        const mm = String(d.getUTCMinutes()).padStart(2, "0");
        return `${hh}:${mm}`;
      },
    },
    localization: {
      dateFormat: "yyyy-MM-dd",
      timeFormatter: (time) => {
        const d = new Date(time * 1000);
        const hh = String(d.getUTCHours()).padStart(2, "0");
        const mm = String(d.getUTCMinutes()).padStart(2, "0");
        return `${hh}:${mm}`;
      },
      dateFormatter: (time) => {
        const d = new Date(time * 1000);
        return d.toISOString().split("T")[0];
      },
    },
  });

  // Candlestick series (rich, thick, crisp high-contrast TradingView colors)
  candleSeries = chart.addCandlestickSeries({
    upColor: "#089981",
    downColor: "#f23645",
    borderVisible: true,
    borderUpColor: "#089981",
    borderDownColor: "#f23645",
    wickUpColor: "#089981",
    wickDownColor: "#f23645",
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  });

  // Volume series (toggleable)
  volumeSeries = chart.addHistogramSeries({
    color: "#26a69a",
    priceFormat: { type: "volume" },
    priceScaleId: "",
    scaleMargins: { top: 0.82, bottom: 0 },
  });

  // Crosshair move handler
  chart.subscribeCrosshairMove((param) => {
    if (!param.time || !param.seriesPrices || !param.seriesPrices.get(candleSeries)) {
      return;
    }
    const price = param.seriesPrices.get(candleSeries);
    const vol = param.seriesPrices.get(volumeSeries) || 0;
    const d = new Date(param.time * 1000);
    const timeStr = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
    legendOHLC.textContent = `[${timeStr}]  O: ${price.open?.toFixed(2)}  H: ${price.high?.toFixed(2)}  L: ${price.low?.toFixed(2)}  C: ${price.close?.toFixed(2)}  V: ${Math.round(vol)}`;
  });

  // Handle resize
  window.addEventListener("resize", () => {
    if (chart && container) {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }
  });

  setupToggleListeners();
}

// 2. Fetch & Render SMC Data for Selected Timeframe
async function loadSMCData(timeframe) {
  try {
    if (timeframe) {
      currentTf = timeframe.toUpperCase();
    }
    const isIndexSym = (window.currentSymbol === ".DEXAUTUSD" || document.getElementById("headerBadge")?.textContent?.includes("Index"));
    if (legendTitle) legendTitle.textContent = `${isIndexSym ? "XAUTUSD (INDEX)" : "XAUTUSD"} · ${currentTf} · DELTA INDIA`;

    const res = await fetch(`/api/smc?timeframe=${currentTf}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.success) {
      currentAnalysis = data.analysis;
      if (warningBanner) warningBanner.style.display = "none";
      try { updateStatusPanel(data.status); } catch (e) { console.error("updateStatusPanel error:", e); }
      try { renderMarketOverview(data.analysis); } catch (e) { console.error("renderMarketOverview error:", e); }
      try { renderChartData(data.analysis); } catch (e) { console.error("renderChartData error:", e); }
      try { renderWatchlist(data.analysis); } catch (e) { console.error("renderWatchlist error:", e); }
      try { renderSidebarData(data.analysis); } catch (e) { console.error("renderSidebarData error:", e); }
    }
  } catch (err) {
    console.error("Failed to load SMC data:", err);
    showWarning("Failed to connect to backend server. Retrying...");
  }
}

// 3. Render Market Overview Bar
function renderMarketOverview(analysis) {
  if (!analysis) return;
  const ms = analysis.market_state || {};

  if (ovDailyTrend) {
    const dt = ms.daily_trend || "Undetermined";
    ovDailyTrend.textContent = dt.toUpperCase();
    ovDailyTrend.className = `overview-val ${dt === "bullish" ? "bullish" : dt === "bearish" ? "bearish" : ""}`;
  }

  if (ovH4Trend) {
    const ht = ms.h4_trend || "Undetermined";
    ovH4Trend.textContent = ht.toUpperCase();
    ovH4Trend.className = `overview-val ${ht === "bullish" ? "bullish" : ht === "bearish" ? "bearish" : ""}`;
  }

  if (ovDealingRange) {
    const pos = ms.daily_position || "Equilibrium";
    const pct = ms.daily_position_pct || 50;
    ovDealingRange.textContent = `${pos.toUpperCase()} (${pct}%)`;
  }

  if (ovNearestAbove) {
    if (ms.nearest_level_above_price) {
      ovNearestAbove.textContent = `$${ms.nearest_level_above_price.toFixed(2)}`;
      ovNearestAbove.title = ms.nearest_level_above || "";
    } else {
      ovNearestAbove.textContent = "None nearby";
    }
  }

  if (ovNearestBelow) {
    if (ms.nearest_level_below_price) {
      ovNearestBelow.textContent = `$${ms.nearest_level_below_price.toFixed(2)}`;
      ovNearestBelow.title = ms.nearest_level_below || "";
    } else {
      ovNearestBelow.textContent = "None nearby";
    }
  }

  if (ovOteStatus) {
    if (ms.in_ote_zone) {
      ovOteStatus.textContent = "INSIDE OTE ZONE";
      ovOteStatus.style.color = "var(--accent-gold)";
    } else {
      ovOteStatus.textContent = "Outside OTE";
      ovOteStatus.style.color = "var(--text-muted)";
    }
  }
}

// 4. Render Chart Candles & Overlays
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
        color: c.close >= c.open ? "rgba(38, 166, 154, 0.4)" : "rgba(239, 83, 80, 0.4)",
      }));

      candleSeries.setData(chartCandles);
      volumeSeries.setData(chartVolumes);
      
      // Auto-fit to show full continuous history (guaranteed at least 24 hours)
      chart.timeScale().fitContent();

      clearOverlayLines();
      drawSMCLevels(analysis);

      // Markers for Swings / BoS
      if (layerToggles.swings) {
        drawChartMarkers(analysis);
      }

      const last = candles[candles.length - 1];
      if (last) {
        headerPrice.textContent = last.close.toFixed(2);
      }
    });
}

function clearOverlayLines() {
  activeLines.forEach((line) => {
    try {
      candleSeries.removePriceLine(line);
    } catch (e) {}
  });
  activeLines = [];
}

function drawSMCLevels(analysis) {
  // 1. Liquidity Levels (PDH, PDL, PWH, PWL)
  if (layerToggles.liquidity) {
    const liqs = analysis.liquidity_levels || [];
    liqs.forEach((l) => {
      if (l.type === "PDH" || l.type === "PDL") {
        const line = candleSeries.createPriceLine({
          price: l.price,
          color: l.type === "PDH" ? "#29b6f6" : "#0288d1",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${l.type} (${l.swept ? "SWEPT" : "ACTIVE"})`,
        });
        activeLines.push(line);
      } else if (l.type === "PWH" || l.type === "PWL") {
        const line = candleSeries.createPriceLine({
          price: l.price,
          color: "#26c6da",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: `${l.type}`,
        });
        activeLines.push(line);
      }
    });
  }

  // 2. Higher Timeframe FVGs (1D & 4H)
  if (layerToggles.htfFvg) {
    const htfFvgs = [...(analysis.daily_fvgs || []), ...(analysis.h4_fvgs || [])];
    htfFvgs.forEach((f) => {
      if (!f.mitigated && !f.inverted) {
        const isBullish = f.direction === "bullish";
        // User rule: Bullish FVGs = Peacock Green (#00b49f), Bearish FVGs = Orange (#f97316) for 4H & 1D
        const fvgColor = isBullish ? "#00b49f" : "#f97316";
        const boundColor = isBullish ? "rgba(0, 180, 159, 0.45)" : "rgba(249, 115, 22, 0.45)";
        const dirLabel = isBullish ? "Bullish" : "Bearish";

        // 50% Midpoint POI line
        const midLine = candleSeries.createPriceLine({
          price: f.midpoint,
          color: fvgColor,
          lineWidth: 2,
          lineStyle: LightweightCharts.LineStyle.SparseDotted,
          axisLabelVisible: true,
          title: `${f.timeframe} ${dirLabel} FVG 50%`,
        });
        activeLines.push(midLine);

        // Boundary lines
        const topBound = candleSeries.createPriceLine({
          price: f.top,
          color: boundColor,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: false,
        });
        const botBound = candleSeries.createPriceLine({
          price: f.bottom,
          color: boundColor,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: false,
        });
        activeLines.push(topBound, botBound);
      }
    });

    // 2b. 1-Hour (1H) FVGs: Lighter colors than 4H & Daily to avoid visual clashing when overlapping
    // Bullish 1H FVG: Mint (#5eead4) | Bearish 1H FVG: Peach (#fdba74)
    if (currentTf !== "1D" && currentTf !== "4H") {
      const h1List = (currentTf === "1H") ? (analysis.timeframe_fvgs || []) : (analysis.h1_fvgs || []);
      h1List.slice(-4).forEach((f) => {
        if (!f.mitigated && !f.inverted) {
          const isBullish = f.direction === "bullish";
          const fvgColor = isBullish ? "#5eead4" : "#fdba74";
          const boundColor = isBullish ? "rgba(94, 234, 212, 0.35)" : "rgba(253, 186, 116, 0.35)";
          const dirLabel = isBullish ? "Bullish" : "Bearish";

          const midLine = candleSeries.createPriceLine({
            price: f.midpoint,
            color: fvgColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: true,
            title: `1H ${dirLabel} FVG 50%`,
          });
          activeLines.push(midLine);

          const topBound = candleSeries.createPriceLine({
            price: f.top,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
          const botBound = candleSeries.createPriceLine({
            price: f.bottom,
            color: boundColor,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted,
            axisLabelVisible: false,
          });
          activeLines.push(topBound, botBound);
        }
      });
    }
  }

  // 3. Current Sub-Hourly Timeframe FVGs (30M, 15M, 5M, 1M)
  if (layerToggles.ltfFvg && currentTf !== "1D" && currentTf !== "4H" && currentTf !== "1H") {
    (analysis.timeframe_fvgs || []).slice(-4).forEach((f) => {
      if (!f.mitigated && !f.inverted) {
        const midLine = candleSeries.createPriceLine({
          price: f.midpoint,
          color: f.direction === "bullish" ? "rgba(38, 166, 154, 0.8)" : "rgba(239, 83, 80, 0.8)",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: `${f.timeframe} FVG 50%`,
        });
        activeLines.push(midLine);
      }
    });
  }

  // 4. Order Blocks (Active zones)
  if (layerToggles.orderBlocks) {
    (analysis.order_blocks || []).slice(-3).forEach((ob) => {
      if (!ob.mitigated && !ob.is_breaker) {
        const obLine = candleSeries.createPriceLine({
          price: ob.midpoint,
          color: "#ab47bc",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${ob.timeframe} ${ob.direction[0].toUpperCase()} OB Mid`,
        });
        activeLines.push(obLine);
      }
    });
  }

  // 5. Psychological 20s and 80s Levels
  if (layerToggles.psych) {
    const psychs = analysis.psychological_levels || [];
    psychs.slice(0, 2).forEach((p) => {
      const line = candleSeries.createPriceLine({
        price: p.price,
        color: "#ff9800",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: false,
        title: `Round ${p.level_type}`,
      });
      activeLines.push(line);
    });
  }

  // 6. Trendlines projected price
  if (layerToggles.trendlines) {
    (analysis.trendlines || []).forEach((tl) => {
      if (!tl.broken && tl.current_projected_price) {
        const line = candleSeries.createPriceLine({
          price: tl.current_projected_price,
          color: tl.direction === "resistance" ? "#ef5350" : "#26a69a",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: `${tl.timeframe} TL (${tl.touch_count}T)`,
        });
        activeLines.push(line);
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
      color: s.type === "high" ? "#f23645" : "#089981",
      shape: s.type === "high" ? "arrowDown" : "arrowUp",
      text: s.label || (s.type === "high" ? "SH" : "SL"),
    });
  });

  // Structure breaks (BoS / CHoCH) - darkened for clear high-contrast readability
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

// 4b. Render Key-Level Activation & Trade-Readiness Watchlist
async function renderWatchlist(analysis) {
  if (!analysis) return;

  let watchlist = analysis.watchlist || [];
  let alerts = analysis.active_alerts || [];

  // Fallback: If watchlist array is empty, fetch directly from /api/watchlist
  if (!watchlist.length) {
    try {
      const resp = await fetch(`/api/watchlist?timeframe=${currentTf}`);
      if (resp.ok) {
        const wlData = await resp.json();
        if (wlData.success && wlData.watchlist && wlData.watchlist.length) {
          watchlist = wlData.watchlist;
          alerts = wlData.active_alerts || alerts;
          if (currentAnalysis) {
            currentAnalysis.watchlist = watchlist;
            currentAnalysis.active_alerts = alerts;
          }
        }
      }
    } catch (e) {
      console.warn("Watchlist fallback fetch failed:", e);
    }
  }

  renderAlerts(alerts);

  // Update filter counts
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

  // Filter entries
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
      <div style="color: var(--text-dim); font-size: 11px; text-align: center; padding: 20px; background: rgba(21, 25, 34, 0.4); border-radius: 6px; border: 1px dashed var(--border);">
        No key levels currently in "${watchlistFilter.toUpperCase()}" filter.
      </div>
    `;
    return;
  }

  filtered.forEach((entry) => {
    const card = document.createElement("div");
    let cardClass = "surveillance-card";
    if (entry.state === "CHECKLIST REVIEW") cardClass += " active-setup";
    else if (entry.state === "SETUP TO INSPECT") cardClass += " inspect-setup";
    card.className = cardClass;

    const stateClass = `state-${entry.state.replace(/\s+/g, "-").replace("/", "-")}`;
    const distSign = entry.distance >= 0 ? `+${entry.distance.toFixed(2)}` : entry.distance.toFixed(2);
    const rangeSpan = (entry.top && entry.bottom) ? `$${entry.bottom.toFixed(2)} - $${entry.top.toFixed(2)}` : `$${entry.price.toFixed(2)}`;

    // Build checklist rows
    let checklistHtml = "";
    let missingItems = [];
    if (entry.checklist && entry.checklist.length) {
      entry.checklist.forEach((item) => {
        const iconClass = item.satisfied ? "passed" : (item.id === "clean_path" && !item.satisfied ? "failed" : "pending");
        const iconSymbol = item.satisfied ? "✓" : (item.id === "clean_path" && !item.satisfied ? "✗" : "○");
        if (!item.satisfied) {
          missingItems.push(item.name.replace(/^[0-9.]+\s*/, ""));
        }
        checklistHtml += `
          <div class="checklist-item-row">
            <span class="check-icon ${iconClass}">${iconSymbol}</span>
            <div class="check-name">
              <span>${item.name}</span>
              <div class="check-detail">${item.evidence}</div>
            </div>
          </div>
        `;
      });
    }

    let missingHtml = "";
    if (missingItems.length && ["AT KEY LEVEL", "REACTION DEVELOPING", "SETUP TO INSPECT"].includes(entry.state)) {
      missingHtml = `
        <div class="missing-callout">
          <strong>Missing for Setup:</strong> ${missingItems.join(" · ")}
        </div>
      `;
    }

    let opposingHtml = "";
    if (entry.opposing_zone_warning) {
      opposingHtml = `
        <div style="margin-top: 6px; padding: 4px 8px; background: rgba(239, 83, 80, 0.1); border-left: 2px solid var(--red); font-size: 10px; color: #ff8a80; border-radius: 0 3px 3px 0;">
          ⚠ ${entry.opposing_zone_warning}
        </div>
      `;
    }

    const isHtfFvg = (entry.timeframe === "1D" || entry.timeframe === "4H") && (entry.type.includes("FVG") || entry.name.includes("FVG"));
    const isH1Fvg = entry.timeframe === "1H" && (entry.type.includes("FVG") || entry.name.includes("FVG"));
    let typeClass = "type-fvg";
    let rangeColor = "var(--text-main)";
    if (isHtfFvg) {
      typeClass = entry.direction === "bullish" ? "type-fvg-bullish" : "type-fvg-bearish";
      rangeColor = entry.direction === "bullish" ? "#00d2b4" : "#fb923c";
    } else if (isH1Fvg) {
      typeClass = entry.direction === "bullish" ? "type-fvg-h1-bullish" : "type-fvg-h1-bearish";
      rangeColor = entry.direction === "bullish" ? "#5eead4" : "#fdba74";
    } else if (entry.type.includes("OB")) {
      typeClass = "type-ob";
    } else if (entry.type.includes("Liquidity") || entry.type.includes("EQ")) {
      typeClass = "type-liq";
    }

    card.innerHTML = `
      <div class="card-top">
        <div class="level-meta-left">
          <span class="type-tag ${typeClass}">${entry.timeframe}</span>
          <span class="level-name-title" style="${(isHtfFvg || isH1Fvg) ? `color: ${rangeColor};` : ''}">${entry.name}</span>
        </div>
        <span class="state-pill ${stateClass}">${entry.state}</span>
      </div>
      <div class="card-middle">
        <div class="level-stat-row">
          <span>Target Range: <strong style="color: ${rangeColor}; font-family: var(--font-mono);">${rangeSpan}</strong></span>
          <span>Dist: <strong style="font-family: var(--font-mono); color: ${Math.abs(entry.distance) < 20 ? '#ffca28' : 'var(--text-main)'};">${distSign} (${entry.distance_pct}%)</strong></span>
        </div>
        <div class="state-reason-callout">
          <strong>Market State Reason:</strong> ${entry.state_reason}
        </div>
        ${opposingHtml}
        <div class="checklist-container">
          <div class="checklist-title">SMC Strategy Checklist Progress</div>
          ${checklistHtml}
        </div>
        ${missingHtml}
      </div>
    `;

    watchlistCardsContainer.appendChild(card);
  });
}

function renderAlerts(alerts) {
  if (!alertsDrawerArea) return;
  alertsDrawerArea.innerHTML = "";

  const unacked = alerts.filter((a) => !a.acknowledged);

  if (watchlistAlertBadge) {
    if (unacked.length > 0) {
      watchlistAlertBadge.style.display = "inline";
      watchlistAlertBadge.textContent = unacked.length;
    } else {
      watchlistAlertBadge.style.display = "none";
    }
  }

  if (!unacked.length) return;

  const drawer = document.createElement("div");
  drawer.className = "alerts-drawer";

  let alertsItemsHtml = "";
  unacked.slice(0, 3).forEach((alt) => {
    const stClass = `state-${alt.state.replace(/\s+/g, "-").replace("/", "-")}`;
    alertsItemsHtml += `
      <div class="alert-item ${stClass}">
        <div class="alert-content">
          <div class="alert-msg">${alt.message}</div>
          <div class="alert-meta">Detected: ${alt.ist_time || "Now"} ${alt.is_stale_suppressed ? '<span style="color:var(--red);">[Data Stale - Suppressed]</span>' : ""}</div>
        </div>
        <button class="btn-ack" onclick="acknowledgeAlert('${alt.id}')">Ack</button>
      </div>
    `;
  });

  drawer.innerHTML = `
    <div class="alerts-header">
      <span class="alerts-title">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
        Attention Alerts (${unacked.length})
      </span>
      <button class="btn-dismiss-all" onclick="dismissAllAlerts()">Dismiss All</button>
    </div>
    ${alertsItemsHtml}
  `;

  alertsDrawerArea.appendChild(drawer);
}

async function acknowledgeAlert(alertId) {
  try {
    await fetch(`/api/alerts/acknowledge?alert_id=${encodeURIComponent(alertId)}`, { method: "POST" });
    if (currentAnalysis) {
      currentAnalysis.active_alerts = (currentAnalysis.active_alerts || []).filter((a) => a.id !== alertId);
      renderAlerts(currentAnalysis.active_alerts);
    }
  } catch (e) {
    console.error("Ack alert error:", e);
  }
}

async function dismissAllAlerts() {
  try {
    await fetch("/api/alerts/acknowledge?dismiss_all=true", { method: "POST" });
    if (currentAnalysis) {
      currentAnalysis.active_alerts = [];
      renderAlerts([]);
    }
  } catch (e) {
    console.error("Dismiss all alerts error:", e);
  }
}

function setupWatchlistFilters() {
  document.querySelectorAll(".watchlist-filters .filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".watchlist-filters .filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      watchlistFilter = btn.getAttribute("data-filter") || "all";
      if (currentAnalysis) {
        renderWatchlist(currentAnalysis);
      }
    });
  });
}

// 5. Render Sidebar Tables & Panels
function renderSidebarData(analysis) {
  // Opposing Zone Warnings
  opposingAlertsArea.innerHTML = "";
  if (analysis.opposing_warnings && analysis.opposing_warnings.length) {
    analysis.opposing_warnings.forEach((w) => {
      const div = document.createElement("div");
      div.className = "poi-callout";
      div.style.borderLeftColor = "#ef5350";
      div.style.background = "rgba(239, 83, 80, 0.1)";
      div.innerHTML = `<strong style="color: #ef5350;">Opposing Zone Alert</strong><p>${w}</p>`;
      opposingAlertsArea.appendChild(div);
    });
  }

  // Key Levels Table (Ranked with Scores and Reasons)
  const levels = analysis.key_levels_summary || [];
  levelsCount.textContent = levels.length;
  levelsTableBody.innerHTML = "";

  if (!levels.length) {
    levelsTableBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-dim); padding: 12px;">No unmitigated levels nearby</td></tr>`;
  } else {
    levels.forEach((l) => {
      const tr = document.createElement("tr");
      const distSign = l.distance >= 0 ? `+${l.distance.toFixed(2)}` : l.distance.toFixed(2);
      const isNear = Math.abs(l.distance) < 20.0;
      const isHtfFvg = (l.timeframe === "1D" || l.timeframe === "4H") && (l.type.includes("FVG") || l.name.includes("FVG"));
      const isH1Fvg = l.timeframe === "1H" && (l.type.includes("FVG") || l.name.includes("FVG"));
      let typeClass = "type-fvg";
      let priceColor = "inherit";
      if (isHtfFvg) {
        typeClass = l.direction === "bullish" ? "type-fvg-bullish" : "type-fvg-bearish";
        priceColor = l.direction === "bullish" ? "#00d2b4" : "#fb923c";
      } else if (isH1Fvg) {
        typeClass = l.direction === "bullish" ? "type-fvg-h1-bullish" : "type-fvg-h1-bearish";
        priceColor = l.direction === "bullish" ? "#5eead4" : "#fdba74";
      } else if (l.type.includes("Liquidity")) typeClass = "type-liq";
      else if (l.type.includes("OB")) typeClass = "type-ob";
      else if (l.type.includes("Psych")) typeClass = "type-psych";

      let statusInfo = "";
      if (l.score) {
        statusInfo = `<span class="score-badge" title="${l.score_reason}">Score: ${l.score}</span>`;
      }
      if (l.mitigation) {
        statusInfo += ` <span style="font-size: 10px; color: var(--accent-gold);">${l.mitigation}</span>`;
      } else if (l.swept !== undefined) {
        statusInfo += l.swept ? ` <span style="color: var(--green); font-size: 10px;">Swept</span>` : ` <span style="color: var(--blue); font-size: 10px;">Active</span>`;
      }

      tr.innerHTML = `
        <td><span class="type-tag ${typeClass}">${l.timeframe || ""}</span> <span style="font-weight: 500; ${(isHtfFvg || isH1Fvg) ? `color: ${priceColor};` : ''}" title="${l.score_reason || ''}">${l.name}</span></td>
        <td style="font-weight: 600; color: ${priceColor};">$${l.price.toFixed(2)}</td>
        <td class="${isNear ? "dist-near" : "dist-far"}">${distSign} (${l.distance_pct}%)</td>
        <td>${statusInfo}</td>
      `;
      levelsTableBody.appendChild(tr);
    });
  }

  // Order Blocks
  const obs = analysis.order_blocks || [];
  if (obCount) obCount.textContent = obs.length;
  if (obBody) {
    obBody.innerHTML = "";
    if (!obs.length) {
      obBody.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No active order blocks detected.</div>`;
    } else {
      obs.slice(-4).reverse().forEach((ob) => {
        const div = document.createElement("div");
        div.style.padding = "6px 0";
        div.style.borderBottom = "1px solid rgba(35, 42, 56, 0.4)";
        div.style.fontSize = "11px";
        const dirCol = ob.direction === "bullish" ? "var(--green)" : "var(--red)";
        div.innerHTML = `
          <div style="display: flex; justify-content: space-between;">
            <span style="font-weight: 600; color: ${dirCol};">${ob.timeframe} ${ob.direction.toUpperCase()} OB</span>
            <span style="font-size: 10px; color: ${ob.mitigated ? "var(--text-dim)" : "var(--accent-gold);"}">${ob.mitigated ? "Mitigated" : "Active"}</span>
          </div>
          <div style="font-family: var(--font-mono); margin-top: 2px;">
            Range: $${ob.bottom} - $${ob.top} | <strong>Mid: $${ob.midpoint}</strong>
          </div>
          <div style="color: var(--text-dim); font-size: 10px; margin-top: 2px;">Origin: ${ob.origin_ist || "N/A"}</div>
        `;
        obBody.appendChild(div);
      });
    }
  }

  // Psychological Levels
  const psychs = analysis.psychological_levels || [];
  psychTableBody.innerHTML = "";
  psychs.forEach((p) => {
    const tr = document.createElement("tr");
    const distSign = p.distance >= 0 ? `+${p.distance.toFixed(2)}` : p.distance.toFixed(2);
    tr.innerHTML = `
      <td><span class="type-tag type-psych">Round ${p.level_type}</span></td>
      <td style="font-weight: 600;">$${p.price.toFixed(2)}</td>
      <td>${distSign} (${p.distance_pct}%)</td>
    `;
    psychTableBody.appendChild(tr);
  });

  // FVGs & Critical Sections Tab
  renderFvgList(dailyFvgBody, analysis.daily_fvgs || [], "1D");
  dailyFvgCount.textContent = (analysis.daily_fvgs || []).length;

  renderFvgList(h4FvgBody, analysis.h4_fvgs || [], "4H");
  h4FvgCount.textContent = (analysis.h4_fvgs || []).length;

  if (h1FvgBody && h1FvgCount) {
    const h1List = analysis.h1_fvgs || (currentTf === "1H" ? analysis.timeframe_fvgs : []) || [];
    renderFvgList(h1FvgBody, h1List, "1H");
    h1FvgCount.textContent = h1List.length;
  }

  // Overlapping HTF FVGs
  const overlaps = analysis.overlapping_htf_fvgs || [];
  overlapsCount.textContent = overlaps.length;
  overlapsBody.innerHTML = "";
  if (!overlaps.length) {
    overlapsBody.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No overlapping Daily & 4H FVGs at current price range.</div>`;
  } else {
    overlaps.forEach((ov) => {
      const div = document.createElement("div");
      div.className = "poi-callout";
      const isBull = ov.direction === "bullish";
      const ovColor = isBull ? "#00b49f" : "#f97316";
      const ovBg = isBull ? "rgba(0, 180, 159, 0.12)" : "rgba(249, 115, 22, 0.12)";
      div.style.borderLeftColor = ovColor;
      div.style.background = ovBg;
      div.innerHTML = `
        <strong style="color: ${ovColor};">Overlapping ${ov.direction.toUpperCase()} Critical Section (POI)</strong>
        <p>Span: $${ov.overlap_bottom} - $${ov.overlap_top}<br>
        50% Equilibrium Midpoint: <strong style="color: ${isBull ? '#00d2b4' : '#fb923c'}; font-size: 12px;">$${ov.overlap_midpoint}</strong><br>
        Formed by: ${ov.htf_timeframe} & ${ov.ltf_timeframe} FVGs</p>
      `;
      overlapsBody.appendChild(div);
    });
  }

  // Market Structure Tab
  // Premium / Discount Body
  if (premDiscBody) {
    const pd = analysis.premium_discount || {};
    premDiscBody.innerHTML = `
      <div style="font-size: 12px; margin-bottom: 4px;">
        State: <strong style="color: ${pd.position === 'discount' ? 'var(--green)' : pd.position === 'premium' ? 'var(--red)' : 'var(--text-main)'};">${(pd.position || 'N/A').toUpperCase()}</strong> (${pd.position_pct || 50}%)
      </div>
      <div style="font-size: 11px; color: var(--text-muted);">${pd.description || ''}</div>
    `;
  }

  // Trendlines Body
  if (trendlineBody) {
    const tls = analysis.trendlines || [];
    if (tlCount) tlCount.textContent = tls.length;
    trendlineBody.innerHTML = "";
    if (!tls.length) {
      trendlineBody.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No validated trendlines currently active on this timeframe.</div>`;
    } else {
      tls.forEach((tl) => {
        const div = document.createElement("div");
        div.style.padding = "4px 0";
        div.style.borderBottom = "1px solid rgba(35, 42, 56, 0.4)";
        div.style.fontSize = "11px";
        div.innerHTML = `
          <div style="display: flex; justify-content: space-between;">
            <span>${tl.timeframe} ${tl.direction.toUpperCase()} (${tl.touch_count} touches)</span>
            <span style="font-weight: 600; color: ${tl.broken ? 'var(--red)' : 'var(--green)'};">${tl.broken ? 'Broken' : 'Intact'}</span>
          </div>
          <div style="color: var(--text-dim); font-size: 10px;">Projected Price: $${tl.current_projected_price || '--'}</div>
        `;
        trendlineBody.appendChild(div);
      });
    }
  }

  // BoS List
  const bosList = analysis.bos_signals || [];
  bosCount.textContent = bosList.length;
  bosBody.innerHTML = "";
  if (!bosList.length) {
    bosBody.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No Break of Structure detected on this timeframe.</div>`;
  } else {
    bosList.slice(-5).reverse().forEach((b) => {
      const div = document.createElement("div");
      div.style.padding = "6px 0";
      div.style.borderBottom = "1px solid rgba(35, 42, 56, 0.4)";
      div.style.fontSize = "11px";
      const validClass = b.valid ? "" : "invalid";
      div.innerHTML = `
        <div style="display: flex; justify-content: space-between;">
          <span style="font-weight: 600; color: ${b.type === "bullish" ? "var(--green)" : "var(--red)"};">
            ${b.kind || 'BoS'} (${b.type.toUpperCase()}) at $${b.broken_level}
          </span>
          <span class="bos-tag ${validClass}">${b.valid ? "Valid (>=40%)" : "Invalid (<40%)"}</span>
        </div>
        <div style="color: var(--text-muted); font-size: 10px; margin-top: 2px;">
          Retracement: ${b.retracement_pct}% · Time: ${b.ist_time || "N/A"}
        </div>
      `;
      bosBody.appendChild(div);
    });
  }

  // Liquidity Levels
  liquidityBody.innerHTML = "";
  (analysis.liquidity_levels || []).forEach((l) => {
    const div = document.createElement("div");
    div.style.display = "flex";
    div.style.justifyContent = "space-between";
    div.style.padding = "4px 0";
    div.style.fontSize = "11px";
    div.innerHTML = `
      <span>${l.label}</span>
      <span style="font-family: var(--font-mono); font-weight: 600;">$${l.price.toFixed(2)} ${l.swept ? '<span style="color: var(--green); font-size: 10px;">[SWEPT]</span>' : ""}</span>
    `;
    liquidityBody.appendChild(div);
  });
}

function renderFvgList(container, fvgs, tf) {
  container.innerHTML = "";
  if (!fvgs.length) {
    container.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No ${tf} Fair Value Gaps found.</div>`;
    return;
  }
  fvgs.slice(-6).reverse().forEach((f) => {
    const div = document.createElement("div");
    div.style.padding = "6px 0";
    div.style.borderBottom = "1px solid rgba(35, 42, 56, 0.4)";
    div.style.fontSize = "11px";
    const isHtf = tf === "1D" || tf === "4H";
    const isH1 = tf === "1H";
    const isBull = f.direction === "bullish";
    let dirColor = isBull ? "var(--green)" : "var(--red)";
    let poiColor = "var(--accent-gold)";
    if (isHtf) {
      dirColor = isBull ? "#00b49f" : "#f97316";
      poiColor = isBull ? "#00d2b4" : "#fb923c";
    } else if (isH1) {
      dirColor = isBull ? "#5eead4" : "#fdba74";
      poiColor = isBull ? "#5eead4" : "#fdba74";
    }

    div.innerHTML = `
      <div style="display: flex; justify-content: space-between;">
        <span style="font-weight: 700; color: ${dirColor};">${f.direction.toUpperCase()} FVG (${tf})</span>
        <span style="font-size: 10px; color: ${f.mitigated ? "var(--text-dim)" : "var(--accent-gold)"};">
          ${f.mitigation_level}
        </span>
      </div>
      <div style="font-family: var(--font-mono); margin-top: 2px;">
        Boundaries: $${f.bottom} - $${f.top} | <strong style="color: ${poiColor};">50% POI: $${f.midpoint}</strong>
      </div>
      <div style="color: var(--text-dim); font-size: 10px; margin-top: 2px;">Created: ${f.start_ist || "N/A"}</div>
    `;
    container.appendChild(div);
  });
}

// 6. Update Status Panel
function updateStatusPanel(stat) {
  if (!stat) return;

  if (statTimeframe) statTimeframe.textContent = stat.selected_timeframe || currentTf;
  if (statLastCandle) statLastCandle.textContent = stat.last_candle_ist || "--";

  if (statCandleState) {
    if (stat.candle_state === "Forming") {
      statCandleState.className = "forming-badge";
      statCandleState.textContent = "Forming...";
    } else {
      statCandleState.className = "confirmed-badge";
      statCandleState.textContent = "Confirmed";
    }
  }

  if (statLastUpdate) statLastUpdate.textContent = stat.last_update_ist || "--";
  lastUpdateTs = stat.last_update_timestamp || Date.now() / 1000;

  if (connStatusText) connStatusText.textContent = stat.connection_status;
  if (connectionPill) connectionPill.className = `conn-pill ${stat.connection_status.replace(" ", "-")}`;

  if (stat.symbol) window.currentSymbol = stat.symbol;
  const statInst = document.getElementById("statInstrument");
  const statCont = document.getElementById("statContract");
  const statBasis = document.getElementById("statBasis");
  const headerBadge = document.getElementById("headerBadge");

  if (stat.symbol === ".DEXAUTUSD" || stat.contract_type === "spot_index") {
    if (statInst) statInst.textContent = stat.instrument_name || "Tether Gold Spot Index (.DEXAUTUSD)";
    if (statCont) statCont.textContent = "Spot Price Index (1 oz Benchmark)";
    if (statBasis) statBasis.textContent = "0.00% (Spot Index Reference)";
    if (headerBadge) headerBadge.textContent = "Spot Index";
    if (legendTitle) legendTitle.textContent = `XAUTUSD (INDEX) · ${currentTf} · DELTA INDIA`;
  } else {
    if (statInst) statInst.textContent = stat.instrument_name || "Tether Gold (XAUTUSD #131253)";
    if (statCont) statCont.textContent = "Perpetual Futures (0.001 XAUT/ct)";
    if (statBasis) statBasis.textContent = "+0.06% to +0.18% (Disclosed)";
    if (headerBadge) headerBadge.textContent = "Perpetual Future";
    if (legendTitle) legendTitle.textContent = `XAUTUSD · ${currentTf} · DELTA INDIA`;
  }

  if (statStreamMode) {
    if (stat.connection_status === "Polling Fallback") {
      statStreamMode.textContent = "REST Polling";
      statStreamMode.style.color = "var(--blue)";
    } else if (stat.connection_status === "Connected") {
      statStreamMode.textContent = "WebSocket Live";
      statStreamMode.style.color = "var(--green)";
    } else {
      statStreamMode.textContent = stat.connection_status;
      statStreamMode.style.color = "var(--accent-gold)";
    }
  }

  if (stat.warnings && stat.warnings.length) {
    showWarning(stat.warnings[0]);
  } else {
    if (warningBanner) warningBanner.style.display = "none";
  }
}

function showWarning(msg) {
  warningBanner.style.display = "flex";
  warningText.textContent = msg;
}

// 7. Layer Toggle Listeners
function setupToggleListeners() {
  const mapping = [
    { id: "togHtfFvg", key: "htfFvg" },
    { id: "togLtfFvg", key: "ltfFvg" },
    { id: "togOrderBlocks", key: "orderBlocks" },
    { id: "togLiquidity", key: "liquidity" },
    { id: "togTrendlines", key: "trendlines" },
    { id: "togPsych", key: "psych" },
    { id: "togSwings", key: "swings" },
    { id: "togVolume", key: "volume" },
  ];

  mapping.forEach(({ id, key }) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", (e) => {
        layerToggles[key] = e.target.checked;
        if (key === "volume" && volumeSeries) {
          volumeSeries.applyOptions({ visible: e.target.checked });
          return;
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
    }
  });
}

// 8. Connect WebSocket for Real-Time Streaming
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    ws.send(JSON.stringify({ action: "subscribe_timeframe", timeframe: currentTf }));
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.event === "candle_update") {
        if (data.timeframe === currentTf && data.candle && candleSeries) {
          const c = data.candle;
          const localTime = toLocalChartTime(c.time);
          candleSeries.update({
            time: localTime,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          });
          volumeSeries.update({
            time: localTime,
            value: c.volume,
            color: c.close >= c.open ? "rgba(38, 166, 154, 0.4)" : "rgba(239, 83, 80, 0.4)",
          });
          headerPrice.textContent = c.close.toFixed(2);
          updateStatusPanel(data.status);
        }
      } else if (data.event === "smc_sync") {
        updateStatusPanel(data.status);
        if (data.analysis) {
          currentAnalysis = data.analysis;
          renderMarketOverview(data.analysis);
          renderSidebarData(data.analysis);
          renderWatchlist(data.analysis);
        }
      }
    } catch (e) {
      console.error("WS message parse error:", e);
    }
  };

  ws.onclose = () => {
    connStatusText.textContent = "Reconnecting";
    connectionPill.className = "conn-pill Reconnecting";
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// 9. Event Listeners
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

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => (p.style.display = "none"));
    btn.classList.add("active");
    const tabId = btn.getAttribute("data-tab");
    const pane = document.getElementById(tabId);
    if (pane) pane.style.display = "block";
    if (tabId === "tab-watchlist" && currentAnalysis) {
      renderWatchlist(currentAnalysis);
    }
  });
});

document.getElementById("btnRefresh").addEventListener("click", async () => {
  const btn = document.getElementById("btnRefresh");
  btn.style.opacity = "0.5";
  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadSMCData(currentTf);
  } finally {
    btn.style.opacity = "1";
  }
});

// Periodic status tick to update latency counter
setInterval(() => {
  if (lastUpdateTs > 0) {
    const elapsed = Math.round(Date.now() / 1000 - lastUpdateTs);
    if (elapsed > 45) {
      showWarning(`Data stream delayed (${elapsed}s since last update)`);
    }
  }
}, 5000);

// 10. Fullscreen Mode Manager
function setupFullscreenToggle() {
  const chartPanel = document.querySelector(".chart-panel");
  const container = document.getElementById("chart");
  const btnFs = document.getElementById("btnFullscreen");

  if (!chartPanel || !btnFs) return;

  function resizeChart() {
    if (chart && container) {
      setTimeout(() => {
        chart.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        });
        chart.timeScale().fitContent();
      }, 70);
    }
  }

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

  // Keyboard shortcut 'F' to toggle fullscreen
  window.addEventListener("keydown", (e) => {
    if (e.key === "f" || e.key === "F") {
      if (
        document.activeElement &&
        (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA")
      ) {
        return;
      }
      toggleFullscreen();
    }
  });
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  setupWatchlistFilters();
  setupFullscreenToggle();
  loadSMCData(currentTf);
  connectWebSocket();
});
