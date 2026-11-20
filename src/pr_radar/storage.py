"""DuckDB storage with an append-only Parquet archive.

The DuckDB file is a local working copy. Every collection run also writes the rows
it touched to data/archive/*.parquet. Those small files are committed by the weekly
GitHub Actions job, so history survives without a database server, and a fresh
checkout rebuilds the database from them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import duckdb

from .config import Settings
from .matching import BrandMatcher, TopicMatcher
from .models import Article

log = logging.getLogger(__name__)

COLUMNS = (
    "id",
    "title",
    "url",
    "source_name",
    "source_domain",
    "published_at",
    "language",
    "country",
    "collector",
    "brands",
    "topics",
    "cluster_id",
    "first_seen_at",
    "headline_brands",
)

# Uniqueness of id is enforced by upsert(); no PRIMARY KEY so list columns can be
# updated in place without DuckDB's index constraint checks.
SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            VARCHAR NOT NULL,
    title         VARCHAR NOT NULL,
    url           VARCHAR,
    source_name   VARCHAR,
    source_domain VARCHAR,
    published_at  TIMESTAMP NOT NULL,
    language      VARCHAR,
    country       VARCHAR,
    collector     VARCHAR,
    brands        VARCHAR[],
    topics        VARCHAR[],
    cluster_id    VARCHAR,
    first_seen_at TIMESTAMP NOT NULL,
    headline_brands VARCHAR[]
);
-- Aspect-level sentiment (DimABSA): one row per article x brand named in the headline.
CREATE TABLE IF NOT EXISTS aspect_sentiment (
    article_id VARCHAR NOT NULL,
    brand      VARCHAR NOT NULL,
    aspect     VARCHAR NOT NULL,
    valence    DOUBLE NOT NULL,
    arousal    DOUBLE NOT NULL,
    model      VARCHAR NOT NULL,
    scored_at  TIMESTAMP NOT NULL
);
"""


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


