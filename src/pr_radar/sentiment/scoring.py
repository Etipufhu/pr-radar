"""Score brand mentions in headlines with the trained DimASR model."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings
from ..matching import BrandMatcher
from ..storage import Store

log = logging.getLogger(__name__)


def model_id(model_dir: str | Path) -> str:
    return Path(model_dir).name


def score_new_mentions(
    store: Store, settings: Settings, model_dir: str | Path, predict=None
) -> int:
    """Score every headline brand mention not yet scored by this model.

    The aspect is the brand name exactly as written in the headline, so the model
    rates how the headline talks about that brand. `predict(aspects, texts)` can be
    injected for tests; by default the model in `model_dir` is loaded.
    """
    pending = store.unscored_headline_mentions(model_id(model_dir))
    if not pending:
        return 0
    matcher = BrandMatcher(settings.brands)
    aspects = [
        matcher.find(title).get(brand, settings.brand_names.get(brand, brand))
        for _, title, brand in pending
    ]
    titles = [title for _, title, _ in pending]
    if predict is None:
        from .model import VARegressor

        predict = VARegressor.load(model_dir).predict
    scores = predict(aspects, titles)
    rows = [
        (article_id, brand, aspect, round(v, 2), round(a, 2))
        for (article_id, _, brand), aspect, (v, a) in zip(pending, aspects, scores, strict=True)
    ]
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    saved = store.save_sentiment(rows, model_id(model_dir), now)
    log.info("scored %d headline brand mentions with %s", saved, model_id(model_dir))
    return saved
