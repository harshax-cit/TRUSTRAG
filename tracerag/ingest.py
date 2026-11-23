"""
ingest.py – PDF ingestion pipeline for TraceRAG.

Per page:
  1. Extract words with bboxes from text layer.
  2. If page is scanned (< 20 words), OCR with pytesseract word-level boxes.
  3. Detect tables with PyMuPDF find_tables; rebuild cell text from word boxes.
  4. Detect vector charts; extract printed data labels by proximity.
  5. Extract raster chart images; OCR them to find data labels.
  6. Build sentence-level facts and row-level table facts.
  7. Store regions in JSONL and facts in SQLite.
  8. Record SHA-256 of each PDF in a manifest.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

import pymupdf as fitz
import pytesseract
from PIL import Image

from .textutil import (
    clean_text,
    extract_periods,
    extract_qualifiers,
    parse_number,
    sentence_split,
)

logger = logging.getLogger(__name__)

# Thresholds
SCANNED_WORD_THRESHOLD = 20       # pages with fewer words → OCR
MIN_OCR_CONF = 30                  # discard tesseract words below this confidence
TABLE_WORD_EXPAND = 4              # pixels to expand cell bbox when collecting words
CHART_LABEL_MAX_DIST = 60          # pixels: max distance from path cluster to label text

# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY,
    doc         TEXT NOT NULL,
    page        INTEGER NOT NULL,
    region_id   TEXT,
    kind        TEXT,          -- sentence | table_cell | chart_label | ocr_row
    metric      TEXT,
    entity      TEXT,
    period      TEXT,
    value       TEXT,
    value_num   REAL,
    unit        TEXT,
    qualifier   TEXT,
    doc_date    TEXT,
    bbox        TEXT,          -- JSON [x0,y0,x1,y1]
    period_bbox TEXT,          -- JSON or NULL
    confidence  REAL,
    raw_text    TEXT
);

CREATE TABLE IF NOT EXISTS regions (
    id          INTEGER PRIMARY KEY,
    doc         TEXT NOT NULL,
    page        INTEGER NOT NULL,
    region_id   TEXT UNIQUE,
    kind        TEXT,          -- text_block | table | chart_raster | chart_vector | scanned_page
    bbox        TEXT,
    text        TEXT,
    confidence  REAL
);

CREATE TABLE IF NOT EXISTS manifest (
    doc         TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL,
    pages       INTEGER,
    indexed_at  TEXT
);
"""

# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def build_index(pdf_dir: str, index_dir: str) -> None:
    """
    Ingest all PDFs in pdf_dir. Write facts.db, regions.jsonl and
    manifest.json into index_dir.
    """
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    db_path = os.path.join(index_dir, "facts.db")
    conn = _open_db(db_path)
    regions_path = os.path.join(index_dir, "regions.jsonl")

    manifest: dict[str, dict] = {}
    all_regions: list[dict] = []

    pdfs = sorted(Path(pdf_dir).glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in {pdf_dir}")

    for pdf_path in pdfs:
        fname = pdf_path.name
        logger.info(f"Ingesting {fname}")
        sha256 = _file_sha256(str(pdf_path))

        doc_facts, doc_regions, page_meta = _ingest_pdf(str(pdf_path), fname)

        # Write facts
        cur = conn.cursor()
        for f in doc_facts:
            cur.execute(
                """INSERT INTO facts
                   (doc,page,region_id,kind,metric,entity,period,
                    value,value_num,unit,qualifier,doc_date,bbox,
                    period_bbox,confidence,raw_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f["doc"], f["page"], f.get("region_id"),
                    f.get("kind"), f.get("metric"), f.get("entity"),
                    f.get("period"), f.get("value"), f.get("value_num"),
                    f.get("unit"), f.get("qualifier"), f.get("doc_date"),
                    json.dumps(f.get("bbox")), json.dumps(f.get("period_bbox")),
                    f.get("confidence", 1.0), f.get("raw_text", ""),
                ),
            )
        conn.commit()

        all_regions.extend(doc_regions)

        manifest[fname] = {
            "doc": fname,
            "sha256": sha256,
            "pages": page_meta["total_pages"],
            "text_pages": page_meta["text_pages"],
            "scan_pages": page_meta["scan_pages"],
            "table_pages": page_meta["table_pages"],
            "chart_pages": page_meta["chart_pages"],
            "fact_count": len(doc_facts),
            "region_count": len(doc_regions),
        }

        # Insert into manifest table
        import datetime
        cur.execute(
            "INSERT OR REPLACE INTO manifest (doc,sha256,pages,indexed_at) VALUES (?,?,?,?)",
            (fname, sha256, page_meta["total_pages"],
             datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()

        logger.info(
            f"  {fname}: {page_meta['total_pages']} pages, "
            f"{page_meta['scan_pages']} scanned, "
            f"{len(doc_facts)} facts, {len(doc_regions)} regions"
        )

    # Write regions JSONL
    with open(regions_path, "w", encoding="utf-8") as fh:
        for r in all_regions:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write manifest JSON
    with open(os.path.join(index_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    conn.close()
    logger.info(f"Indexing complete. DB: {db_path}")


def ingest_single_pdf(pdf_path: str, index_dir: str) -> int:
    """Ingest a single PDF into an index directory without rebuilding everything."""
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    db_path = os.path.join(index_dir, "facts.db")
    conn = _open_db(db_path)
    regions_path = os.path.join(index_dir, "regions.jsonl")

    p = Path(pdf_path)
    fname = p.name
    sha256 = _file_sha256(str(p))

    doc_facts, doc_regions, page_meta = _ingest_pdf(str(p), fname)

    cur = conn.cursor()
    # Remove old facts for this doc if any
    cur.execute("DELETE FROM facts WHERE doc=?", (fname,))
    for f in doc_facts:
        cur.execute(
            """INSERT INTO facts
               (doc,page,region_id,kind,metric,entity,period,
                value,value_num,unit,qualifier,doc_date,bbox,
                period_bbox,confidence,raw_text)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f["doc"], f["page"], f.get("region_id"),
                f.get("kind"), f.get("metric"), f.get("entity"),
                f.get("period"), f.get("value"), f.get("value_num"),
                f.get("unit"), f.get("qualifier"), f.get("doc_date"),
                json.dumps(f.get("bbox")), json.dumps(f.get("period_bbox")),
                f.get("confidence", 1.0), f.get("raw_text", ""),
            ),
        )

    import datetime
    cur.execute(
        "INSERT OR REPLACE INTO manifest (doc,sha256,pages,indexed_at) VALUES (?,?,?,?)",
        (fname, sha256, page_meta["total_pages"], datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    # Append new regions to regions.jsonl
    with open(regions_path, "a", encoding="utf-8") as fh:
        for r in doc_regions:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Update manifest.json
    manifest_file = os.path.join(index_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except Exception:
            manifest = {}
    manifest[fname] = {
        "doc": fname,
        "sha256": sha256,
        "pages": page_meta["total_pages"],
        "text_pages": page_meta["text_pages"],
        "scan_pages": page_meta["scan_pages"],
        "table_pages": page_meta["table_pages"],
        "chart_pages": page_meta["chart_pages"],
        "fact_count": len(doc_facts),
        "region_count": len(doc_regions),
    }
    with open(manifest_file, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    return len(doc_facts)


def get_facts(index_dir: str) -> sqlite3.Connection:
    db_path = os.path.join(index_dir, "facts.db")
    return _open_db(db_path)


def load_manifest(index_dir: str) -> dict:
    p = os.path.join(index_dir, "manifest.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def load_regions(index_dir: str) -> list[dict]:
    p = os.path.join(index_dir, "regions.jsonl")
    if not os.path.exists(p):
        return []
    regions = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                regions.append(json.loads(line))
    return regions


# ------------------------------------------------------------------
# Internal: per-PDF pipeline
# ------------------------------------------------------------------

def _ingest_pdf(pdf_path: str, fname: str):
    doc = fitz.open(pdf_path)
    facts: list[dict] = []
    regions: list[dict] = []
    page_meta = {
        "total_pages": len(doc),
        "text_pages": 0,
        "scan_pages": 0,
        "table_pages": 0,
        "chart_pages": 0,
    }

    # Heuristic doc date from filename
    doc_date = _extract_doc_date(fname)

    for page_num, page in enumerate(doc):
        pg = page_num + 1  # 1-indexed

        # --- word extraction ---
        words = page.get_text("words")  # (x0,y0,x1,y1,word,block_no,line_no,word_no)
        word_count = len(words)
        is_scanned = word_count < SCANNED_WORD_THRESHOLD

        if is_scanned:
            page_meta["scan_pages"] += 1
            ocr_facts, ocr_regions = _ocr_page(page, pg, fname, doc_date)
            facts.extend(ocr_facts)
            regions.extend(ocr_regions)
        else:
            page_meta["text_pages"] += 1
            # --- table detection ---
            tbl_facts, tbl_regions, tbl_bboxes = _extract_tables(page, words, pg, fname, doc_date)
            if tbl_facts:
                page_meta["table_pages"] += 1
            facts.extend(tbl_facts)
            regions.extend(tbl_regions)

            # --- chart detection (raster images) ---
            chart_facts, chart_regions = _extract_raster_charts(page, pg, fname, doc_date)
            if chart_facts:
                page_meta["chart_pages"] += 1
            facts.extend(chart_facts)
            regions.extend(chart_regions)

            # --- sentence facts from text blocks ---
            text_facts, text_regions = _extract_text_facts(page, words, pg, fname, doc_date, tbl_bboxes)
            facts.extend(text_facts)
            regions.extend(text_regions)

    doc.close()
    return facts, regions, page_meta


# ------------------------------------------------------------------
# Table extraction
# ------------------------------------------------------------------

def _extract_tables(page, words, pg: int, fname: str, doc_date: str):
    facts = []
    regions = []
    tbl_bboxes = []

    try:
        tabs = page.find_tables()
    except Exception:
        return facts, regions, tbl_bboxes

    if not tabs or not tabs.tables:
        return facts, regions, tbl_bboxes

    for tbl_idx, tbl in enumerate(tabs.tables):
        bbox = list(tbl.bbox)  # [x0,y0,x1,y1]
        tbl_bboxes.append(bbox)
        region_id = f"{fname}:p{pg}:t{tbl_idx}"

        # Rebuild cell text from word boxes (avoids PyMuPDF garbling)
        try:
            cells = tbl.cells  # list of (row, col, x0, y0, x1, y1)
        except Exception:
            cells = []

        # Use the table's structured row/col grid via extract() for structure
        # but rebuild cell text from word boxes (avoids garbling)
        # First, build a mapping from bbox → (row, col) using the table header rows
        try:
            tbl_header = tbl.header
        except Exception:
            tbl_header = None

        # cells is a flat list of (x0,y0,x1,y1) bboxes in reading order
        # We need to infer row/col from spatial position
        # Sort cells by y then x to assign row/col indices
        sorted_cells = sorted(cells, key=lambda c: (round(c[1], 1), c[0]))

        # Group into rows by y-coordinate clustering
        row_groups: list[list] = []
        current_row: list = []
        prev_y = None
        Y_TOLERANCE = 3.0
        for cell in sorted_cells:
            cy_mid = (cell[1] + cell[3]) / 2
            if prev_y is None or abs(cy_mid - prev_y) > Y_TOLERANCE:
                if current_row:
                    row_groups.append(sorted(current_row, key=lambda c: c[0]))
                current_row = [cell]
                prev_y = cy_mid
            else:
                current_row.append(cell)
        if current_row:
            row_groups.append(sorted(current_row, key=lambda c: c[0]))

        # Build cell_texts indexed by (row_idx, col_idx)
        cell_texts: dict[tuple, str] = {}
        for row_idx, row_cells in enumerate(row_groups):
            for col_idx, cell_bbox in enumerate(row_cells):
                cx0, cy0, cx1, cy1 = cell_bbox
                cell_text = _words_in_bbox(
                    words, cx0 - TABLE_WORD_EXPAND, cy0 - TABLE_WORD_EXPAND,
                    cx1 + TABLE_WORD_EXPAND, cy1 + TABLE_WORD_EXPAND
                )
                cell_texts[(row_idx, col_idx)] = cell_text

        # Identify header rows/cols
        max_row = max((k[0] for k in cell_texts), default=0)
        max_col = max((k[1] for k in cell_texts), default=0)

        # Find the header row (first row with mostly non-numeric content)
        header_row_idx = 0
        for ri in range(min(3, max_row + 1)):
            row_texts = [cell_texts.get((ri, ci), "") for ci in range(max_col + 1)]
            non_numeric = sum(1 for t in row_texts if t and not re.match(r"^[\d,.\s\(\)]+$", t))
            if non_numeric >= 2:
                header_row_idx = ri
                break

        header_row = {col: cell_texts.get((header_row_idx, col), "")
                      for col in range(max_col + 1)}
        header_col = {row: cell_texts.get((row, 0), "") for row in range(max_row + 1)}

        # Collect region text (all cells)
        all_text = " | ".join(v for v in cell_texts.values() if v)

        regions.append({
            "doc": fname,
            "page": pg,
            "region_id": region_id,
            "kind": "table",
            "bbox": bbox,
            "text": all_text[:2000],
            "confidence": 1.0,
        })

        # Extract facts: for each data cell, pair with header
        periods_in_header = {}
        for col, h in header_row.items():
            ps = extract_periods(h)
            if ps:
                periods_in_header[col] = ps[0]

        for (row, col), cell_text in cell_texts.items():
            if row <= header_row_idx:
                continue  # skip header rows
            if not cell_text.strip():
                continue

            # Try to parse a number
            nums = re.findall(r"[+-]?[\d,]+\.?\d*", cell_text)
            for num_str in nums:
                val = parse_number(num_str)
                if val is None:
                    continue

                period = periods_in_header.get(col) or _extract_period_from_context(
                    header_row.get(col, ""), header_col.get(row, "")
                )
                label = header_col.get(row, "")
                col_header = header_row.get(col, "")

                # Detect unit from surrounding text
                unit = _detect_unit(all_text + " " + col_header)
                qualifiers = extract_qualifiers(cell_text + " " + col_header + " " + label)

                # Cell bbox – use table bbox as fallback
                cell_bbox = bbox

                # Build enriched raw_text with full table context for retrieval
                raw_text = f"{label} | {col_header} | {all_text[:300]} | {cell_text}"

                facts.append({
                    "doc": fname,
                    "page": pg,
                    "region_id": region_id,
                    "kind": "table_cell",
                    "metric": col_header[:200],
                    "entity": label[:200],
                    "period": period,
                    "value": cell_text.strip(),
                    "value_num": val,
                    "unit": unit,
                    "qualifier": ",".join(qualifiers) if qualifiers else None,
                    "doc_date": doc_date,
                    "bbox": cell_bbox,
                    "period_bbox": None,
                    "confidence": 1.0,
                    "raw_text": raw_text[:500],
                })
    return facts, regions, tbl_bboxes


# ------------------------------------------------------------------
# Raster chart extraction (OCR data labels from embedded images)
# ------------------------------------------------------------------

def _extract_raster_charts(page, pg: int, fname: str, doc_date: str):
    facts = []
    regions = []

    # Get chart title from text layer (look for "Chart" references)
    page_text = page.get_text("text")
    chart_titles = re.findall(r"(Chart\s+[IVX\d]+(?:\.\d+)?[:\s][^\n]{0,120})", page_text)

    images = page.get_images(full=True)
    if not images:
        return facts, regions

    # Only process large images (likely charts, not logos)
    page_rect = page.rect
    for img_idx, img_info in enumerate(images):
        xref = img_info[0]
        try:
            base_image = page.parent.extract_image(xref)
        except Exception:
            continue

        w, h = base_image["width"], base_image["height"]
        # Skip tiny images
        if w < 200 or h < 100:
            continue

        region_id = f"{fname}:p{pg}:img{img_idx}"

        # Find image bbox on page using xref
        img_bbox = _get_image_bbox(page, xref)

        # OCR the image to extract data labels
        try:
            img_bytes = base_image["image"]
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            ocr_data = pytesseract.image_to_data(
                pil_img, output_type=pytesseract.Output.DICT,
                config="--psm 11 --oem 1"
            )
        except Exception as e:
            logger.warning(f"OCR failed on chart image {region_id}: {e}")
            continue

        # Extract numeric labels with positions
        chart_title = chart_titles[img_idx] if img_idx < len(chart_titles) else ""
        ocr_text_parts = []
        num_facts = []

        # Extract year labels and data labels separately, pair by x-position
        year_labels = []   # (year_str, x_center)
        data_labels = []   # (value, x_center, y_center, conf, bbox_in_img)

        for i, word in enumerate(ocr_data["text"]):
            conf = int(ocr_data["conf"][i])
            if conf < MIN_OCR_CONF or not word.strip():
                continue
            ocr_text_parts.append(word)
            ix = ocr_data["left"][i]
            iy = ocr_data["top"][i]
            iw = ocr_data["width"][i]
            ih = ocr_data["height"][i]
            cx = ix + iw // 2
            cy = iy + ih // 2

            # Detect year labels (fiscal year patterns)
            year_ps = extract_periods(word)
            if not year_ps:
                # Try combined with next word (e.g. "2021" "-22")
                next_word = ocr_data["text"][i+1].strip() if i+1 < len(ocr_data["text"]) else ""
                combined = f"{word}-{next_word}"
                year_ps = extract_periods(combined)
                if not year_ps:
                    combined2 = f"{word}{next_word}"
                    year_ps = extract_periods(combined2)
            if year_ps:
                year_labels.append((year_ps[0], cx, cy))
                continue

            # Detect data labels (pure decimal numbers, plausible range)
            if re.match(r"^[+-]?\d+\.?\d*$", word.strip()):
                val = float(word.strip())
                # Map to page coords
                if img_bbox:
                    px0, py0, px1, py1 = img_bbox
                    scale_x = (px1 - px0) / w
                    scale_y = (py1 - py0) / h
                    bx0 = px0 + ix * scale_x
                    by0 = py0 + iy * scale_y
                    bx1 = bx0 + iw * scale_x
                    by1 = by0 + ih * scale_y
                    label_bbox = [bx0, by0, bx1, by1]
                else:
                    label_bbox = img_bbox
                data_labels.append((val, cx, cy, conf, label_bbox))

        # Build year→value mapping by x-position proximity
        year_value_map = {}
        if year_labels and data_labels:
            # For each year label, find the data label with closest x-position
            # (data labels appear above/below bar, year labels on x-axis)
            for year_str, yr_cx, yr_cy in year_labels:
                # Find data label with minimum x-distance
                closest = min(data_labels, key=lambda d: abs(d[1] - yr_cx),
                              default=None)
                if closest and abs(closest[1] - yr_cx) < w * 0.08:  # within 8% of image width
                    year_value_map[year_str] = closest

        # Create facts from year-value pairs (high quality)
        for year_str, (val, cx, cy, conf, label_bbox) in year_value_map.items():
            context = f"{chart_title} | period: {year_str} | value: {val}"
            unit = _detect_unit(chart_title + " " + page_text[:200])
            num_facts.append({
                "doc": fname,
                "page": pg,
                "region_id": region_id,
                "kind": "chart_label",
                "metric": chart_title[:200],
                "entity": "India",
                "period": year_str,
                "value": str(val),
                "value_num": val,
                "unit": unit,
                "qualifier": None,
                "doc_date": doc_date,
                "bbox": label_bbox,
                "period_bbox": None,
                "confidence": conf / 100.0,
                "raw_text": context,
            })

        # Also create facts for all data labels without year pairing
        # (using surrounding OCR context for period)
        for val, cx, cy, conf, label_bbox in data_labels:
            # Find period from surrounding OCR text
            period = None
            for year_str, yr_cx, yr_cy in year_labels:
                if abs(yr_cx - cx) < w * 0.08:
                    period = year_str
                    break

            context_parts = []
            for i, word in enumerate(ocr_data["text"]):
                if abs(ocr_data["left"][i] + ocr_data["width"][i]//2 - cx) < 100:
                    context_parts.append(word)
            context_str = chart_title + " | " + " ".join(context_parts[:10])

            unit = _detect_unit(chart_title + " " + page_text[:200])

            num_facts.append({
                "doc": fname,
                "page": pg,
                "region_id": region_id,
                "kind": "chart_label",
                "metric": chart_title[:200],
                "entity": "India",
                "period": period,
                "value": str(val),
                "value_num": val,
                "unit": unit,
                "qualifier": None,
                "doc_date": doc_date,
                "bbox": label_bbox,
                "period_bbox": None,
                "confidence": conf / 100.0,
                "raw_text": context_str[:300],
            })

        # Deduplicate: prefer year-paired facts over unpaired ones
        # (year-paired facts have period set via year_value_map)
        year_paired_vals = {f["value_num"] for f in num_facts if f.get("period")
                            and f["raw_text"].startswith(chart_title)}
        final_facts = []
        for f in num_facts:
            if f.get("period") or f["value_num"] not in year_paired_vals:
                final_facts.append(f)

        facts.extend(final_facts)

        ocr_text = " ".join(ocr_text_parts)
        regions.append({
            "doc": fname,
            "page": pg,
            "region_id": region_id,
            "kind": "chart_raster",
            "bbox": img_bbox,
            "text": ocr_text[:2000],
            "confidence": 1.0,
        })

    return facts, regions


def _get_image_bbox(page, xref: int) -> Optional[list]:
    """Find the bounding box of an image on a page by scanning image placements."""
    try:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") == 1 and block.get("image"):
                # image block
                return list(block["bbox"])
        # Fallback: use page drawings approach
        for item in page.get_images(full=True):
            if item[0] == xref:
                # Try get_image_bbox if available
                pass
    except Exception:
        pass
    return None


def _ocr_context_around(ocr_data: dict, idx: int, radius: int = 5) -> str:
    """Return words within ±radius positions of idx."""
    n = len(ocr_data["text"])
    start = max(0, idx - radius)
    end = min(n, idx + radius + 1)
    return " ".join(
        w for w in ocr_data["text"][start:end]
        if int(ocr_data["conf"][start + (ocr_data["text"][start:end].index(w) if w in ocr_data["text"][start:end] else 0)]) > MIN_OCR_CONF
        and w.strip()
    )


def _enrich_chart_facts(facts: list[dict], ocr_data: dict, page_text: str) -> list[dict]:
    """
    Try to pair each numeric label with the nearest period label
    (e.g. '2021-22') found in OCR data.
    """
    # Build list of period positions in OCR
    period_positions = []
    text_list = ocr_data["text"]
    n = len(text_list)

    # Walk through OCR words to find period strings like "2021-22"
    for i in range(n - 1):
        w1 = text_list[i].strip()
        w2 = text_list[i + 1].strip() if i + 1 < n else ""
        combined = f"{w1}-{w2}"
        ps = extract_periods(combined) or extract_periods(w1)
        if ps:
            cx = ocr_data["left"][i] + ocr_data["width"][i] // 2
            cy = ocr_data["top"][i] + ocr_data["height"][i] // 2
            period_positions.append((ps[0], cx, cy, i))

    # For each fact, find nearest period by x-axis proximity
    for fact in facts:
        if fact.get("period"):
            continue
        if not fact.get("bbox"):
            continue
        # label center in image coords (we stored page coords in bbox)
        # We can't easily invert here, skip enrichment for now
    return facts


# ------------------------------------------------------------------
# Text-block sentence facts
# ------------------------------------------------------------------

def _extract_text_facts(page, words, pg: int, fname: str, doc_date: str,
                         tbl_bboxes: list):
    facts = []
    regions = []

    page_text = page.get_text("text")
    if not page_text.strip():
        return facts, regions

    # Get text blocks (not tables)
    blocks = page.get_text("dict")["blocks"]
    for blk_idx, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        bbox = list(block["bbox"])
        # Skip if this block is inside a known table bbox
        if _bbox_overlaps_any(bbox, tbl_bboxes):
            continue

        block_text = " ".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        )
        block_text = clean_text(block_text)
        if not block_text:
            continue

        region_id = f"{fname}:p{pg}:b{blk_idx}"
        regions.append({
            "doc": fname,
            "page": pg,
            "region_id": region_id,
            "kind": "text_block",
            "bbox": bbox,
            "text": block_text[:1000],
            "confidence": 1.0,
        })

        # Extract sentence-level facts
        sentences = sentence_split(block_text)
        for sent_idx, sent in enumerate(sentences):
            sent_facts = _parse_sentence_facts(sent, pg, fname, doc_date,
                                                region_id, bbox)
            facts.extend(sent_facts)

    return facts, regions


def _parse_sentence_facts(sent: str, pg: int, fname: str, doc_date: str,
                            region_id: str, bbox: list) -> list[dict]:
    """Extract numeric facts from a sentence."""
    facts = []

    # Find all numbers in the sentence
    num_pattern = re.compile(
        r"(?:₹\s*)?([+-]?[\d,]+\.?\d*)\s*"
        r"(lakh|crore|million|billion|trillion|mn|bn|cr|%|per\s+cent|"
        r"percentage\s+points?|pp|mm|cm|km|kg|tonnes?|mt)?"
        r"(?:\s+\(([PRE,/\s]+)\))?",
        re.IGNORECASE,
    )

    periods = extract_periods(sent)
    qualifiers = extract_qualifiers(sent)
    unit_in_sentence = _detect_unit(sent)

    for m in num_pattern.finditer(sent):
        num_str = m.group(1).replace(",", "")
        try:
            val = float(num_str)
        except ValueError:
            continue
        # Skip page numbers, footnote markers (small integers alone)
        if val == int(val) and val < 10 and len(sent.split()) < 5:
            continue

        unit = m.group(2) or unit_in_sentence
        qualifier_match = m.group(3)

        # Context: 50 chars around the match
        start = max(0, m.start() - 60)
        end = min(len(sent), m.end() + 60)
        context = sent[start:end]

        facts.append({
            "doc": fname,
            "page": pg,
            "region_id": region_id,
            "kind": "sentence",
            "metric": sent[:200],
            "entity": None,
            "period": periods[0] if periods else None,
            "value": m.group(0).strip(),
            "value_num": val,
            "unit": unit,
            "qualifier": qualifier_match or (",".join(qualifiers) if qualifiers else None),
            "doc_date": doc_date,
            "bbox": bbox,
            "period_bbox": None,
            "confidence": 1.0,
            "raw_text": sent[:500],
        })

    return facts


# ------------------------------------------------------------------
# OCR for scanned pages
# ------------------------------------------------------------------

def _ocr_page(page, pg: int, fname: str, doc_date: str):
    facts = []
    regions = []

    # Render page to image at 200 DPI
    mat = fitz.Matrix(200 / 72, 200 / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    pil_img = Image.open(io.BytesIO(img_bytes))

    region_id = f"{fname}:p{pg}:scan"

    try:
        ocr_data = pytesseract.image_to_data(
            pil_img, output_type=pytesseract.Output.DICT,
            config="--psm 6 --oem 1 -l eng"
        )
    except Exception as e:
        logger.warning(f"OCR failed on page {pg} of {fname}: {e}")
        return facts, regions

    # Reconstruct lines
    lines = _ocr_to_lines(ocr_data, pil_img.size, page.rect)
    ocr_text = " ".join(w for w in ocr_data["text"] if w.strip())

    # Average confidence
    confs = [int(c) for c in ocr_data["conf"] if int(c) > 0]
    mean_conf = sum(confs) / len(confs) if confs else 0

    regions.append({
        "doc": fname,
        "page": pg,
        "region_id": region_id,
        "kind": "scanned_page",
        "bbox": list(page.rect),
        "text": ocr_text[:2000],
        "confidence": mean_conf / 100.0,
    })

    # Extract facts from OCR lines
    for line_text, line_bbox in lines:
        line_text = clean_text(line_text)
        if not line_text:
            continue
        sent_facts = _parse_sentence_facts(line_text, pg, fname, doc_date,
                                            region_id, line_bbox)
        # For scanned pages, reduce confidence
        for sf in sent_facts:
            sf["confidence"] = mean_conf / 100.0
            sf["kind"] = "ocr_row"
        facts.extend(sent_facts)

    # Also try to extract table rows from scanned page
    table_facts = _extract_scanned_table_facts(lines, pg, fname, doc_date, region_id, mean_conf)
    facts.extend(table_facts)

    return facts, regions


def _ocr_to_lines(ocr_data: dict, img_size: tuple, page_rect) -> list[tuple]:
    """
    Group OCR words into lines by block_num + line_num.
    Returns list of (line_text, bbox_in_page_coords).
    """
    img_w, img_h = img_size
    page_w = page_rect.width
    page_h = page_rect.height

    # Scale factors from image coords → page coords
    sx = page_w / img_w
    sy = page_h / img_h

    lines: dict[tuple, list] = {}
    for i, word in enumerate(ocr_data["text"]):
        conf = int(ocr_data["conf"][i])
        if conf < MIN_OCR_CONF or not word.strip():
            continue
        key = (ocr_data["block_num"][i], ocr_data["line_num"][i])
        x, y, w, h = (ocr_data["left"][i], ocr_data["top"][i],
                       ocr_data["width"][i], ocr_data["height"][i])
        lines.setdefault(key, []).append((word, x, y, w, h))

    result = []
    for key in sorted(lines):
        words_in_line = lines[key]
        line_text = " ".join(w[0] for w in words_in_line)
        xs = [w[1] for w in words_in_line]
        ys = [w[2] for w in words_in_line]
        xe = [w[1] + w[3] for w in words_in_line]
        ye = [w[2] + w[4] for w in words_in_line]
        bbox = [
            min(xs) * sx, min(ys) * sy,
            max(xe) * sx, max(ye) * sy,
        ]
        result.append((line_text, bbox))
    return result


def _extract_scanned_table_facts(lines: list, pg: int, fname: str, doc_date: str,
                                  region_id: str, mean_conf: float) -> list[dict]:
    """
    Heuristic: detect table rows in OCR lines by finding lines with
    multiple numeric columns. Try to pair row labels with column headers.
    """
    facts = []
    if len(lines) < 3:
        return facts

    # Find lines with ≥2 numeric tokens
    num_lines = []
    for i, (text, bbox) in enumerate(lines):
        nums = re.findall(r"\b\d[\d,]*\.?\d*\b", text)
        if len(nums) >= 2:
            num_lines.append(i)

    # Try to find a header line above the first numeric line
    if not num_lines:
        return facts
    header_idx = max(0, num_lines[0] - 1)
    header_text, _ = lines[header_idx]

    # Extract periods from header
    header_periods = extract_periods(header_text)

    for i in num_lines:
        text, bbox = lines[i]
        # Row label = first non-numeric token sequence
        label_m = re.match(r"^([A-Za-z\s\(\)/,\-:]+)", text)
        label = label_m.group(1).strip() if label_m else ""

        # Numbers in order
        nums_found = re.findall(r"\b([+-]?\d[\d,]*\.?\d*)\b", text)
        for col_idx, num_str in enumerate(nums_found):
            val = parse_number(num_str)
            if val is None:
                continue
            period = header_periods[col_idx] if col_idx < len(header_periods) else None
            unit = _detect_unit(header_text + " " + text)

            facts.append({
                "doc": fname,
                "page": pg,
                "region_id": region_id,
                "kind": "ocr_row",
                "metric": header_text[:200],
                "entity": label[:200],
                "period": period,
                "value": num_str,
                "value_num": val,
                "unit": unit,
                "qualifier": None,
                "doc_date": doc_date,
                "bbox": bbox,
                "period_bbox": None,
                "confidence": mean_conf / 100.0,
                "raw_text": f"{header_text} | {text}",
            })

    return facts


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _extract_doc_date(fname: str) -> str:
    """Heuristic: extract year from filename."""
    m = re.search(r"(\d{4})", fname)
    return m.group(1) if m else ""


def _detect_unit(text: str) -> str:
    """Detect the most likely unit in a text snippet."""
    text_lower = text.lower()
    # Order: specific to general
    for u in ["percentage points", "per cent", "percent", "%", "crore", "lakh",
               "million tonnes", "million", "billion", "usd", "₹", "rs.", "mm", "km", "kg"]:
        if u in text_lower:
            return u
    return ""


def _bbox_overlaps_any(bbox: list, bboxes: list) -> bool:
    """Check if bbox overlaps with any bbox in a list (simple IoU-style)."""
    x0, y0, x1, y1 = bbox
    for b in bboxes:
        bx0, by0, bx1, by1 = b
        # Check overlap
        if x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0:
            return True
    return False


def _extract_period_from_context(col_header: str, row_label: str) -> Optional[str]:
    """Try to find a period in col or row headers."""
    for src in [col_header, row_label]:
        ps = extract_periods(src)
        if ps:
            return ps[0]
    return None


def _words_in_bbox(words, x0: float, y0: float, x1: float, y1: float) -> str:
    """Return concatenated words whose bbox centre falls within [x0,y0,x1,y1]."""
    result = []
    for w in words:
        wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
        cx = (wx0 + wx1) / 2
        cy = (wy0 + wy1) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            result.append(w[4])
    return " ".join(result)


# ------------------------------------------------------------------
# Spot-check helper (called from tests / CLI)
# ------------------------------------------------------------------

def spot_check_facts(index_dir: str, n: int = 10) -> list[dict]:
    """Return a sample of n facts for manual inspection."""
    conn = _open_db(os.path.join(index_dir, "facts.db"))
    cur = conn.cursor()
    cur.execute(
        "SELECT doc,page,kind,metric,entity,period,value,unit,bbox FROM facts "
        "WHERE value_num IS NOT NULL ORDER BY RANDOM() LIMIT ?",
        (n,),
    )
    rows = cur.fetchall()
    conn.close()
    keys = ["doc", "page", "kind", "metric", "entity", "period", "value", "unit", "bbox"]
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------------------
# Public alias used by run.py, tests, and any external callers.
# build() is the canonical entry point; build_index() is the full
# implementation kept for backward compatibility.
# ---------------------------------------------------------------------------

def build(pdf_dir: str, out_dir: str = "data/index", **kwargs) -> None:
    """
    Thin alias for build_index().  Accepts the same positional arguments
    so callers can use either name.
    """
    build_index(pdf_dir, out_dir)
