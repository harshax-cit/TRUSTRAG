"""
study/leitner.py – Simple Leitner spaced-repetition (5 boxes).

Stored entirely in Streamlit session_state — no database needed.

Box schedule (review every N sessions):
  Box 1 → every session
  Box 2 → every 2 sessions
  Box 3 → every 4 sessions
  Box 4 → every 8 sessions
  Box 5 → graduated (review rarely)
"""

from __future__ import annotations



SCHEDULE = {1: 1, 2: 2, 3: 4, 4: 8, 5: 999}


class LeitnerDeck:
    def __init__(self, cards: list[dict]):
        # boxes[card_id] = box number (1–5)
        self.boxes:    dict[str, int] = {c["id"]: 1 for c in cards}
        self.cards:    dict[str, dict] = {c["id"]: c for c in cards}
        self.session:  int = 0
        self.history:  list[dict] = []  # {card_id, correct, session}

    def due_cards(self) -> list[dict]:
        """Return cards due this session."""
        due = []
        for cid, box in self.boxes.items():
            interval = SCHEDULE.get(box, 1)
            if self.session % interval == 0:
                due.append(self.cards[cid])
        return due

    def answer(self, card_id: str, knew_it: bool) -> None:
        """Move card up or down a box based on answer."""
        box = self.boxes.get(card_id, 1)
        if knew_it:
            self.boxes[card_id] = min(box + 1, 5)
        else:
            self.boxes[card_id] = 1
        self.history.append({
            "card_id": card_id,
            "correct": knew_it,
            "session": self.session,
        })

    def advance_session(self) -> None:
        self.session += 1

    def progress(self) -> dict:
        """Return progress stats."""
        total   = len(self.boxes)
        by_box  = {b: 0 for b in range(1, 6)}
        for box in self.boxes.values():
            by_box[box] = by_box.get(box, 0) + 1
        graduated = by_box[5]
        return {
            "total":          total,
            "graduated":      graduated,
            "pct_graduated":  round(graduated / max(total, 1) * 100, 1),
            "by_box":         by_box,
            "session":        self.session,
        }

    def topic_progress(self) -> dict[str, dict]:
        """Return per-topic progress."""
        topics: dict[str, list[int]] = {}
        for cid, box in self.boxes.items():
            tid = self.cards[cid].get("topic_id", "?")
            topics.setdefault(tid, []).append(box)
        return {
            tid: {
                "cards":        len(boxes),
                "mean_box":     round(sum(boxes) / len(boxes), 1),
                "graduated":    sum(1 for b in boxes if b == 5),
            }
            for tid, boxes in topics.items()
        }

    def make_quiz_question(self, card: dict,
                            all_cards: list[dict]) -> dict:
        """
        Make a multiple-choice question from a card.
        Distractors are other cards of the same type and unit.
        """
        import random
        same_type = [c for c in all_cards
                     if c["id"] != card["id"] and c["type"] == card["type"]]
        random.shuffle(same_type)
        distractors = [c["back"] for c in same_type[:3]]
        while len(distractors) < 3:
            distractors.append("None of the above")

        choices = distractors + [card["back"]]
        random.shuffle(choices)

        return {
            "question":     card["front"],
            "choices":      choices,
            "answer":       card["back"],
            "card_id":      card["id"],
            "doc":          card.get("doc"),
            "page":         card.get("page"),
            "bbox":         card.get("bbox"),
        }
