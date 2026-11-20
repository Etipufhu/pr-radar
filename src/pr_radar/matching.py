"""Brand and topic tagging with Unicode-aware word boundaries."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .config import Brand


def _compile(terms: Iterable[str], *, prefix: bool) -> re.Pattern[str] | None:
    """Match any term starting at a word boundary.

    prefix=True lets "sustainab" match "sustainability"; prefix=False requires the
    term to end at a word boundary too, so "FOREO" does not match "foreordained".
    """
    cleaned = sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)
    if not cleaned:
        return None
    body = "|".join(re.escape(t) for t in cleaned)
    tail = "" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w)(?:{body}){tail}", re.IGNORECASE)


class BrandMatcher:
    def __init__(self, brands: Iterable[Brand]) -> None:
        self._rules = [
            (b.id, _compile(b.match_terms, prefix=False), _compile(b.exclude, prefix=False))
            for b in brands
        ]

    def match(self, text: str) -> list[str]:
        return list(self.find(text))

    def find(self, text: str) -> dict[str, str]:
        """Brand id -> the exact text that matched (used as the sentiment aspect)."""
        found: dict[str, str] = {}
        for brand_id, pattern, exclude in self._rules:
            hit = pattern.search(text) if pattern else None
            if hit and not (exclude and exclude.search(text)):
                found[brand_id] = hit.group(0)
        return found


class TopicMatcher:
    def __init__(self, topics: dict[str, list[str]]) -> None:
        self._rules = [(name, _compile(words, prefix=True)) for name, words in topics.items()]

    def match(self, text: str) -> list[str]:
        # Pad so keywords with a trailing space ("led ") also match at the end of a title.
        padded = f"{text} "
        return [name for name, pattern in self._rules if pattern and pattern.search(padded)]
