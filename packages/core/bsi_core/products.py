"""Product-title wedge (PRD F16): import a catalogue, infer each
product's generic shopper keyword, compare its title with the titles that
rank for that keyword, and rewrite it.

Parsing, voting, the missing-keyword rule and the rule check are pure.
`run_products` orchestrates the job in short tenant sessions, with no
transaction open during a model call, the `suggest_competitors` shape.
"""

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import partial
from typing import Any

from pydantic import BaseModel

from .crawl import Fetch, http_fetch

MAX_PRODUCTS = 1_000  # per brand, the PRD's run ceiling
CSV_MAX_BYTES = 4 * 1024 * 1024
FEED_CAP_BYTES = 8 * 1024 * 1024
FEED_FETCH: Fetch = partial(http_fetch, cap=FEED_CAP_BYTES, raw=True)

# CSV header (lowercased) -> row key. Any other header is an attribute.
CSV_FIELDS = {
    "id": "external_id",
    "title": "title",
    "description": "description",
    "url": "url",
    "link": "url",
    "price": "price",
    "category": "category",
}
# Merchant feed tags (namespace stripped) kept as attributes.
FEED_ATTRS = (
    "brand",
    "color",
    "size",
    "material",
    "gender",
    "age_group",
    "condition",
)
EXPORT_COLUMNS = [
    "external_id",
    "url",
    "title",
    "keyword",
    "missing_keywords",
    "suggested_title",
    "suggested_bullets",
    "rule_check",
]


class CatalogueCap(ValueError):
    """An import would take the brand past MAX_PRODUCTS."""


def _external_id(row: dict[str, Any]) -> str:
    return str(
        row.get("external_id")
        or row.get("url")
        or hashlib.sha1(str(row["title"]).encode()).hexdigest()
    )


def parse_attributes(cell: str) -> dict[str, str]:
    """`Size: 10; Color: Blue` -> {"size": "10", "color": "blue"}. A
    fragment without a colon is dropped."""
    out: dict[str, str] = {}
    for frag in cell.split(";"):
        key, sep, value = frag.partition(":")
        if sep and key.strip():
            out[key.strip().lower()] = value.strip().lower()
    return out


def _blank_row() -> dict[str, Any]:
    return {
        "external_id": None,
        "title": None,
        "description": None,
        "attributes": {},
        "url": None,
        "price": None,
        "category": None,
    }


