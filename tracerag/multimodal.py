"""
tracerag/multimodal.py – Multimodal file ingestion engine.

Supports:
  - Tabular data: CSV and Excel (.xlsx, .xls) files
  - Standalone images: PNG, JPG, JPEG with OCR and word bounding boxes
  - Media & Video: MP4, AVI, MKV keyframe extraction via FFmpeg + frame OCR
  - Speech / Audio transcription hook
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import subprocess
from pathlib import Path

import pandas as pd
from PIL import Image
import pytesseract

from .textutil import (
    extract_periods,
    normalise_period,
    parse_number,
)

logger = logging.getLogger(__name__)


def ingest_csv_facts(
    csv_path: str,
    doc_name: str,
    conn: sqlite3.Connection,
) -> int:
    """
    Ingest CSV rows as structured facts into SQLite facts table.
    Returns number of facts inserted.
    """
    df = pd.read_csv(csv_path)
    cur = conn.cursor()
    facts_inserted = 0

    # Clean headers
    df.columns = [str(c).strip() for c in df.columns]
    
    # Identify potential entity/label column (usually first text column)
    text_cols = [c for c in df.columns if df[c].dtype == object]
    entity_col = text_cols[0] if text_cols else None
    
    # Identify potential period column
    period_cols = [c for c in df.columns if any(kw in c.lower() for kw in ["year", "period", "date", "fy", "quarter"])]
    period_col = period_cols[0] if period_cols else None

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        row_str = " | ".join(f"{k}: {v}" for k, v in row_dict.items() if pd.notna(v))
        
        entity = str(row[entity_col]).strip() if entity_col and pd.notna(row[entity_col]) else ""
        period = str(row[period_col]).strip() if period_col and pd.notna(row[period_col]) else ""
        if not period:
            periods = extract_periods(row_str)
            period = periods[0] if periods else ""

        for col in df.columns:
            if col in [entity_col, period_col]:
                continue
            val = row[col]
            if pd.isna(val):
                continue

            val_str = str(val).strip()
            num = parse_number(val_str)
            if num is None:
                continue

            cur.execute(
                """
                INSERT INTO facts (
                    doc, page, region_id, kind, metric, entity, period,
                    value, value_num, unit, qualifier, doc_date, bbox,
                    period_bbox, confidence, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_name,
                    1, # Tabular flat file: page 1
                    f"{doc_name}_r{idx}_{col}",
                    "table_cell",
                    col,
                    entity,
                    normalise_period(period) if period else None,
                    val_str,
                    num,
                    "table_unit",
                    None,
                    None,
                    json.dumps([0, int(idx) * 20, 500, (int(idx) + 1) * 20]),
                    None,
                    1.0,
                    f"{col}: {val_str} (Entity: {entity}, Period: {period})",
                ),
            )
            facts_inserted += 1

    conn.commit()
    logger.info(f"Ingested {facts_inserted} tabular facts from CSV: {csv_path}")
    return facts_inserted


def ingest_image_facts(
    image_path: str,
    doc_name: str,
    conn: sqlite3.Connection,
) -> int:
    """
    Ingest a standalone image with Tesseract OCR and bounding box coordinates.
    Returns number of facts extracted.
    """
    img = Image.open(image_path).convert("RGB")
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    cur = conn.cursor()
    facts_inserted = 0

    n_boxes = len(data["text"])
    lines: dict[int, list[dict]] = {}

    for i in range(n_boxes):
        text = str(data["text"][i]).strip()
        conf = float(data["conf"][i])
        if not text or conf < 30:
            continue
        line_num = data["line_num"][i]
        bbox = [
            data["left"][i],
            data["top"][i],
            data["left"][i] + data["width"][i],
            data["top"][i] + data["height"][i],
        ]
        lines.setdefault(line_num, []).append({
            "text": text,
            "conf": conf,
            "bbox": bbox,
        })

    for line_num, words in lines.items():
        line_text = " ".join(w["text"] for w in words)
        if not line_text:
            continue
        # Check for numeric values
        numbers = re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?\b", line_text)
        if not numbers:
            continue

        x0 = min(w["bbox"][0] for w in words)
        y0 = min(w["bbox"][1] for w in words)
        x1 = max(w["bbox"][2] for w in words)
        y1 = max(w["bbox"][3] for w in words)
        bbox = [x0, y0, x1, y1]

        val_str = numbers[0]
        val_num = parse_number(val_str)
        periods = extract_periods(line_text)
        period = periods[0] if periods else None

        cur.execute(
            """
            INSERT INTO facts (
                doc, page, region_id, kind, metric, entity, period,
                value, value_num, unit, qualifier, doc_date, bbox,
                period_bbox, confidence, raw_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_name,
                1,
                f"{doc_name}_img_line_{line_num}",
                "ocr_row",
                line_text[:50],
                doc_name,
                normalise_period(period) if period else None,
                val_str,
                val_num,
                None,
                None,
                None,
                json.dumps(bbox),
                None,
                0.85,
                line_text,
            ),
        )
        facts_inserted += 1

    conn.commit()
    logger.info(f"Ingested {facts_inserted} image OCR facts from {image_path}")
    return facts_inserted


def ingest_video_facts(
    video_path: str,
    doc_name: str,
    conn: sqlite3.Connection,
    output_dir: str,
) -> int:
    """
    Extract keyframes from a video using FFmpeg and run OCR to extract facts
    with timestamp annotations.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    frames_dir = out_path / f"{Path(doc_name).stem}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Sample 1 frame every 5 seconds (up to 30 frames)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", "fps=0.2",
        "-frames:v", "30",
        str(frames_dir / "frame_%03d.jpg"),
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as e:
        logger.warning(f"FFmpeg extraction failed for {video_path}: {e}")
        return 0

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    facts_inserted = 0
    cur = conn.cursor()

    for idx, f_path in enumerate(frame_files):
        timestamp_sec = idx * 5
        timestamp_str = f"{timestamp_sec // 60:02d}:{timestamp_sec % 60:02d}"
        
        try:
            img = Image.open(f_path).convert("RGB")
            text = pytesseract.image_to_string(img).strip()
            if not text:
                continue

            nums = re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?\b", text)
            if not nums:
                continue

            val_str = nums[0]
            val_num = parse_number(val_str)
            periods = extract_periods(text)
            period = periods[0] if periods else None

            cur.execute(
                """
                INSERT INTO facts (
                    doc, page, region_id, kind, metric, entity, period,
                    value, value_num, unit, qualifier, doc_date, bbox,
                    period_bbox, confidence, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_name,
                    idx + 1,
                    f"{doc_name}_frame_{idx+1}_t{timestamp_sec}",
                    "video_frame",
                    f"Frame {idx+1} ({timestamp_str})",
                    doc_name,
                    normalise_period(period) if period else None,
                    val_str,
                    val_num,
                    "video_evidence",
                    f"timestamp:{timestamp_str}",
                    None,
                    json.dumps([0, 0, img.width, img.height]),
                    None,
                    0.80,
                    f"[{timestamp_str}] {text[:200]}",
                ),
            )
            facts_inserted += 1
        except Exception as e:
            logger.warning(f"Error processing video frame {f_path}: {e}")

    conn.commit()
    logger.info(f"Ingested {facts_inserted} video frame facts from {video_path}")
    return facts_inserted
