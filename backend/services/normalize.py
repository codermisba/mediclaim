"""Pure-Python normalisation helpers used by the agents.

Everything here is deterministic: no model calls, no network, no side effects.
Keeping it separate makes the "Gemini -> structured JSON -> deterministic
output" boundary explicit and makes validation reproducible.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9 ]+")

TITLES = {
    "dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "miss.",
    "prof", "prof.", "shri", "smt",
}

GENERIC_NAMES = {"patient", "name", "unknown", "n/a", "na", "not available", "none", "-"}


def clean_text(value: Any) -> str:
    """Trim, collapse whitespace and normalise unicode punctuation."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = unicodedata.normalize("NFKC", text)
    text = _WHITESPACE.sub(" ", text).strip(" \t\r\n|;,")
    return text


def is_blank(value: Any) -> bool:
    """True for values that carry no real information."""
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    text = clean_text(value)
    if not text:
        return True
    return text.lower() in GENERIC_NAMES or text.lower() in {
        "not specified", "not mentioned", "not provided", "not available",
        "unavailable", "missing", "tbd", "to be determined", "null", "nil",
    }


#: First occurrence of a medical credential marks the end of a person's name.
_CREDENTIAL = re.compile(
    r"\(?\b(?:MBBS|M\.?D\.?|M\.?S\.?|MDS|DNB|BDS|PhD|D\.?O|FMGE|MCI|NMC)\b",
    re.IGNORECASE,
)


def _strip_credentials(text: str) -> str:
    """Drop "(MBBS, MS (General Surgery))" / ", MS" style suffixes from a name."""
    match = _CREDENTIAL.search(text)
    if not match:
        return text
    # Cut before the credential and discard any bracket that opened before it.
    return text[: match.start()].split("(")[0].strip(" ,;-")


def normalize_person_name(value: Any) -> str:
    """Trim titles and qualifications, collapse spaces, keep the original casing style."""
    text = clean_text(value)
    if not text:
        return ""
    text = _strip_credentials(text)
    parts = [p for p in text.split(" ") if p]
    while parts and parts[0].lower().strip(".") in {t.strip(".") for t in TITLES}:
        parts = parts[1:]
    text = " ".join(parts)
    if not text:
        return clean_text(value)
    if text.isupper() and len(text) > 4:
        return " ".join(word.capitalize() for word in text.split(" "))
    return text


def normalize_gender(value: Any) -> str:
    text = clean_text(value).lower().replace(".", "")
    mapping = {
        "m": "Male", "male": "Male", "man": "Male",
        "f": "Female", "female": "Female", "woman": "Female",
        "o": "Other", "other": "Other", "x": "Other",
    }
    if text in mapping:
        return mapping[text]
    return clean_text(value).title() if text else ""


def normalize_identifier(value: Any) -> str:
    """Identifiers: drop spaces/dashes used as separators, keep alphanumerics."""
    text = clean_text(value).upper()
    text = re.sub(r"[\s\-_/.]+", "", text)
    return text


def normalize_currency(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    symbol_map = {
        "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR",
        "rupee": "INR", "india": "INR",
        "$": "USD", "usd": "USD", "us dollars": "USD", "dollar": "USD", "dollars": "USD",
        "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
        "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
        "د.إ": "AED", "aed": "AED", "dirham": "AED", "dirhams": "AED",
    }
    key = text.lower()
    if key in symbol_map:
        return symbol_map[key]
    match = re.match(r"^([A-Za-z]{3})$", text)
    return match.group(1).upper() if match else text.upper()


CURRENCY_SYMBOLS = {
    "INR": "Rs.", "USD": "$", "EUR": "EUR ", "GBP": "GBP ",
    "AED": "AED ", "SGD": "S$", "AUD": "A$", "CAD": "C$", "JPY": "JPY ",
}


def currency_symbol(code: str) -> str:
    return CURRENCY_SYMBOLS.get(normalize_currency(code), f"{code} " if code else "")


def format_money(amount: float, code: str) -> str:
    symbol = currency_symbol(code)
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f}"


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_AMOUNT_CLEAN = re.compile(r"[^\d\.\-]")


def parse_amount(value: Any) -> float:
    """Parse '1,23,456.50', '₹ 1200', 'USD 45.9' -> float. 0.0 when unusable."""
    if isinstance(value, (int, float)):
        amount = float(value)
        return round(amount, 2) if amount > 0 else 0.0
    text = clean_text(value)
    if not text:
        return 0.0
    negative = text.startswith("-") or (text.count("-") == 1 and not text.startswith("-"))
    text = _AMOUNT_CLEAN.sub("", text.replace(",", ""))
    if text in {"", "-", ".", "-."}:
        return 0.0
    try:
        amount = float(text)
    except ValueError:
        match = re.search(r"\d[\d,]*\.?\d*", clean_text(value))
        if not match:
            return 0.0
        amount = float(match.group(0).replace(",", ""))
    if negative and text.startswith("-"):
        amount = -abs(amount)
    return round(abs(amount), 2) if amount > 0 else 0.0


