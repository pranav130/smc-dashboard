"""
Institutional Level Memory & Tactical Co-Pilot Engine.

Provides:
1. Persistent Level Reliability Memory: Tracks how often each key zone (FVG, PDH, PDL, EQH, EQL)
   generates institutional reactions vs. gets blown through. Calculates an adaptive reliability
   score and letter grade (A+, A, B, C) that deepens over time.
2. Proactive Proximity & Liquidity Sweep Alerts: Alerts the trader when price is approaching (<=0.18%)
   a high-conviction POI or sweeping liquidity pools before the move takes off.
3. Tactical Co-Pilot Guidance: Computes live real-time guidance (headline, action plan, lifecycle step,
   and nearest POI metrics) for the trader's command dashboard.
"""
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.smc.activation import global_alert_store
from backend.smc.models import WatchlistAlert

DB_PATH = os.getenv("LEVEL_MEMORY_DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "data" / "level_memory.sqlite3"))
LOCK = threading.RLock()


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""
    CREATE TABLE IF NOT EXISTS smc_level_memory (
        level_key TEXT PRIMARY KEY,
        level_type TEXT NOT NULL,
        price REAL NOT NULL,
        timeframe TEXT NOT NULL,
        touches INTEGER NOT NULL DEFAULT 1,
        reactions INTEGER NOT NULL DEFAULT 0,
        sweeps INTEGER NOT NULL DEFAULT 0,
        invalidations INTEGER NOT NULL DEFAULT 0,
        reliability_score REAL NOT NULL DEFAULT 82.0,
        grade TEXT NOT NULL DEFAULT 'A',
        last_seen_ts REAL NOT NULL,
        last_interaction_ts REAL NOT NULL
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_level_memory_type ON smc_level_memory(level_type);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_level_memory_price ON smc_level_memory(price);")
    c.commit()
    return c


class LevelMemoryManager:
    """
    Manages historical zone reliability learning, proximity tracking, and tactical guidance.
    """
    def __init__(self):
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._last_alert_time: Dict[str, float] = {}
        self._alert_cooldown: float = 300.0  # 5 min cooldown per level alert
        self._load_cache()

    def _load_cache(self):
        try:
            with LOCK:
                c = _get_db()
                rows = c.execute("SELECT * FROM smc_level_memory").fetchall()
                for r in rows:
                    self._memory_cache[r["level_key"]] = dict(r)
                c.close()
        except Exception as e:
            # Fallback gracefully if database initialization encounters temporary lock
            pass

    def _make_key(self, kind: str, price: float, tf: str) -> str:
        rounded_p = round(price, 1)
        return f"{kind}_{tf}_{rounded_p}"

    def get_or_create_level(self, kind: str, price: float, tf: str, label: str) -> Dict[str, Any]:
        key = self._make_key(kind, price, tf)
        now = time.time()
        with LOCK:
            if key in self._memory_cache:
                return self._memory_cache[key]

            # Institutional default priors by level type
            default_score = 80.0
            if "4H" in tf or "1D" in tf:
                default_score = 86.0
            if any(k in kind for k in ["BSL", "SSL", "EQH", "EQL"]):
                default_score = 84.0
            if "20" in label or "80" in label:
                default_score = 88.0

            grade = "A+" if default_score >= 85 else ("A" if default_score >= 70 else "B")
            record = {
                "level_key": key,
                "level_type": kind,
                "price": price,
                "timeframe": tf,
                "touches": 1,
                "reactions": 1,
                "sweeps": 0,
                "invalidations": 0,
                "reliability_score": default_score,
                "grade": grade,
                "last_seen_ts": now,
                "last_interaction_ts": now,
            }
            self._memory_cache[key] = record

            try:
                c = _get_db()
                c.execute("""
                INSERT OR IGNORE INTO smc_level_memory
                (level_key, level_type, price, timeframe, touches, reactions, sweeps, invalidations, reliability_score, grade, last_seen_ts, last_interaction_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    key, kind, price, tf, 1, 1, 0, 0, default_score, grade, now, now
                ))
                c.commit()
                c.close()
            except Exception:
                pass

            return record

    def record_interaction(self, kind: str, price: float, tf: str, interaction_type: str):
        """
        Record a bounce, sweep, or invalidation to update zone reliability score.
        """
        key = self._make_key(kind, price, tf)
        now = time.time()
        with LOCK:
            rec = self.get_or_create_level(kind, price, tf, kind)
            touches = rec.get("touches", 1) + 1
            reactions = rec.get("reactions", 1)
            sweeps = rec.get("sweeps", 0)
            invalidations = rec.get("invalidations", 0)

            if interaction_type == "bounce":
                reactions += 1
            elif interaction_type == "sweep":
                sweeps += 1
                reactions += 1
            elif interaction_type == "invalidation":
                invalidations += 1

            # Bayesian weighted formula: gives high confidence to repeated reactions
            # while decaying levels that get sliced through repeatedly
            numerator = (reactions * 1.6) + (sweeps * 2.2) + 8.0
            denominator = touches + (invalidations * 2.0) + 10.0
            score = round(min(98.0, max(35.0, (numerator / denominator) * 100.0)), 1)

            if score >= 85:
                grade = "A+"
            elif score >= 72:
                grade = "A"
            elif score >= 55:
                grade = "B"
            else:
                grade = "C"

            rec["touches"] = touches
            rec["reactions"] = reactions
            rec["sweeps"] = sweeps
            rec["invalidations"] = invalidations
            rec["reliability_score"] = score
            rec["grade"] = grade
            rec["last_interaction_ts"] = now
            self._memory_cache[key] = rec

            try:
                c = _get_db()
                c.execute("""
                UPDATE smc_level_memory
                SET touches = ?, reactions = ?, sweeps = ?, invalidations = ?, reliability_score = ?, grade = ?, last_interaction_ts = ?
                WHERE level_key = ?
                """, (touches, reactions, sweeps, invalidations, score, grade, now, key))
                c.commit()
                c.close()
            except Exception:
                pass

    def evaluate_and_annotate_levels(
        self,
        current_price: float,
        levels: List[Dict[str, Any]],
        candles: Optional[List[Any]] = None,
        is_stale: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Annotates all levels with adaptive institutional grade and reliability score.
        Generates proactive proximity and liquidity sweep alerts.
        """
        if current_price <= 0:
            return levels

        now = time.time()
        annotated = []

        for lvl in levels:
            p = lvl.get("price", 0.0)
            if p <= 0:
                annotated.append(lvl)
                continue

            kind = lvl.get("kind", "POI")
            tf = lvl.get("tf", "1H")
            label = lvl.get("label", kind)
            mem = self.get_or_create_level(kind, p, tf, label)

            score = mem.get("reliability_score", 82.0)
            grade = mem.get("grade", "A")

            # Determine stars
            stars = "⭐⭐⭐" if grade == "A+" else ("⭐⭐" if grade == "A" else "⭐")

            dist = round(abs(p - current_price), 2)
            dist_pct = round((dist / current_price) * 100.0, 2)

            enhanced = dict(lvl)
            enhanced["grade"] = grade
            enhanced["reliability_score"] = score
            enhanced["stars"] = stars
            enhanced["distance"] = dist
            enhanced["distance_pct"] = dist_pct
            annotated.append(enhanced)

            # Proactive Alert Evaluation (Only if data feed is live and healthy)
            if not is_stale and dist_pct <= 0.18:
                alert_key = f"prox_{mem['level_key']}"
                last_alert = self._last_alert_time.get(alert_key, 0.0)
                if (now - last_alert) >= self._alert_cooldown:
                    self._last_alert_time[alert_key] = now
                    is_above = p > current_price
                    direction_txt = "overhead" if is_above else "underneath"
                    alert_title = f"Approaching {grade} {kind} ({tf})"
                    alert_msg = f"Price is ${dist:.2f} ({dist_pct:.2f}%) away from {label} at ${p:.2f} ({direction_txt}). Prepare for reaction."
                    
                    alert = WatchlistAlert(
                        id=f"alt_prox_{int(now)}_{int(p)}",
                        level_id=mem["level_key"],
                        level_name=label,
                        timeframe=tf,
                        state="APPROACHING",
                        message=f"[PROXIMITY] {alert_title} — {alert_msg}",
                        evidence=[f"Proximity distance: ${dist:.2f} ({dist_pct:.2f}%)", f"Zone Grade: {grade} ({score}%)"],
                        timestamp=int(now),
                        ist_time=time.strftime("%I:%M:%S %p IST", time.localtime(now)),
                        acknowledged=False,
                        is_stale_suppressed=False
                    )
                    global_alert_store._alerts[alert.id] = alert

        return annotated

    def generate_tactical_guidance(
        self,
        current_price: float,
        annotated_levels: List[Dict[str, Any]],
        bias_map: Dict[str, str],
        state: str,
        setup: Dict[str, Any],
        checklist: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Synthesizes market structure, HTF bias, nearest POIs, and setup lifecycle into
        actionable tactical advice.
        """
        if current_price <= 0 or not annotated_levels:
            return {
                "headline": "Awaiting Live Market Feed...",
                "action_plan": "Connecting to Delta Exchange feed to establish liquidity boundaries.",
                "lifecycle_step": "Step 0: Initializing",
                "nearest_poi": None,
                "market_phase": "Connecting",
                "grade": "B",
                "confidence_score": 75
            }

        # Find closest level above and below
        above = [lvl for lvl in annotated_levels if lvl.get("price", 0) > current_price]
        below = [lvl for lvl in annotated_levels if lvl.get("price", 0) < current_price]

        above.sort(key=lambda x: x.get("price", 0))
        below.sort(key=lambda x: x.get("price", 0), reverse=True)

        nearest_above = above[0] if above else None
        nearest_below = below[0] if below else None

        # Determine absolute nearest POI
        nearest_poi = None
        if nearest_above and nearest_below:
            dist_above = nearest_above["price"] - current_price
            dist_below = current_price - nearest_below["price"]
            nearest_poi = nearest_above if dist_above <= dist_below else nearest_below
        elif nearest_above:
            nearest_poi = nearest_above
        elif nearest_below:
            nearest_poi = nearest_below

        # Multi-timeframe bias summary
        d_bias = bias_map.get("1d", "Neutral")
        h4_bias = bias_map.get("4h", "Neutral")
        h1_bias = bias_map.get("1h", "Neutral")

        is_macro_aligned = (d_bias == h4_bias) and d_bias != "Neutral"
        primary_bias = d_bias if is_macro_aligned else (h4_bias if h4_bias != "Neutral" else h1_bias)

        # Tactical narrative construction
        poi_label = nearest_poi.get("label", "Key POI") if nearest_poi else "Key Level"
        poi_price = nearest_poi.get("price", current_price) if nearest_poi else current_price
        poi_dist = nearest_poi.get("distance", 0.0) if nearest_poi else 0.0
        poi_dist_pct = nearest_poi.get("distance_pct", 0.0) if nearest_poi else 0.0
        poi_grade = nearest_poi.get("grade", "A") if nearest_poi else "A"
        poi_tf = nearest_poi.get("tf", "1H") if nearest_poi else "1H"
        is_overhead = (nearest_poi.get("price", 0) > current_price) if nearest_poi else False

        passed_checks = sum(1 for c in checklist if c.get("met"))
        total_checks = max(1, len(checklist))

        if state in ["ACTIVE", "EXTREME"] and passed_checks >= 4:
            direction_str = str(setup.get("direction") or "Trend").upper()
            headline = f"🚀 HIGH-CONFLUENCE {direction_str} SETUP ACTIVE ({passed_checks}/{total_checks} Checklist Passed)"
            action_plan = f"Key confluence confirmed with R:R >= 2:1. Invalidation at ${setup.get('stop') or 0:.2f}. Consider simulated execution."
            lifecycle_step = "Step 3/3: Execution & Target Management"
            market_phase = "High-Confluence Order Flow"
        elif poi_dist_pct <= 0.20:
            headline = f"🎯 APPROACHING {poi_grade} {poi_label} (${poi_price:.2f}) · {poi_dist_pct:.2f}% Away"
            if is_overhead:
                action_plan = f"Price is reaching overhead liquidity at ${poi_price:.2f}. Look for sweep wick + 5M/10M rejection before considering short, or strong displacement close above for continuation."
            else:
                action_plan = f"Price is entering support zone at ${poi_price:.2f}. Look for sweep of equal lows + 5M/10M CHoCH displacement before considering long entry."
            lifecycle_step = "Step 1/3: Key Level Proximity & Attention"
            market_phase = "Zone Proximity Reaction"
        elif passed_checks >= 3:
            headline = f"⚡ SETUP DEVELOPING: {passed_checks}/{total_checks} Confluence Conditions Met"
            action_plan = f"Market is aligning with {primary_bias} HTF bias. Awaiting final displacement and POI retracement."
            lifecycle_step = "Step 2/3: Structural Break & Retracement"
            market_phase = "Structural Alignment"
        else:
            headline = f"⚖️ CONSOLIDATION EQUILIBRIUM: HTF Bias is {primary_bias}"
            action_plan = f"Nearest resistance: ${nearest_above['price']:.2f} (+${nearest_above['distance']:.2f}) · Nearest support: ${nearest_below['price']:.2f} (-${nearest_below['distance']:.2f}). Avoid mid-range chop; wait for boundary sweep." if nearest_above and nearest_below else "Monitor price action near session boundaries."
            lifecycle_step = "Step 1/3: Surveillance & Boundary Mapping"
            market_phase = "Range Equilibrium"

        return {
            "headline": headline,
            "action_plan": action_plan,
            "lifecycle_step": lifecycle_step,
            "market_phase": market_phase,
            "grade": poi_grade,
            "confidence_score": nearest_poi.get("reliability_score", 82.0) if nearest_poi else 80.0,
            "nearest_poi": nearest_poi,
            "nearest_above": nearest_above,
            "nearest_below": nearest_below,
            "bias_summary": f"1D: {d_bias} · 4H: {h4_bias} · 1H: {h1_bias}",
            "passed_checks": passed_checks,
            "total_checks": total_checks
        }


# Global instance
global_level_memory = LevelMemoryManager()
