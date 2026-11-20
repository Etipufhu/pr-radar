from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from pr_radar.config import load_config
from pr_radar.models import Article
from pr_radar.storage import Store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings():
    return load_config(ROOT / "config" / "brands.yaml")


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def make_article(
    title: str,
    domain: str,
    brands: list[str],
    published: datetime,
    country: str = "US",
    topics: list[str] | None = None,
    collector: str = "gdelt",
) -> Article:
    return Article(
        title=title,
        url=f"https://{domain}/{abs(hash(title))}",
        source_name=domain,
        source_domain=domain,
        published_at=published,
        collector=collector,
        query_brand=brands[0],
        language="en",
        country=country,
        brands=list(brands),
        topics=topics or [],
    )
