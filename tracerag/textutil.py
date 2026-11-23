"""
textutil.py – text normalisation helpers for TraceRAG.

Covers:
  - period normalisation  ("FY 2021-22", "2021-22", "FY22", "FY2022" → canonical "2021-22")
  - unit / scale normalisation  (lakh, crore, million, billion, %)
  - qualifier detection  ((P), (R), (RE), (BE))
  - light Porter-style stemming
  - stop-word filtering
  - synonym expansion (editable MAP at top of file)
  - IDF-weighted coverage scoring helper
"""

from __future__ import annotations
import re
import math
from typing import Optional

# ---------------------------------------------------------------------------
# Editable synonym map  (lower-case canonical → set of variants)
# ---------------------------------------------------------------------------
SYNONYM_MAP: dict[str, list[str]] = {
    "cpi": ["consumer price index", "retail inflation", "retail price"],
    "inflation": ["price rise", "inflationary", "price level"],
    "gdp": ["gross domestic product"],
    "fiscal deficit": ["budget deficit"],
    "revenue": ["income", "receipts"],
    "expenditure": ["spending", "expense", "outlay", "outgo"],
    "export": ["exports", "exported"],
    "import": ["imports", "imported"],
    "trade": ["bilateral trade", "commerce"],
    "production": ["produce", "output", "manufactured"],
    "onion": ["onions"],
    "tomato": ["tomatoes"],
    "registration": ["registrations"],
    "tax": ["taxes", "taxation"],
    "appeal": ["appeals"],
    "pending": ["pendency"],
    "crore": ["cr"],
    "lakh": ["lac"],
    "million": ["mn", "mil"],
    "billion": ["bn"],
    "per cent": ["percent", "percentage", "%"],
    "percentage points": ["pp", "ppt", "bps"],
}
# Build reverse map: variant → canonical
_VARIANT_TO_CANONICAL: dict[str, str] = {}
for _canon, _variants in SYNONYM_MAP.items():
    for _v in _variants:
        _VARIANT_TO_CANONICAL[_v.lower()] = _canon

# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------
STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall can of to in for on at by "
    "from with as this that it its he she they we i and or but not so "
    "also such what how when where which who whom".split()
)

# ---------------------------------------------------------------------------
# Qualifier patterns
# ---------------------------------------------------------------------------
QUALIFIER_PATTERN = re.compile(
    r"\(\s*(P|R|RE|BE|PE|AE|PA)\s*\)",
    re.IGNORECASE,
)
QUALIFIERS = {"P": "provisional", "R": "revised", "RE": "revised estimate",
              "BE": "budget estimate", "PE": "provisional estimate",
              "AE": "advance estimate", "PA": "provisional actual"}

# ---------------------------------------------------------------------------
# Period normalisation
# ---------------------------------------------------------------------------
# Patterns ordered from most specific to least
_PERIOD_PATTERNS: list[tuple[re.Pattern, str]] = [
    # FY 2021-22  /  FY2021-22
    (re.compile(r"\bFY\s*(\d{4})[–\-](\d{2,4})\b", re.I), "{y1}-{y2}"),
    # 2021-22  /  2021–22
    (re.compile(r"\b(\d{4})[–\-](\d{2,4})\b"), "{y1}-{y2}"),
    # FY22  /  FY2022  (single-year shorthand)
    (re.compile(r"\bFY\s*(\d{2,4})\b", re.I), "FYSHORT"),
    # April-December FY25  → "FY25 Apr-Dec" period marker (keep as-is for now)
]


def normalise_period(text: str) -> str:
    """Return canonical period string, e.g. '2021-22'."""
    # Try FY YYYY-YY / YYYY-YY patterns first
    m = re.search(r"\bFY\s*(\d{4})[–\-](\d{2,4})\b", text, re.I)
    if m:
        y1, y2 = m.group(1), m.group(2)
        y2 = _expand_year_suffix(y1, y2)
        return f"{y1}-{y2}"

    m = re.search(r"\b(\d{4})[–\-](\d{2,4})\b", text)
    if m:
        y1, y2 = m.group(1), m.group(2)
        y2 = _expand_year_suffix(y1, y2)
        return f"{y1}-{y2}"

    # FY22 / FY2022 shorthand
    m = re.search(r"\bFY\s*(\d{2,4})\b", text, re.I)
    if m:
        yr = m.group(1)
        if len(yr) == 2:
            full = int("20" + yr)
            return f"{full-1}-{yr}"
        else:
            # FY2022 → 2021-22
            full = int(yr)
            return f"{full-1}-{str(full)[2:]}"

    # Bare 4-digit year: treat as calendar year (not fiscal)
    m = re.search(r"\b(19|20)(\d{2})\b", text)
    if m:
        return m.group(0)  # e.g. "2024"

    return text.strip()


