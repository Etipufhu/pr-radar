"""Core data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .text import article_id


@dataclass
class Article:
    title: str
    url: str
    source_name: str
    source_domain: str
    published_at: datetime  # naive UTC
    collector: str  # "google_news" | "gdelt" | "rss"
    query_brand: str
    language: str | None = None
    country: str | None = None
    brands: list[str] = field(default_factory=list)
    headline_brands: list[str] = field(default_factory=list)  # named in the title itself
    topics: list[str] = field(default_factory=list)
    cluster_id: str | None = None

    @property
    def id(self) -> str:
        """Stable id: the same headline from the same outlet is the same article,
        whichever collector or market edition found it."""
        return article_id(self.title, self.source_domain or self.source_name.lower())
