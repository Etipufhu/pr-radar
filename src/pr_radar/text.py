"""Text and URL normalisation helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def domain_of(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def article_id(title: str, outlet: str) -> str:
    key = f"{normalize_title(title)}|{outlet}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def strip_source_suffix(title: str, source_name: str) -> str:
    """Google News appends ' - Publisher' to every headline."""
    if source_name:
        suffix = f" - {source_name}"
        if title.endswith(suffix):
            return title[: -len(suffix)].rstrip()
    return title.strip()
