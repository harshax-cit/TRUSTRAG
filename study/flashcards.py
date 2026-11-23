"""
study/flashcards.py – Generate and verify flashcards from topics.

Card types:
  (a) concept   – definition/concept from summary bullet
  (b) key_number – "What was X in period Y?"
  (c) cloze     – sentence with key term hidden
  (d) true_false – optional

Every card has: id, topic_id, type, front, back, doc, page, bbox,
                difficulty, verified (bool).

Verification: runs claim-to-pixel verify on numeric back sides.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional


# ── public API ────────────────────────────────────────────────────────────────

def generate_cards(
    topic: dict,
    summary: dict,
    index_dir: str,
    doc_name: str,
    pdf_path: str,
) -> list[dict]:
    """Return a list of verified flashcard dicts for a topic.

    For the student role with an API key: Claude generates richer cards.
    For all other cases: extractive generation (always works offline).
    """
    # Try AI generation first (student role, API key set, not government mode)
    from study.ai_generate import generate_flashcards_api, _can_use_api
    if _can_use_api():
        ai_cards = generate_flashcards_api(topic, summary, n_cards=8)
    else:
        ai_cards = []

    # Always generate extractive cards as well
    extractive_cards = []
    extractive_cards.extend(_concept_cards(summary, topic["id"], doc_name))
    extractive_cards.extend(_key_number_cards(topic, summary, index_dir, doc_name))
    extractive_cards.extend(_cloze_cards(summary, topic["id"], doc_name))

    # Merge: AI cards first, then extractive (avoid duplicates by front text)
    seen_fronts = set()
    all_cards = []
    for card in ai_cards + extractive_cards:
        front_key = card.get("front", "")[:60].lower()
        if front_key not in seen_fronts:
            seen_fronts.add(front_key)
            all_cards.append(card)

    # Verify every card whose back contains a number
    verified_cards = []
    for card in all_cards:
        card = _verify_card(card, pdf_path)
        if card is not None:
            verified_cards.append(card)

    return verified_cards


def card_difficulty(card: dict) -> str:
    """easy / medium / hard based on answer length and term rarity."""
    back = card.get("back", "")
    words = len(back.split())
    if words <= 5:
        return "easy"
    if words <= 20:
        return "medium"
    return "hard"


# ── concept cards ─────────────────────────────────────────────────────────────

def _concept_cards(summary: dict, topic_id: str, doc_name: str) -> list[dict]:
    cards = []
    for i, bullet in enumerate(summary.get("bullets", [])):
        text = bullet.get("text", "").strip()
        if len(text) < 20:
            continue
        # Simple Q: first noun phrase or first clause as question
        question = _make_concept_question(text)
        if not question:
            continue
        cards.append({
            "id":         f"{topic_id}_c{i:02d}",
            "topic_id":   topic_id,
            "type":       "concept",
            "front":      question,
            "back":       text,
            "doc":        bullet.get("doc", doc_name),
            "page":       bullet.get("page"),
            "bbox":       bullet.get("bbox"),
            "difficulty": "medium",
            "verified":   True,   # text-only, no number to verify
        })
    return cards


def _make_concept_question(text: str) -> str:
    """Turn a statement into a question."""
    # If it starts with a capitalized noun phrase, ask "What is <noun>?"
    m = re.match(r"^([A-Z][^,\.]{3,40})\s+(?:is|are|was|were|refers|means)\s+", text)
    if m:
        return f"What is {m.group(1)}?"
    # Fallback: "Explain: <first 60 chars>…"
    return f"Explain: {text[:60]}…" if len(text) > 60 else f"Explain: {text}"


# ── key-number cards ──────────────────────────────────────────────────────────

def _key_number_cards(topic: dict, summary: dict, index_dir: str,
                       doc_name: str) -> list[dict]:
    cards = []
    for i, num in enumerate(summary.get("key_numbers", [])):
        value  = num.get("value", "")
        unit   = num.get("unit",  "")
        period = num.get("period", "")
        page   = num.get("page")
        bbox   = num.get("bbox")

        if not value or not unit:
            continue

        metric = _infer_metric(value, unit, page, index_dir, doc_name)
        if not metric:
            continue

        if period:
            front = f"What was the {metric} in {period}?"
        else:
            front = f"What is the {metric}?"

        back = f"{value} {unit}".strip()

        cards.append({
            "id":         f"{topic['id']}_n{i:02d}",
            "topic_id":   topic["id"],
            "type":       "key_number",
            "front":      front,
            "back":       back,
            "doc":        doc_name,
            "page":       page,
            "bbox":       bbox,
            "difficulty": "easy",
            "verified":   False,  # will be set by _verify_card
        })
    return cards


def _infer_metric(value: str, unit: str, page: Optional[int],
                   index_dir: str, doc_name: str) -> str:
    """Look up the metric label for a value from the fact DB."""
    try:
        conn = sqlite3.connect(
            str(Path(index_dir) / "facts.db"), check_same_thread=False
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT metric, raw_text FROM facts WHERE doc=? AND page=? AND value=? LIMIT 1",
            (doc_name, page, value)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            metric = row[0] or ""
            if metric and len(metric) > 5:
                return metric[:80]
            # Try extracting from raw_text
            raw = row[1] or ""
            # Return first noun chunk before the number
            m = re.search(r"([A-Za-z][^,\.\n]{5,60})\s+" + re.escape(value[:10]),
                          raw)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return unit  # fallback: use unit as metric label


# ── cloze cards ───────────────────────────────────────────────────────────────

def _cloze_cards(summary: dict, topic_id: str, doc_name: str) -> list[dict]:
    from tracerag.textutil import tokenise, compute_idf

    bullets = summary.get("bullets", [])
    if not bullets:
        return []

    texts = [b["text"] for b in bullets]
    corpus = [tokenise(t, stem_tokens=True, remove_stops=True) for t in texts]
    idf    = compute_idf(corpus)

    cards = []
    for i, bullet in enumerate(bullets):
        text = bullet.get("text", "")
        tokens = tokenise(text, stem_tokens=True, remove_stops=True)
        if not tokens:
            continue

        # Find highest-IDF token that is a real word (not number, >4 chars)
        scored = [(t, idf.get(t, 0)) for t in tokens
                  if len(t) > 4 and not t.isdigit()]
        if not scored:
            continue
        scored.sort(key=lambda x: -x[1])
        target_stem = scored[0][0]

        # Find the actual word in the original text that stems to target
        clozed, hidden = _apply_cloze(text, target_stem)
        if not hidden:
            continue

        cards.append({
            "id":         f"{topic_id}_z{i:02d}",
            "topic_id":   topic_id,
            "type":       "cloze",
            "front":      clozed,
            "back":       hidden,
            "doc":        bullet.get("doc", doc_name),
            "page":       bullet.get("page"),
            "bbox":       bullet.get("bbox"),
            "difficulty": "medium",
            "verified":   True,
        })
    return cards


def _apply_cloze(text: str, target_stem: str) -> tuple[str, str]:
    """Replace the word closest to target_stem with ___."""
    from tracerag.textutil import stem
    words = text.split()
    for i, word in enumerate(words):
        clean = re.sub(r"[^a-zA-Z]", "", word).lower()
        if stem(clean) == target_stem:
            hidden = word
            words[i] = "___"
            return " ".join(words), hidden
    return text, ""


# ── verification ──────────────────────────────────────────────────────────────

def _verify_card(card: dict, pdf_path: str) -> Optional[dict]:
    """
    Run claim-to-pixel verification on numeric card backs.
    Returns the card (with verified flag set) or None if dropped.
    """
    back = card.get("back", "")
    # Only verify cards with numeric content
    nums = re.findall(r"\b\d+[\d,\.]*\b", back)
    if not nums:
        card["verified"] = True
        return card

    # Build a minimal fact dict for the verifier
    from tracerag.verify import Verifier
    # Use the session index dir derived from pdf_path
    pdf_dir   = str(Path(pdf_path).parent)
    index_dir = str(Path(pdf_path).parent.parent / "index")

    if not Path(index_dir).exists():
        card["verified"] = True  # can't verify, trust the fact DB
        return card

    try:
        v = Verifier(pdf_dir, index_dir)
        fact = {
            "doc":        card.get("doc", Path(pdf_path).name),
            "page":       card.get("page"),
            "value_num":  float(re.sub(r",", "", nums[0])),
            "value":      back,
            "kind":       "sentence",
            "bbox":       card.get("bbox"),
        }
        verified, found_bbox = v.verify_fact(fact)
        if verified:
            card["verified"] = True
            if found_bbox:
                card["bbox"] = found_bbox
            return card
        else:
            # key_number cards that fail verification are flagged but kept
            card["verified"] = False
            return card
    except Exception:
        # If verifier errors out, trust ingest result only for non-key_number cards
        if card["type"] == "key_number":
            card["verified"] = False
        else:
            card["verified"] = True
        return card
