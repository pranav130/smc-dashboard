/**
 * SMC Gold Liquidity Intelligence · Professional Trading Terminal
 * XAUTUSD / .DEXAUTUSD · Delta Exchange India
 */

const CFG = {
  candles: "/api/candles?symbol=XAUTUSD&tf={tf}",
  signal: "/api/signal?symbol=XAUTUSD&tf={tf}",
  smc: "/api/smc?timeframe={tf}",
  watchlist: "/api/watchlist?timeframe={tf}",
  status: "/api/status?timeframe={tf}",
  alerts: "/api/alerts",
  alertsAck: "/api/alerts/acknowledge",
  insights: "/api/insights",
  paperSimulate: "/api/paper/simulate-demo-trade",
  pollMs: 6000,
};

const TFS = {
  "1D": 86400,
  "4H": 14400,
  "2H": 7200,
  "1H": 3600,
  "30M": 1800,
  "15M": 900,
  "10M": 600,
  "5M": 300,
  "1M": 60,
};

// Core state
let tf = "1H";
let focus = false;
let data = null;
let sig = null;
let smcData = null;
let sample = false;
let pollTimer = null;
let ws = null;
let previousPrice = 0;
let lwChart = null;
let lwSeries = null;
let lwVolumeSeries = null;
let activePriceLines = [];

// Overlay layers toggle state (mirrors V2 workstation)
const layers = {
  htfFvg: true, // 4H / 1D Fair Value Gaps
  curFvg: true, // Same-Timeframe Fair Value Gaps
  curLiq: true, // Same-Timeframe Liquidity & Levels (EQH/EQL/OB)
  htfSr: true, // 1D / 1W Key Levels & S/R (PDH/PDL, PWH/PWL)
  setups: true, // Setup targets (Entry, SL, TP1, TP2)
  volume: false, // Volume sub-chart (unchecked by default)
};

// Alert and audio state
let audioCtx = null;
let seenAlertIds = new Set();
let unreadAlertCount = 0;
let audioMode = localStorage.getItem("smc_audio_mode") || "chime"; // "chime" | "voice" | "mute"
let lastSpeechTime = 0;

// Chart interactive navigation state
let viewCandleCount = 90;
let panOffset = 0; // 0 means latest candle at the right edge
let isDragging = false;
let dragStartX = 0;
let dragStartPan = 0;
let mouseX = -1;
let mouseY = -1;
let priceScaleMultiplier = 1.0;
let isDraggingYAxis = false;
let dragStartY = 0;
let dragStartMultiplier = 1.0;

const $ = (id) => document.getElementById(id);
const f = (v, d = 2) =>
  v == null || isNaN(v)
    ? "—"
    : Number(v).toLocaleString("en-US", {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
      });

// Theme state & configurations (Dark, Midnight OLED, Light)
const THEMES = [
  { id: "dark", label: "Dark", icon: "🌙" },
  { id: "midnight", label: "Midnight", icon: "🌑" },
  { id: "light", label: "Light", icon: "☀️" },
];
let currentTheme = localStorage.getItem("smc_terminal_theme") || "dark";

const THEME_CHART_CONFIGS = {
  dark: {
    textColor: "#6f8399",
    borderColor: "#1b2a3a",
    gridV: "rgba(255, 255, 255, 0.025)",
    gridH: "rgba(255, 255, 255, 0.04)",
    candleUp: "#18c37e",
    candleDn: "#ff3b4e",
    canvasGrid: "#121b27",
    canvasText: "#6f8399",
  },
  midnight: {
    textColor: "#71717a",
    borderColor: "#1e2025",
    gridV: "rgba(255, 255, 255, 0.018)",
    gridH: "rgba(255, 255, 255, 0.028)",
    candleUp: "#18c37e",
    candleDn: "#ff3b4e",
    canvasGrid: "#141418",
    canvasText: "#71717a",
  },
  light: {
    textColor: "#64748b",
    borderColor: "#cbd5e1",
    gridV: "rgba(0, 0, 0, 0.04)",
    gridH: "rgba(0, 0, 0, 0.06)",
    candleUp: "#089981",
    candleDn: "#f23645",
    canvasGrid: "#e2e8f0",
    canvasText: "#64748b",
  },
};

function applyTheme(themeId) {
  const found = THEMES.find((t) => t.id === themeId) || THEMES[0];
  currentTheme = found.id;
  localStorage.setItem("smc_terminal_theme", currentTheme);

  if (currentTheme === "dark") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", currentTheme);
  }

  const iconEl = $("themeIcon");
  const textEl = $("themeText");
  if (iconEl) iconEl.textContent = found.icon;
  if (textEl) textEl.textContent = found.label;

  const cfg = THEME_CHART_CONFIGS[currentTheme] || THEME_CHART_CONFIGS.dark;
  if (lwChart) {
    try {
      lwChart.applyOptions({
        layout: {
          background: { type: "solid", color: "transparent" },
          textColor: cfg.textColor,
        },
        grid: {
          vertLines: { color: cfg.gridV },
          horzLines: { color: cfg.gridH },
        },
        rightPriceScale: {
          borderColor: cfg.borderColor,
        },
        timeScale: {
          borderColor: cfg.borderColor,
        },
      });
    } catch (e) {
      console.warn("lwChart applyOptions error:", e);
    }
  }

  if (lwSeries) {
    try {
      lwSeries.applyOptions({
        upColor: cfg.candleUp,
        downColor: cfg.candleDn,
        wickUpColor: cfg.candleUp,
        wickDownColor: cfg.candleDn,
      });
    } catch (e) {}
  }

  if ($("cv") && $("cv").style.display !== "none") {
    drawCanvasFallback();
  }
}

function cycleTheme() {
  const idx = THEMES.findIndex((t) => t.id === currentTheme);
  const nextIdx = (idx + 1) % THEMES.length;
  applyTheme(THEMES[nextIdx].id);
}

// --------------------------------------------------------------------------
// 1. Timeframe Navigation Setup
// --------------------------------------------------------------------------
function initTimeframeBar() {
  const container = $("tfs");
  if (!container) return;
  // Primary trading timeframes prominently presented
  const supported = ["1D", "4H", "2H", "1H", "30M", "15M", "10M", "5M"];
  container.innerHTML = supported
    .map(
      (k) =>
        `<button data-tf="${k}" class="${k === tf ? "on" : ""}">${k}</button>`
    )
    .join("");

  if ($("layerCurTf")) $("layerCurTf").textContent = tf;

  container.onclick = (e) => {
    const targetTf = e.target.dataset.tf;
    if (!targetTf || targetTf === tf) return;
    tf = targetTf;
    if ($("layerCurTf")) $("layerCurTf").textContent = tf;
    [...container.children].forEach((b) =>
      b.classList.toggle("on", b.dataset.tf === targetTf)
    );
    panOffset = 0;
    if (lwChart) {
      setTimeout(() => {
        if (lwChart) lwChart.timeScale().fitContent();
      }, 150);
    }
    load();
  };
}

// --------------------------------------------------------------------------
// 2. Data Fetching & State Synchronization
// --------------------------------------------------------------------------
function conn(txt, cls) {
  const c = $("conn");
  if (!c) return;
  c.textContent = txt;
  c.className = "badge " + cls;
}

function over(t, s) {
  const o = $("overlay");
  if (!o) return;
  o.classList.add("show");
  if ($("ovt")) $("ovt").textContent = t;
  if ($("ovs")) $("ovs").textContent = s;
}

async function load() {
  if (sample) {
    data = mkSample();
    sig = mkSig(data);
    return paint();
  }

  try {
    const [cRes, sRes, smcRes] = await Promise.all([
      fetch(CFG.candles.replace("{tf}", tf)),
      fetch(CFG.signal.replace("{tf}", tf)),
      fetch(CFG.smc.replace("{tf}", tf)).catch(() => null),
    ]);

    if (!cRes.ok) throw new Error("candles HTTP " + cRes.status);
    const rawCandles = await cRes.json();
    data = Array.isArray(rawCandles)
      ? rawCandles
      : rawCandles.candles || [];

    if (!Array.isArray(data) || !data.length) {
      throw new Error("empty candle response");
    }

    sig = sRes.ok ? await sRes.json() : null;
    smcData = smcRes && smcRes.ok ? await smcRes.json() : null;

    paint();
  } catch (e) {
    console.error("Load failed:", e);
    data = null;
    sig = null;
    conn("DISCONNECTED", "b-bad");
    over(
      "Feed Disconnected",
      String(e.message || "Failed to reach backend") + " — reconnecting..."
    );
    paint(true);
  }
}

