"""
study/youtube.py – Offline Local Media & Topic Study Guide.

Mode A: generate search queries without calling external APIs.
Mode B: disabled in offline mode.
Government mode: strictly returns blocked status.
"""

from __future__ import annotations

import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = ""
DISCLAIMER = "Recommendations are external and not verified against your document."


def recommendations_for_topic(
    topic: dict,
    n: int = 3,
) -> list[dict]:
    """
    Return video recommendations for topic.
    Strictly blocked in government mode.
    """
    try:
        from config import is_government_mode
        if is_government_mode():
            return [{
                "title":   "YouTube recommendations disabled in Government offline mode.",
                "url":     "#",
                "channel": "",
                "duration":"",
                "mode":    "blocked",
                "query":   "",
                "note":    "External network access is blocked in Government mode.",
            }]
    except ImportError:
        pass

    title = topic.get("title", "Topic")
    query = re.sub(r"(?i)(ignore|system|prompt|instruction)", "", title).strip()[:80]
    encoded = urllib.parse.quote_plus(query)

    return [{
        "title":   f"Study Video: {query}",
        "url":     f"https://www.youtube.com/results?search_query={encoded}",
        "channel": "Educational Search",
        "duration":"",
        "mode":    "A",
        "query":   query,
        "note":    DISCLAIMER,
    } for _ in range(min(n, 3))]
