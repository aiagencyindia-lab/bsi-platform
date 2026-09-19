from bsi_core.extraction import EntityJudgement, ExtractionOut, apply_sanity
from bsi_core.matching import Entity, find_mentions

NIKE = Entity("n", "brand", ("Nike",))
ADIDAS = Entity("a", "competitor", ("Adidas", "Adi"))
PUMA = Entity("p", "competitor", ("Puma",))
ALL = [NIKE, ADIDAS, PUMA]
TEXT = "Adidas first, then Nike, then Puma. Nike again."


def judged(name, rec="listed", sentiment="neutral"):
    return EntityJudgement(
        name=name,
        position=9,
        rec_status=rec,
        sentiment=sentiment,
        sentiment_conf=0.8,
    )


def test_matcher_only_when_no_model_output():
    rows, notes = apply_sanity(find_mentions(TEXT, ALL), ALL, None)
    assert [(r.entity.id, r.position) for r in rows] == [
        ("a", 1),
        ("n", 2),
        ("p", 3),
    ]
    assert {r.rec_status for r in rows} == {"mentioned"}
    assert notes == []


def test_model_labels_are_used_but_position_is_the_matchers():
    out = ExtractionOut(entities=[judged("nike", "recommended", "positive")])
    rows, notes = apply_sanity(find_mentions(TEXT, ALL), ALL, out)
    nike = next(r for r in rows if r.entity.id == "n")
    assert (nike.position, nike.rec_status, nike.sentiment) == (
        2,
        "recommended",
        "positive",
    )
    assert sorted(notes) == ["matcher_only:Adidas", "matcher_only:Puma"]


def test_model_only_entities_are_not_counted():
    out = ExtractionOut(entities=[judged("Reebok"), judged("Puma")])
    rows, notes = apply_sanity(find_mentions("Only Nike here", ALL), ALL, out)
    assert [r.entity.id for r in rows] == ["n"]
    assert sorted(notes) == [
        "matcher_only:Nike",
        "model_only:Puma",
        "model_only:Reebok",
    ]


def test_model_may_name_an_entity_by_alias():
    out = ExtractionOut(entities=[judged("ADI", "negative")])
    rows, _ = apply_sanity(find_mentions("Adidas", ALL), ALL, out)
    assert rows[0].rec_status == "negative"