// --------------------------------------------------------------------------
// 3. UI Presentation & Data Rendering
// --------------------------------------------------------------------------
function paint(failed) {
  if (failed) {
    ["px", "chg", "hi", "lo", "t-str", "t-ret", "t-exp", "t-sup", "t-res"].forEach(
      (i) => {
        if ($(i)) $(i).textContent = "—";
      }
    );
    setSig(null);
    renderCopilotGuidance(null, true);
    draw();
    return;
  }

  const o = $("overlay");
  if (o) o.classList.remove("show");

  if (!data || !data.length) return;

  const last = data[data.length - 1];
  const first = data[0];
  const lastTime = last.t || last.time;
  const lastClose = last.c !== undefined ? last.c : last.close;
  const firstOpen = first.o !== undefined ? first.o : first.open;

  const tfSeconds = TFS[tf] || 3600;
  const age = Date.now() / 1000 - (lastTime + tfSeconds);
  const stale = !sample && age > tfSeconds * 0.5 + 120;

  // Header Metrics
  if ($("px")) {
    $("px").textContent = f(lastClose);
    if (previousPrice > 0 && previousPrice !== lastClose) {
      $("px").style.color =
        lastClose > previousPrice ? "var(--up)" : "var(--dn)";
      setTimeout(() => {
        if ($("px")) $("px").style.color = "#fff";
      }, 400);
    }
    previousPrice = lastClose;
  }

  const ch = lastClose - firstOpen;
  if ($("chg")) {
    $("chg").textContent =
      (ch >= 0 ? "+" : "") + f(ch) + " (" + f((ch / firstOpen) * 100) + "%)";
    $("chg").style.color = ch >= 0 ? "var(--up)" : "var(--dn)";
  }

  const allHighs = data.map((d) => (d.h !== undefined ? d.h : d.high));
  const allLows = data.map((d) => (d.l !== undefined ? d.l : d.low));
  if ($("hi")) $("hi").textContent = f(Math.max(...allHighs));
  if ($("lo")) $("lo").textContent = f(Math.min(...allLows));

  // Timestamp
  if ($("upd")) {
    const dObj = new Date(lastTime * 1000);
    $("upd").textContent =
      dObj.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) +
      " IST";
  }

  // Connection Badge
  if (sample) {
    conn("SAMPLE DATA", "b-warn");
  } else if (stale) {
    conn("STALE", "b-bad");
    setSig(null, true);
  } else {
    conn("LIVE", "b-ok");
  }

  // Contract specs / Basis
  if ($("basis") && smcData && smcData.status) {
    const stat = smcData.status;
    const isSpot = stat.contract_type === "spot_index";
    $("basis").textContent = isSpot ? "Spot Index" : "Perp (Delta IN)";
  }

  if (!(stale && !sample)) {
    setSig(sig);
    renderCopilotGuidance(sig ? sig.tactical_guidance : null, false);
  } else {
    renderCopilotGuidance(null, true);
  }

  draw();
  renderLevels();
  renderDrawerPanes();
}

// --------------------------------------------------------------------------
// 4. Signal & Strategy State Rendering
// --------------------------------------------------------------------------
function setSig(s, stale) {
  if ($("smp")) $("smp").textContent = sample ? "· SAMPLE" : "";
  const ids = ["dir", "en", "sl", "t1", "t2", "rr"];

  if (!s || stale) {
    if ($("st")) {
      $("st").textContent = stale ? "DATA STALE" : "WAIT & WATCH";
      $("st").style.color = stale ? "var(--dn)" : "var(--am)";
    }
    ids.forEach((i) => {
      if ($(i)) $(i).textContent = "—";
    });
    if ($("ck")) {
      $("ck").innerHTML = `<li class="n">${
        stale ? "Signals suspended until data is fresh" : "No signal data"
      }</li>`;
    }
    ["t-str", "t-ret", "t-exp", "t-sup", "t-res"].forEach((i) => {
      if ($(i)) $(i).textContent = "—";
    });
    if ($("mtf")) $("mtf").innerHTML = '<div class="lv"><span>No bias data</span></div>';
    if ($("btnPaperTrade")) $("btnPaperTrade").classList.remove("show");
    return;
  }

  const allMet =
    (s.checklist || []).length > 0 && s.checklist.every((c) => c.met);
  let st = (s.state || "WAIT_WATCH").toUpperCase();
  if ((st === "ACTIVE" || st === "EXTREME") && !allMet) {
    st = "WATCH";
  }

  const act = st === "ACTIVE" || st === "EXTREME";
  if ($("st")) {
    $("st").textContent = st.replace("_", " & ");
    $("st").style.color = act
      ? s.direction === "short"
        ? "var(--dn)"
        : "var(--up)"
      : "var(--am)";
  }

  if ($("dir")) $("dir").textContent = s.direction ? s.direction.toUpperCase() : "—";
  if ($("en")) $("en").textContent = act ? f(s.entry) : "—";
  if ($("sl")) $("sl").textContent = act ? f(s.stop) : "—";
  if ($("t1")) $("t1").textContent = act ? f((s.targets || [])[0]) : "—";
  if ($("t2")) $("t2").textContent = act ? f((s.targets || [])[1]) : "—";

  const risk = Math.abs(s.entry - s.stop);
  const rew = Math.abs((s.targets || [])[0] - s.entry);
  if ($("rr")) {
    $("rr").textContent = act && risk > 0 ? "1 : " + f(rew / risk) : "—";
  }

  // Paper trade action button
  if ($("btnPaperTrade")) {
    if (act) {
      $("btnPaperTrade").classList.add("show");
      $("btnPaperTrade").textContent = `⚡ Execute Paper ${s.direction ? s.direction.toUpperCase() : "TRADE"}`;
    } else {
      $("btnPaperTrade").classList.remove("show");
    }
  }

  // Checklist
  if ($("ck")) {
    $("ck").innerHTML =
      (s.checklist || [])
        .map(
          (c) =>
            `<li class="${c.met ? "y" : "n"}"><span>${
              c.met ? "✔" : "○"
            }</span>${c.label}</li>`
        )
        .join("") || `<li class="n">Awaiting confirmation criteria</li>`;
  }

  // Bottom tiles
  if ($("t-str")) $("t-str").textContent = s.structure || "Consolidation / Range";
  if ($("t-ret")) $("t-ret").textContent = s.retracement || "In Equilibrium";
  if ($("t-exp")) {
    $("t-exp").textContent = s.expires_at
      ? new Date(s.expires_at * 1000).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "Invalidation level monitored";
  }

  // MTF Bias
  if ($("mtf")) {
    $("mtf").innerHTML =
      Object.entries(s.bias || {})
        .map(([k, v]) => {
          const isBull = String(v).toLowerCase().includes("bull");
          const isBear = String(v).toLowerCase().includes("bear");
          const col = isBull ? "var(--up)" : isBear ? "var(--dn)" : "var(--mu)";
          return `<div class="lv"><span>${k.toUpperCase()}</span><b style="color:${col}">${v}</b></div>`;
        })
        .join("") || '<div class="lv"><span>No bias data</span></div>';
  }
}

