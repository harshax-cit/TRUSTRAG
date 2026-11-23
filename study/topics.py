"""
study/topics.py – Topic extraction from an uploaded PDF.

Strategy (in order):
  1. PDF outline / bookmarks (fitz.get_toc)
  2. Heading detection from font size + bold spans
  3. Fallback: BM25/TF-IDF similarity clustering of consecutive page blocks

Each topic: {id, title, page_start, page_end, region_ids, page_texts}
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Optional

import pymupdf as fitz


# ── public API ────────────────────────────────────────────────────────────────

def extract_topics(pdf_path: str, regions_jsonl: str) -> list[dict]:
    """
    Extract topics from a PDF, returning a list of topic dicts.
    Falls back through three strategies.
    """
    doc = fitz.open(pdf_path)
    n   = len(doc)
    doc.close()

    # Strategy 1: bookmarks / outline
    topics = _topics_from_outline(pdf_path)
    if len(topics) >= 2:
        return _attach_regions(topics, regions_jsonl)

    # Strategy 2: heading detection
    topics = _topics_from_headings(pdf_path)
    if len(topics) >= 2:
        return _attach_regions(topics, regions_jsonl)

    # Strategy 3: TF-IDF clustering
    topics = _topics_from_tfidf(pdf_path)
    return _attach_regions(topics, regions_jsonl)


# ── strategy 1: outline ───────────────────────────────────────────────────────

def _topics_from_outline(pdf_path: str) -> list[dict]:
    doc    = fitz.open(pdf_path)
    toc    = doc.get_toc()          # [[level, title, page], ...]
    n      = len(doc)
    doc.close()

    if not toc:
        return []

    # Keep only level-1 (chapter) entries
    level1 = [(title.strip(), page) for level, title, page in toc if level == 1]
    if len(level1) < 2:
        # Try level 2
        level1 = [(title.strip(), page) for level, title, page in toc if level <= 2]

    topics = []
    for i, (title, page_start) in enumerate(level1):
        page_end = level1[i + 1][1] - 1 if i + 1 < len(level1) else n
        topics.append({
            "id":         f"t{i:02d}",
            "title":      title[:120],
            "page_start": max(1, page_start),
            "page_end":   max(1, page_end),
            "source":     "outline",
            "region_ids": [],
            "page_texts": {},
        })
    return topics


# ── strategy 2: heading detection ────────────────────────────────────────────

def _topics_from_headings(pdf_path: str) -> list[dict]:
    doc    = fitz.open(pdf_path)
    n      = len(doc)

    # Collect font sizes across first 20 pages to establish baseline
    sizes = []
    for pg in doc[:min(20, n)]:
        for block in pg.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sizes.append(span.get("size", 0))

    if not sizes:
        doc.close()
        return []

    sizes.sort()
    p75 = sizes[int(len(sizes) * 0.75)]   # 75th percentile = likely headings

    headings = []   # (page_1indexed, text)
    for pg_idx, pg in enumerate(doc):
        for block in pg.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size  = span.get("size", 0)
                    flags = span.get("flags", 0)
                    bold  = bool(flags & 2**4)   # bold bit
                    text  = span.get("text", "").strip()
                    if not text or len(text) < 3 or len(text) > 150:
                        continue
                    if (size > p75 or bold) and not text[0].isdigit():
                        headings.append((pg_idx + 1, text))

    doc.close()

    if len(headings) < 2:
        return []

    # Deduplicate consecutive identical headings
    unique = []
    for h in headings:
        if not unique or h[1] != unique[-1][1]:
            unique.append(h)
    headings = unique

    topics = []
    for i, (page_start, title) in enumerate(headings[:20]):
        page_end = headings[i + 1][0] - 1 if i + 1 < len(headings) else n
        topics.append({
            "id":         f"t{i:02d}",
            "title":      title[:120],
            "page_start": page_start,
            "page_end":   max(page_start, page_end),
            "source":     "heading",
            "region_ids": [],
            "page_texts": {},
        })
    return topics


# ── strategy 3: TF-IDF similarity clustering ─────────────────────────────────

def _topics_from_tfidf(pdf_path: str) -> list[dict]:
    """
    Group consecutive pages into 3–8 topics using cosine similarity of TF-IDF vectors.
    """
    doc    = fitz.open(pdf_path)
    n      = len(doc)

    page_texts = []
    for pg in doc:
        page_texts.append(pg.get_text("text").lower())
    doc.close()

    if n == 0:
        return []

    # Compute TF-IDF for each page
    from tracerag.textutil import tokenise, compute_idf
    page_tokens = [tokenise(t, stem_tokens=True, remove_stops=True) for t in page_texts]
    idf = compute_idf(page_tokens)

    def tfidf_vec(tokens: list[str]) -> dict[str, float]:
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        total = max(len(tokens), 1)
        return {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}

    vecs = [tfidf_vec(t) for t in page_tokens]

    def cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        na  = math.sqrt(sum(v * v for v in a.values()))
        nb  = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb + 1e-9)

    # Find breakpoints where similarity drops
    target_topics = max(3, min(8, n // 3))
    sims = [cosine(vecs[i], vecs[i + 1]) for i in range(n - 1)]
    if not sims:
        # Single-page doc
        return [{
            "id": "t00", "title": "Document", "page_start": 1,
            "page_end": n, "source": "tfidf", "region_ids": [], "page_texts": {}
        }]

    # Pick the lowest-similarity gaps as topic breaks
    indexed = sorted(enumerate(sims), key=lambda x: x[1])
    breaks  = sorted(i + 1 for i, _ in indexed[:target_topics - 1])
    breaks  = [b for b in breaks if b > 0]

    boundaries = [1] + [b + 1 for b in breaks] + [n + 1]
    topics = []
    for i in range(len(boundaries) - 1):
        ps = boundaries[i]
        pe = boundaries[i + 1] - 1
        # Title from most distinctive term of first page
        v = vecs[ps - 1]
        top_terms = sorted(v.items(), key=lambda x: -x[1])[:3]
        title = " / ".join(t for t, _ in top_terms) if top_terms else f"Topic {i+1}"
        topics.append({
            "id":         f"t{i:02d}",
            "title":      title[:120].title(),
            "page_start": ps,
            "page_end":   pe,
            "source":     "tfidf",
            "region_ids": [],
            "page_texts": {},
        })
    return topics


# ── attach regions from index ─────────────────────────────────────────────────

def _attach_regions(topics: list[dict], regions_jsonl: str) -> list[dict]:
    """
    For each topic, collect region_ids whose page falls within the topic's range.
    Also collect raw page texts.
    """
    if not Path(regions_jsonl).exists():
        return topics

    # Build page → list[region_id] map
    page_to_regions: dict[int, list[str]] = {}
    page_to_texts:   dict[int, str]       = {}

    with open(regions_jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            pg = r.get("page", 0)
            rid = r.get("region_id", "")
            page_to_regions.setdefault(pg, []).append(rid)
            if r.get("text"):
                page_to_texts[pg] = page_to_texts.get(pg, "") + " " + r["text"]

    for topic in topics:
        rids = []
        texts = {}
        for pg in range(topic["page_start"], topic["page_end"] + 1):
            rids.extend(page_to_regions.get(pg, []))
            if pg in page_to_texts:
                texts[pg] = page_to_texts[pg].strip()
        topic["region_ids"] = rids
        topic["page_texts"] = texts

    return topics
