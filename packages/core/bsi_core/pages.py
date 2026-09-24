"""URL optimizer and AI Citability Score (PRD F11, second half).

`parse` reads one HTML page into the few things the score looks at;
`score` compares that page with one content-gap cluster (a `Target`) and
returns nine weighted components, a 0-100 score and four suggestion
lists. Pure: the caller fetches and embeds."""

import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .entity import _ld_nodes, _names_in, _types
from .matching import is_owned

NOTE = (
    "The AI Citability Score is a diagnostic of the page against this "
    "cluster's prompts and sources, not a promised outcome."
)
SECTION_CAP = 60
SECTION_CHARS = 2_000
_SKIP = frozenset(
    {
        "script",
        "style",
        "nav",
        "aside",
        "noscript",
        "template",
        "svg",
    }
)
# header/footer are chrome at page level but content inside these.
_CONTENT = frozenset({"article", "main", "section"})
_LEVELS = {"h1": 1, "h2": 2, "h3": 3}


@dataclass
class Section:
    level: int
    heading: str
    text: str = ""

    def embed_text(self) -> str:
        return f"{self.heading}\n{self.text}"


def _squash(s: str) -> str:
    return " ".join(s.split())


class Page(HTMLParser):
    """Collects what the score looks at, and nothing else."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.author: str | None = None
        self.ld: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.sections: list[Section] = []
        self.tables = 0
        self.lists = 0
        self.ordered_lists = 0
        self.links: list[tuple[str, str]] = []
        self.byline = False
        self.words = 0
        self._skip = 0
        self._content = 0
        self._chrome: list[bool] = []  # open header/footer: skipped?
        self._in: str | None = None
        self._heading: tuple[int, list[str]] | None = None
        self._section: Section | None = None
        self._rows: list[int] = []
        self._items: list[tuple[str, int]] = []

    @property
    def h1_count(self) -> int:
        return sum(1 for level, _ in self.headings if level == 1)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == (
            "application/ld+json"
        ):
            self._in = "ld"
            self.ld.append("")
            return
        if tag in ("header", "footer"):
            skipped = bool(self._skip) or not self._content
            self._chrome.append(skipped)
            if skipped:
                self._skip += 1
                return
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _CONTENT:
            self._content += 1
        marker = f"{a.get('class', '')} {a.get('id', '')}".lower()
        if "author" in marker or "byline" in marker:
            self.byline = True
        if tag == "title":
            self._in = "title"
            self.title = self.title or ""
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description":
                self.description = a.get("content", "")
            elif name == "author":
                self.author = a.get("content", "")
        elif tag in _LEVELS:
            self._in = "heading"
            self._heading = (_LEVELS[tag], [])
        elif tag == "table":
            self._rows.append(0)
        elif tag == "tr" and self._rows:
            self._rows[-1] += 1
        elif tag in ("ol", "ul"):
            self._items.append((tag, 0))
        elif tag == "li" and self._items:
            kind, n = self._items[-1]
            self._items[-1] = (kind, n + 1)
        elif tag == "a" and a.get("href"):
            rel = a.get("rel", "").lower()
            self.links.append((a["href"], rel))
            if "author" in rel.split():
                self.byline = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in == "ld":
            self._in = None
            return
        if tag in ("header", "footer"):
            if self._chrome and self._chrome.pop():
                self._skip = max(0, self._skip - 1)
            return
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in _CONTENT:
            self._content = max(0, self._content - 1)
        if tag == "title":
            self._in = None
        elif tag in _LEVELS and self._heading is not None:
            level, chunks = self._heading
            text = _squash("".join(chunks))
            self.headings.append((level, text))
            if len(self.sections) < SECTION_CAP:
                self._section = Section(level, text)
                self.sections.append(self._section)
            else:
                self._section = None
            self._heading = None
            self._in = None
        elif tag == "table" and self._rows:
            if self._rows.pop() >= 2:
                self.tables += 1
        elif tag in ("ol", "ul") and self._items:
            kind, n = self._items.pop()
            if n >= 3:
                self.lists += 1
                if kind == "ol":
                    self.ordered_lists += 1

    def handle_data(self, data: str) -> None:
        if self._in == "ld":
            self.ld[-1] += data
            return
        if self._skip:
            return
        if self._in == "title" and self.title is not None:
            self.title += data
        elif self._in == "heading" and self._heading is not None:
            self._heading[1].append(data)
        else:
            self.words += len(data.split())
            s = self._section
            if s is not None and len(s.text) < SECTION_CHARS:
                s.text = (s.text + " " + data)[:SECTION_CHARS]


def parse(html: str) -> Page:
    page = Page()
    page.feed(html)
    page.close()
    if page.title is not None:
        page.title = _squash(page.title)
    for s in page.sections:
        s.text = _squash(s.text)
    return page


def normalize_url(url: str) -> str:
    """http(s), a host, no userinfo; scheme and host lower-cased, fragment
    dropped, an empty path made '/'. ValueError otherwise."""
    u = urlsplit(url.strip())
    scheme = u.scheme.lower()
    if scheme not in ("http", "https") or not u.hostname or u.username:
        raise ValueError(f"not an http(s) URL: {url!r}")
    host = u.hostname.lower() + (f":{u.port}" if u.port else "")
    return urlunsplit((scheme, host, u.path or "/", u.query, ""))


WEIGHTS_VERSION = "v1"
# Weight order is display order; the frontend sorts nothing.
WEIGHTS = {
    "topic_coverage": 25,
    "evidence": 15,
    "intent_fit": 10,
    "entity_coverage": 10,
    "structure": 10,
    "faqs": 10,
    "direct_answers": 10,
    "author_attribution": 5,
    "tables": 5,
}
# ponytail: hand-picked for gemini-embedding-001 from the slice-4 probe
# (unrelated ~0.5, paraphrase ~0.8); recalibrate after real pages.
COS_FLOOR = 0.55
COS_SPAN = 0.30
COS_COVERED = 0.70
FIRST_SENTENCE_WORDS = 40
MIN_WORDS = 300
_OPENERS = re.compile(r"^\s*in this (article|post|guide|page)\b", re.I)
_FAQ = re.compile(r"\b(faqs?|questions)\b", re.I)

# Page-type signals (gaps.PAGE_TYPES values). Each is (what to add, ok).
_LIST_AND_H2 = ("a list", "at least two H2 sections")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Target:
    """What the score compares the page with: one gap cluster."""

    intent: str
    topic: str
    queries: list[tuple[str, str]]  # (prompt_id, text), worst first
    rivals: list[str]
    brand: str
    aliases: list[str]
    brand_hosts: list[str]
    rival_hosts: list[str]
    cited: list[dict[str, Any]]  # {url, domain, answers, observation_ids}
    observation_ids: list[str]  # the cluster's absent answers
    page_type: str = field(init=False)

    def __post_init__(self) -> None:
        from .gaps import PAGE_TYPES  # gaps imports recommend imports pages

        self.page_type = PAGE_TYPES[self.intent]


def _suggestion(
    text: str,
    *,
    urls: list[str] | None = None,
    prompt_ids: list[str] | None = None,
    observation_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "urls": list(urls or []),
        "prompt_ids": list(prompt_ids or []),
        "observation_ids": list(observation_ids or []),
    }


def _first_sentence_words(text: str) -> int:
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return len(first.split())


def _signals(
    t: Target, page: Page, rivals_named: int
) -> list[tuple[str, bool]]:
    h2 = sum(1 for level, _ in page.headings if level == 2)
    types = {x for n in _ld_nodes(page.ld) for x in _types(n)}
    pt = t.page_type
    if pt == "comparison page":
        out = [("a comparison table", page.tables >= 1)]
        need = min(2, len(t.rivals))  # no rivals: the table alone
        if need:
            what = "at least two rivals" if need == 2 else "the rival"
            out.append((f"{what} named", rivals_named >= need))
        return out
    if pt == "best-of round-up":
        return [
            ("a list of at least three picks", page.lists >= 1),
            ("at least three H2 sections", h2 >= 3),
        ]
    if pt == "guide":
        return [
            ("at least three H2 sections", h2 >= 3),
            (f"at least {MIN_WORDS} words", page.words >= MIN_WORDS),
        ]
    if pt in ("product page", "category page"):
        return [
            (
                "Product, Offer or ItemList schema",
                bool(types & {"Product", "Offer", "ItemList"}),
            )
        ]
    if pt == "how-to":
        return [
            (
                "HowTo schema or an ordered list of steps",
                "HowTo" in types or page.ordered_lists >= 1,
            )
        ]
    return [(_LIST_AND_H2[0], page.lists >= 1), (_LIST_AND_H2[1], h2 >= 2)]


def score(
    page: Page,
    t: Target,
    query_vectors: list[list[float] | None],
    section_vectors: list[list[float]],
) -> dict[str, Any]:
    """Nine components, the weighted score and the suggestion lists.

    `query_vectors` is aligned with `t.queries` (None: no embedding);
    `section_vectors` with `page.sections`."""
    obs = t.observation_ids
    all_pids = [pid for pid, _ in t.queries]
    # A cluster with no absent answers: cite its prompts instead.
    lone = [] if obs else all_pids
    values: dict[str, tuple[float, str, list[str]]] = {}
    add: list[dict[str, Any]] = []
    remove: list[dict[str, Any]] = []
    rewrite: list[dict[str, Any]] = []
    evidence_to_add: list[dict[str, Any]] = []

    # topic_coverage
    best: list[tuple[str, str, float]] = []
    for (pid, q), qv in zip(t.queries, query_vectors, strict=True):
        if qv is None or not section_vectors:
            continue
        best.append((pid, q, max(cosine(qv, sv) for sv in section_vectors)))
    if best:
        mapped = [
            min(1.0, max(0.0, (b - COS_FLOOR) / COS_SPAN)) for *_, b in best
        ]
        value = round(sum(mapped) / len(mapped), 4)
        uncovered = [(pid, q) for pid, q, b in best if b < COS_COVERED]
        observed = (
            f"{len(best) - len(uncovered)} of {len(best)} prompts covered"
        )
        for pid, q in uncovered:
            add.append(
                _suggestion(
                    f"Add a section that answers “{q}” directly.",
                    prompt_ids=[pid],
                    observation_ids=obs,
                )
            )
        values["topic_coverage"] = (value, observed, [q for _, q in uncovered])
    else:
        values["topic_coverage"] = (0.0, "no prompt embeddings or sections", [])

    # text the entity and rival checks read
    body = " ".join(
        [page.title or "", *(h for _, h in page.headings)]
        + [s.text for s in page.sections]
    )
    names = {t.brand, *t.aliases}
    rivals_named = [r for r in t.rivals if _names_in(body, {r})]

    # evidence: owned and rival hosts are not third-party evidence
    cited_domains = [c["domain"] for c in t.cited]
    linked_cited: set[str] = set()
    other: set[str] = set()
    hosts: set[str] = set()  # every linked host, owned and rival included
    for href, _ in page.links:
        if not href.startswith(("http:", "https:")):
            continue
        host = urlsplit(href).hostname
        if host:
            hosts.add(host)
        if (
            not host
            or is_owned(host, t.brand_hosts)
            or is_owned(host, t.rival_hosts)
        ):
            continue
        matched = {d for d in cited_domains if is_owned(host, [d])}
        if matched:
            linked_cited |= matched
        else:
            other.add(host.removeprefix("www."))
    value = round(
        0.6 * min(1.0, len(linked_cited) / 3) + 0.4 * min(1.0, len(other) / 5),
        4,
    )
    linked = sorted(hosts)
    for c in t.cited:
        # Already linked: the cited domain is (or is under) a linked host,
        # or a linked host is under the cited domain.
        if is_owned(c["domain"], linked) or any(
            is_owned(h, [c["domain"]]) for h in linked
        ):
            continue
        # A rival's page is one to study, not to link.
        lead = (
            f"See how {c['url']} covers this"
            if is_owned(c["domain"], t.rival_hosts)
            else f"Cite {c['url']}"
        )
        evidence_to_add.append(
            _suggestion(
                f"{lead}: {c['answers']} answers in this cluster draw on it.",
                urls=[c["url"]],
                observation_ids=list(c["observation_ids"]),
            )
        )
    values["evidence"] = (
        value,
        f"{len(linked_cited)} cited domains linked, {len(other)} other "
        "third-party domains",
        sorted(linked_cited),
    )

    # intent_fit
    signals = _signals(t, page, len(rivals_named))
    value = round(sum(ok for _, ok in signals) / len(signals), 4)
    for what, ok in signals:
        if not ok:
            add.append(
                _suggestion(
                    f"Add {what}: a {t.page_type} is expected to have it.",
                    prompt_ids=lone,
                    observation_ids=obs,
                )
            )
    values["intent_fit"] = (
        value,
        f"{t.page_type}: "
        + ", ".join(f"{w} {'yes' if ok else 'no'}" for w, ok in signals),
        [],
    )

    # entity_coverage
    h1s = " ".join(h for level, h in page.headings if level == 1)
    in_head = _names_in(f"{page.title or ''} {h1s}", names)
    in_body = _names_in(body, names)
    value = 0.5 * in_head + 0.25 * in_body
    if t.intent in ("comparison", "alternative"):
        value += 0.25 * (len(rivals_named) / len(t.rivals) if t.rivals else 1.0)
        for r in t.rivals:
            if r not in rivals_named:
                add.append(
                    _suggestion(
                        f"Name {r}: the cluster's answers name it.",
                        prompt_ids=all_pids,
                        observation_ids=obs,
                    )
                )
    else:
        value += 0.25 * _names_in(page.description or "", names)
    if not in_head:
        rewrite.append(
            _suggestion(
                f"Name {t.brand} in the title or H1.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    values["entity_coverage"] = (
        round(value, 4),
        f"brand in title/H1 {'yes' if in_head else 'no'}, in body "
        f"{'yes' if in_body else 'no'}, rivals named {len(rivals_named)}",
        rivals_named,
    )

    # structure
    levels = [level for level, _ in page.headings]
    skipped = any(b - a > 1 for a, b in pairwise(levels))
    h2 = levels.count(2)
    value = (
        0.3 * (page.h1_count == 1)
        + 0.3 * (h2 >= 3)
        + 0.2 * (not skipped)
        + 0.2 * (page.words >= MIN_WORDS)
    )
    if page.h1_count > 1:
        remove.append(
            _suggestion(
                f"Remove the {page.h1_count - 1} extra H1 heading(s); "
                "keep one.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    elif page.h1_count == 0:
        add.append(
            _suggestion(
                "Add one H1 naming the topic.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    if h2 < 3:
        add.append(
            _suggestion(
                "Add H2 sections, one per prompt the cluster asks.",
                prompt_ids=all_pids,
                observation_ids=obs,
            )
        )
    if skipped:
        rewrite.append(
            _suggestion(
                "Fix skipped heading levels (H1 to H3).",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    if page.words < MIN_WORDS:
        rewrite.append(
            _suggestion(
                f"Expand the page: {page.words} words, under {MIN_WORDS}.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    order = "levels skipped" if skipped else "levels in order"
    values["structure"] = (
        round(value, 4),
        f"{page.h1_count} H1, {h2} H2, {order}, {page.words} words",
        [],
    )

    # faqs
    nodes = _ld_nodes(page.ld)
    faq_blocks = sum("FAQPage" in _types(n) for n in nodes)
    questions = sum(h.endswith("?") for _, h in page.headings)
    faq_heading = any(_FAQ.search(h) for _, h in page.headings)
    if faq_blocks:
        value, observed = 1.0, f"FAQPage schema ({faq_blocks})"
    elif questions >= 3 or faq_heading:
        value = 0.6
        observed = f"{questions} question headings, no FAQPage schema"
    else:
        value, observed = 0.0, "no FAQ"
    if value < 1.0:
        add.append(
            _suggestion(
                "Add an FAQ section with FAQPage schema answering the "
                "cluster's prompts.",
                prompt_ids=all_pids,
                observation_ids=obs,
            )
        )
    if faq_blocks > 1:
        remove.append(
            _suggestion(
                "Remove the duplicate FAQPage blocks; keep one.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    values["faqs"] = (value, observed, [])

    # direct_answers
    h2_sections = [s for s in page.sections if s.level == 2]
    direct = 0
    for s in h2_sections:
        opener = bool(_OPENERS.match(s.text))
        short = 0 < _first_sentence_words(s.text) <= FIRST_SENTENCE_WORDS
        if short and not opener:
            direct += 1
            continue
        if opener:
            remove.append(
                _suggestion(
                    f"Remove the “in this article” opener under “{s.heading}”.",
                    prompt_ids=lone,
                    observation_ids=obs,
                )
            )
        rewrite.append(
            _suggestion(
                f"Open “{s.heading}” with a direct answer of at most "
                f"{FIRST_SENTENCE_WORDS} words.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    value = round(direct / len(h2_sections), 4) if h2_sections else 0.0
    values["direct_answers"] = (
        value,
        f"{direct} of {len(h2_sections)} H2 sections open with a direct answer",
        [],
    )

    # author_attribution
    author = bool(
        page.author
        or page.byline
        or any("author" in n or "Person" in _types(n) for n in nodes)
    )
    if not author:
        add.append(
            _suggestion(
                "Add an author byline or Article schema with an author.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    values["author_attribution"] = (
        float(author),
        "author found" if author else "no author",
        [],
    )

    # tables
    if not page.tables:
        add.append(
            _suggestion(
                "Add a table (a comparison or a specification) with at "
                "least two rows.",
                prompt_ids=lone,
                observation_ids=obs,
            )
        )
    values["tables"] = (float(page.tables >= 1), f"{page.tables} tables", [])

    components: list[dict[str, Any]] = [
        {
            "code": code,
            "weight": w,
            "value": values[code][0],
            "points": round(w * values[code][0], 2),
            "observed": values[code][1],
            "evidence": values[code][2],
        }
        for code, w in WEIGHTS.items()
    ]
    return {
        "score": round(sum(c["points"] for c in components)),
        "weights_version": WEIGHTS_VERSION,
        "components": components,
        "suggestions": {
            "add": add,
            "remove": remove,
            "rewrite": rewrite,
            "evidence_to_add": evidence_to_add,
        },
    }