// --------------------------------------------------------------------------
// 4b. Tactical Co-Pilot Guidance Rendering
// --------------------------------------------------------------------------
function renderCopilotGuidance(g, isStale) {
  const iconEl = $("copilotIcon");
  const headEl = $("copilotHeadline");
  const stepEl = $("copilotStep");
  const gradeEl = $("copilotGrade");
  const planEl = $("copilotActionPlan");

  if (!iconEl || !headEl) return;

  if (isStale) {
    iconEl.textContent = "⚠️";
    headEl.textContent = "SMC Tactical Co-Pilot · Market Data Stale";
    if (stepEl) stepEl.textContent = "Feed Suspended";
    if (gradeEl) {
      gradeEl.textContent = "Data Delayed";
      gradeEl.style.borderColor = "var(--dn)";
      gradeEl.style.color = "var(--dn)";
      gradeEl.style.background = "rgba(255, 59, 78, 0.1)";
    }
    if (planEl) planEl.textContent = "Waiting for fresh live ticks from Delta Exchange India before calculating key POI reactions.";
    return;
  }

  if (!g) {
    iconEl.textContent = "🎯";
    headEl.textContent = "SMC Tactical Co-Pilot · Establishing Liquidity Boundaries...";
    if (stepEl) stepEl.textContent = "Step 1/3: Surveillance";
    if (gradeEl) {
      gradeEl.textContent = "Grade A [85%]";
      gradeEl.style.borderColor = "rgba(245, 197, 24, 0.35)";
      gradeEl.style.color = "var(--am)";
      gradeEl.style.background = "rgba(245, 197, 24, 0.15)";
    }
    if (planEl) planEl.textContent = "Monitoring multi-timeframe order blocks and liquidity pools for high-probability setups.";
    return;
  }

  const headline = g.headline || "SMC Tactical Co-Pilot Active";
  headEl.textContent = headline;

  if (headline.includes("HIGH-CONFLUENCE") || headline.includes("ACTIVE")) {
    iconEl.textContent = "🚀";
  } else if (headline.includes("APPROACHING")) {
    iconEl.textContent = "🎯";
  } else if (headline.includes("DEVELOPING")) {
    iconEl.textContent = "⚡";
  } else {
    iconEl.textContent = "⚖️";
  }

  if (stepEl) stepEl.textContent = g.lifecycle_step || "Active Monitoring";

  if (gradeEl) {
    const gr = g.grade || "A";
    const conf = Math.round(g.confidence_score || 85);
    gradeEl.textContent = `Grade ${gr} [${conf}%]`;
    if (gr === "A+" || conf >= 88) {
      gradeEl.style.background = "rgba(245, 197, 24, 0.18)";
      gradeEl.style.color = "var(--am)";
      gradeEl.style.borderColor = "rgba(245, 197, 24, 0.4)";
    } else if (gr === "A") {
      gradeEl.style.background = "rgba(24, 195, 126, 0.15)";
      gradeEl.style.color = "var(--up)";
      gradeEl.style.borderColor = "rgba(24, 195, 126, 0.35)";
    } else {
      gradeEl.style.background = "rgba(47, 155, 255, 0.15)";
      gradeEl.style.color = "var(--bl)";
      gradeEl.style.borderColor = "rgba(47, 155, 255, 0.35)";
    }
  }

  if (planEl) {
    planEl.textContent = g.action_plan || "Surveillance active. Awaiting institutional boundary interaction.";
  }
}

// --------------------------------------------------------------------------
// 5. Liquidity & Key Levels Computation
// --------------------------------------------------------------------------
function levels() {
  if (!sig || !sig.levels) return [];
  return sig.levels.filter((l) => {
    const isHtfFvg = l.is_htf_fvg !== undefined
      ? l.is_htf_fvg
      : (l.kind === "FVG" && (l.label.includes("4H") || l.label.includes("1D") || l.label.includes("Daily") || l.label.includes("Weekly")));
    const isCurFvg = l.is_curr_fvg !== undefined
      ? l.is_curr_fvg
      : (l.kind === "FVG" && !isHtfFvg);
    const isHtfLvl = l.is_htf_level !== undefined
      ? l.is_htf_level
      : (l.kind !== "FVG" && (l.label.includes("Day") || l.label.includes("Week") || l.label.includes("PDH") || l.label.includes("PDL") || l.label.includes("Institutional") || l.label.includes("Round")));
    const isCurLvl = l.is_curr_level !== undefined
      ? l.is_curr_level
      : (l.kind !== "FVG" && !isHtfLvl);

    // Layer toggles
    if (isHtfFvg && !layers.htfFvg) return false;
    if (isCurFvg && !layers.curFvg) return false;
    if (isCurLvl && !layers.curLiq) return false;
    if (isHtfLvl && !layers.htfSr) return false;

    // Focus mode suppresses minor micro levels
    if (focus && (isCurFvg || (isCurLvl && !["BSL", "SSL"].includes(l.kind)))) return false;

    return true;
  });
}

function renderLevels() {
  const L = levels();
  const last = data && data[data.length - 1];
  const lastClose = last ? (last.c !== undefined ? last.c : last.close) : 0;

  if ($("liq-cnt")) $("liq-cnt").textContent = `${L.length} levels`;

  if ($("liq")) {
    $("liq").innerHTML =
      L.slice(0, 14)
        .map((l) => {
          const dist = lastClose > 0 ? l.price - lastClose : 0;
          const distTag =
            dist !== 0
              ? ` <small style="color:var(--mu)">(${dist > 0 ? "+" : ""}${f(
                  dist,
                  1
                )})</small>`
              : "";
          const isSup = ["SSL", "SUP", "EQL"].includes(l.kind);
          const col = isSup ? "var(--up)" : "var(--dn)";
          const gradeBadge = l.grade
            ? `<span class="tag-pill" style="background:rgba(245,197,24,0.12); color:var(--am); font-size:9px; margin-left:3px;" title="Historical zone reliability score">${l.grade} ${Math.round(l.reliability_score || 80)}%</span>`
            : "";
          return `<div class="lv"><span><span class="tag-pill" style="background:rgba(255,255,255,0.06);color:${col}">${
            l.kind
          }</span> ${l.label || ""}${gradeBadge}</span><b>${f(l.price)}${distTag}</b></div>`;
        })
        .join("") || '<div class="lv"><span>No active levels detected</span></div>';
  }

  if (lastClose > 0) {
    const b = (sig && sig.levels) || [];
    const sup = b
      .filter((l) => ["SUP", "SSL", "EQL"].includes(l.kind) && l.price < lastClose)
      .map((l) => l.price);
    const res = b
      .filter((l) => ["RES", "BSL", "EQH"].includes(l.kind) && l.price > lastClose)
      .map((l) => l.price);

    if ($("t-sup")) $("t-sup").textContent = sup.length ? f(Math.max(...sup)) : "—";
    if ($("t-res")) $("t-res").textContent = res.length ? f(Math.min(...res)) : "—";
  }
}

// --------------------------------------------------------------------------
// 6. Professional TradingView LightweightCharts Engine (from smc-workstation-v2)
// --------------------------------------------------------------------------
function initLightweightChart() {
  const container = $("chartContainer");
  if (!container || !window.LightweightCharts) return false;

  if (lwChart) {
    try { lwChart.remove(); } catch (e) {}
    lwChart = null;
    lwSeries = null;
    activePriceLines = [];
  }

  container.innerHTML = "";

  const cfg = THEME_CHART_CONFIGS[currentTheme] || THEME_CHART_CONFIGS.dark;

  lwChart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "transparent" },
      textColor: cfg.textColor,
      fontSize: 11,
      fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    },
    grid: {
      vertLines: { color: cfg.gridV },
      horzLines: { color: cfg.gridH }
    },
    rightPriceScale: {
      borderColor: cfg.borderColor,
      scaleMargins: { top: 0.08, bottom: 0.12 }
    },
    timeScale: {
      borderColor: cfg.borderColor,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 12
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: {
      priceFormatter: (p) => Number(p).toFixed(2)
    }
  });

  lwSeries = lwChart.addCandlestickSeries({
    upColor: cfg.candleUp,
    downColor: cfg.candleDn,
    borderVisible: false,
    wickUpColor: cfg.candleUp,
    wickDownColor: cfg.candleDn,
    priceLineVisible: true,
    lastValueVisible: true
  });

  // Crosshair move listener to update legend O/H/L/C in real-time
  lwChart.subscribeCrosshairMove((param) => {
    if (!param || !param.time || !param.seriesData) {
      if (data && data.length) {
        const lc = data[data.length - 1];
        if ($("leg-o")) $("leg-o").textContent = f(lc.o || lc.open);
        if ($("leg-h")) $("leg-h").textContent = f(lc.h || lc.high);
        if ($("leg-l")) $("leg-l").textContent = f(lc.l || lc.low);
        if ($("leg-c")) $("leg-c").textContent = f(lc.c || lc.close);
        if ($("leg-v")) $("leg-v").textContent = lc.v || lc.volume || 0;
      }
      return;
    }
    const c = param.seriesData.get(lwSeries);
    if (c) {
      if ($("leg-o")) $("leg-o").textContent = f(c.open);
      if ($("leg-h")) $("leg-h").textContent = f(c.high);
      if ($("leg-l")) $("leg-l").textContent = f(c.low);
      if ($("leg-c")) $("leg-c").textContent = f(c.close);
    }
  });

  return true;
}

