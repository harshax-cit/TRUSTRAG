"""
study/youtube.py – YouTube recommendations per topic.

Mode A (default): generate YouTube search result URLs only.
Mode B (if YOUTUBE_API_KEY set): call YouTube Data API v3.

NEVER invents video titles or IDs.
NEVER sends document text to YouTube — only short topic queries.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from typing import Optional

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# Simple in-memory cache: query_hash → results
_cache: dict[str, list[dict]] = {}

# Visible note added to every recommendation
DISCLAIMER = "Recommendations are external and not verified against your document."


def recommendations_for_topic(
    topic: dict,
    n: int = 3,
) -> list[dict]:
    """
    Return n video recommendations for a topic.
    Blocked entirely in government mode (no external calls).
    """
    # Government mode: no external calls allowed
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

    query = _build_query(topic)
    if not query:
        return []

    cache_key = hashlib.md5(query.encode()).hexdigest()
    if cache_key in _cache:
        return _cache[cache_key]

    if YOUTUBE_API_KEY:
        try:
            results = _mode_b(query, n)
            _cache[cache_key] = results
            return results
        except Exception:
            pass  # fall back to Mode A

    results = _mode_a(query, n)
    _cache[cache_key] = results
    return results


def _build_query(topic: dict) -> str:
    """
    Build a URL-safe search query from topic title + top key terms.
    Length-limited to 100 chars. Never contains document text.
    """
    title = topic.get("title", "")
    # Strip anything that looks like an instruction
    title = re.sub(r"(?i)(ignore|system|prompt|instruction)", "", title)
    title = title.strip()[:80]

    # Add top key terms from key_numbers
    terms = []
    for num in topic.get("key_numbers", [])[:2]:
        unit = num.get("unit", "")
        if unit and len(unit) > 2:
            terms.append(unit)

    query = title
    if terms:
        query += " " + " ".join(terms[:2])

    query = query.strip()[:100]
    return query if len(query) >= 3 else ""


def _mode_a(query: str, n: int) -> list[dict]:
    """Generate YouTube search result URLs — no API call."""
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://www.youtube.com/results?search_query={encoded}"
    return [
        {
            "title":    f"Search YouTube for: {query}",
            "url":      url,
            "channel":  "",
            "duration": "",
            "mode":     "A",
            "query":    query,
            "note":     DISCLAIMER,
        }
    ] * min(n, 1)  # one search link per topic in Mode A


def _mode_b(query: str, n: int) -> list[dict]:
    """
    Call YouTube Data API v3. Only returns IDs from the API response.
    Key is never logged or shown in the UI.
    """
    import urllib.request

    encoded = urllib.parse.quote_plus(query)
    # Build URL — key kept server-side, never in logs
    api_url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&safeSearch=strict"
        f"&videoEmbeddable=true&maxResults={n}"
        f"&q={encoded}"
        f"&key={YOUTUBE_API_KEY}"
    )

    with urllib.request.urlopen(api_url, timeout=5) as resp:
        import json
        data = json.loads(resp.read())

    results = []
    for item in data.get("items", [])[:n]:
        vid_id  = item["id"].get("videoId", "")
        snippet = item.get("snippet", {})
        if not vid_id:
            continue
        # Only use IDs returned by the API
        results.append({
            "title":    snippet.get("title", ""),
            "url":      f"https://www.youtube.com/watch?v={vid_id}",
            "channel":  snippet.get("channelTitle", ""),
            "duration": "",   # would need a separate contentDetails call
            "mode":     "B",
            "query":    query,
            "note":     DISCLAIMER,
        })

    return results if results else _mode_a(query, n)
