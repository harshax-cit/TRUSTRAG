"""
llm.py – Optional LLM/vision model hook.

Disabled unless OPENAI_API_KEY (or ANTHROPIC_API_KEY) is set.
When enabled, used ONLY for raster/unlabeled chart reading,
and the output is ALWAYS re-verified by verify.py before use.

The module exposes two functions:
  - read_chart_image(image_bytes) → list[dict] data-label records
  - read_text_passage(text, question) → str raw answer (must be verified)

Both return empty/None when no key is available (offline mode).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_API_MODE: Optional[str] = None  # "openai" | "anthropic" | None


def _detect_mode() -> Optional[str]:
    global _API_MODE
    if _API_MODE is not None:
        return _API_MODE
    if os.environ.get("OPENAI_API_KEY"):
        _API_MODE = "openai"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _API_MODE = "anthropic"
    else:
        _API_MODE = None
    return _API_MODE


def is_online() -> bool:
    return _detect_mode() is not None


def read_chart_image(image_bytes: bytes, chart_title: str = "") -> list[dict]:
    """
    Ask a vision model to extract data labels from a chart image.
    Returns list of {"label": str, "value": str, "period": str}.
    Returns [] if offline.
    """
    mode = _detect_mode()
    if not mode:
        return []

    b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        f"This is a chart titled: '{chart_title}'. "
        "List every numeric data label printed on the chart in the format: "
        'JSON array of objects with keys "period", "value", "entity". '
        "Only include values that are explicitly labelled. "
        "Return ONLY valid JSON, no prose."
    )

    if mode == "openai":
        return _openai_vision(b64, prompt)
    elif mode == "anthropic":
        return _anthropic_vision(b64, prompt)
    return []


def _openai_vision(b64: str, prompt: str) -> list[dict]:
    try:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}",
                                   "detail": "high"}},
                ],
            }],
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"OpenAI vision failed: {e}")
        return []


def _anthropic_vision(b64: str, prompt: str) -> list[dict]:
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": "image/png",
                                "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Anthropic vision failed: {e}")
        return []


def read_text_passage(text: str, question: str) -> str:
    """
    Ask LLM to extract an answer from a passage.
    Result MUST be re-verified before use.
    Returns "" if offline.
    """
    mode = _detect_mode()
    if not mode:
        return ""

    prompt = (
        f"Question: {question}\n\n"
        f"Passage:\n{text[:3000]}\n\n"
        "Answer the question using ONLY information in the passage. "
        "If the passage does not contain the answer, reply exactly: NOT_FOUND. "
        "Do not add explanation, just the answer value."
    )

    if mode == "openai":
        try:
            import openai
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"OpenAI text failed: {e}")
    elif mode == "anthropic":
        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Anthropic text failed: {e}")

    return ""
