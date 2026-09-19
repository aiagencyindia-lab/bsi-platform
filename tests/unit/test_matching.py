import pytest
from bsi_core.matching import (
    Entity,
    find_mentions,
    is_owned,
    normalize_domain,
    tokenize,
)

NIKE = Entity("nike", "brand", ("Nike", "नाइकी"))
ADIDAS = Entity("adidas", "competitor", ("Adidas",))
PUMA = Entity("puma", "competitor", ("Puma",))
FOOT = Entity("foot", "competitor", ("Foot",))
LOCKER = Entity("locker", "competitor", ("Foot Locker",))
ALL = [NIKE, ADIDAS, PUMA, FOOT, LOCKER]


def ids(text: str) -> list[str]:
    return [h.entity_id for h in find_mentions(text, ALL)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I would buy Nike shoes.", ["nike"]),  # exact
        ("NIKE and ＮＩＫＥ", ["nike", "nike"]),  # noqa: RUF001 casefold + NFKC
        ("Nike's latest and Nike’s older", ["nike", "nike"]),  # noqa: RUF001 possessive
        ("NikeKids is a different store", []),  # substring collision
        ("Try Adiddas or Adidas", ["adidas", "adidas"]),  # fuzzy, long token
        ("Pumas are big cats", []),  # no fuzzy on short tokens
        ("Nikes", []),  # plural of a short alias is not the brand
        ("सबसे अच्छे जूते नाइकी के हैं", ["nike"]),  # Devanagari alias
        ("See https://nike.com/kids and shop.nike.com/x", []),  # URL only
        ("Contact us at nike.com for more", []),  # bare domain
        ("Nike. Great shoes", ["nike"]),  # normal sentence end
        ("Visit Foot Locker today", ["locker"]),  # longest alias wins
        ("Puma, then Nike, then Adidas", ["puma", "nike", "adidas"]),  # order
        ("", []),
    ],
)
def test_find_mentions(text, expected):
    assert ids(text) == expected


def test_hit_records_fuzzy_flag_and_alias():
    (hit,) = find_mentions("Adiddas", [ADIDAS])
    assert (hit.fuzzy, hit.alias, hit.entity_type) == (
        True,
        "Adidas",
        "competitor",
    )


def test_exact_beats_fuzzy_on_same_span():
    a = Entity("a", "brand", ("Adidas",))
    b = Entity("b", "competitor", ("Adidass",))
    assert [h.entity_id for h in find_mentions("Adidas", [b, a])] == ["a"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://WWW.Nike.com/in/kids?x=1", "nike.com"),
        ("shop.nike.com:443", "shop.nike.com"),
        ("nike.com.", "nike.com"),
        ("  Nike.com  ", "nike.com"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_is_owned():
    assert is_owned("shop.nike.com", ["nike.com"])
    assert is_owned("nike.com", ["nike.com"])
    assert not is_owned("notnike.com", ["nike.com"])


def test_tokenize_devanagari_combining_marks():
    """Tokenizer preserves combining marks; vowel signs not split."""
    assert tokenize("नाइकी") == ["नाइकी"]


def test_find_mentions_split_devanagari_fails():
    """Separate Devanagari tokens do not match as single token alias."""
    assert find_mentions("न इक", [NIKE]) == []