class Store:
    def __init__(self, path: str | Path = ":memory:", read_only: bool = False) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path, read_only=read_only)
        if not read_only:
            self.con.execute(SCHEMA)
            # Migration for databases created before headline_brands existed.
            self.con.execute(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS headline_brands VARCHAR[]"
            )

    def close(self) -> None:
        self.con.close()

    def count(self) -> int:
        return self.con.execute("SELECT count(*) FROM articles").fetchone()[0]

    def recent_titles(self, since: datetime) -> list[tuple[str, str]]:
        return self.con.execute(
            "SELECT cluster_id, title FROM articles WHERE published_at >= ?", [since]
        ).fetchall()

    def upsert(self, articles: Iterable[Article], now: datetime) -> tuple[int, int]:
        """Insert new articles; for known ones merge brands/topics. Returns (inserted, updated)."""
        batch = list(articles)
        if not batch:
            return 0, 0
        ids = [a.id for a in batch]
        existing = {
            row[0]: row
            for row in self.con.execute(
                "SELECT id, brands, topics FROM articles WHERE list_contains(?::VARCHAR[], id)",
                [ids],
            ).fetchall()
        }

        inserts, updates = [], []
        for a in batch:
            if a.id in existing:
                _, old_brands, old_topics = existing[a.id]
                brands = sorted(set(old_brands or []) | set(a.brands))
                topics = sorted(set(old_topics or []) | set(a.topics))
                if brands != sorted(old_brands or []) or topics != sorted(old_topics or []):
                    updates.append((brands, topics, a.language, a.country, a.id))
            else:
                inserts.append(
                    (
                        a.id,
                        a.title,
                        a.url,
                        a.source_name,
                        a.source_domain,
                        a.published_at,
                        a.language,
                        a.country,
                        a.collector,
                        sorted(a.brands),
                        sorted(a.topics),
                        a.cluster_id or a.id,
                        now,
                        sorted(a.headline_brands),
                    )
                )

        placeholders = ", ".join("?" for _ in COLUMNS)
        self.con.execute("BEGIN TRANSACTION")
        try:
            if inserts:
                self.con.executemany(
                    f"INSERT INTO articles ({', '.join(COLUMNS)}) VALUES ({placeholders})",
                    inserts,
                )
            if updates:
                self.con.executemany(
                    """UPDATE articles
                       SET brands = ?, topics = ?,
                           language = coalesce(language, ?), country = coalesce(country, ?)
                       WHERE id = ?""",
                    updates,
                )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return len(inserts), len(updates)

    def refresh_tags(self, settings: Settings) -> int:
        """Re-derive everything that comes from the config, for the whole history.

        Headline brands and topics depend only on the title and config/brands.yaml,
        so editing aliases, exclusions or the topic taxonomy re-tags old coverage
        too. Articles from excluded outlets are deleted. Returns rows changed.
        """
        excluded = sorted({d.lower() for d in settings.exclude_domains})
        changed = 0
        if excluded:
            changed += self.con.execute(
                "DELETE FROM articles WHERE list_contains(?::VARCHAR[], source_domain)",
                [excluded],
            ).fetchone()[0]
        brands, topics = BrandMatcher(settings.brands), TopicMatcher(settings.topics)
        updates = []
        rows = self.con.execute(
            "SELECT id, title, brands, topics, headline_brands FROM articles"
        ).fetchall()
        for id_, title, old_brands, old_topics, old_headline in rows:
            headline = sorted(brands.match(title))
            new_brands = sorted(set(old_brands or []) | set(headline))
            new_topics = topics.match(title)
            if (headline, new_brands, new_topics) != (
                sorted(old_headline or []) if old_headline is not None else None,
                sorted(old_brands or []),
                sorted(old_topics or []),
            ):
                updates.append((headline, new_brands, new_topics, id_))
        if updates:
            self.con.executemany(
                "UPDATE articles SET headline_brands = ?, brands = ?, topics = ? WHERE id = ?",
                updates,
            )
        return changed + len(updates)

    def unscored_headline_mentions(self, model: str) -> list[tuple[str, str, str]]:
        """(article_id, title, brand) for headline mentions this model has not scored."""
        return self.con.execute(
            """
            WITH h AS (
                SELECT id, title, unnest(headline_brands) AS brand
                FROM articles WHERE headline_brands IS NOT NULL
            )
            SELECT h.id, h.title, h.brand FROM h
            ANTI JOIN aspect_sentiment s
                ON s.article_id = h.id AND s.brand = h.brand AND s.model = ?
            ORDER BY h.id, h.brand
            """,
            [model],
        ).fetchall()

    def save_sentiment(self, rows: list[tuple], model: str, now: datetime) -> int:
        """rows: (article_id, brand, aspect, valence, arousal)."""
        if rows:
            self.con.executemany(
                "INSERT INTO aspect_sentiment VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(*r, model, now) for r in rows],
            )
        return len(rows)

    # -- archive -------------------------------------------------------------------

    def export_archive(
        self, ids: Iterable[str], archive_dir: str | Path, run_at: datetime
    ) -> Path | None:
        ids = sorted(set(ids))
        if not ids:
            return None
        archive = Path(archive_dir)
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"articles_{run_at:%Y%m%dT%H%M%S}.parquet"
        self.con.execute(
            "CREATE OR REPLACE TEMP TABLE _touched AS SELECT unnest(?::VARCHAR[]) AS id", [ids]
        )
        self.con.execute(
            f"""COPY (SELECT a.* FROM articles a JOIN _touched USING (id) ORDER BY a.id)
                TO '{_sql_path(target)}' (FORMAT parquet)"""
        )
        self.con.execute("DROP TABLE _touched")
        return target

    def bootstrap_from_archive(self, archive_dir: str | Path) -> int:
        """Rebuild an empty database from the Parquet archive (latest row per id wins)."""
        archive = Path(archive_dir)
        if self.count() > 0 or not any(archive.glob("articles_*.parquet")):
            return 0
        pattern = _sql_path(archive) + "/articles_*.parquet"
        self.con.execute(
            f"""INSERT INTO articles BY NAME
                SELECT * EXCLUDE (filename, rn) FROM (
                    SELECT *, row_number() OVER (PARTITION BY id ORDER BY filename DESC) AS rn
                    FROM read_parquet('{pattern}', filename = true, union_by_name = true)
                ) WHERE rn = 1"""
        )
        restored = self.count()
        log.info("Restored %d articles from %s", restored, archive)
        return restored
