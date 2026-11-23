"""
eval.py – Evaluation against practice answers.

Metrics:
  - Answer accuracy per question type
  - Page accuracy
  - Status accuracy (answer/conflict/refuse)
  - Overall score

Also generates synthetic unanswerable questions and reports refusal P/R.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING)

TOLERANCE = 0.015   # 1.5% relative tolerance for numeric comparison


def load_jsonl(path: str) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def normalise_answer(answer) -> str:
    """Canonicalise an answer value for comparison."""
    if answer is None:
        return ""
    if isinstance(answer, list):
        return " | ".join(str(a) for a in answer)
    s = str(answer).strip()
    # Remove currency symbols, standardise spacing
    s = s.replace("₹", "").replace("$", "").replace("USD", "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def extract_number(text: str) -> Optional[float]:
    """Extract the first significant number from an answer string."""
    if not text:
        return None
    # Remove commas (Indian number format)
    text = text.replace(",", "")
    nums = re.findall(r"[+-]?\d+\.?\d*", text)
    for n in nums:
        try:
            v = float(n)
            if abs(v) > 0.001:  # skip near-zero
                return v
        except ValueError:
            pass
    return None


def numbers_match(pred: str, gold: str, tol: float = TOLERANCE) -> bool:
    """Check if two answer strings represent the same number within tolerance."""
    p_num = extract_number(pred)
    g_num = extract_number(gold)
    if p_num is None or g_num is None:
        return False
    if g_num == 0:
        return abs(p_num) < 1e-6
    return abs(p_num - g_num) / (abs(g_num) + 1e-9) <= tol


def answer_matches(pred_answer, gold_answer: str, q_type: str) -> bool:
    """Compare predicted answer to gold answer."""
    pred_str = normalise_answer(pred_answer)
    gold_str = normalise_answer(gold_answer)

    if not gold_str:
        return pred_str == ""

    # Exact string match
    if pred_str == gold_str:
        return True

    # Numeric match
    if numbers_match(pred_str, gold_str):
        return True

    # For conflict questions: both values should appear
    if q_type == "conflict" and isinstance(pred_answer, list):
        # Check if both gold values are in the prediction
        gold_parts = gold_str.split(";")
        for gp in gold_parts:
            gp_stripped = gp.strip()
            found = any(numbers_match(normalise_answer(p), gp_stripped)
                        for p in pred_answer)
            if not found:
                return False
        return True

    return False


def page_matches(pred_page, gold_page) -> bool:
    """Check if the predicted page matches gold."""
    if gold_page is None:
        return True  # No page requirement for refusals

    if isinstance(pred_page, list):
        return any(p == gold_page for p in pred_page)
    return pred_page == gold_page


def evaluate(predictions_path: str, answers_path: str,
             verbose: bool = True) -> dict:
    preds = {p["id"]: p for p in load_jsonl(predictions_path)}
    golds = {g["id"]: g for g in load_jsonl(answers_path)}

    results = []
    type_counts: dict[str, dict] = {}
    status_correct = 0
    answer_correct = 0
    page_correct = 0
    total = 0

    for qid, gold in golds.items():
        pred = preds.get(qid)
        if pred is None:
            if verbose:
                print(f"  MISSING: {qid}")
            continue

        total += 1
        q_type = gold.get("type", "text")
        gold_status = gold.get("status", "answer")
        gold_answer = gold.get("answer", "")
        gold_page = gold.get("page")

        pred_status = pred.get("status", "answer")
        pred_answer = pred.get("answer", "")
        pred_page = pred.get("page")

        # Status match
        status_ok = pred_status == gold_status
        if status_ok:
            status_correct += 1

        # Answer match
        ans_ok = False
        if gold_status == "refuse":
            ans_ok = pred_status == "refuse"
        elif gold_status == "conflict":
            # Conflict: status must be conflict, and both values present
            if pred_status == "conflict":
                ans_ok = answer_matches(pred_answer, gold_answer, "conflict")
            elif pred_status == "answer":
                # Partial credit: at least one correct value
                gold_vals = [v.get("value", "") for v in gold.get("conflict", [])]
                for gv in gold_vals:
                    if numbers_match(normalise_answer(pred_answer),
                                     normalise_answer(gv)):
                        ans_ok = True
                        break
        else:
            ans_ok = answer_matches(pred_answer, gold_answer, q_type)

        if ans_ok:
            answer_correct += 1

        # Page match (only for answered questions)
        pg_ok = False
        if gold_status != "refuse":
            pg_ok = page_matches(pred_page, gold_page)
            if pg_ok:
                page_correct += 1

        # Track by type
        if q_type not in type_counts:
            type_counts[q_type] = {"total": 0, "answer_ok": 0, "page_ok": 0, "status_ok": 0}
        type_counts[q_type]["total"] += 1
        if ans_ok:
            type_counts[q_type]["answer_ok"] += 1
        if pg_ok:
            type_counts[q_type]["page_ok"] += 1
        if status_ok:
            type_counts[q_type]["status_ok"] += 1

        results.append({
            "id": qid,
            "type": q_type,
            "status_ok": status_ok,
            "answer_ok": ans_ok,
            "page_ok": pg_ok,
            "gold_answer": gold_answer,
            "pred_answer": pred_answer,
            "gold_page": gold_page,
            "pred_page": pred_page,
            "gold_status": gold_status,
            "pred_status": pred_status,
        })

        if verbose:
            marks = []
            marks.append("✓ANS" if ans_ok else "✗ANS")
            marks.append("✓PG" if pg_ok else "✗PG")
            marks.append("✓ST" if status_ok else "✗ST")
            status_flag = " ".join(marks)
            print(f"  {qid} [{q_type:12s}] {status_flag}")
            print(f"    Gold: [{gold_status}] {str(gold_answer)[:60]!r} p={gold_page}")
            print(f"    Pred: [{pred_status}] {str(pred_answer)[:60]!r} p={pred_page}")

    # Overall scores
    ans_acc = answer_correct / total if total else 0
    pg_acc = page_correct / total if total else 0
    st_acc = status_correct / total if total else 0

    # Weighted score (per rubric)
    weighted = ans_acc * 0.45 + pg_acc * 0.25 + st_acc * 0.30

    summary = {
        "total": total,
        "answer_accuracy": round(ans_acc, 3),
        "page_accuracy": round(pg_acc, 3),
        "status_accuracy": round(st_acc, 3),
        "weighted_score": round(weighted, 3),
        "by_type": {
            t: {
                "total": v["total"],
                "ans_acc": round(v["answer_ok"] / v["total"], 3),
                "pg_acc": round(v["page_ok"] / v["total"], 3),
                "st_acc": round(v["status_ok"] / v["total"], 3),
            }
            for t, v in type_counts.items()
        },
        "results": results,
    }

    return summary


def generate_synthetic_unanswerables(gold_path: str, n: int = 20) -> list[dict]:
    """
    Generate synthetic unanswerable questions by perturbing gold questions.
    Changes: year, entity, metric.
    """
    golds = load_jsonl(gold_path)
    answerable = [g for g in golds if g.get("status") == "answer"]

    synthetics = []
    year_map = {"2021": "2015", "2022": "2016", "2023": "2017", "2024": "2018",
                "FY23": "FY19", "FY24": "FY18", "2026": "2015"}
    entity_map = {"Mauritius": "Mongolia", "Kerala": "Assam",
                  "India": "Bangladesh", "tomato": "carrot",
                  "onion": "cabbage", "core inflation": "wage inflation"}

    for g in answerable[:n]:
        q = g["question"]
        # Perturbation 1: change year
        q_yr = q
        for old_yr, new_yr in year_map.items():
            q_yr = q_yr.replace(old_yr, new_yr)
        if q_yr != q:
            synthetics.append({
                "id": f"syn_{g['id']}_yr",
                "question": q_yr,
                "type": "synthetic_refuse",
                "expected_status": "refuse",
                "original_id": g["id"],
                "perturbation": "year",
            })

        # Perturbation 2: change entity
        q_ent = q
        for old_ent, new_ent in entity_map.items():
            q_ent = q_ent.replace(old_ent, new_ent)
        if q_ent != q:
            synthetics.append({
                "id": f"syn_{g['id']}_ent",
                "question": q_ent,
                "type": "synthetic_refuse",
                "expected_status": "refuse",
                "original_id": g["id"],
                "perturbation": "entity",
            })

    return synthetics[:n]


def eval_synthetic(engine, synthetics: list[dict]) -> dict:
    """Run synthetic unanswerables and check refusal rate."""
    correct_refuse = 0
    wrong_answer = 0
    total = len(synthetics)

    for s in synthetics:
        qid = s["id"]
        question = s["question"]
        try:
            result = engine.answer(qid, question)
            if result["status"] == "refuse":
                correct_refuse += 1
            else:
                wrong_answer += 1
                print(f"  WRONG: {qid}: {result.get('answer', '')[:50]}")
        except Exception as e:
            print(f"  ERROR on {qid}: {e}")
            wrong_answer += 1

    precision = correct_refuse / total if total else 0
    return {
        "total": total,
        "correct_refuse": correct_refuse,
        "wrong_answer": wrong_answer,
        "refusal_precision": round(precision, 3),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", help="Path to predictions.jsonl")
    parser.add_argument("--answers", default="data/raw/practice_answers.jsonl")
    parser.add_argument("--run-synthetic", action="store_true",
                        help="Also run synthetic unanswerable test")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--pdf-dir", default="data/raw/pdfs")
    args = parser.parse_args()

    print("=" * 70)
    print("TRACERAG EVALUATION")
    print("=" * 70)

    summary = evaluate(args.predictions, args.answers, verbose=True)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total questions: {summary['total']}")
    print(f"  Answer accuracy: {summary['answer_accuracy']:.1%}")
    print(f"  Page accuracy:   {summary['page_accuracy']:.1%}")
    print(f"  Status accuracy: {summary['status_accuracy']:.1%}")
    print(f"  Weighted score:  {summary['weighted_score']:.1%}")

    print("\nBy type:")
    for t, v in sorted(summary["by_type"].items()):
        print(f"  {t:15s}: ans={v['ans_acc']:.1%} pg={v['pg_acc']:.1%} st={v['st_acc']:.1%} (n={v['total']})")

    if args.run_synthetic:
        from tracerag.engine import Engine
        engine = Engine(args.index_dir, args.pdf_dir)
        synthetics = generate_synthetic_unanswerables(args.answers, n=20)
        print(f"\nRunning {len(synthetics)} synthetic unanswerables...")
        syn_results = eval_synthetic(engine, synthetics)
        print(f"  Refusal precision: {syn_results['refusal_precision']:.1%}")
        print(f"  Correct refusals: {syn_results['correct_refuse']}/{syn_results['total']}")

    # Save evaluation report
    report_path = "outputs/eval_report.json"
    os.makedirs("outputs", exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({k: v for k, v in summary.items() if k != "results"}, f, indent=2)
    print(f"\nReport saved to {report_path}")