def format_amount(amount: float) -> str:
    return f"{amount:,.2f}"


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                "%d-%b-%Y", "%d %B %Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y",
                "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M", "%Y%m%d")


def parse_date(value: Any) -> Optional[date]:
    """Best-effort date parsing. Returns ``None`` when the value is unusable."""
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"[,]?\s*\d{1,2}:\d{2}\s*(am|pm)?.*$", "", text, flags=re.IGNORECASE).strip(" ,")
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # "12 March 2024" and "March 12, 2024" handled above; try bare month names.
    match = re.match(r"^(\d{1,2})[\s\-/]+([A-Za-z]+)[\s\-/,]+(\d{4})$", text)
    if match and match.group(2).lower() in _MONTHS:
        try:
            return date(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))
        except ValueError:
            return None
    # ISO-ish prefix inside longer strings.
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def normalize_date(value: Any) -> str:
    """Normalise any parseable date to ISO ``YYYY-MM-DD``; else keep cleaned text."""
    parsed = parse_date(value)
    if parsed:
        return parsed.isoformat()
    return clean_text(value)


def human_date(value: Any, fmt: str = "%d %b %Y") -> str:
    parsed = parse_date(value)
    if parsed:
        return parsed.strftime(fmt)
    return clean_text(value)


# ---------------------------------------------------------------------------
# Dotted-path helpers (used for missing_fields / field_sources)
# ---------------------------------------------------------------------------


def get_path(payload: Any, path: str) -> Any:
    node = payload
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            node = getattr(node, part, None)
        if node is None:
            return None
    return node


def set_path(payload: Any, path: str, value: Any) -> None:
    from pydantic import BaseModel

    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    node = payload
    for part in parts[:-1]:
        nxt = node.get(part) if isinstance(node, dict) else getattr(node, part, None)
        if not isinstance(nxt, (dict, BaseModel)):
            # The intermediate is missing or holds a scalar - replace it with a
            # container so the leaf can be written. Never write a bare key.
            nxt = {}
            if isinstance(node, dict):
                node[part] = nxt
            else:
                setattr(node, part, nxt)
        node = nxt
    last = parts[-1]
    if isinstance(node, dict):
        node[last] = value
    elif isinstance(node, BaseModel):
        setattr(node, last, value)


def collect_blank_paths(payload: Any, prefix: str = "") -> List[str]:
    """Every leaf path whose value is blank (empty string / 0.0 / empty list)."""
    from pydantic import BaseModel

    found: List[str] = []
    data = payload.model_dump() if isinstance(payload, BaseModel) else payload
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            found.extend(collect_blank_paths(value, prefix=f"{path}."))
        elif isinstance(value, list):
            if not value:
                found.append(path)
        else:
            if is_blank(value):
                found.append(path)
    return found


def humanise_path(path: str) -> str:
    return path.replace("_", " ").replace(".", " > ").title()


def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = str(item).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(str(item).strip())
    return result


def similar(a: str, b: str) -> bool:
    """Loose equality used to decide whether two values really conflict."""
    left, right = clean_text(a).lower(), clean_text(b).lower()
    if not left or not right:
        return False
    if left == right:
        return True
    strip = lambda text: re.sub(r"[^a-z0-9]+", "", text)  # noqa: E731
    return strip(left) == strip(right)


def word_overlap(a: str, b: str) -> float:
    """Token Jaccard overlap - used to judge whether names are 'the same'."""
    left = set(re.findall(r"[a-z0-9]+", clean_text(a).lower()))
    right = set(re.findall(r"[a-z0-9]+", clean_text(b).lower()))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def split_multi(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[;/|]|,(?![^(]*\))", value) if part.strip()]


def first_sentences(text: str, count: int = 2, limit: int = 320) -> str:
    """Trim free text to a bounded, display-friendly summary."""
    text = clean_text(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:count]).strip()
    if len(out) > limit:
        out = out[: limit - 1].rstrip() + "…"
    return out


def parse_pair(text: str) -> Tuple[str, str]:
    """Split 'Label: value' into its parts (used by the offline reader)."""
    if ":" not in text:
        return "", text
    label, _, value = text.partition(":")
    return clean_text(label), clean_text(value)


__all__ = [
    "clean_text", "is_blank", "normalize_person_name", "normalize_gender",
    "normalize_identifier", "normalize_currency", "currency_symbol", "format_money",
    "parse_amount", "format_amount", "parse_date", "normalize_date", "human_date",
    "get_path", "set_path", "collect_blank_paths", "humanise_path", "dedupe",
    "similar", "word_overlap", "split_multi", "first_sentences", "parse_pair",
    "CURRENCY_SYMBOLS", "normalize_text",
]


def normalize_text(value: Any) -> str:
    return clean_text(value)