def _expand_year_suffix(y1: str, y2: str) -> str:
    """'2021', '22' → '22'; already 4-digit passes through."""
    if len(y2) == 4:
        return y2[-2:]
    return y2.zfill(2)


def extract_periods(text: str) -> list[str]:
    """Extract all period strings from text, normalised."""
    found = []
    # FY YYYY-YY
    for m in re.finditer(r"\bFY\s*(\d{4})[–\-](\d{2,4})\b", text, re.I):
        y1, y2 = m.group(1), _expand_year_suffix(m.group(1), m.group(2))
        found.append(f"{y1}-{y2}")
    # YYYY-YY
    for m in re.finditer(r"\b(\d{4})[–\-](\d{2,4})\b", text):
        y1, y2 = m.group(1), _expand_year_suffix(m.group(1), m.group(2))
        found.append(f"{y1}-{y2}")
    # FY22 shorthand
    for m in re.finditer(r"\bFY\s*(\d{2,4})\b", text, re.I):
        yr = m.group(1)
        if len(yr) == 2:
            full = int("20" + yr)
            found.append(f"{full-1}-{yr}")
        else:
            full = int(yr)
            found.append(f"{full-1}-{str(full)[2:]}")
    return list(dict.fromkeys(found))  # deduplicate, preserve order


def period_matches(query_period: str, fact_period: str) -> bool:
    """
    Exact period match by default.
    Decision: "2022" (calendar year) matches "2021-22" (fiscal year) only if
    the numeric year appears at the boundary, since these reports use Indian FY.
    We do NOT auto-match – callers must supply canonicalised periods.
    """
    if not query_period or not fact_period:
        return False
    q = query_period.strip().lower()
    f = fact_period.strip().lower()
    if q == f:
        return True
    # "fy24" vs "2023-24"
    q_norm = normalise_period(q)
    f_norm = normalise_period(f)
    return q_norm == f_norm


# ---------------------------------------------------------------------------
# Unit / scale normalisation
# ---------------------------------------------------------------------------
UNIT_SCALE = {
    "lakh": 1e5,
    "lac": 1e5,
    "crore": 1e7,
    "cr": 1e7,
    "million": 1e6,
    "mn": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "trillion": 1e12,
}
UNIT_FAMILY = {
    "lakh": "INR", "lac": "INR", "crore": "INR", "cr": "INR",
    "million": "generic", "mn": "generic", "billion": "generic", "bn": "generic",
    "trillion": "generic",
    "%": "pct", "per cent": "pct", "percent": "pct", "percentage": "pct",
    "percentage points": "pp", "pp": "pp", "ppt": "pp", "bps": "pp",
    "usd": "USD", "us$": "USD", "$": "USD",
    "₹": "INR", "rs": "INR", "inr": "INR",
    "mt": "weight", "million tonnes": "weight", "lakh tonnes": "weight",
    "kg": "weight", "tonnes": "weight",
    "mm": "length", "cm": "length", "km": "length",
}


def normalise_unit(unit_str: str) -> str:
    """Return canonical unit string."""
    u = unit_str.strip().lower()
    return UNIT_FAMILY.get(u, u)


def parse_number(text: str) -> Optional[float]:
    """
    Parse a potentially formatted number like '10,08,558' or '1.3 lakh'.
    Returns None if unparseable.
    """
    text = text.strip()
    # Remove currency symbols
    text = re.sub(r"[₹$€£]", "", text)
    # Remove thousand-separators (Indian: 10,08,558)
    num_part = re.sub(r",", "", text)
    # Try direct float
    m = re.match(r"^\s*([+-]?\d+\.?\d*)\s*$", num_part)
    if m:
        return float(m.group(1))
    return None