function draw() {
  if (window.LightweightCharts && $("chartContainer")) {
    const cv = $("cv");
    if (cv) cv.style.display = "none";
    const container = $("chartContainer");
    if (container) container.style.display = "block";

    if (!lwChart) {
      initLightweightChart();
    }

    if (lwSeries && data && data.length) {
      const formatted = [];
      const seenTimes = new Set();
      for (const c of data) {
        let t = Math.floor(c.t !== undefined ? c.t : c.time);
        if (!t || seenTimes.has(t)) continue;
        seenTimes.add(t);
        formatted.push({
          time: t,
          open: Number(c.o !== undefined ? c.o : c.open),
          high: Number(c.h !== undefined ? c.h : c.high),
          low: Number(c.l !== undefined ? c.l : c.low),
          close: Number(c.c !== undefined ? c.c : c.close)
        });
      }
      formatted.sort((a, b) => a.time - b.time);
      lwSeries.setData(formatted);

      // Volume Series Handling (Layer: Volume)
      if (layers.volume) {
        if (!lwVolumeSeries) {
          lwVolumeSeries = lwChart.addHistogramSeries({
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
            lastValueVisible: false,
            priceLineVisible: false
          });
          lwChart.priceScale("vol").applyOptions({
            scaleMargins: { top: 0.82, bottom: 0 },
            visible: false
          });
        }
        const volData = [];
        const seenVols = new Set();
        for (const c of data) {
          let t = Math.floor(c.t !== undefined ? c.t : c.time);
          if (!t || seenVols.has(t)) continue;
          seenVols.add(t);
          const open = Number(c.o !== undefined ? c.o : c.open);
          const close = Number(c.c !== undefined ? c.c : c.close);
          const vol = Number(c.v !== undefined ? c.v : (c.volume || 0));
          volData.push({
            time: t,
            value: vol > 0 ? vol : 10,
            color: close >= open ? "rgba(24, 195, 126, 0.35)" : "rgba(255, 59, 78, 0.35)"
          });
        }
        volData.sort((a, b) => a.time - b.time);
        lwVolumeSeries.setData(volData);
      } else if (lwVolumeSeries) {
        try { lwChart.removeSeries(lwVolumeSeries); } catch (e) {}
        lwVolumeSeries = null;
      }

      // Re-create SMC Level Price Lines
      activePriceLines.forEach((pl) => {
        try { lwSeries.removePriceLine(pl); } catch (e) {}
      });
      activePriceLines = [];

      const colMap = {
        BSL: "#ff3b4e",
        RES: "#ff3b4e",
        SSL: "#18c37e",
        SUP: "#18c37e",
        EQH: "#f5c518",
        EQL: "#f5c518",
        FVG: "#2f9bff"
      };

      const L = levels();
      L.forEach((lvl) => {
        if (lvl.price > 0) {
          const isHtf = lvl.is_htf_fvg || lvl.is_htf_level;
          const isFvg = lvl.kind === "FVG";
          const fvgCol = lvl.is_htf_fvg ? "#2f9bff" : "#22d3ee";
          const lineCol = isFvg ? fvgCol : (colMap[lvl.kind] || "#6f8399");
          const gradeStr = lvl.grade ? ` [${lvl.grade} ${Math.round(lvl.reliability_score || 80)}%]` : "";

          const pl = lwSeries.createPriceLine({
            price: lvl.price,
            color: lineCol,
            lineWidth: isHtf ? 2 : 1,
            lineStyle: isHtf ? LightweightCharts.LineStyle.Solid : LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: (lvl.kind + " " + (lvl.label || "") + gradeStr).trim()
          });
          activePriceLines.push(pl);
        }
      });

      // Active Trade Setup Markers (Layer: Setups)
      if (layers.setups) {
        const act =
          sig &&
          ["ACTIVE", "EXTREME"].includes((sig.state || "").toUpperCase()) &&
          (sig.checklist || []).every((c) => c.met);

        if (act) {
          if (sig.entry) {
            activePriceLines.push(lwSeries.createPriceLine({
              price: sig.entry,
              color: "#f5c518",
              lineWidth: 2,
              lineStyle: LightweightCharts.LineStyle.Solid,
              axisLabelVisible: true,
              title: "ENTRY " + f(sig.entry)
            }));
          }
          if (sig.stop) {
            activePriceLines.push(lwSeries.createPriceLine({
              price: sig.stop,
              color: "#ff3b4e",
              lineWidth: 2,
              lineStyle: LightweightCharts.LineStyle.Solid,
              axisLabelVisible: true,
              title: "STOP " + f(sig.stop)
            }));
          }
          (sig.targets || []).forEach((t, i) => {
            activePriceLines.push(lwSeries.createPriceLine({
              price: t,
              color: "#18c37e",
              lineWidth: 2,
              lineStyle: LightweightCharts.LineStyle.Solid,
              axisLabelVisible: true,
              title: "TARGET " + (i + 1) + " " + f(t)
            }));
          });
        }
      }

      // Default legend to latest candle
      const lc = data[data.length - 1];
      if (lc) {
        if ($("leg-o")) $("leg-o").textContent = f(lc.o || lc.open);
        if ($("leg-h")) $("leg-h").textContent = f(lc.h || lc.high);
        if ($("leg-l")) $("leg-l").textContent = f(lc.l || lc.low);
        if ($("leg-c")) $("leg-c").textContent = f(lc.c || lc.close);
        if ($("leg-v")) $("leg-v").textContent = lc.v || lc.volume || 0;
      }
      return;
    }
  }

  // Fallback 2D Canvas Renderer
  drawCanvasFallback();
}

