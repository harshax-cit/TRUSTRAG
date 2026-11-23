"""
tracerag/compare.py – Cross-document comparison and conflict analysis.

Provides:
  - Multi-document metric comparison across years/periods
  - Growth and percentage change calculations
  - Discrepancy & conflicting value detection
  - Original source citations (doc, page, bbox) for every figure
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from .textutil import normalise_period

logger = logging.getLogger(__name__)


def compare_documents(
    doc1: str,
    doc2: str,
    conn: sqlite3.Connection,
    metric_filter: Optional[str] = None,
) -> dict:
    """
    Compare metrics and facts between two documents.
    Returns:
      {
        "shared_metrics": list[dict],
        "conflicts": list[dict],
        "comparisons": list[dict]
      }
    """
    cur = conn.cursor()
    
    query = """
    SELECT id, doc, page, metric, entity, period, value, value_num, unit, bbox, raw_text
    FROM facts
    WHERE doc IN (?, ?) AND value_num IS NOT NULL
    """
    params = [doc1, doc2]
    if metric_filter:
        query += " AND (metric LIKE ? OR raw_text LIKE ?)"
        params.extend([f"%{metric_filter}%", f"%{metric_filter}%"])
        
    cur.execute(query, params)
    rows = cur.fetchall()
    cols = ["id", "doc", "page", "metric", "entity", "period", "value", "value_num", "unit", "bbox", "raw_text"]
    
    facts1 = []
    facts2 = []
    for r in rows:
        item = dict(zip(cols, r))
        if item["doc"] == doc1:
            facts1.append(item)
        else:
            facts2.append(item)

    comparisons = []
    conflicts = []

    # Map by normalized (metric, entity, period)
    map1 = {}
    for f in facts1:
        m = (f["metric"] or "").strip().lower()
        p = normalise_period(f["period"] or "")
        e = (f["entity"] or "").strip().lower()
        if m and p:
            map1.setdefault((m, p), []).append(f)

    for f2 in facts2:
        m2 = (f2["metric"] or "").strip().lower()
        p2 = normalise_period(f2["period"] or "")
        if (m2, p2) in map1:
            for f1 in map1[(m2, p2)]:
                v1 = f1["value_num"]
                v2 = f2["value_num"]
                # If values differ by more than 0.5%
                rel_diff = abs(v1 - v2) / (abs(v1) + 1e-9)
                is_conflict = rel_diff > 0.005

                diff_num = round(v2 - v1, 4)
                pct_change = round(((v2 - v1) / (v1 + 1e-9)) * 100, 2)

                entry = {
                    "metric": f1["metric"] or f2["metric"],
                    "period": p2,
                    "doc1": doc1,
                    "page1": f1["page"],
                    "value1": f1["value"],
                    "value_num1": v1,
                    "bbox1": f1["bbox"],
                    "doc2": doc2,
                    "page2": f2["page"],
                    "value2": f2["value"],
                    "value_num2": v2,
                    "bbox2": f2["bbox"],
                    "delta": diff_num,
                    "pct_change": pct_change,
                    "unit": f1["unit"] or f2["unit"],
                    "status": "conflict" if is_conflict else "verified_match",
                }

                comparisons.append(entry)
                if is_conflict:
                    conflicts.append(entry)

    # Ensure YoY Delta column is Arrow‑compatible (numeric or placeholder)
    # The function that builds the DataFrame for the UI will call this helper,
    # but we also normalise here for safety when used directly.
    def _sanitize(comparisons: list[dict]) -> list[dict]:
        for entry in comparisons:
            # If a numeric delta exists, keep it; otherwise replace with placeholder
            if entry.get("delta") is None:
                entry["delta"] = "—"
            if entry.get("pct_change") is None:
                entry["pct_change"] = "—"
        return comparisons

    # Apply sanitisation to both comparisons and conflicts
    comparisons = _sanitize(comparisons)
    conflicts = _sanitize(conflicts)

    return {
        "doc1": doc1,
        "doc2": doc2,
        "comparisons": comparisons,
        "conflicts": conflicts,
    }





def analyze_metric_trend(
    metric_keyword: str,
    conn: sqlite3.Connection,
) -> list[dict]:
    """
    Trace a metric across all indexed documents ordered by period.
    Computes YoY growth and flags any revisions.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT doc, page, metric, entity, period, value, value_num, unit, bbox
        FROM facts
        WHERE (metric LIKE ? OR raw_text LIKE ?) AND value_num IS NOT NULL AND period IS NOT NULL
        ORDER BY period ASC
        """,
        (f"%{metric_keyword}%", f"%{metric_keyword}%"),
    )
    rows = cur.fetchall()
    cols = ["doc", "page", "metric", "entity", "period", "value", "value_num", "unit", "bbox"]
    records = [dict(zip(cols, r)) for r in rows]

    trends = []
    prev_val = None
    for rec in records:
        val = rec["value_num"]
        delta = round(val - prev_val, 4) if prev_val is not None else None
        pct_change = round(((val - prev_val) / (prev_val + 1e-9)) * 100, 2) if prev_val is not None else None
        
        trends.append({
            **rec,
            "delta": delta,
            "pct_change": pct_change,
        })
        prev_val = val

    return trends
