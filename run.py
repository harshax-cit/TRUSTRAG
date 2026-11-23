#!/usr/bin/env python3
"""
run.py – TraceRAG CLI

Usage:
  python run.py build <pdf_dir>
  python run.py answer <questions.json> [--strict]
  python run.py verify-chain
  python run.py export-audit <out_path>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run")

DEFAULT_INDEX_DIR = os.path.join(os.path.dirname(__file__), "data", "index")
DEFAULT_PDF_DIR = os.path.join(os.path.dirname(__file__), "data", "raw", "pdfs")


def cmd_build(pdf_dir: str, index_dir: str):
    from tracerag.ingest import build_index
    logger.info(f"Building index from {pdf_dir} → {index_dir}")
    build_index(pdf_dir, index_dir)
    logger.info("Build complete.")

    # Print manifest summary
    from tracerag.ingest import load_manifest
    manifest = load_manifest(index_dir)
    print(f"\n{'Document':<50} {'Pages':>6} {'Scan':>5} {'Facts':>7}")
    print("-" * 72)
    total_facts = 0
    for fname, info in sorted(manifest.items()):
        print(f"{fname:<50} {info['pages']:>6} {info['scan_pages']:>5} {info['fact_count']:>7}")
        total_facts += info.get("fact_count", 0)
    print("-" * 72)
    print(f"Total facts indexed: {total_facts}")


def cmd_answer(questions_path: str, index_dir: str, pdf_dir: str,
               strict: bool, out_path: str):
    from tracerag.engine import Engine

    with open(questions_path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    questions = []
    for line in lines:
        q = json.loads(line)
        if "question" in q:
            questions.append(q)

    engine = Engine(index_dir, pdf_dir)
    results = []

    for q in questions:
        qid = q.get("id", f"q{len(results)}")
        question = q.get("question", "")
        logger.info(f"Answering {qid}: {question[:80]}")
        try:
            answer = engine.answer(qid, question, strict=strict)
        except Exception as e:
            logger.error(f"Error on {qid}: {e}")
            answer = {
                "id": qid,
                "answer": "",
                "doc": None,
                "page": None,
                "bbox": None,
                "status": "refuse",
            }
            if not strict:
                answer["reason_codes"] = ["EXCEPTION"]
                answer["evidence"] = str(e)
                answer["confidence"] = 0.0
        results.append(answer)
        # Print brief result
        status = answer.get("status", "?")
        ans_preview = str(answer.get("answer", ""))[:60]
        print(f"  [{status.upper():>8}] {qid}: {ans_preview}")

    # Write outputs
    pred_path = out_path
    with open(pred_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(results)} answers to {pred_path}")

    if not strict:
        strict_path = pred_path.replace(".jsonl", ".strict.jsonl")
        STRICT_FIELDS = {"id", "answer", "doc", "page", "bbox", "status"}
        with open(strict_path, "w", encoding="utf-8") as f:
            for r in results:
                strict_r = {k: v for k, v in r.items() if k in STRICT_FIELDS}
                f.write(json.dumps(strict_r, ensure_ascii=False) + "\n")
        logger.info(f"Wrote strict predictions to {strict_path}")

    return results


def cmd_verify_chain(index_dir: str):
    from tracerag.audit import AuditLog
    audit = AuditLog(index_dir)
    ok, message = audit.verify_chain()
    print(f"Chain {'OK' if ok else 'BROKEN'}: {message}")
    sys.exit(0 if ok else 1)


def cmd_export_audit(index_dir: str, out_path: str):
    from tracerag.audit import AuditLog
    audit = AuditLog(index_dir)
    n = audit.export_jsonl(out_path)
    print(f"Exported {n} audit records to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="TraceRAG CLI")
    sub = parser.add_subparsers(dest="command")

    # build
    p_build = sub.add_parser("build", help="Ingest PDFs and build index")
    p_build.add_argument("pdf_dir", nargs="?", default=DEFAULT_PDF_DIR)
    p_build.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)

    # answer
    p_answer = sub.add_parser("answer", help="Answer questions from JSONL")
    p_answer.add_argument("questions", help="Path to questions JSONL")
    p_answer.add_argument("--strict", action="store_true",
                          help="Output only 6 required fields")
    p_answer.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)
    p_answer.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR)
    p_answer.add_argument("--out", default="outputs/predictions.jsonl")

    # verify-chain
    p_vc = sub.add_parser("verify-chain", help="Verify audit chain integrity")
    p_vc.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)

    # export-audit
    p_ea = sub.add_parser("export-audit", help="Export audit log to JSONL")
    p_ea.add_argument("out_path", help="Output JSONL path")
    p_ea.add_argument("--index-dir", default=DEFAULT_INDEX_DIR)

    args = parser.parse_args()

    if args.command == "build":
        cmd_build(args.pdf_dir, args.index_dir)
    elif args.command == "answer":
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        cmd_answer(args.questions, args.index_dir, args.pdf_dir,
                   args.strict, args.out)
    elif args.command == "verify-chain":
        cmd_verify_chain(args.index_dir)
    elif args.command == "export-audit":
        cmd_export_audit(args.index_dir, args.out_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
