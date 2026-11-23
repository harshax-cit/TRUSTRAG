"""
retrieve.py – BM25-based retrieval with Reciprocal Rank Fusion.

Retrieves regions from the JSONL index, scores them with BM25,
optionally fuses with a dense ranker, and returns top-k regions.
"""

from __future__ import annotations

import logging
from typing import Optional

from rank_bm25 import BM25Okapi

from .textutil import (
    compute_idf,
    expand_synonyms,
    tokenise,
    unseen_term_check,
    idf_coverage_score,
    normalise_period,
    extract_periods,
)

logger = logging.getLogger(__name__)

# Weights for RRF
RRF_K = 60
TOP_K_RETRIEVE = 20


class Retriever:
    """
    Builds BM25 index over regions on first call, caches it.
    Thread-safe for read (index is built once).
    """

    def __init__(self, index_dir: str):
        self.index_dir = index_dir
        self._regions: list[dict] = []
        self._bm25: Optional[BM25Okapi] = None
        self._corpus_tokens: list[list[str]] = []
        self._idf: dict[str, float] = {}
        self._vocab: set[str] = set()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        from .ingest import load_regions
        self._regions = load_regions(self.index_dir)
        if not self._regions:
            logger.warning("No regions found in index.")
            self._loaded = True
            return

        self._corpus_tokens = []
        for r in self._regions:
            text = r.get("text", "")
            tokens = tokenise(text, stem_tokens=True, remove_stops=True)
            tokens = expand_synonyms(tokens)
            self._corpus_tokens.append(tokens)
            self._vocab.update(tokens)

        self._bm25 = BM25Okapi(self._corpus_tokens)
        self._idf = compute_idf(self._corpus_tokens)
        self._loaded = True
        logger.info(f"BM25 index built: {len(self._regions)} regions, vocab={len(self._vocab)}")

    def retrieve(self, query: str, top_k: int = TOP_K_RETRIEVE,
                 doc_filter: Optional[str] = None) -> list[dict]:
        """
        Return top_k regions most relevant to query.
        Each result is the region dict with added 'score' and 'unseen_terms'.
        """
        self._load()
        if not self._regions or self._bm25 is None:
            return []

        q_tokens = tokenise(query, stem_tokens=True, remove_stops=True)
        q_tokens = expand_synonyms(q_tokens)
        unseen = unseen_term_check(q_tokens, self._vocab)

        # BM25 scores
        bm25_scores = self._bm25.get_scores(q_tokens)

        # Build ranked list
        ranked = sorted(
            enumerate(bm25_scores), key=lambda x: x[1], reverse=True
        )

        results = []
        for idx, score in ranked[:top_k * 3]:  # over-fetch before filtering
            region = self._regions[idx]
            if doc_filter and region.get("doc") != doc_filter:
                continue

            # IDF coverage score (bonus)
            cov = idf_coverage_score(q_tokens, self._corpus_tokens[idx], self._idf)

            results.append({
                **region,
                "bm25_score": float(score),
                "coverage": cov,
                "score": float(score) + cov * 2.0,  # combined
                "unseen_terms": unseen,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def retrieve_facts(self, query: str, conn,
                       top_k: int = 20,
                       period_filter: Optional[str] = None) -> list[dict]:
        """
        Retrieve facts from SQLite, scored by IDF-weighted term coverage
        and exact period match bonus.
        """
        self._load()

        q_tokens = tokenise(query, stem_tokens=True, remove_stops=True)
        q_tokens = expand_synonyms(q_tokens)
        query_periods = extract_periods(query)
        query_period = query_periods[0] if query_periods else period_filter

        cur = conn.cursor()
        # Fetch all facts (we'll score in Python)
        cur.execute(
            """SELECT id,doc,page,region_id,kind,metric,entity,period,
                      value,value_num,unit,qualifier,doc_date,bbox,
                      period_bbox,confidence,raw_text
               FROM facts WHERE value_num IS NOT NULL"""
        )
        rows = cur.fetchall()
        cols = ["id", "doc", "page", "region_id", "kind", "metric", "entity",
                "period", "value", "value_num", "unit", "qualifier", "doc_date",
                "bbox", "period_bbox", "confidence", "raw_text"]

        scored = []
        for row in rows:
            fact = dict(zip(cols, row))
            # Tokenise fact text
            fact_text = " ".join(filter(None, [
                fact.get("metric", ""), fact.get("entity", ""),
                fact.get("raw_text", ""), fact.get("unit", ""),
            ]))
            fact_tokens = tokenise(fact_text, stem_tokens=True, remove_stops=True)
            fact_tokens = expand_synonyms(fact_tokens)

            # IDF coverage
            cov = idf_coverage_score(q_tokens, fact_tokens, self._idf)

            # Period match bonus
            period_bonus = 0.0
            if query_period and fact.get("period"):
                fp = normalise_period(fact["period"]) if fact["period"] else ""
                qp = normalise_period(query_period)
                if fp == qp:
                    period_bonus = 3.0
                elif qp and fp and (qp[:4] in fp or fp[:4] in qp):
                    period_bonus = 1.0  # partial year match

            # Unseen-term penalty: if important query terms appear nowhere
            unseen = unseen_term_check(q_tokens, set(fact_tokens))
            unseen_penalty = len(unseen) * 0.3

            combined = cov * 5.0 + period_bonus - unseen_penalty
            fact["_score"] = combined
            fact["_coverage"] = cov
            fact["_period_bonus"] = period_bonus
            scored.append(fact)

        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored[:top_k]


def rrf_fuse(ranked_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """
    Reciprocal Rank Fusion over multiple ranked lists.
    Each list item must have a 'region_id' or 'id' key.
    """
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            key = item.get("region_id") or str(item.get("id", ""))
            if not key:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in items:
                items[key] = item

    merged = [(key, scores[key]) for key in scores]
    merged.sort(key=lambda x: x[1], reverse=True)
    return [items[key] for key, _ in merged]
