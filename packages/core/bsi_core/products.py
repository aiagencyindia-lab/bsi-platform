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
import time
import uuid
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m
from .crawl import Fetch, http_fetch
from .db import tenant_session
from .judge import JudgeFailed
from .matching import normalize_domain
from .providers.base import EngineAdapter
from .rivals import _stem
from .scheduling import budget_fits
from .suggest import Generator

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
    "dropped_words",
]

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


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
    '|'-joined, None is blank and a formula-like cell gets a leading
    apostrophe."""

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            value = "|".join(str(v) for v in value)
        text = str(value)
        # Spreadsheets run a cell that starts like a formula; titles come
        # from a model that read competitor pages.
        return "'" + text if text.startswith(FORMULA_START) else text

    return [[cell(getattr(p, c)) for c in EXPORT_COLUMNS] for p in products]


_CATALOGUE = (
    "external_id",
    "title",
    "description",
    "attributes",
    "url",
    "price",
    "category",
)


def upsert(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    rows: Sequence[dict[str, Any]],
    source: str,
) -> tuple[int, int]:
    """(created, updated). One INSERT ... ON CONFLICT on
    (brand_id, external_id) that rewrites only the catalogue columns,
    source and imported_at; the result columns are kept. Raises
    CatalogueCap, before writing, if the brand would exceed MAX_PRODUCTS.
    A later row with the same external_id wins."""
    by_id = {str(r["external_id"]): r for r in rows}
    if not by_id:
        return 0, 0
    existing = set(
        s.scalars(
            select(m.Product.external_id).where(m.Product.brand_id == brand_id)
        )
    )
    new_ids = set(by_id) - existing
    if len(existing) + len(new_ids) > MAX_PRODUCTS:
        raise CatalogueCap(f"{len(existing) + len(new_ids)} > {MAX_PRODUCTS}")
    values = [
        {
            "org_id": org_id,
            "brand_id": brand_id,
            "source": source,
            "imported_at": func.now(),
            **{k: r[k] for k in _CATALOGUE},
        }
        for r in by_id.values()
    ]
    stmt = pg_insert(m.Product).values(values)
    s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_product_brand_external",
            set_={
                c: getattr(stmt.excluded, c)
                for c in (*_CATALOGUE, "source", "imported_at")
            },
        )
    )
    return len(new_ids), len(by_id) - len(new_ids)


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
# R12: no batch starts after this, which leaves two minutes of
# claim_job's 10-minute stale cutoff for the last batch (3 keyword calls,
# its new keywords' grounded searches, one rewrite), like the worker's
# RIVAL_JOB_SECONDS. A batch of 20 new keywords can take longer. The
# next run continues with the products whose results are oldest.
PRODUCT_JOB_SECONDS = 480
TOP_TITLES = 5
# Stored titles carry this; a cached row parsed by an older prompt is
# searched again. ponytail: a bump re-searches every keyword (~$0.04).
TITLES_PARSE = 2
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
    "new a an in of on to by at or com".split()
)
# missing() never suggests these (slice 21 spec §2). ponytail: English
# and closed; a real colour phrase ("white sneakers") is never suggested;
# a noise word is skipped even when it is in the keyword; outside
# footwear some are product words (cream, gold, silver, orange, plus
# size, hair color); toddler/youth/infant are not listed, and "kid" from
# "Little Kid" is still suggested.
NOISE_WORDS = frozenset(
    "white black blue red green pink grey gray brown navy beige tan silver "
    "gold purple orange yellow cream multi multicolor color colour size "
    "little big".split()
)
NOISE_STEMS = frozenset(_stem(w) for w in NOISE_WORDS)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def brand_tokens(names: Sequence[str]) -> frozenset[str]:
    return frozenset(t for n in names for t in tokens(n))


def fold(text: str) -> list[str]:
    """The text's tokens without 1-letter ones (the s of "men's"), each
    with one trailing s dropped (rivals._stem): sandals and sandal, mens
    and men meet. ponytail: crude on purpose; irregular plurals (feet)
    do not fold. The one place to swap in a real lemmatiser."""
    return [_stem(t) for t in tokens(text) if len(t) > 1]


def fold_set(text: str) -> frozenset[str]:
    return frozenset(fold(text))


def _brand_stems(brand_names: Sequence[str]) -> frozenset[str]:
    return frozenset(_stem(t) for t in brand_tokens(brand_names))


# Removed from the end of a fixed title: "Sandal And" -> "Sandal".
CONNECTORS = frozenset({"and", "with", "for", "&", "-", "|"})

# rule_check keeps these even when the rewrite adds them.
FUNCTION_WORDS = frozenset(
    {"and", "for", "with", "of", "the", "a", "an", "in", "on", "to", "by", "or"}
)


def _allowed_stems(
    original: str, allowed: Sequence[str], brand_names: Sequence[str]
) -> frozenset[str]:
    """Stems a suggestion word may come from: the original title, the
    allowed texts (keyword, missing words, the product's description,
    category and attribute values), the brand's names; plus, for an
    allowed token ending in "es", its singular ("watches" -> watch).
    ponytail: rivals._stem drops only one "s"; this patches -es for
    allowed words only."""
    text = " ".join(allowed)
    es = {
        _stem(t[:-2]) for t in tokens(text) if len(t) > 3 and t.endswith("es")
    }
    return (
        fold_set(original)
        | fold_set(text)
        | _brand_stems(brand_names)
        | frozenset(es)
    )


def _strip_connectors(words: list[str]) -> list[str]:
    while words and words[-1].casefold() in CONNECTORS:
        words = words[:-1]
    return words


def _clean(keyword: str) -> str:
    return " ".join(keyword.casefold().split())


_POSSESSIVE = re.compile(r"['\u2019]s\b")


def _display(keyword: str) -> str:
    """The keyword as stored and searched: lowercased, whitespace
    collapsed, possessive 's removed ("men's sandals" -> "men sandals")."""
    return _clean(_POSSESSIVE.sub("", keyword.casefold()))