function drawCanvasFallback() {
  const cv = $("cv");
  if (!cv) return;
  cv.style.display = "block";
  const container = $("chartContainer");
  if (container) container.style.display = "none";

  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  cv.width = r.width * dpr;
  cv.height = r.height * dpr;

  const g = cv.getContext("2d");
  g.scale(dpr, dpr);
  g.clearRect(0, 0, r.width, r.height);

  if (!data || !data.length) return;

  const W = r.width;
  const H = r.height;
  const pr = 64; // right price scale width
  const pb = 24; // bottom time scale height

  const total = data.length;
  const count = Math.min(viewCandleCount, total);
  const endIdx = Math.max(count, total - panOffset);
  const startIdx = Math.max(0, endIdx - count);
  const d = data.slice(startIdx, endIdx);

  if (!d.length) return;

  const L = levels();
  const act =
    sig &&
    ["ACTIVE", "EXTREME"].includes((sig.state || "").toUpperCase()) &&
    (sig.checklist || []).every((c) => c.met);
  const extra = [
    ...(act ? [sig.entry, sig.stop, ...(sig.targets || [])] : []),
  ];

  const highs = d.map((x) => (x.h !== undefined ? x.h : x.high));
  const lows = d.map((x) => (x.l !== undefined ? x.l : x.low));

  let hi = Math.max(...highs, ...extra);
  let lo = Math.min(...lows, ...extra);
  const mid = (hi + lo) / 2;
  const halfRange = Math.max(0.5, ((hi - lo) / 2) * priceScaleMultiplier);
  hi = mid + halfRange * 1.08;
  lo = mid - halfRange * 1.08;

  const Y = (v) =>
    H - pb - ((v - lo) / (hi - lo)) * (H - pb - 12) - 4;
  const cw = (W - pr) / d.length;

  // Background Grid Lines & Price Labels
  const cfg = THEME_CHART_CONFIGS[currentTheme] || THEME_CHART_CONFIGS.dark;
  g.font = "10.5px 'Segoe UI', sans-serif";
  g.strokeStyle = cfg.canvasGrid;
  g.fillStyle = cfg.canvasText;
  g.lineWidth = 1;

  for (let i = 0; i <= 6; i++) {
    const v = lo + ((hi - lo) * i) / 6;
    const y = Y(v);
    g.beginPath();
    g.moveTo(0, y);
    g.lineTo(W - pr, y);
    g.stroke();
    g.fillText(f(v, 2), W - pr + 6, y + 4);
  }

  // Draw Candlesticks
  d.forEach((c, i) => {
    const o = c.o !== undefined ? c.o : c.open;
    const h = c.h !== undefined ? c.h : c.high;
    const l = c.l !== undefined ? c.l : c.low;
    const cl = c.c !== undefined ? c.c : c.close;
    const isClosed = c.closed !== undefined ? c.closed : !c.is_forming;

    const x = i * cw + cw / 2;
    const up = cl >= o;
    const col = up ? "#18c37e" : "#ff3b4e";

    g.strokeStyle = col;
    g.fillStyle = col;
    g.lineWidth = 1;

    g.beginPath();
    g.moveTo(x, Y(h));
    g.lineTo(x, Y(l));
    g.stroke();

    const y1 = Y(Math.max(o, cl));
    const bodyH = Math.max(1.5, Math.abs(Y(o) - Y(cl)));
    const candleWidth = Math.max(2, cw * 0.72);

    if (!isClosed) {
      g.strokeRect(x - candleWidth / 2, y1, candleWidth, bodyH);
    } else {
      g.fillRect(x - candleWidth / 2, y1, candleWidth, bodyH);
    }
  });

  const tag = (v, txt, col) => {
    if (v < lo || v > hi) return;
    const y = Y(v);
    g.strokeStyle = col;
    g.setLineDash([4, 4]);
    g.beginPath();
    g.moveTo(0, y);
    g.lineTo(W - pr, y);
    g.stroke();
    g.setLineDash([]);

    g.fillStyle = col;
    g.fillRect(W - pr, y - 9, pr, 18);
    g.fillStyle = "#000";
    g.font = "bold 9.5px 'Segoe UI', sans-serif";
    g.fillText(txt + " " + f(v, 1), W - pr + 3, y + 4);
  };

  L.forEach((lvl) => {
    const colMap = {
      BSL: "#ff3b4e",
      RES: "#ff3b4e",
      SSL: "#18c37e",
      SUP: "#18c37e",
      EQH: "#f5c518",
      EQL: "#f5c518",
      FVG: "#2f9bff",
    };
    const gradeStr = lvl.grade ? ` [${lvl.grade}]` : "";
    tag(lvl.price, lvl.kind + gradeStr, colMap[lvl.kind] || "#6f8399");
  });

  if (act) {
    tag(sig.entry, "ENT", "#f5c518");
    tag(sig.stop, "SL", "#ff3b4e");
    (sig.targets || []).forEach((t, i) =>
      tag(t, "T" + (i + 1), "#18c37e")
    );
  }

  const lc = d[d.length - 1];
  const lastClose = lc.c !== undefined ? lc.c : lc.close;
  const currentY = Y(lastClose);

  g.strokeStyle = "#2f9bff";
  g.setLineDash([2, 2]);
  g.beginPath();
  g.moveTo(0, currentY);
  g.lineTo(W - pr, currentY);
  g.stroke();
  g.setLineDash([]);

  g.fillStyle = "#2f9bff";
  g.fillRect(W - pr, currentY - 9, pr, 18);
  g.fillStyle = "#000";
  g.font = "bold 10px 'Segoe UI', sans-serif";
  g.fillText(f(lastClose, 2), W - pr + 4, currentY + 4);

  g.fillStyle = cfg.canvasText;
  g.font = "10px 'Segoe UI', sans-serif";
  [0, Math.floor(d.length / 2), d.length - 1].forEach((i) => {
    if (!d[i]) return;
    const tVal = d[i].t !== undefined ? d[i].t : d[i].time;
    const str = new Date(tVal * 1000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    const xPos = Math.min(i * cw, W - pr - 100);
    g.fillText(str, Math.max(6, xPos), H - 7);
  });
}

// --------------------------------------------------------------------------
// 7. Intelligence Hub Drawer Panes (Watchlist, Radar, Events)
// --------------------------------------------------------------------------
function renderDrawerPanes() {
  if (!smcData) return;

  // Render Watchlist
  const wlContainer = $("wl-items");
  const watchlist = smcData.analysis?.watchlist || [];
  if (wlContainer && watchlist.length) {
    wlContainer.innerHTML = watchlist
      .slice(0, 15)
      .map((item) => {
        const stateColor =
          item.state === "ACTIVE"
            ? "var(--up)"
            : item.state === "WATCH"
            ? "var(--am)"
            : "var(--mu)";
        return `
        <div class="card-sm" style="border-left: 3px solid ${stateColor};">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b>${item.name || "SMC Setup"}</b>
            <span class="tag-pill" style="background:rgba(255,255,255,0.06); color:${stateColor}">${item.state}</span>
          </div>
          <p>${item.description || item.reason || "Under surveillance"}</p>
        </div>`;
      })
      .join("");
  }

  // Render Liquidity Radar
  const radarContainer = $("radar-items");
  const radarZones =
    smcData.analysis?.hidden_liquidity_zones ||
    smcData.analysis?.liquidity_levels ||
    [];
  if (radarContainer && radarZones.length) {
    radarContainer.innerHTML = radarZones
      .slice(0, 12)
      .map((z) => {
        const isBsl = (z.type || z.kind || "").includes("BSL");
        const col = isBsl ? "var(--dn)" : "var(--up)";
        return `
        <div class="card-sm">
          <div style="display:flex; justify-content:space-between;">
            <b style="color:${col}">${z.type || z.kind || "LIQ POOL"}</b>
            <span style="font-family:monospace; color:var(--tx-b)">${f(z.price)}</span>
          </div>
          <p>Confidence: ${z.score || "80%"} · ${z.status || "Unswept"}</p>
        </div>`;
      })
      .join("");
  }
}

// --------------------------------------------------------------------------
// 8. WebSocket Stream Integration
// --------------------------------------------------------------------------
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      conn("LIVE", "b-ok");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === "candle_update" || msg.type === "candle_update") {
          if (msg.candle && data && data.length) {
            const incoming = msg.candle;
            const last = data[data.length - 1];
            if (incoming.time === last.t || incoming.time === last.time) {
              data[data.length - 1] = {
                t: incoming.time,
                time: incoming.time,
                o: incoming.open,
                open: incoming.open,
                h: incoming.high,
                high: incoming.high,
                l: incoming.low,
                low: incoming.low,
                c: incoming.close,
                close: incoming.close,
                v: incoming.volume,
                volume: incoming.volume,
                closed: !incoming.is_forming,
              };
            } else if (incoming.time > (last.t || last.time)) {
              data.push({
                t: incoming.time,
                time: incoming.time,
                o: incoming.open,
                open: incoming.open,
                h: incoming.high,
                high: incoming.high,
                l: incoming.low,
                low: incoming.low,
                c: incoming.close,
                close: incoming.close,
                v: incoming.volume,
                volume: incoming.volume,
                closed: !incoming.is_forming,
              });
            }
            paint();
          }
        }
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };

    ws.onclose = () => {
      conn("CONNECTING", "b-warn");
      setTimeout(initWebSocket, 4000);
    };

    ws.onerror = () => {
      ws.close();
    };
  } catch (e) {
    console.warn("WebSocket init error:", e);
  }
}

