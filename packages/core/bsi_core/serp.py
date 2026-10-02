"""Brand SERP audit: classify a first-page item and count ownership."""

from collections.abc import Iterable, Mapping
from typing import Any

from .matching import is_owned, normalize_domain

# Provider item type -> our type.
ITEM_TYPES = {
    "knowledge_graph": "knowledge_panel",
    "ai_overview": "ai_overview",
    "top_stories": "news",
    "video": "video",
    "images": "image",
}
# Decided by host, in classify()'s order.
HOSTED = ("organic", "featured_snippet")
VIDEO_HOSTS = ("youtube.com",)
# ponytail: x.com is listed beside twitter.com; entity._social folds one
# into the other for profile URLs, a host test needs both.
SOCIAL_HOSTS = (
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
)
REVIEW_HOSTS = (
    "trustpilot.com",
    "mouthshut.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "ambitionbox.com",
    "consumercomplaints.in",
    "sitejabber.com",
    "g2.com",
)


def classify(
    item_type: str, host: str, own: Iterable[str], rivals: Iterable[str]
) -> str | None:
    """Our result type for one provider item; None = not stored. `host`
    is the item's domain, or its URL when the provider gives no domain."""
    if item_type in ITEM_TYPES:
        return ITEM_TYPES[item_type]
    if item_type not in HOSTED:
        return None
    host = normalize_domain(host)
    if is_owned(host, VIDEO_HOSTS):
        return "video"
    if is_owned(host, [normalize_domain(h) for h in own]):
        return "official"
    if is_owned(host, [normalize_domain(h) for h in rivals]):
        return "competitor"
    if is_owned(host, SOCIAL_HOSTS):
        return "social"
    if is_owned(host, REVIEW_HOSTS):
        return "review"
    return "other"


def ownership(results: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """(official organic results, all organic results)."""
    organic = [r for r in results if r.get("item_type") == "organic"]
    owned = sum(r.get("result_type") == "official" for r in organic)
    return owned, len(organic)
