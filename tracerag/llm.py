"""
tracerag/llm.py – Local Offline Vision & LLM Model Interface.

In government/offline mode:
  - External network calls are strictly blocked.
  - _detect_mode() returns None.
  - Uses local Ollama vision or built-in OCR.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

from .local_llm import check_ollama_status, load_model_config

logger = logging.getLogger(__name__)


def _detect_mode() -> Optional[str]:
    """Detect configured API provider. Strictly returns None in government mode."""
    try:
        from config import is_government_mode
        if is_government_mode():
            return None
    except ImportError:
        pass

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def is_online() -> bool:
    return _detect_mode() is not None


def is_local_llm_ready() -> bool:
    return check_ollama_status().get("available", False)


def read_chart_image(image_bytes: bytes, chart_title: str = "") -> list[dict]:
    """
    Ask local Ollama vision model to extract data labels if available.
    Returns [] if no local vision model is running (caller uses Tesseract OCR).
    """
    status = check_ollama_status()
    if not status["available"]:
        return []

    cfg = load_model_config().get("ollama", {})
    vision_model = cfg.get("vision_model", "llava:latest")
    endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")

    if not any("llava" in m.lower() or "vision" in m.lower() for m in status.get("models", [])):
        return []

    try:
        import urllib.request
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            f"This is a chart titled '{chart_title}'. Extract printed data labels and numeric values as JSON array "
            "with keys: 'period', 'value', 'entity'. Return ONLY valid JSON."
        )
        payload = {
            "model": vision_model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        req = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                raw = data.get("response", "").replace("```json", "").replace("```", "").strip()
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
    except Exception as e:
        logger.debug(f"Local Ollama vision chart reading skipped: {e}")

    return []


def read_text_passage(text: str, question: str) -> Optional[str]:
    """Local text passage answer generation via local Ollama."""
    from .local_llm import local_generate
    prompt = f"Context:\n{text[:2000]}\n\nQuestion: {question}\nAnswer strictly using the context:"
    res = local_generate(prompt, max_tokens=200)
    return res if res else None
