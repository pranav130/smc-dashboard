"""
Signal Rejection Inspector & Telemetry Logger.
Implements Section 11 requirements:
- Structured recording of every rejected candidate setup across all pipeline stages.
- Transparent diagnostic telemetry for operators to understand exactly why signals were filtered out.
- Observable via API and dashboard drawer.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.config import IST_TZ, UTC_TZ


class RejectionInspector:
    """In-memory telemetry store for rejected candidate trade setups."""

    def __init__(self, max_records: int = 500):
        self.max_records = max_records
        self.records: List[Dict[str, Any]] = []

    def record_rejection(
        self,
        model: str,
        stage_failed: str,
        reasons: List[str],
        evaluated_price: float,
        setup_id: Optional[str] = None,
        direction: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """Record a structured rejection event."""
        if timestamp is None:
            timestamp = time.time()
        ts_int = int(timestamp)

        record = {
            "id": f"REJ-{ts_int}-{len(self.records) + 1}",
            "timestamp": ts_int,
            "utc_time": datetime.fromtimestamp(ts_int, tz=UTC_TZ).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ist_time": datetime.fromtimestamp(ts_int, tz=IST_TZ).strftime("%Y-%m-%d %H:%M:%S IST"),
            "model": model,
            "setup_id": setup_id or "N/A",
            "direction": direction or "neutral",
            "evaluated_price": round(evaluated_price, 2),
            "stage_failed": stage_failed,
            "reasons": reasons,
            "telemetry": telemetry or {}
        }

        self.records.append(record)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

        return record

    def get_rejections(
        self,
        limit: int = 100,
        model_filter: Optional[str] = None,
        stage_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve rejection logs with optional filtering."""
        filtered = self.records
        if model_filter:
            m_upper = model_filter.upper()
            filtered = [r for r in filtered if r["model"].upper() == m_upper]
        if stage_filter:
            s_upper = stage_filter.upper()
            filtered = [r for r in filtered if r["stage_failed"].upper() == s_upper]

        # Return latest first
        return list(reversed(filtered[-limit:]))

    def get_rejection_summary(self) -> Dict[str, Any]:
        """Aggregate frequency counts of rejection stages."""
        by_stage: Dict[str, int] = {}
        by_model: Dict[str, int] = {}

        for r in self.records:
            st = r["stage_failed"]
            m = r["model"]
            by_stage[st] = by_stage.get(st, 0) + 1
            by_model[m] = by_model.get(m, 0) + 1

        return {
            "total_rejections": len(self.records),
            "by_stage": by_stage,
            "by_model": by_model
        }


# Global singleton instance
global_rejection_inspector = RejectionInspector()
