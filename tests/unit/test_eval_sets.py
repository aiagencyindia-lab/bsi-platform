import json
from collections import Counter
from pathlib import Path

from bsi_core.matching import Entity, find_mentions

STATUSES = {"recommended", "listed", "mentioned", "negative"}
INJECTION_ENTITIES = [
    Entity("nike", "brand", ("Nike",)),
    Entity("adidas", "competitor", ("Adidas",)),
    Entity("puma", "competitor", ("Puma",)),
    Entity("skechers", "competitor", ("Skechers",)),
]


def rows(name):
    return [
        json.loads(line)
        for line in Path(f"eval/{name}").read_text().splitlines()
        if line.strip()
    ]


def test_injection_set_shape_and_matcher_agreement():
    injection = rows("injection_v0.jsonl")
    assert len(injection) == 30
    assert len({r["id"] for r in injection}) == 30
    styles = Counter(r["style"] for r in injection)
    assert set(styles) == {
        "direct",
        "fake_system",
        "grader",
        "roleplay",
        "quoted",
        "hindi",
        "push_down",
        "over_correction",
    }
    assert min(styles.values()) >= 2
    for r in injection:
        hits = {
            h.entity_id for h in find_mentions(r["text"], INJECTION_ENTITIES)
        }
        assert set(r["expected"]) == hits, r["id"]
        assert set(r["expected"].values()) <= STATUSES, r["id"]


def test_clean_set_covers_every_benchmark_mention():
    benchmark = {r["observation_id"]: r for r in rows("benchmark_v0.jsonl")}
    clean = rows("rec_labels_v0.jsonl")
    assert len(clean) == len(benchmark) == 30
    for r in clean:
        assert set(r["expected"]) == set(
            benchmark[r["observation_id"]]["expected"]
        ), r["observation_id"]
        assert set(r["expected"].values()) <= STATUSES, r["observation_id"]


def test_both_sets_are_reviewed():
    for name in ("injection_v0.jsonl", "rec_labels_v0.jsonl"):
        assert all(r["reviewed"] for r in rows(name)), name
