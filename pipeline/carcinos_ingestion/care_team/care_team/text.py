"""Text cleanup and exact-quote matching used by the validator."""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"})
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def clean_source_text(raw: str | None) -> str:
    """Strip XML/HTML tags and entities, collapse whitespace. Keeps the words intact."""
    if not raw:
        return ""
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def normalize(s: str) -> str:
    """Lowercase, unify dashes/quotes, collapse whitespace — for matching only."""
    s = (s or "").translate(_DASHES).translate(_QUOTES).lower()
    return _WS.sub(" ", s).strip().strip(" .;,")


def quote_in(quote: str, haystack: str, min_len: int = 12) -> bool:
    """True if `quote` appears word for word in `haystack` (after normalization).

    Very short quotes are rejected: they would match almost anything.
    """
    q = normalize(quote)
    if len(q) < min_len:
        return False
    return q in normalize(haystack)


def numbers_in(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))
