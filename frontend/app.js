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
const liquidityBody = document.getElementById("liquidityBody");
const bosBody = document.getElementById("bosBody");
const bosCount = document.getElementById("bosCount");
const srBody = document.getElementById("srBody");
const opposingAlertsArea = document.getElementById("opposingAlertsArea");

// 1. Initialize Lightweight Chart
function initChart() {
  const container = document.getElementById("chart");
  container.innerHTML = "";

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      backgroundColor: "#0b0e14",
      textColor: "#8b949e",
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: "#161b24" },
      horzLines: { color: "#161b24" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "#232a38",
      autoScale: true,
      scaleMargins: { top: 0.1, bottom: 0.2 },
    },
    timeScale: {
      borderColor: "#232a38",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // Candlestick series
  candleSeries = chart.addCandlestickSeries({
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  });

  // Volume series
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
    legendOHLC.textContent = `O: ${price.open?.toFixed(2)}  H: ${price.high?.toFixed(2)}  L: ${price.low?.toFixed(2)}  C: ${price.close?.toFixed(2)}  V: ${Math.round(vol)}`;
  });

  // Handle resize
  window.addEventListener("resize", () => {
    if (chart && container) {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    }
  });
}

// 2. Fetch & Render SMC Data for Selected Timeframe
async function loadSMCData(timeframe) {
  try {
    currentTf = timeframe.toUpperCase();
    statTimeframe.textContent = currentTf;
    legendTitle.textContent = `XAUTUSD · ${currentTf} · DELTA INDIA`;

    const res = await fetch(`/api/smc?timeframe=${currentTf}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.success) {
      updateStatusPanel(data.status);
      renderChartData(data.analysis);
      renderSidebarData(data.analysis);
    }
  } catch (err) {
    console.error("Failed to load SMC data:", err);
    showWarning("Failed to connect to backend server. Retrying...");
  }
}

// 3. Render Chart Candles & Overlays
function renderChartData(analysis) {
  // Fetch candles directly to ensure full set
  fetch(`/api/candles?timeframe=${currentTf}`)
    .then((r) => r.json())
    .then((cData) => {
      if (!cData.success || !cData.candles.length) return;

      const candles = cData.candles;
      const chartCandles = candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

      const chartVolumes = candles.map((c) => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? "rgba(38, 166, 154, 0.4)" : "rgba(239, 83, 80, 0.4)",
      }));

      candleSeries.setData(chartCandles);
      volumeSeries.setData(chartVolumes);

      // Clear previous overlay lines
      clearOverlayLines();

      // Draw Key Overlays
      drawSMCLevels(analysis);

      // Update current price
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
  // 1. Draw Previous Day High/Low
  const liqs = analysis.liquidity_levels || [];
  liqs.forEach((l) => {
    if (l.type === "PDH" || l.type === "PDL") {
      const line = candleSeries.createPriceLine({
        price: l.price,
        color: l.type === "PDH" ? "#29b6f6" : "#0288d1",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: `${l.type} (${l.swept ? "SWEPT" : "UNSWEPT"})`,
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

  // 2. Draw Unmitigated HTF FVG Midpoints (50% Equilibrium POI)
  const htfFvgs = [...(analysis.daily_fvgs || []), ...(analysis.h4_fvgs || [])];
  htfFvgs.forEach((f) => {
    if (!f.mitigated) {
      const color = f.direction === "bullish" ? "#26a69a" : "#ef5350";
      // 50% Midpoint POI
      const midLine = candleSeries.createPriceLine({
        price: f.midpoint,
        color: "#e5b342",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.SparseDotted,
        axisLabelVisible: true,
        title: `${f.timeframe} ${f.direction[0].toUpperCase()} FVG 50% POI`,
      });
      activeLines.push(midLine);
    }
  });

  // 3. Draw Psychological 20s & 80s Levels (Nearest 2)
  const psychs = analysis.psychological_levels || [];
  psychs.slice(0, 2).forEach((p) => {
    const line = candleSeries.createPriceLine({
      price: p.price,
      color: "#ab47bc",
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted,
      axisLabelVisible: false,
      title: `Round ${p.level_type}`,
    });
    activeLines.push(line);
  });
}

// 4. Render Sidebar Tables & Rules
function renderSidebarData(analysis) {
  // Opposing Warnings
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

  // Key Levels Table
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
      const typeClass = l.type.includes("FVG") ? "type-fvg" : l.type.includes("Liquidity") ? "type-liq" : "type-psych";

      let statusBadge = l.mitigation ? `<span style="color: var(--accent-gold); font-size: 10px;">${l.mitigation}</span>` : "";
      if (l.swept !== undefined) {
        statusBadge = l.swept ? `<span style="color: var(--green); font-size: 10px;">Swept</span>` : `<span style="color: var(--blue); font-size: 10px;">Active</span>`;
      }

      tr.innerHTML = `
        <td><span class="type-tag ${typeClass}">${l.timeframe || ""}</span> <span style="font-weight: 500;">${l.name}</span></td>
        <td style="font-weight: 600;">${l.price.toFixed(2)}</td>
        <td class="${isNear ? "dist-near" : "dist-far"}">${distSign} (${l.distance_pct}%)</td>
        <td>${statusBadge}</td>
      `;
      levelsTableBody.appendChild(tr);
    });
  }

  // Psychological Levels
  const psychs = analysis.psychological_levels || [];
  psychTableBody.innerHTML = "";
  psychs.forEach((p) => {
    const tr = document.createElement("tr");
    const distSign = p.distance >= 0 ? `+${p.distance.toFixed(2)}` : p.distance.toFixed(2);
    tr.innerHTML = `
      <td><span class="type-tag type-psych">Round ${p.level_type}</span></td>
      <td style="font-weight: 600;">${p.price.toFixed(2)}</td>
      <td>${distSign} (${p.distance_pct}%)</td>
    `;
    psychTableBody.appendChild(tr);
  });

  // FVGs & Critical Sections Tab
  renderFvgList(dailyFvgBody, analysis.daily_fvgs || [], "1D");
  dailyFvgCount.textContent = (analysis.daily_fvgs || []).length;

  renderFvgList(h4FvgBody, analysis.h4_fvgs || [], "4H");
  h4FvgCount.textContent = (analysis.h4_fvgs || []).length;

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
      div.innerHTML = `
        <strong>Overlapping ${ov.direction.toUpperCase()} Critical Section (POI)</strong>
        <p>Span: $${ov.overlap_bottom} - $${ov.overlap_top}<br>
        50% Equilibrium Midpoint: <strong>$${ov.overlap_midpoint}</strong><br>
        Formed by: ${ov.htf_timeframe} & ${ov.ltf_timeframe} FVGs</p>
      `;
      overlapsBody.appendChild(div);
    });
  }

  // Market Structure Tab
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
            ${b.type.toUpperCase()} BoS at $${b.broken_level}
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

  // Support / Resistance
  srBody.innerHTML = "";
  (analysis.support_resistance || []).forEach((sr) => {
    const div = document.createElement("div");
    div.style.display = "flex";
    div.style.justifyContent = "space-between";
    div.style.padding = "4px 0";
    div.style.fontSize = "11px";
    div.innerHTML = `
      <span>${sr.role.toUpperCase()} ($${sr.price})</span>
      <span style="color: var(--text-dim);">${sr.touches} touches</span>
    `;
    srBody.appendChild(div);
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
    const dirColor = f.direction === "bullish" ? "var(--green)" : "var(--red)";
    div.innerHTML = `
      <div style="display: flex; justify-content: space-between;">
        <span style="font-weight: 600; color: ${dirColor};">${f.direction.toUpperCase()} FVG</span>
        <span style="font-size: 10px; color: ${f.mitigated ? "var(--text-dim)" : "var(--accent-gold)"};">
          ${f.mitigation_level}
        </span>
      </div>
      <div style="font-family: var(--font-mono); margin-top: 2px;">
        Boundaries: $${f.bottom} - $${f.top} | <strong>50% POI: $${f.midpoint}</strong>
      </div>
      <div style="color: var(--text-dim); font-size: 10px; margin-top: 2px;">Created: ${f.start_ist || "N/A"}</div>
    `;
    container.appendChild(div);
  });
}

// 5. Update Status Panel
function updateStatusPanel(stat) {
  if (!stat) return;

  statTimeframe.textContent = stat.selected_timeframe || currentTf;
  statLastCandle.textContent = stat.last_candle_ist || "--";

  if (stat.candle_state === "Forming") {
    statCandleState.className = "forming-badge";
    statCandleState.textContent = "Forming...";
  } else {
    statCandleState.className = "confirmed-badge";
    statCandleState.textContent = "Confirmed";
  }

  statLastUpdate.textContent = stat.last_update_ist || "--";
  lastUpdateTs = stat.last_update_timestamp || Date.now() / 1000;

  connStatusText.textContent = stat.connection_status;
  connectionPill.className = `conn-pill ${stat.connection_status.replace(" ", "-")}`;

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

  if (stat.warnings && stat.warnings.length) {
    showWarning(stat.warnings[0]);
  } else {
    warningBanner.style.display = "none";
  }
}

function showWarning(msg) {
  warningBanner.style.display = "flex";
  warningText.textContent = msg;
}

// 6. Connect WebSocket for Real-Time Streaming
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log("Connected to dashboard WebSocket");
    ws.send(JSON.stringify({ action: "subscribe_timeframe", timeframe: currentTf }));
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.event === "candle_update") {
        if (data.timeframe === currentTf && data.candle && candleSeries) {
          const c = data.candle;
          candleSeries.update({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          });
          volumeSeries.update({
            time: c.time,
            value: c.volume,
            color: c.close >= c.open ? "rgba(38, 166, 154, 0.4)" : "rgba(239, 83, 80, 0.4)",
          });
          headerPrice.textContent = c.close.toFixed(2);
          updateStatusPanel(data.status);
        }
      } else if (data.event === "smc_sync") {
        updateStatusPanel(data.status);
        if (data.analysis) {
          renderSidebarData(data.analysis);
        }
      }
    } catch (e) {
      console.error("WS message parse error:", e);
    }
  };

  ws.onclose = () => {
    console.warn("WebSocket closed. Reconnecting in 3s...");
    connStatusText.textContent = "Reconnecting";
    connectionPill.className = "conn-pill Reconnecting";
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// 7. Event Listeners
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
      showWarning(`Data delayed (${elapsed}s since last update)`);
    }
  }
}, 5000);

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  loadSMCData(currentTf);
  connectWebSocket();
});
