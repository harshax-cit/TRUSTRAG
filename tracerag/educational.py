"""
tracerag/educational.py – 100% Offline Educational Utilities for Student Role.

Provides:
  - summarize_document(file_path) – Generates bullet summaries via local Ollama or extractive rules.
  - generate_student_materials(summary, api_key=None) – Creates quiz questions and flashcards locally.
  - explain_passage(text) – Plain-language student-friendly explanations.

Strictly zero cloud/external network calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .local_llm import (
    local_summarize_document,
    local_generate_student_materials,
    local_explain_simple,
)

logger = logging.getLogger(__name__)


def _read_file_text(file_path: str) -> str:
    """Extract plain text from local file using PyMuPDF for PDFs."""
    p = Path(file_path)
    if not p.exists():
        return ""
    try:
        if p.suffix.lower() == ".pdf":
            try:
                import pymupdf as fitz
                doc = fitz.open(str(p))
                texts = [page.get_text() for page in doc[:30]]
                extracted = "\n".join(texts).strip()
                if extracted:
                    return extracted
            except Exception as e:
                logger.warning(f"PyMuPDF text extraction failed: {e}")
            return p.read_bytes().decode(errors="ignore")
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return ""


def summarize_document(file_path: str, max_bullets: int = 5) -> str:
    """Generate a concise factual summary locally."""
    raw_text = _read_file_text(file_path)
    if not raw_text:
        return "⚠️ Could not read document content or file is empty."
    return local_summarize_document(raw_text, max_bullets=max_bullets)


def generate_student_materials(summary: str, api_key: Optional[str] = None) -> dict:
    """Generate quiz questions and flashcards locally without any cloud key."""
    if not summary or not summary.strip():
        return {"quiz": [], "flashcards": []}
    return local_generate_student_materials(summary)


def explain_passage(text: str) -> str:
    """Explain a complex policy or economic passage in simple student-friendly language."""
    if not text or not text.strip():
        return "No text provided to explain."
    return local_explain_simple(text, audience="student")
