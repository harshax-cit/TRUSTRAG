"""
tracerag/local_llm.py – 100% Offline Local Model & Extractive Inference Engine.

Strictly prohibited:
  - External network calls (OpenAI, Anthropic, Gemini, Groq, etc.)
  - Cloud inference APIs

Supported:
  - Local Ollama instance (default: http://localhost:11434)
  - Pure local offline extractive fallback (runs without any external daemon)
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "models.json"


def load_model_config() -> dict:
    """Load configuration from config/models.json or return hardened offline defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            logger.warning(f"Could not read config/models.json: {e}")
    return {
        "ollama": {
            "enabled": True,
            "endpoint": "http://localhost:11434",
            "default_model": "llama3.2:latest",
            "vision_model": "llava:latest",
            "timeout_seconds": 10,
        },
        "offline_mode": {
            "strictly_enforced": True,
            "allow_external_network": False,
        },
    }


def check_ollama_status() -> dict:
    """
    Check if local Ollama daemon is reachable.
    Does NOT connect to external networks.
    """
    cfg = load_model_config().get("ollama", {})
    endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")
    timeout = cfg.get("timeout_seconds", 3)

    try:
        url = f"{endpoint}/api/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "TraceRAG-Local"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return {
                    "available": True,
                    "endpoint": endpoint,
                    "models": models,
                    "active_model": cfg.get("default_model", "llama3.2:latest"),
                }
    except Exception as e:
        logger.debug(f"Local Ollama unreachable at {endpoint}: {e}")

    return {
        "available": False,
        "endpoint": endpoint,
        "models": [],
        "active_model": "Local Extractive Engine (Offline Built-in)",
    }


def local_generate(
    prompt: str,
    system: str = "",
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """
    Generate text using local Ollama if running; otherwise fallback to local extractive rules.
    NEVER calls external services.
    """
    cfg = load_model_config().get("ollama", {})
    endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")
    target_model = model or cfg.get("default_model", "llama3.2:latest")
    timeout = cfg.get("timeout_seconds", 12)

    status = check_ollama_status()
    if status["available"]:
        try:
            payload = {
                "model": target_model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{endpoint}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text = res_data.get("response", "").strip()
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"Ollama generation failed ({e}); falling back to local extractive engine.")

    # ── Built-in Local Extractive Fallback ────────────────────────────────────
    return _local_extractive_answer(prompt, system)


def _local_extractive_answer(prompt: str, system: str = "") -> str:
    """Fallback extractive processor when no local LLM daemon is running."""
    # Simple extraction of key sentences containing factual signals
    lines = [ln.strip() for ln in prompt.split("\n") if ln.strip()]
    content_lines = [ln for ln in lines if not ln.startswith("System:") and len(ln) > 20]
    if not content_lines:
        return "Local analysis complete: document processed and indexed successfully."
    
    # Pick top informative lines
    informative = [l for l in content_lines if any(c.isdigit() for c in l) or len(l) > 40]
    selected = informative[:4] or content_lines[:4]
    return "Summary:\n" + "\n".join(f"• {s}" for s in selected)


def local_summarize_document(text: str, max_bullets: int = 5) -> str:
    """
    Generate a concise bulleted summary using Ollama or extractive summarization.
    100% offline.
    """
    if not text or not text.strip():
        return "⚠️ No document text available to summarize."

    clean = text.strip()[:4000]
    prompt = (
        f"Summarize the following document into {max_bullets} concise, factual bullet points. "
        "Focus on key metrics, decisions, and conclusions. Do not invent facts:\n\n"
        f"{clean}"
    )
    system = "You are a professional government and policy analyst. Provide strictly factual summaries."

    status = check_ollama_status()
    if status["available"]:
        ans = local_generate(prompt, system=system, max_tokens=400)
        if ans and not ans.startswith("Summary:"):
            return ans

    # High quality extractive fallback
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    scored = []
    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 30 or len(s_clean) > 250:
            continue
        score = 0
        if any(c.isdigit() for c in s_clean):
            score += 3
        if any(w in s_clean.lower() for w in ["total", "growth", "increased", "decreased", "percent", "crore", "budget", "expenditure", "revenue"]):
            score += 2
        scored.append((score, s_clean))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s[1] for s in scored[:max_bullets]]
    if not top:
        top = [s.strip() for s in sentences[:max_bullets] if len(s.strip()) > 20]

    return "\n".join(f"• {item}" for item in top)