def parse_csv(text: str) -> tuple[list[dict[str, Any]], int]:
    """(rows, rows skipped for an empty title). Headers are matched
    case-insensitively after stripping; unknown headers become
    attributes keyed by the lowercased header."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw in csv.DictReader(io.StringIO(text)):
        row = _blank_row()
        for header, cell in raw.items():
            if header is None:  # a row with more cells than headers
                continue
            key = header.strip().lower()
            value = (cell or "").strip()
            if key == "attributes":
                row["attributes"].update(parse_attributes(value))
            elif key in CSV_FIELDS:
                row[CSV_FIELDS[key]] = value or None
            elif key and value:
                row["attributes"][key] = value
        if not row["title"]:
            skipped += 1
            continue
        row["external_id"] = _external_id(row)
        rows.append(row)
    return rows, skipped


def _feed_row(fields: dict[str, str]) -> dict[str, Any] | None:
    title = fields.get("title")
    if not title:
        return None
    row = _blank_row()
    row.update(
        external_id=fields.get("id") or None,
        title=title,
        description=fields.get("description") or None,
        url=fields.get("link") or None,
        price=fields.get("price") or None,
        category=fields.get("product_type")
        or fields.get("google_product_category")
        or None,
        attributes={k: fields[k] for k in FEED_ATTRS if fields.get(k)},
    )
    row["external_id"] = _external_id(row)
    return row


def parse_feed(body: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """(rows, note). Reads RSS <item> and Atom <entry> elements with the
    XMLPullParser pattern of rivals.parse_sitemap: namespaces are
    stripped, so g:id and id both read as "id"; an Atom <link href> is
    read from the attribute. Gzip is inflated under FEED_CAP_BYTES.
    Malformed or cut XML returns what was read, with note "malformed"."""
    note: str | None = None
    if body[:2] == b"\x1f\x8b":
        z = zlib.decompressobj(47)
        try:
            body = z.decompress(body, FEED_CAP_BYTES)
        except zlib.error:
            return [], "gzip error"
        if z.unconsumed_tail:
            note = "truncated"
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    rows: list[dict[str, Any]] = []
    depth = 0
    entry_depth = 0
    closed = False  # the root's end event arrived
    fields: dict[str, str] = {}
    try:
        parser.feed(body)
        for ev in parser.read_events():
            event, el = ev[0], ev[-1]
            if not isinstance(el, ET.Element):
                continue
            tag = str(el.tag).rsplit("}", 1)[-1]
            if event == "start":
                depth += 1
                if tag in ("item", "entry") and not entry_depth:
                    entry_depth, fields = depth, {}
                continue
            if entry_depth and depth == entry_depth:
                row = _feed_row(fields)
                if row:
                    rows.append(row)
                entry_depth = 0
                el.clear()
            elif entry_depth and depth == entry_depth + 1:
                value = (el.text or "").strip()
                if tag == "link" and not value:
                    value = (el.get("href") or "").strip()
                fields.setdefault(tag, value)
            elif depth == 1:
                closed = True
            depth -= 1
    except ET.ParseError:
        note = note or "malformed"
    if not closed:  # feed() does not raise on a cut body; close() would
        note = note or "malformed"
    return rows, note


def export_rows(products: Iterable[Any]) -> list[list[str]]:
    """One CSV row per product in EXPORT_COLUMNS order; lists are
    '|'-joined and None is blank."""

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "|".join(str(v) for v in value)
        return str(value)

    return [[cell(getattr(p, c)) for c in EXPORT_COLUMNS] for p in products]


BATCH = 20
SAMPLES = 3
KEYWORD_TEMPERATURE = 0.4
MAX_KEYWORDS = 5
KEYWORD_CAP = 100  # grounded searches per run
SEARCH_TTL_DAYS = 7
# 35,000 micros grounding + tokens + the flash-lite parse call.
SEARCH_MICROS = 45_000
# The keyword phase: 150 flash-lite calls for 1,000 products.
PRODUCT_JOB_MICROS = 20_000
TOP_TITLES = 5
MIN_TITLES = 2
MAX_MISSING = 8
MAX_TITLE_CHARS = 150
MAX_BULLETS = 3
MAX_BULLET_CHARS = 200
MAX_DESCRIPTION_CHARS = 300  # in prompts
MAX_ATTRIBUTES = 10  # in prompts

_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "and for the with from your our this that are you all any buy online "
    "free shop shopping sale offer offers price prices deal deals off "
    "new".split()
)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def brand_tokens(names: Sequence[str]) -> frozenset[str]:
    return frozenset(t for n in names for t in tokens(n))


def vote(samples: Sequence[Sequence[str]]) -> list[str]:
    """One product's ranked keywords from SAMPLES ranked lists: rank 1 is
    the keyword most often at rank 1 (ties: sample order), then the union
    in first-seen order, capped at MAX_KEYWORDS."""
    firsts = [s[0] for s in samples if s]
    if not firsts:
        return []
    counts = Counter(firsts)
    top = max(firsts, key=lambda k: (counts[k], -firsts.index(k)))
    out = [top]
    for sample in samples:
        for keyword in sample:
            if keyword not in out:
                out.append(keyword)
    return out[:MAX_KEYWORDS]


def drop_brand_terms(
    keywords: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Drop any keyword sharing a token with the brand name or an alias."""
    bt = brand_tokens(brand_names)
    return [k for k in keywords if not (set(tokens(k)) & bt)]