def scale_value(value: float, unit: str) -> float:
    """Scale value to base unit (ones)."""
    u = unit.strip().lower()
    for k, s in UNIT_SCALE.items():
        if k in u:
            return value * s
    return value


# ---------------------------------------------------------------------------
# Stemming (Porter light)
# ---------------------------------------------------------------------------
def _stem(word: str) -> str:
    """Very light suffix stripping – enough for Indian report vocabulary."""
    w = word.lower()
    if len(w) <= 3:
        return w
    # -ing
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    # -tion / -sion → t/s
    if w.endswith("tion"):
        return w[:-3]
    if w.endswith("sion"):
        return w[:-3]
    # -ed
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    # -ness
    if w.endswith("ness"):
        return w[:-4]
    # -ly
    if w.endswith("ly") and len(w) > 4:
        return w[:-2]
    # -s (but not -ss, -us, -is)
    if w.endswith("s") and not w.endswith(("ss", "us", "is", "as")):
        return w[:-1]
    return w


def stem(word: str) -> str:
    return _stem(word)


# ---------------------------------------------------------------------------
# Tokenisation + normalisation pipeline
# ---------------------------------------------------------------------------
def tokenise(text: str, stem_tokens: bool = True, remove_stops: bool = True) -> list[str]:
    """
    Lowercase, remove punctuation (keep hyphens in fiscal years), split,
    optionally stem and remove stop words.
    """
    # Preserve fiscal-year strings like 2021-22
    text = re.sub(r"[^\w\s\-/%.₹$]", " ", text.lower())
    tokens = text.split()
    result = []
    for tok in tokens:
        # strip leading/trailing hyphens
        tok = tok.strip("-")
        if not tok:
            continue
        if remove_stops and tok in STOP_WORDS:
            continue
        if stem_tokens:
            tok = _stem(tok)
        result.append(tok)
    return result


def expand_synonyms(tokens: list[str]) -> list[str]:
    """Add canonical forms for known variant tokens."""
    extra = []
    text = " ".join(tokens)
    for variant, canon in _VARIANT_TO_CANONICAL.items():
        if variant in text:
            extra.extend(tokenise(canon, stem_tokens=True, remove_stops=False))
    return tokens + extra


# ---------------------------------------------------------------------------
# Qualifier extraction
# ---------------------------------------------------------------------------
def extract_qualifiers(text: str) -> list[str]:
    """Return list of qualifier codes found in text, e.g. ['RE', 'P']."""
    return [m.group(1).upper() for m in QUALIFIER_PATTERN.finditer(text)]


# ---------------------------------------------------------------------------
# IDF helper (computed over a corpus at build time)
# ---------------------------------------------------------------------------

def compute_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Compute IDF weights for a token corpus (list of tokenised docs)."""
    N = len(corpus)
    df: dict[str, int] = {}
    for doc in corpus:
        for tok in set(doc):
            df[tok] = df.get(tok, 0) + 1
    idf: dict[str, float] = {}
    for tok, freq in df.items():
        idf[tok] = math.log((N + 1) / (freq + 1)) + 1.0
    return idf


def idf_coverage_score(query_tokens: list[str], doc_tokens: list[str],
                        idf: dict[str, float]) -> float:
    """
    IDF-weighted fraction of query tokens covered by doc_tokens.
    Returns 0.0–1.0.
    """
    doc_set = set(doc_tokens)
    total_weight = sum(idf.get(t, 1.0) for t in query_tokens)
    if total_weight == 0:
        return 0.0
    matched_weight = sum(idf.get(t, 1.0) for t in query_tokens if t in doc_set)
    return matched_weight / total_weight


def unseen_term_check(query_tokens: list[str], corpus_vocab: set[str]) -> list[str]:
    """Return query tokens that do not appear anywhere in the corpus."""
    return [t for t in query_tokens if t not in corpus_vocab]


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Remove excessive whitespace, ligatures, control chars."""
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sentence_split(text: str) -> list[str]:
    """Split text into sentences (simple rule-based)."""
    # Split on ". " followed by capital letter or digit
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹])", text)
    return [p.strip() for p in parts if len(p.strip()) > 10]