// --------------------------------------------------------------------------
// 9. Interactive Chart Controls & Listeners
// --------------------------------------------------------------------------
function setupChartEvents() {
  const cv = $("cv");
  const chartwrap = $("chartwrap");
  const resizer = $("chartResizer");
  const btnHeight = $("btnHeightToggle");
  const heightText = $("heightText");
  const btnFs = $("btnFullscreen");
  const fsText = $("fsText");
  const btnHeaderFs = $("btnHeaderFullscreen");

  if (!cv || !chartwrap) return;

  // Restore saved chart height
  const savedH = localStorage.getItem("smc_chart_height");
  if (savedH) {
    chartwrap.style.height = `${savedH}px`;
    if (heightText) heightText.textContent = `${savedH}px`;
  }

  // 1. Chart Vertical Resizer Drag Handle
  if (resizer) {
    let isResizing = false;
    let startY = 0;
    let startH = 0;

    resizer.addEventListener("mousedown", (e) => {
      isResizing = true;
      startY = e.clientY;
      startH = chartwrap.getBoundingClientRect().height;
      resizer.classList.add("dragging");
      document.body.style.cursor = "row-resize";
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizing) return;
      const deltaY = e.clientY - startY;
      const newH = Math.max(340, Math.min(1400, Math.round(startH + deltaY)));
      chartwrap.style.height = `${newH}px`;
      if (heightText) heightText.textContent = `${newH}px`;
      if (lwChart) {
        const container = $("chartContainer");
        if (container) {
          const bounds = container.getBoundingClientRect();
          lwChart.applyOptions({ width: bounds.width, height: bounds.height });
        }
      } else {
        draw();
      }
    });

    window.addEventListener("mouseup", () => {
      if (isResizing) {
        isResizing = false;
        resizer.classList.remove("dragging");
        document.body.style.cursor = "";
        const finalH = Math.round(chartwrap.getBoundingClientRect().height);
        localStorage.setItem("smc_chart_height", finalH);
        if (lwChart) {
          const container = $("chartContainer");
          if (container) {
            const bounds = container.getBoundingClientRect();
            lwChart.applyOptions({ width: bounds.width, height: bounds.height });
          }
        } else {
          draw();
        }
      }
    });
  }

  // 2. Quick Height Toggle Button (Toolbar)
  if (btnHeight) {
    const heights = [440, 560, 720, 880];
    btnHeight.onclick = () => {
      const curH = chartwrap.getBoundingClientRect().height;
      const nextH = heights.find((h) => h > curH + 25) || heights[0];
      chartwrap.style.height = `${nextH}px`;
      if (heightText) heightText.textContent = `${nextH}px`;
      localStorage.setItem("smc_chart_height", nextH);
      if (lwChart) {
        const container = $("chartContainer");
        if (container) {
          const bounds = container.getBoundingClientRect();
          lwChart.applyOptions({ width: bounds.width, height: bounds.height });
        }
      } else {
        draw();
      }
    };
  }

  // 3. Full Screen Mode Toggle (Matching smc-workstation-v2.html)
  function fullOn() {
    return !!document.fullscreenElement || chartwrap.classList.contains("maxed");
  }

  async function toggleFull() {
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
    } else if (chartwrap.classList.contains("maxed")) {
      chartwrap.classList.remove("maxed");
      document.body.classList.remove("chart-max");
    } else {
      try {
        if (!chartwrap.requestFullscreen) throw new Error("no api");
        await chartwrap.requestFullscreen();
      } catch (e) {
        chartwrap.classList.add("maxed");
        document.body.classList.add("chart-max");
      }
    }
    setTimeout(syncFull, 60);
  }

  function syncFull() {
    const on = fullOn();
    if (fsText) fsText.textContent = on ? "Exit Full Screen" : "Full Screen";
    if (btnFs) btnFs.classList.toggle("on", on);
    if (btnHeaderFs) {
      btnHeaderFs.textContent = on ? "✕ Exit Fullscreen" : "⛶ Fullscreen";
      btnHeaderFs.classList.toggle("on", on);
    }
    if (lwChart) {
      const container = $("chartContainer");
      if (container) {
        const bounds = container.getBoundingClientRect();
        lwChart.applyOptions({ width: bounds.width, height: bounds.height });
      }
      lwChart.timeScale().fitContent();
    } else {
      draw();
    }
  }

  if (btnFs) btnFs.onclick = toggleFull;
  if (btnHeaderFs) btnHeaderFs.onclick = toggleFull;

  document.addEventListener("fullscreenchange", syncFull);
  document.addEventListener("webkitfullscreenchange", syncFull);

  // Keyboard shortcuts: 'F' / 'f' to toggle fullscreen, 'Escape' to exit
  window.addEventListener("keydown", (e) => {
    if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.metaKey && !e.altKey && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      e.preventDefault();
      toggleFull();
    }
    if (e.key === "Escape" && chartwrap.classList.contains("maxed")) {
      toggleFull();
    }
  });

  // 4. Interactive Canvas Mouse Events (Pan, Zoom, Y-Axis Price Scaling, Dynamic Cursors)
  const pr = 64; // right price scale width

  cv.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect();
    mouseX = e.clientX - r.left;
    mouseY = e.clientY - r.top;

    if (isDraggingYAxis) {
      cv.style.cursor = "ns-resize";
      const deltaY = dragStartY - e.clientY;
      priceScaleMultiplier = Math.max(
        0.15,
        Math.min(8.0, dragStartMultiplier * (1 + deltaY / 120))
      );
    } else if (isDragging) {
      cv.style.cursor = "grabbing";
      const deltaX = e.clientX - dragStartX;
      const cw = (r.width - pr) / Math.max(10, viewCandleCount);
      const candlesShift = Math.round(deltaX / Math.max(2, cw));
      panOffset = Math.max(
        0,
        Math.min((data ? data.length : 100) - 15, dragStartPan + candlesShift)
      );
    } else {
      if (mouseX >= r.width - pr) {
        cv.style.cursor = "ns-resize";
      } else {
        cv.style.cursor = "crosshair";
      }
    }
    draw();
  });

  cv.addEventListener("mouseleave", () => {
    mouseX = -1;
    mouseY = -1;
    if (!isDragging && !isDraggingYAxis) {
      cv.style.cursor = "crosshair";
    }
    draw();
  });

  cv.addEventListener("mousedown", (e) => {
    const r = cv.getBoundingClientRect();
    const curX = e.clientX - r.left;
    if (curX >= r.width - pr) {
      // Clicked on right price scale -> drag up/down to stretch/compress price scale
      isDraggingYAxis = true;
      dragStartY = e.clientY;
      dragStartMultiplier = priceScaleMultiplier;
      cv.style.cursor = "ns-resize";
    } else {
      isDragging = true;
      dragStartX = e.clientX;
      dragStartPan = panOffset;
      cv.style.cursor = "grabbing";
    }
    e.preventDefault();
  });

  cv.addEventListener("dblclick", (e) => {
    const r = cv.getBoundingClientRect();
    const curX = e.clientX - r.left;
    if (curX >= r.width - pr) {
      // Double click right price scale to reset vertical price stretch
      priceScaleMultiplier = 1.0;
    } else {
      // Double click chart body to reset horizontal candle zoom & pan
      viewCandleCount = 90;
      panOffset = 0;
    }
    draw();
  });

  window.addEventListener("mouseup", () => {
    if (isDragging || isDraggingYAxis) {
      isDragging = false;
      isDraggingYAxis = false;
      if (cv) cv.style.cursor = "crosshair";
    }
  });

  // Wheel zoom: Price scale vertical zoom vs Candle horizontal zoom
  cv.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      const r = cv.getBoundingClientRect();
      const curX = e.clientX - r.left;

      if (curX >= r.width - pr) {
        // Scrolled over price scale -> Zoom / contract prices vertically
        const factor = e.deltaY > 0 ? 0.90 : 1.11;
        priceScaleMultiplier = Math.max(0.15, Math.min(8.0, priceScaleMultiplier * factor));
      } else {
        // Scrolled over chart body -> Zoom candle count in / out
        const zoomDelta = e.deltaY > 0 ? 4 : -4;
        viewCandleCount = Math.max(15, Math.min(320, viewCandleCount + zoomDelta));
      }
      draw();
    },
    { passive: false }
  );
}

// --------------------------------------------------------------------------
// 10. Sample Data Generator (Explicitly Labelled Sample Simulation)
// --------------------------------------------------------------------------
function mkSample() {
  let s = 7;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  let p = 4165;
  const o = [];
  const now = Math.floor(Date.now() / 1000);
  const step = TFS[tf] || 3600;
  const t0 = Math.floor(now / step) * step - 89 * step;

  for (let i = 0; i < 90; i++) {
    const op = p;
    const cl = op + (rnd() - 0.51) * 12;
    const h = Math.max(op, cl) + rnd() * 5;
    const l = Math.min(op, cl) - rnd() * 5;
    o.push({
      t: t0 + i * step,
      time: t0 + i * step,
      o: op,
      open: op,
      h: h,
      high: h,
      l: l,
      low: l,
      c: cl,
      close: cl,
      closed: i < 89,
    });
    p = cl;
  }
  return o;
}

function mkSig(d) {
  const p = d[d.length - 1].c;
  return {
    state: "ACTIVE",
    direction: "short",
    entry: p + 2.5,
    stop: p + 14.0,
    targets: [p - 15.0, p - 28.0],
    expires_at: Date.now() / 1000 + 14400,
    structure: "Bearish BOS (1H Sample)",
    retracement: "Into 1H Resistance FVG",
    bias: {
      "1d": "Bearish",
      "4h": "Bearish",
      "2h": "Neutral",
      "1h": "Bearish",
      "15m": "Bearish",
    },
    levels: [
      { kind: "RES", price: p + 8.5, label: "PDH ($" + f(p + 8.5) + ")", grade: "A+", reliability_score: 92.0 },
      { kind: "BSL", price: p + 18.0, label: "Equal Highs Pool", grade: "A", reliability_score: 87.5 },
      { kind: "SUP", price: p - 14.0, label: "PDL ($" + f(p - 14.0) + ")", grade: "A", reliability_score: 85.0 },
      { kind: "SSL", price: p - 26.0, label: "Equal Lows Target", grade: "B", reliability_score: 78.0 },
      { kind: "FVG", price: p - 6.0, label: "1H Imbalance", grade: "A", reliability_score: 84.0 },
    ],
    checklist: [
      { label: "HTF directional bias alignment", met: true },
      { label: "Valid structural break (BOS / CHoCH)", met: true },
      { label: "Retracement into key POI (FVG / OB)", met: true },
      { label: "Liquidity sweep confluence", met: true },
      { label: "Favorable Risk:Reward (>= 2.0:1)", met: true },
    ],
    tactical_guidance: {
      headline: "🚀 HIGH-CONFLUENCE SHORT SETUP ACTIVE (5/5 Checklist Passed)",
      action_plan: "Key confluence confirmed with R:R >= 2:1. Invalidation at $" + f(p + 14.0) + ". Consider simulated execution.",
      lifecycle_step: "Step 3/3: Execution & Target Management",
      market_phase: "High-Confluence Order Flow",
      grade: "A+",
      confidence_score: 92.0,
      bias_summary: "1D: Bearish · 4H: Bearish · 1H: Bearish"
    }
  };
}

// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// 11. Audio Mode, Web Audio Synthesizer & Speech Guidance
// --------------------------------------------------------------------------
const AUDIO_MODES = [
  { id: "chime", label: "Chime", icon: "🔊" },
  { id: "voice", label: "Voice", icon: "🗣️" },
  { id: "mute", label: "Muted", icon: "🔇" },
];

function applyAudioModeUI() {
  const current = AUDIO_MODES.find((m) => m.id === audioMode) || AUDIO_MODES[0];
  const iconEl = $("audioModeIcon");
  const textEl = $("audioModeText");
  const btn = $("btnAudioMode");
  if (iconEl) iconEl.textContent = current.icon;
  if (textEl) textEl.textContent = current.label;
  if (btn) btn.classList.toggle("on", audioMode !== "mute");
}

function cycleAudioMode() {
  const idx = AUDIO_MODES.findIndex((m) => m.id === audioMode);
  const nextIdx = (idx + 1) % AUDIO_MODES.length;
  audioMode = AUDIO_MODES[nextIdx].id;
  localStorage.setItem("smc_audio_mode", audioMode);
  applyAudioModeUI();

  if (audioMode === "chime") {
    playChime("default");
    showToast("Alert Sound", "Dual-tone chimes enabled", "ok");
  } else if (audioMode === "voice") {
    speakAlert("Voice guidance enabled. Proximity and sweep alerts will be announced.");
    showToast("Alert Voice", "Speech synthesizer guidance enabled", "ok");
  } else {
    showToast("Alert Sound", "Alerts muted", "warn");
  }
}

function playChime(type = "default") {
  if (audioMode === "mute") return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    if (!audioCtx) audioCtx = new AudioContext();
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    const now = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";

    if (type === "proximity") {
      // Soft proximity alert chime (520Hz -> 660Hz)
      osc.frequency.setValueAtTime(520, now);
      osc.frequency.exponentialRampToValueAtTime(660, now + 0.16);
      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.38);
    } else if (type === "sweep") {
      // Dynamic liquidity sweep double chime
      osc.frequency.setValueAtTime(740, now);
      osc.frequency.exponentialRampToValueAtTime(1080, now + 0.14);
      gain.gain.setValueAtTime(0.09, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.34);
    } else if (type === "setup") {
      // High-conviction setup execution chime
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.18);
      gain.gain.setValueAtTime(0.1, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.42);
    } else {
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start(now);
      osc.stop(now + 0.32);
    }
  } catch (err) {
    console.warn("Audio chime prevented:", err);
  }
}

function speakAlert(text) {
  if (audioMode !== "voice" || !("speechSynthesis" in window) || !text) return;
  const now = Date.now();
  if (now - lastSpeechTime < 7000) return; // Throttled to prevent overlapping
  lastSpeechTime = now;

  try {
    window.speechSynthesis.cancel();
    const clean = text
      .replace(/[\$#\*_\[\]\(\)]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    utterance.volume = 0.9;
    window.speechSynthesis.speak(utterance);
  } catch (e) {
    console.warn("Speech synthesis error:", e);
  }
}

function showToast(title, message, type = "warn") {
  const container = $("toastContainer");
  if (!container) return;
  const t = document.createElement("div");
  const typeCls = type === "bad" || type === "danger" ? "t-bad" : (type === "ok" ? "t-ok" : "t-warn");
  t.className = `toast-msg ${typeCls}`;
  t.innerHTML = `
    <div style="flex:1;">
      <b style="display:block; font-size:12px; margin-bottom:2px;">${title}</b>
      <span style="font-size:11px; color:var(--tx);">${message || ""}</span>
    </div>
    <button style="background:none; border:none; color:var(--mu); font-size:14px; cursor:pointer; padding:0 4px;" title="Dismiss">✕</button>
  `;
  const closeBtn = t.querySelector("button");
  const remove = () => {
    t.classList.add("toast-out");
    setTimeout(() => t.remove(), 320);
  };
  closeBtn.onclick = remove;
  container.appendChild(t);
  setTimeout(remove, 6000);
}

// --------------------------------------------------------------------------
// 12. Alert Intelligence & Drawer Pane Handlers
// --------------------------------------------------------------------------
async function fetchAlerts() {
  try {
    const res = await fetch(CFG.alerts);
    if (!res.ok) return;
    const json = await res.json();
    const alerts = json.alerts || [];

    const unread = alerts.filter((a) => !a.acknowledged);
    unreadAlertCount = unread.length;
    const b = $("alertBadge");
    if (b) {
      b.style.display = unreadAlertCount > 0 ? "inline-block" : "none";
      b.textContent = unreadAlertCount;
    }
    const db = $("drawerAlertBadge");
    if (db) {
      db.style.display = unreadAlertCount > 0 ? "inline-block" : "none";
      db.textContent = unreadAlertCount;
    }

    let hasNew = false;
    let highestSeverity = "default";
    let newestVoiceText = "";

    for (const a of unread) {
      if (!seenAlertIds.has(a.id)) {
        seenAlertIds.add(a.id);
        hasNew = true;
        const title = a.title || "Market Alert";
        const msg = a.message || a.text || "";
        showToast(title, msg, a.severity || "warn");

        const upper = (title + " " + msg + " " + (a.alert_type || "")).toUpperCase();
        if (upper.includes("ACTIVE") || upper.includes("EXTREME") || upper.includes("SETUP")) {
          highestSeverity = "setup";
          newestVoiceText = title + ". " + msg;
        } else if (upper.includes("SWEEP") || upper.includes("LIQUIDITY")) {
          if (highestSeverity !== "setup") highestSeverity = "sweep";
          if (!newestVoiceText) newestVoiceText = title;
        } else if (upper.includes("PROXIMITY") || upper.includes("APPROACHING")) {
          if (highestSeverity === "default") highestSeverity = "proximity";
          if (!newestVoiceText) newestVoiceText = title;
        } else {
          if (!newestVoiceText) newestVoiceText = title;
        }
      }
    }

    if (hasNew) {
      playChime(highestSeverity);
      if (newestVoiceText) {
        speakAlert(newestVoiceText);
      }
    }

    renderAlertsList(alerts);
  } catch (err) {
    console.warn("Failed to fetch alerts:", err);
  }
}

async function acknowledgeAlert(alertId) {
  try {
    await fetch(`${CFG.alertsAck}?alert_id=${encodeURIComponent(alertId)}`, { method: "POST" });
    fetchAlerts();
  } catch (err) {
    console.error("Error acknowledging alert:", err);
  }
}

async function dismissAllAlerts() {
  try {
    await fetch(`${CFG.alertsAck}?dismiss_all=true`, { method: "POST" });
    fetchAlerts();
    showToast("Alerts", "All alerts dismissed", "ok");
  } catch (err) {
    console.error("Error dismissing alerts:", err);
  }
}

function renderAlertsList(alerts) {
  const container = $("alerts-items");
  if (!container) return;
  if (!alerts || !alerts.length) {
    container.innerHTML = `<div class="card-sm"><p>No alerts recorded yet in this session.</p></div>`;
    return;
  }
  container.innerHTML = alerts.slice(0, 35).map((a) => {
    const sev = a.severity || (a.is_active ? "warn" : "ok");
    const badgeClass = sev === "danger" || sev === "bad" ? "b-bad" : (sev === "warn" ? "b-warn" : "b-ok");
    const timeStr = a.timestamp ? new Date(a.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : "";
    return `
      <div class="card-sm" style="border-left: 3px solid ${sev === 'danger' || sev === 'bad' ? 'var(--dn)' : (sev === 'warn' ? 'var(--am)' : 'var(--up)')}; display:flex; flex-direction:column; gap:4px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="badge ${badgeClass}">${a.alert_type || a.severity || "ALERT"}</span>
          <small style="color:var(--mu); font-size:10px;">${timeStr}</small>
        </div>
        <b style="font-size:12px; margin-top:2px;">${a.title || a.message || "Alert"}</b>
        <p style="font-size:11px; color:var(--mu);">${a.description || a.text || a.message || ""}</p>
        ${!a.acknowledged ? `
          <div style="display:flex; justify-content:flex-end; margin-top:4px;">
            <button class="tg btn-ack" data-id="${a.id}" style="padding:1px 7px; font-size:9.5px;">Acknowledge</button>
          </div>
        ` : `<div style="font-size:9.5px; color:var(--mu); text-align:right;">Acknowledged ✓</div>`}
      </div>
    `;
  }).join("");

  container.querySelectorAll(".btn-ack").forEach((btn) => {
    btn.onclick = () => acknowledgeAlert(btn.dataset.id);
  });
}

// --------------------------------------------------------------------------
// 12b. Zone Insights & Persistent Reliability Engine
// --------------------------------------------------------------------------
async function fetchInsights() {
  try {
    const res = await fetch(CFG.insights);
    if (!res.ok) return;
    const json = await res.json();

    if ($("ins-reliability")) {
      $("ins-reliability").textContent = `${f(json.system_average_reliability, 1)}%`;
    }
    if ($("ins-high-conviction")) {
      $("ins-high-conviction").textContent = `${json.high_conviction_count || 0} Zones`;
    }

    const container = $("insights-zones");
    if (!container) return;

    const zones = json.top_performing_zones || [];
    if (!zones.length) {
      container.innerHTML = `<div class="card-sm"><p>Accumulating institutional zone memory. As price tests key levels, reliability scores will automatically calibrate.</p></div>`;
      return;
    }

    container.innerHTML = zones.slice(0, 10).map((z) => {
      const isA = (z.grade || "").startsWith("A");
      const gradeCol = z.grade === "A+" ? "var(--am)" : (isA ? "var(--up)" : "var(--bl)");
      return `
        <div class="card-sm" style="border-left: 3px solid ${gradeCol};">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b>${z.timeframe || ""} ${z.level_type || "POI"} @ ${f(z.price)}</b>
            <span class="copilot-grade" style="font-size:9.5px; border-color:${gradeCol}; color:${gradeCol};">${z.grade || "A"} [${Math.round(z.reliability_score || 80)}%]</span>
          </div>
          <p style="font-size:11px; margin-top:2px;">
            ${z.reactions || 0} successful bounces / ${z.touches || 1} touches · Sweeps: ${z.sweeps || 0} · Invalidations: ${z.invalidations || 0}
          </p>
        </div>
      `;
    }).join("");
  } catch (err) {
    console.warn("Failed to fetch insights:", err);
  }
}


// --------------------------------------------------------------------------
// 13. Layers Dropdown Interactive Controls
// --------------------------------------------------------------------------
function initLayersDropdown() {
  const btn = $("btnLayers");
  const menu = $("layersDropdown");
  if (!btn || !menu) return;

  btn.onclick = (e) => {
    e.stopPropagation();
    const isShowing = menu.style.display !== "none";
    menu.style.display = isShowing ? "none" : "block";
    btn.classList.toggle("on", !isShowing);
  };

  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
      menu.style.display = "none";
      btn.classList.remove("on");
    }
  });

  const bindCheck = (id, key) => {
    const el = $(id);
    if (!el) return;
    el.checked = !!layers[key];
    el.onchange = () => {
      layers[key] = el.checked;
      draw();
      renderLevels();
    };
  };

  bindCheck("layer-htf-fvg", "htfFvg");
  bindCheck("layer-cur-fvg", "curFvg");
  bindCheck("layer-cur-liq", "curLiq");
  bindCheck("layer-htf-sr", "htfSr");
  bindCheck("layer-setups", "setups");
  bindCheck("layer-vol", "volume");

  const focusEl = $("layer-focus");
  if (focusEl) {
    focusEl.checked = focus;
    focusEl.onchange = () => {
      focus = focusEl.checked;
      if ($("focus")) $("focus").classList.toggle("on", focus);
      draw();
      renderLevels();
    };
  }
}