def missing(
    product_title: str, titles: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Tokens of the ranking titles the product title lacks: at least 3
    characters, not a number, not a stopword or brand token, in at least
    MIN_TITLES titles; by title count then alphabetically; MAX_MISSING."""
    have = set(tokens(product_title)) | brand_tokens(brand_names)
    counts: Counter[str] = Counter()
    for title in titles:
        for tok in set(tokens(title)):
            if (
                len(tok) >= 3
                and not tok.isdigit()
                and tok not in STOPWORDS
                and tok not in have
            ):
                counts[tok] += 1
    ranked = sorted(
        (tok for tok, n in counts.items() if n >= MIN_TITLES),
        key=lambda tok: (-counts[tok], tok),
    )
    return ranked[:MAX_MISSING]


def _brand_in(text: str, brand_names: Sequence[str]) -> str | None:
    """The first brand name (name, then aliases) whose tokens all appear."""
    have = set(tokens(text))
    for name in brand_names:
        bt = tokens(name)
        if bt and set(bt) <= have:
            return name
    return None


def rule_check(
    original: str, suggestion: str, brand_names: Sequence[str]
) -> tuple[str, str]:
    """(title, "pass" | "adjusted"). Fixes rather than retries: repeated
    tokens are dropped (first occurrence kept), the brand is prepended
    if the original had it and the suggestion lost it, and the title is
    trimmed to MAX_TITLE_CHARS at a word boundary."""
    seen: set[str] = set()
    kept: list[str] = []
    for word in suggestion.split():
        key = "".join(tokens(word))
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(word)
    title = " ".join(kept)
    brand = _brand_in(original, brand_names)
    if brand and _brand_in(title, [brand]) is None:
        title = f"{brand} {title}".strip()
    if len(title) > MAX_TITLE_CHARS:
        cut = title[: MAX_TITLE_CHARS + 1]
        space = cut.rfind(" ")
        title = cut[:space].rstrip() if space > 0 else title[:MAX_TITLE_CHARS]
    return title, ("pass" if title == suggestion else "adjusted")


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def keep_present(
    titles: list[dict[str, Any]], text: str
) -> list[dict[str, str]]:
    """Only titles found verbatim in the answer text (case and
    whitespace ignored), at most TOP_TITLES, domains lowercased."""
    hay = _squash(text)
    out: list[dict[str, str]] = []
    for t in titles:
        title = str(t.get("title") or "").strip()
        if title and _squash(title) in hay:
            domain = str(t.get("domain") or "").strip().lower()
            out.append({"title": title, "domain": domain})
    return out[:TOP_TITLES]


class KeywordItem(BaseModel):
    index: int
    keywords: list[str]


class KeywordSet(BaseModel):
    products: list[KeywordItem]


class TitleItem(BaseModel):
    title: str
    domain: str = ""


class TitleSet(BaseModel):
    titles: list[TitleItem]


class RewriteItem(BaseModel):
    index: int
    title: str
    bullets: list[str]


class RewriteSet(BaseModel):
    products: list[RewriteItem]


def _product_lines(products: Sequence[dict[str, Any]], *keys: str) -> str:
    rows = []
    for p in products:
        row: dict[str, Any] = {"index": p["index"], "title": p["title"]}
        for k in keys:
            v = p.get(k)
            if k == "description" and isinstance(v, str):
                v = v[:MAX_DESCRIPTION_CHARS]
            if k == "attributes" and isinstance(v, dict):
                v = dict(list(v.items())[:MAX_ATTRIBUTES])
            if v:
                row[k] = v
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def keyword_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    """The ADK keyword-finding prompt, one call per batch, JSON out."""
    return (
        "You find the keywords shoppers type when looking for products "
        f"like these from the brand {brand!r}.\n"
        "For each product give up to "
        f"{MAX_KEYWORDS} keywords, lowercase, generic first: rank 1 is "
        "the shortest phrase naming the audience plus the product "
        'category (for example "kids shoes"), more specific phrases '
        "after it. Never include the brand name. One keyword per entry. "
        "Given the same products, choose the same rank 1.\n"
        'Return JSON {"products": [{"index": <index>, '
        '"keywords": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(products, "description", "attributes", "category")
    )


def titles_prompt(keyword: str, text: str, domains: Sequence[str]) -> str:
    """Parse a grounded answer into the product titles it names."""
    return (
        f"The text below answers a search for {keyword!r} buy online.\n"
        f"List up to {TOP_TITLES} distinct product titles that appear "
        "verbatim in the text, in the order they appear, each with the "
        "seller's domain when the text names it (else an empty string). "
        "Do not invent titles or shorten them.\n"
        f"Known source domains: {', '.join(domains) or 'none'}\n"
        'Return JSON {"titles": [{"title": ..., "domain": ...}]}.\n'
        f"Text:\n{text}"
    )


def rewrite_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    return (
        f"Rewrite each product title for the brand {brand!r}.\n"
        f"Each new title: at most {MAX_TITLE_CHARS} characters; keep the "
        "brand name if the original has it; work in the keyword and the "
        "missing terms naturally; repeat no word; no keyword stuffing. "
        f"Also give {MAX_BULLETS} short description bullet points.\n"
        'Return JSON {"products": [{"index": <index>, "title": ..., '
        '"bullets": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(
            products, "keyword", "missing", "description", "attributes"
        )
    )