def keyword_key(keyword: str) -> str:
    """Keywords with the same key are the same shopper phrase: plural,
    possessive and mens/men variants meet ("men sandal")."""
    return " ".join(_stem(t) for t in tokens(_display(keyword)))


def vote(samples: Sequence[Sequence[str]]) -> list[str]:
    """One product's ranked keywords from SAMPLES ranked lists, compared
    by keyword_key: rank 1 is the key most often at rank 1 (ties: sample
    order), then the other keys in first-seen order; each key shown in
    its first surface form (_display); at most MAX_KEYWORDS."""
    keyed = [
        [(key, k) for k in sample if (key := keyword_key(k))]
        for sample in samples
    ]
    firsts = [s[0][0] for s in keyed if s]
    if not firsts:
        return []
    counts = Counter(firsts)
    top = max(firsts, key=lambda k: (counts[k], -firsts.index(k)))
    shown: dict[str, str] = {}
    for sample_keys in keyed:
        for key, k in sample_keys:
            shown.setdefault(key, _display(k))
    order = [top]
    for sample_keys in keyed:
        for key, _k in sample_keys:
            if key not in order:
                order.append(key)
    return [shown[key] for key in order[:MAX_KEYWORDS]]


def drop_brand_terms(
    keywords: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Keep a keyword only if it has a token and shares none with the
    brand name or an alias."""
    bt = brand_tokens(brand_names)
    return [k for k in keywords if (t := set(tokens(k))) and not t & bt]


# fit_rank cuts a keyword here (R6); "slip on shoes" keeps its "on".
CATEGORY_CUTS = frozenset({"for", "with"})


def fit_rank(
    keywords: Sequence[str],
    title: str,
    category: str | None,
    description: str | None,
) -> list[str]:
    """Keywords whose category word names this product. The category
    word is the last folded word before the keyword's first CATEGORY_CUTS
    token ("slippers for men" -> slipper, "men slip on shoes" -> shoe),
    or the keyword's last folded word if nothing folds before the cut.
    First come those whose category stem is in the title, then those
    whose stem is only in the category or description; others are
    dropped, so a flip flop is never searched as "men slippers" when a
    title fit exists, and never as "kids shoes" at all."""
    in_title = fold_set(title)
    in_other = fold_set(category or "") | fold_set(description or "")
    first: list[str] = []
    second: list[str] = []
    for k in keywords:
        words = fold(k)
        if not words:
            continue
        toks = tokens(k)
        cut = next(
            (i for i, t in enumerate(toks) if t in CATEGORY_CUTS), len(toks)
        )
        head = fold(" ".join(toks[:cut]))
        word = (head or words)[-1]
        if word in in_title:
            first.append(k)
        elif word in in_other:
            second.append(k)
    return first + second


def missing(
    product_title: str,
    titles: Sequence[str],
    brand_names: Sequence[str],
    exclude: Sequence[str] = (),
    keyword: str = "",
) -> list[str]:
    """Words of the ranking titles the product title lacks, compared by
    stem (fold): at least 3 characters, not a number, not a stopword or
    a colour/size word (NOISE_STEMS), not a stem of the brand's names or
    of `exclude` (rival brands, models, competitor names) unless it is a
    stem of the product's keyword, in at least MIN_TITLES titles. The
    first surface form seen is reported; by title count, then stem;
    MAX_MISSING."""
    have = (
        fold_set(product_title)
        | _brand_stems(brand_names)
        | (_brand_stems(exclude) - _brand_stems([keyword]))
    )
    counts: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for title in titles:
        here: set[str] = set()
        for tok in tokens(title):
            if len(tok) < 3 or tok.isdigit() or tok in STOPWORDS:
                continue
            stem = _stem(tok)
            if stem in have or stem in NOISE_STEMS:
                continue
            here.add(stem)
            surface.setdefault(stem, tok)
        counts.update(here)
    ranked = sorted(
        (s for s, n in counts.items() if n >= MIN_TITLES),
        key=lambda s: (-counts[s], s),
    )
    return [surface[s] for s in ranked[:MAX_MISSING]]


def _brand_in(text: str, brand_names: Sequence[str]) -> str | None:
    """The first brand name (name, then aliases) whose tokens all appear."""
    have = set(tokens(text))
    for name in brand_names:
        bt = tokens(name)
        if bt and set(bt) <= have:
            return name
    return None


def dropped(
    original: str, suggestion: str, brand_names: Sequence[str]
) -> list[str]:
    """The original title's words whose stem is not in the suggestion:
    stopwords, brand stems, pure numbers and 1-letter tokens ignored;
    lowercased, in original order, without repeats."""
    have = fold_set(suggestion) | _brand_stems(brand_names)
    out: list[str] = []
    for tok in tokens(original):
        if len(tok) < 2 or tok.isdigit() or tok in STOPWORDS:
            continue
        if _stem(tok) not in have and tok not in out:
            out.append(tok)
    return out


def rule_check(
    original: str,
    suggestion: str,
    brand_names: Sequence[str],
    allowed: Sequence[str] = (),
) -> tuple[str, str, list[str]]:
    """(title, status, dropped_words). Fixes rather than retries: the
    brand is prepended if the original had it and the suggestion lost it;
    a word whose stems come from none of the original title, `allowed` or
    the brand's names is dropped (function words and numbers are kept)
    right after the brand step;
    a word that repeats an earlier word's stem is dropped whole
    (punctuation-only words are kept); trailing CONNECTORS are removed;
    the title is trimmed to MAX_TITLE_CHARS at a word boundary, and
    trailing CONNECTORS are removed again. Status:
    "review" if the final title lost any of the original's words, else
    "adjusted" if it differs from the suggestion, else "pass"."""
    title = suggestion
    brand = _brand_in(original, brand_names)
    if brand and _brand_in(title, [brand]) is None:
        title = f"{brand} {title}".strip()
    ok = _allowed_stems(original, allowed, brand_names)
    title = " ".join(
        w
        for w in title.split()
        if not (stems := fold_set(w))
        or stems & ok
        or all(t in FUNCTION_WORDS or t.isdigit() for t in tokens(w))
    )
    seen: set[str] = set()
    kept: list[str] = []
    for word in title.split():
        stems = fold_set(word)
        if stems & seen:
            continue
        seen |= stems
        kept.append(word)
    title = " ".join(_strip_connectors(kept))
    if len(title) > MAX_TITLE_CHARS:
        cut = title[: MAX_TITLE_CHARS + 1]
        space = cut.rfind(" ")
        title = cut[:space].rstrip() if space > 0 else title[:MAX_TITLE_CHARS]
        title = " ".join(_strip_connectors(title.split()))
    lost = dropped(original, title, brand_names)
    if lost:
        return title, "review", lost
    return title, ("pass" if title == suggestion else "adjusted"), []


def _squash(text: str) -> str:
    return " ".join(text.casefold().split())


def _named_in(value: Any, title: str) -> str:
    """value, stripped, when it has a token and all its tokens are in the
    title's tokens, unless its tokens equal the title's (Ruling R4); else
    "". Keeps the parse from inventing exclusions."""
    v = str(value or "").strip()
    toks, title_toks = set(tokens(v)), set(tokens(title))
    return v if toks and toks <= title_toks and toks != title_toks else ""


def keep_present(
    titles: list[dict[str, Any]], text: str
) -> list[dict[str, Any]]:
    """Only titles found verbatim in the answer text (case and
    whitespace ignored), at most TOP_TITLES, domains lowercased; brand
    and model kept only when named in the title (_named_in); each
    carries the parse version (TITLES_PARSE)."""
    hay = _squash(text)
    out: list[dict[str, Any]] = []
    for t in titles:
        title = str(t.get("title") or "").strip()
        if title and _squash(title) in hay:
            domain = str(t.get("domain") or "").strip().lower()
            out.append(
                {
                    "title": title,
                    "domain": domain,
                    "brand": _named_in(t.get("brand"), title),
                    "model": _named_in(t.get("model"), title),
                    "parse": TITLES_PARSE,
                }
            )
    return out[:TOP_TITLES]


def drop_stores(
    titles: list[dict[str, Any]], domains: Sequence[str]
) -> list[dict[str, Any]]:
    """Titles that are not a store: a title is dropped when its letters
    and digits, joined, equal a known domain's name or joined form
    ("Famous Footwear" = famousfootwear.com, "Zappos.com" = zappos.com),
    or it contains a known dotted domain ("Buy at ShopWSS.com"). Known
    domains are the title's own plus the cited ones, normalised. Order
    kept."""
    # ponytail: a subdomain's name is its first label (shop.nike.com ->
    # "shop"), and a store named unlike its domain ("Journeys Kidz",
    # journeys.com) is left to titles_prompt; a store list would catch it.
    cited = [normalize_domain(d) for d in domains]
    out: list[dict[str, Any]] = []
    for t in titles:
        title = str(t.get("title") or "")
        squashed = "".join(tokens(title))
        low = title.casefold()
        own = normalize_domain(str(t.get("domain") or ""))
        if not any(
            squashed in (d.split(".")[0], "".join(tokens(d)))
            or ("." in d and d in low)
            for d in (own, *cited)
            if d
        ):
            out.append(t)
    return out


class KeywordItem(BaseModel):
    index: int
    keywords: list[str]


class KeywordSet(BaseModel):
    products: list[KeywordItem]


class TitleItem(BaseModel):
    title: str
    domain: str = ""
    brand: str = ""
    model: str = ""


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
        f"For each product give up to {MAX_KEYWORDS} keywords, lowercase, "
        "generic first. Rank 1 is a broad shopper phrase: the audience "
        "plus the product's own category, in the plural (for example "
        '"kids sandals", "men flip flops", "women slippers"). Use "kids" '
        'for children\'s products, not "boys" or "girls". Never replace '
        "the product's type with a different one. More specific phrases "
        "come after rank 1. Never include the brand name. One keyword per "
        "entry. Given the same products, choose the same rank 1.\n"
        'Return JSON {"products": [{"index": <index>, '
        '"keywords": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(products, "description", "attributes", "category")
    )


def search_query(keyword: str) -> str:
    """The grounded search that should list products, not stores."""
    return (
        f"{keyword}: popular products to buy online, "
        "with each product's full title"
    )


def titles_prompt(keyword: str, text: str, domains: Sequence[str]) -> str:
    """Parse a grounded answer into the product titles it names."""
    return (
        f"The text below answers the search {search_query(keyword)!r}.\n"
        f"List up to {TOP_TITLES} distinct product titles that appear "
        "verbatim in the text, in the order they appear, each with the "
        "seller's domain when the text names it (else an empty string). "
        "Do not invent titles or shorten them. A product title names one "
        "product; never list a store, retailer, marketplace or brand name "
        "on its own. For each title also give its brand and its model or "
        "product-line name without the product type (for example "
        '"Taye 2.0", not "Taye 2.0 Sneaker"), each as written in the '
        "title, else an empty string.\n"
        f"Known source domains: {', '.join(domains) or 'none'}\n"
        'Return JSON {"titles": [{"title": ..., "domain": ..., '
        '"brand": ..., "model": ...}]}.\n'
        f"Text:\n{text}"
    )


def rewrite_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    return (
        f"Rewrite each product title for the brand {brand!r}.\n"
        "Keep every word of the original title (you may reorder them); "
        "add the keyword and the missing terms naturally; never change "
        "the product type; repeat no word; no keyword stuffing. Each new "
        f"title is at most {MAX_TITLE_CHARS} characters and keeps the "
        "brand name if the original has it. Also give "
        f"{MAX_BULLETS} short description bullet points.\n"
        'Return JSON {"products": [{"index": <index>, "title": ..., '
        '"bullets": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(
            products, "keyword", "missing", "description", "attributes"
        )
    )


class OverBudget(RuntimeError):
    """A batch's searches do not fit the org's budget; the batches
    already written, and this batch's keywords, stay. The worker
    records error "budget"."""

    def __init__(self, cost_micros: int) -> None:
        super().__init__("budget")
        self.cost_micros = cost_micros


def _batches[T](items: Sequence[T]) -> list[list[T]]:
    return [list(items[i : i + BATCH]) for i in range(0, len(items), BATCH)]


def run_products(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    brand_id: uuid.UUID,
    params: dict[str, Any],
    generator: Generator,
    adapter: EngineAdapter,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """The product_run job (spec §3), one batch at a time, oldest
    results first (R12): keywords, one grounded search per new distinct
    keyword, missing keywords, rewrite, rule check, write. Stops before a
    batch once PRODUCT_JOB_SECONDS have passed; the next run continues.
    Reads and writes in short tenant sessions; no transaction is open
    during a model call. Raises OverBudget before a batch's searches when
    they do not fit, and JudgeFailed (with the spend) on any other
    failure, so the money is recorded either way; finished batches stay."""
    now = now or datetime.now(UTC)
    start = clock()
    locale = params.get("locale") or {}
    country = str(locale.get("country") or "IN")
    language = str(locale.get("language") or "en")
    fresh_after = now - timedelta(days=SEARCH_TTL_DAYS)
    spent = 0
    searched = 0
    done = 0
    titles_by_kw: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()  # distinct keywords, for the summary
    try:
        with tenant_session(org_id) as s:
            brand = s.get_one(m.Brand, brand_id)
            names = [brand.name, *brand.aliases]
            rivals = [
                n
                for c in s.scalars(
                    select(m.Competitor).where(
                        m.Competitor.brand_id == brand_id
                    )
                )
                for n in (c.name, *c.aliases)
            ]
            products: list[dict[str, Any]] = [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "attributes": p.attributes,
                    "category": p.category,
                }
                for p in s.scalars(
                    select(m.Product)
                    .where(m.Product.brand_id == brand_id)
                    .order_by(
                        m.Product.result_at.asc().nulls_first(),
                        m.Product.title,
                        m.Product.id,
                    )
                )
            ]
        # One keyword string per key for the whole run, so plural and
        # possessive variants share one search and one cache row.
        key_map: dict[str, str] = {}
        for batch in _batches(products):
            # R12: at least one batch, so every run makes progress.
            if done and clock() - start > PRODUCT_JOB_SECONDS:
                return (
                    f"out of time after {done} of {len(products)} products; "
                    f"keywords:{len(seen)} searched:{searched}"
                )
            # 1. Keywords, written per batch.
            for i, p in enumerate(batch):
                p["index"] = i
            samples: list[dict[int, list[str]]] = []
            for _ in range(SAMPLES):
                raw, cost, _model = generator(
                    keyword_prompt(brand.name, batch),
                    KeywordSet,
                    KEYWORD_TEMPERATURE,
                )
                spent += cost
                got = KeywordSet.model_validate_json(raw)
                samples.append(
                    {
                        item.index: [
                            _clean(k) for k in item.keywords if k.strip()
                        ]
                        for item in got.products
                    }
                )
            for i, p in enumerate(batch):
                ranked = vote([sm.get(i, []) for sm in samples])
                fitted = fit_rank(
                    drop_brand_terms(ranked, names),
                    p["title"],
                    p["category"],
                    p["description"],
                )
                p["keywords"] = [
                    key_map.setdefault(keyword_key(k), k) for k in fitted
                ]
                p["keyword"] = p["keywords"][0] if p["keywords"] else None
            with tenant_session(org_id) as s:
                for p in batch:
                    # R13: no keyword, no stale suggestion from a past run.
                    cleared: dict[str, Any] = (
                        {}
                        if p["keyword"]
                        else {
                            "missing_keywords": None,
                            "suggested_title": None,
                            "suggested_bullets": None,
                            "rule_check": None,
                            "dropped_words": None,
                            "job_id": job_id,
                            "result_at": now,
                        }
                    )
                    s.execute(
                        update(m.Product)
                        .where(m.Product.id == p["id"])
                        .values(
                            keyword=p["keyword"],
                            keywords=p["keywords"],
                            **cleared,
                        )
                    )
            # 2. One grounded search per new distinct keyword, cached 7
            # days, KEYWORD_CAP per run.
            kept = [p for p in batch if p["keyword"]]
            counts = Counter(p["keyword"] for p in kept)
            seen.update(counts)
            ordered = sorted(
                (k for k in counts if k not in titles_by_kw),
                key=lambda k: (-counts[k], k),
            )
            with tenant_session(org_id) as s:
                titles_by_kw.update(
                    (row.keyword, list(row.titles))
                    for row in s.scalars(
                        select(m.KeywordSearch).where(
                            m.KeywordSearch.brand_id == brand_id,
                            m.KeywordSearch.keyword.in_(ordered),
                            m.KeywordSearch.searched_at > fresh_after,
                            # R9: an error row is searched again
                            m.KeywordSearch.error.is_(None),
                        )
                    )
                    # a row from an older query wording, or parsed by an
                    # older titles_prompt (TITLES_PARSE), is searched again
                    if row.query == search_query(row.keyword)
                    and all(t.get("parse") == TITLES_PARSE for t in row.titles)
                )
                new = [k for k in ordered if k not in titles_by_kw]
                new = new[: max(KEYWORD_CAP - searched, 0)]
                # R10: job.cost_micros is written only at the end, so
                # this job's spend so far is added here.
                fits = not new or budget_fits(
                    s,
                    org_id,
                    0,
                    extra_micros=spent + len(new) * SEARCH_MICROS,
                )
            if not fits:
                raise OverBudget(spent)
            for keyword in new:
                query = search_query(keyword)
                result = adapter.query(query, country, language)
                spent += result.cost_micros
                row: dict[str, Any] = {
                    "query": query,
                    "titles": [],
                    "model": result.model,
                    "cost_micros": result.cost_micros,
                    "error": None,
                }
                if result.kind != "ok" or result.raw is None:
                    row["error"] = result.error or "no answer"
                else:
                    parsed = adapter.parse(result.raw)
                    domains = sorted({d for _, d in parsed.citations if d})
                    raw, cost, _model = generator(
                        titles_prompt(keyword, parsed.text, domains),
                        TitleSet,
                        0.0,
                    )
                    spent += cost
                    row["cost_micros"] += cost
                    row["titles"] = keep_present(
                        drop_stores(
                            [
                                t.model_dump()
                                for t in TitleSet.model_validate_json(
                                    raw
                                ).titles
                            ],
                            domains,
                        ),
                        parsed.text,
                    )
                with tenant_session(org_id) as s:
                    stmt = pg_insert(m.KeywordSearch).values(
                        org_id=org_id,
                        brand_id=brand_id,
                        keyword=keyword,
                        searched_at=now,
                        **row,
                    )
                    s.execute(
                        stmt.on_conflict_do_update(
                            constraint="uq_keyword_search_brand_keyword",
                            set_={
                                c: getattr(stmt.excluded, c)
                                for c in (*row, "searched_at")
                            },
                        )
                    )
                titles_by_kw[keyword] = row["titles"]
                searched += 1
            done += len(batch)
            if not kept:
                continue
            # 3-6. Missing keywords, rewrite, rule check, write. A keyword
            # past KEYWORD_CAP has no titles, so its missing list is [].
            for i, p in enumerate(kept):
                p["index"] = i
                ranking = titles_by_kw.get(p["keyword"], [])
                p["missing"] = missing(
                    p["title"],
                    [t["title"] for t in ranking],
                    names,
                    # ponytail: a generic word in a model ("Classic") is
                    # excluded for this keyword, and one in a competitor's
                    # name or alias for every keyword that does not contain
                    # it (spec §1).
                    exclude=[
                        *rivals,
                        *(
                            v
                            for t in ranking
                            for v in (t.get("brand"), t.get("model"))
                            if v
                        ),
                    ],
                    keyword=p["keyword"],
                )
            raw, cost, _model = generator(
                rewrite_prompt(brand.name, kept), RewriteSet, 0.0
            )
            spent += cost
            rewrites = {
                item.index: item
                for item in RewriteSet.model_validate_json(raw).products
            }
            with tenant_session(org_id) as s:
                for i, p in enumerate(kept):
                    item = rewrites.get(i)
                    suggestion = (item.title.strip() if item else "") or p[
                        "title"
                    ]
                    title, status, lost = rule_check(
                        p["title"],
                        suggestion,
                        names,
                        allowed=[
                            p["keyword"],
                            *p["missing"],
                            p["description"] or "",
                            p["category"] or "",
                            *(str(v) for v in (p["attributes"] or {}).values()),
                        ],
                    )
                    bullets = [
                        b.strip()[:MAX_BULLET_CHARS]
                        for b in (item.bullets if item else [])
                        if b.strip()
                    ][:MAX_BULLETS]
                    s.execute(
                        update(m.Product)
                        .where(m.Product.id == p["id"])
                        .values(
                            missing_keywords=p["missing"],
                            suggested_title=title,
                            suggested_bullets=bullets,
                            rule_check=status,
                            dropped_words=lost,
                            job_id=job_id,
                            result_at=now,
                        )
                    )
        return (
            f"products:{len(products)} keywords:{len(seen)} searched:{searched}"
        )
    except OverBudget:
        raise
    except Exception as e:
        raise JudgeFailed(e, spent) from e
