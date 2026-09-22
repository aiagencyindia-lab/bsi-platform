import pytest
from bsi_core.citations import SOURCE_TYPES, source_type


@pytest.mark.parametrize(
    ("domain", "owner", "expected"),
    [
        ("nike.com", "brand", "vendor"),
        ("adidas.co.in", "rival", "vendor"),
        ("youtube.com", "third_party", "video"),
        ("m.youtube.com", "third_party", "video"),
        # Callers pass normalized domains (no www.), but the keyword
        # match is a substring test, so a stray www. is harmless.
        ("www.youtube.com", "third_party", "video"),
        ("reddit.com", "third_party", "community"),
        ("quora.com", "third_party", "community"),
        ("english.stackexchange.com", "third_party", "community"),
        ("runrepeat.com", "third_party", "other"),
        ("reviews.in", "third_party", "review"),
        ("g2.com", "third_party", "review"),
        ("trustpilot.com", "third_party", "review"),
        ("forbes.com", "third_party", "other"),
        # A vendor is a vendor even if its name says "review".
        ("shoereview.com", "rival", "vendor"),
    ],
)
def test_source_type_heuristic(domain, owner, expected):
    assert source_type(domain, owner) == expected
    assert expected in SOURCE_TYPES
