"""URL optimizer and AI Citability Score (PRD F11, second half).

`parse` reads one HTML page into the few things the score looks at;
`score` compares that page with one content-gap cluster (a `Target`) and
returns nine weighted components, a 0-100 score and four suggestion
lists. Pure: the caller fetches and embeds."""

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

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