// --------------------------------------------------------------------------
// 14. Event Listeners & Bootstrapping
// --------------------------------------------------------------------------
function boot() {
  initTimeframeBar();
  setupChartEvents();
  initLayersDropdown();

  // Theme Toggle Button
  const themeBtn = $("btnTheme");
  if (themeBtn) {
    themeBtn.onclick = cycleTheme;
  }
  applyTheme(currentTheme);

  // Audio Mode Button
  const audioBtn = $("btnAudioMode");
  if (audioBtn) {
    audioBtn.onclick = cycleAudioMode;
  }
  applyAudioModeUI();

  // Focus Mode
  const focusBtn = $("focus");
  if (focusBtn) {
    focusBtn.onclick = () => {
      focus = !focus;
      focusBtn.classList.toggle("on", focus);
      const lFocus = $("layer-focus");
      if (lFocus) lFocus.checked = focus;
      draw();
      renderLevels();
    };
  }

  // Sample data button
  const demoBtn = $("demo");
  if (demoBtn) {
    demoBtn.onclick = () => {
      sample = true;
      data = mkSample();
      sig = mkSig(data);
      paint();
    };
  }

  // Sync button
  const syncBtn = $("btnSync");
  if (syncBtn) {
    syncBtn.onclick = () => {
      sample = false;
      conn("SYNCING", "b-warn");
      load();
      fetchAlerts();
      fetchInsights();
    };
  }

  // Paper Trade Action Button
  const btnPaper = $("btnPaperTrade");
  if (btnPaper) {
    btnPaper.onclick = async () => {
      try {
        btnPaper.textContent = "Executing...";
        const res = await fetch(CFG.paperSimulate, { method: "POST" });
        const json = await res.json();
        if (json.success) {
          btnPaper.textContent = "✔ Paper Order Filled";
          setTimeout(() => {
            btnPaper.textContent = "⚡ Execute Paper Trade";
          }, 2500);
        }
      } catch (e) {
        btnPaper.textContent = "Error executing";
      }
    };
  }

  // Intelligence Hub Drawer
  const btnHub = $("btnHub");
  const drawer = $("drawer");
  const drawerOverlay = $("drawerOverlay");
  const btnCloseDrawer = $("btnCloseDrawer");

  const toggleDrawer = (open) => {
    if (!drawer) return;
    const shouldOpen = open !== undefined ? open : !drawer.classList.contains("open");
    drawer.classList.toggle("open", shouldOpen);
    if (drawerOverlay) drawerOverlay.classList.toggle("open", shouldOpen);
    if (btnHub) btnHub.classList.toggle("on", shouldOpen);
    if (shouldOpen) fetchInsights();
  };

  if (btnHub) btnHub.onclick = () => toggleDrawer();
  if (btnCloseDrawer) btnCloseDrawer.onclick = () => toggleDrawer(false);
  if (drawerOverlay) drawerOverlay.onclick = () => toggleDrawer(false);

  // Drawer Tabs
  const dTabs = document.querySelectorAll(".d-tab");
  const dPanes = document.querySelectorAll(".d-pane");
  dTabs.forEach((tab) => {
    tab.onclick = () => {
      const paneId = tab.dataset.pane;
      dTabs.forEach((t) => t.classList.remove("on"));
      dPanes.forEach((p) => (p.style.display = "none"));
      tab.classList.add("on");
      const target = $(paneId);
      if (target) target.style.display = "flex";
      if (paneId === "pane-insights") fetchInsights();
      if (paneId === "pane-alerts") fetchAlerts();
    };
  });

  // Header Alerts Button & Drawer Dismiss All
  const btnAlerts = $("btnAlerts");
  if (btnAlerts) {
    btnAlerts.onclick = () => {
      toggleDrawer(true);
      dTabs.forEach((t) => t.classList.toggle("on", t.dataset.pane === "pane-alerts"));
      dPanes.forEach((p) => (p.style.display = p.id === "pane-alerts" ? "flex" : "none"));
      fetchAlerts();
    };
  }

  const btnDismiss = $("btnDismissAllAlerts");
  if (btnDismiss) {
    btnDismiss.onclick = dismissAllAlerts;
  }

  window.addEventListener("resize", () => {
    if (lwChart) {
      const container = $("chartContainer");
      if (container) {
        const bounds = container.getBoundingClientRect();
        lwChart.applyOptions({ width: bounds.width, height: bounds.height });
      }
    } else {
      draw();
    }
  });

  // Initial load
  load();
  fetchAlerts();
  fetchInsights();
  initWebSocket();

  // Periodic polling fallback
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (!sample) {
      load();
      fetchAlerts();
      fetchInsights();
    }
  }, CFG.pollMs);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