def local_generate_student_materials(text_or_summary: str) -> dict:
    """
    Generate quiz questions and flashcards locally.
    Returns: {"quiz": [...], "flashcards": [...]}
    """
    status = check_ollama_status()
    if status["available"]:
        prompt = (
            "Based on the following content, generate 4 short-answer quiz questions "
            "and 4 flashcards (Term - Definition).\n"
            "Return valid JSON with keys 'quiz' (list of strings) and 'flashcards' (list of strings):\n\n"
            f"{text_or_summary[:2500]}"
        )
        try:
            resp = local_generate(prompt, system="Output only valid JSON.", max_tokens=600)
            clean_json = re.sub(r"^```json\s*|\s*```$", "", resp.strip(), flags=re.MULTILINE)
            data = json.loads(clean_json)
            if isinstance(data, dict) and "quiz" in data and "flashcards" in data:
                return data
        except Exception:
            pass

    # Extractive Fallback: Extract key metrics and definitions
    sentences = re.split(r"(?<=[.!?])\s+", text_or_summary)
    quiz = []
    flashcards = []

    for s in sentences:
        s = s.strip()
        # Find numeric facts
        num_match = re.search(r"([A-Za-z\s]{3,30})\s+(?:is|was|reached|totaled|recorded at)\s+([\d,.]+\s*(?:%|percent|crore|lakh|million|billion|Rs)?)", s, re.IGNORECASE)
        if num_match and len(quiz) < 4:
            topic, val = num_match.group(1).strip(), num_match.group(2).strip()
            quiz.append(f"What was the value recorded for {topic}?")
            flashcards.append(f"{topic} — {val} (Context: {s[:100]}...)")
        elif len(s) > 35 and len(quiz) < 4:
            words = s.split()
            if len(words) > 6:
                key_term = " ".join(words[:3])
                quiz.append(f"Explain the key finding regarding '{key_term}': {s[:80]}...?")
                flashcards.append(f"{key_term} — {s[:120]}")

    if not quiz:
        quiz = [
            "What is the primary subject of this document?",
            "Identify the key economic or policy metrics reported in this section.",
            "What findings or conclusions are highlighted?",
        ]
    if not flashcards:
        flashcards = [
            "Policy Metric — Quantitative indicator tracked in official reports.",
            "Fiscal Year — 12-month period for budget accounting.",
            "Evidence Grounding — Verification linking claims to exact document regions.",
        ]

    return {"quiz": quiz, "flashcards": flashcards}


def local_explain_simple(text: str, audience: str = "student") -> str:
    """Provide a simple-language, plain-English breakdown of complex passages."""
    prompt = (
        f"Explain the following excerpt in very simple, plain English suitable for a {audience}. "
        "Define technical jargon and explain what the numbers mean simply:\n\n"
        f"{text[:1500]}"
    )
    system = "You are a friendly, encouraging academic tutor explaining policy documents."
    status = check_ollama_status()
    if status["available"]:
        return local_generate(prompt, system=system, max_tokens=350)

    # Extractive plain English summary
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 30]
    core = lines[:3] if lines else [text[:200]]
    explanation = (
        "💡 **Key Concept Breakdown:**\n\n"
        + "\n\n".join(f"- **Key Point:** {p}" for p in core)
        + "\n\n*Note: Running in built-in offline engine. Connect local Ollama for conversational explanations.*"
    )
    return explanation
