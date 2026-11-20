import json
import math

import pytest

from pr_radar.sentiment.data import (
    format_va,
    load_domain_set,
    load_split,
    parse_va,
    records_to_examples,
)
from pr_radar.sentiment.metrics import D_MAX, evaluate, pearson, rmse_va


def test_va_parsing_and_formatting():
    assert parse_va("6.75#6.38") == (6.75, 6.38)
    assert format_va(9.4, 0.2) == "9.00#1.00"  # clipped to the official range


def test_all_three_record_shapes_and_null_aspects():
    records = [
        {"ID": "1", "Text": "great food", "Aspect_VA": [{"Aspect": "food", "VA": "7.5#6.0"}]},
        {
            "ID": "2",
            "Text": "slow service",
            "Triplet": [{"Aspect": "service", "Opinion": "slow", "VA": "3#5"}],
        },
        {
            "ID": "3",
            "Text": "can't wait to go back",
            "Quadruplet": [
                {"Aspect": "NULL", "Opinion": "NULL", "Category": "X#Y", "VA": "7#7"},
                {"Aspect": "back", "Opinion": "NULL", "Category": "X#Y", "VA": "6#6"},
            ],
        },
    ]
    ex = records_to_examples(records, "eng", "restaurant")
    assert [(e.aspect, e.valence, e.arousal) for e in ex] == [
        ("food", 7.5, 6.0),
        ("service", 3.0, 5.0),
        ("back", 6.0, 6.0),
    ]
    assert ex[0].lang == "eng" and ex[0].domain == "restaurant"


def test_load_split_discovers_official_layout(tmp_path):
    folder = tmp_path / "task-dataset/track_a/subtask_1/eng"
    folder.mkdir(parents=True)
    rec = {"ID": "a", "Text": "nice", "Aspect_VA": [{"Aspect": "nice", "VA": "7#5"}]}
    for name in ("eng_laptop_train_alltasks.jsonl", "eng_laptop_dev_task1.jsonl", "README.md"):
        (folder / name).write_text(json.dumps(rec) + "\n", encoding="utf-8")
    train = load_split(tmp_path, "train")
    assert list(train) == [("eng", "laptop")] and len(train[("eng", "laptop")]) == 1
    assert list(load_split(tmp_path, "test")) == []


def test_domain_set_loader(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text(
        json.dumps(
            {
                "ID": "x",
                "Text": "FOREO deal",
                "Language": "en",
                "Quadruplet": [
                    {"Aspect": "deal", "Category": "B#P", "Opinion": "NULL", "VA": "7#6"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (ex,) = load_domain_set(path)
    assert ex.lang == "en" and ex.domain == "beautytech_news" and ex.valence == 7.0


def test_metrics_match_official_definition():
    gold, pred = [(5.0, 5.0), (7.0, 3.0)], [(6.0, 5.0), (7.0, 5.0)]
    # sqrt((1 + 4) / 2)
    assert rmse_va(gold, pred, normalize=False) == pytest.approx(math.sqrt(2.5))
    assert rmse_va(gold, pred) == pytest.approx(math.sqrt(2.5) / D_MAX)
    assert rmse_va([(1, 1)], [(9, 9)]) == pytest.approx(1.0)  # worst case normalises to 1
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert evaluate(gold, gold)["rmse_norm"] == 0
