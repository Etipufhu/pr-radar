"""Language and country normalisation."""

from __future__ import annotations

from functools import lru_cache

import pycountry
from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0  # deterministic results

# GDELT uses everyday country names; a few differ from ISO 3166 names.
_COUNTRY_OVERRIDES = {
    "turkey": "TR",
    "russia": "RU",
    "south korea": "KR",
    "north korea": "KP",
    "vietnam": "VN",
    "iran": "IR",
    "taiwan": "TW",
    "czech republic": "CZ",
    "bolivia": "BO",
    "venezuela": "VE",
    "tanzania": "TZ",
    "syria": "SY",
    "laos": "LA",
    "moldova": "MD",
    "macedonia": "MK",
    "united kingdom": "GB",
    "hong kong": "HK",
}


def detect_language(text: str, min_chars: int = 15, min_prob: float = 0.9) -> str | None:
    """Return an ISO 639-1 code, or None when the text is too short or ambiguous."""
    if not text or len(text.strip()) < min_chars:
        return None
    try:
        best = detect_langs(text)[0]
    except (LangDetectException, IndexError):
        return None
    if best.prob < min_prob:
        return None
    return best.lang.split("-")[0]


@lru_cache(maxsize=512)
def language_name_to_code(name: str | None) -> str | None:
    if not name:
        return None
    try:
        lang = pycountry.languages.lookup(name)
    except LookupError:
        return None
    return getattr(lang, "alpha_2", None) or lang.alpha_3


@lru_cache(maxsize=512)
def country_name_to_code(name: str | None) -> str | None:
    if not name:
        return None
    override = _COUNTRY_OVERRIDES.get(name.strip().lower())
    if override:
        return override
    try:
        return pycountry.countries.lookup(name).alpha_2
    except LookupError:
        return None
