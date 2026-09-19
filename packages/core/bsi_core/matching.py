"""Deterministic brand and competitor matching. Pure functions, no I/O."""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_URL = re.compile(
    r"https?://\S+|"  # scheme-based URLs
    # ponytail: TLD 2-24 chars; prose without space ("Nike.Great") loses mention
    r"\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,24}\b(?:/\S*)?"
)
_FUZZY_MIN = 5


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    entity_id: str
    entity_type: str
    start_token: int
    alias: str
    fuzzy: bool


def _collect_tokens(text: str) -> list[str]:
    """Collect tokens: maximal runs of alnum + combining marks.

    Token must not start with a combining mark (category M*).
    """
    tokens: list[str] = []
    current = []
    for ch in text:
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            current.append(ch)
        else:
            if current and not unicodedata.category(current[0]).startswith("M"):
                tokens.append("".join(current))
            current = []
    if current and not unicodedata.category(current[0]).startswith("M"):
        tokens.append("".join(current))
    return tokens


def tokenize(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _collect_tokens(_URL.sub(" ", folded))


def _within_one(a: str, b: str) -> bool:
    """Levenshtein distance <= 1."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :]
    return a[i:] == b[i + 1 :]


def _span_match(alias: list[str], window: list[str]) -> bool | None:
    """None = no match; otherwise whether the match needed fuzziness."""
    fuzzy = False
    for a, t in zip(alias, window, strict=True):
        if a == t:
            continue
        if min(len(a), len(t)) >= _FUZZY_MIN and _within_one(a, t):
            fuzzy = True
            continue
        return None
    return fuzzy


def find_mentions(text: str, entities: Sequence[Entity]) -> list[Hit]:
    tokens = tokenize(text)
    candidates: list[tuple[int, bool, int, Entity, str]] = []
    for entity in entities:
        for alias in entity.aliases:
            alias_tokens = tokenize(alias)
            size = len(alias_tokens)
            if not size:
                continue
            for i in range(len(tokens) - size + 1):
                fuzzy = _span_match(alias_tokens, tokens[i : i + size])
                if fuzzy is not None:
                    candidates.append((size, fuzzy, i, entity, alias))
    # Longest alias first, then exact before fuzzy, then leftmost.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    taken: set[int] = set()
    hits: list[Hit] = []
    for size, fuzzy, start, entity, alias in candidates:
        span = set(range(start, start + size))
        if span & taken:
            continue
        taken |= span
        hits.append(Hit(entity.id, entity.type, start, alias, fuzzy))
    return sorted(hits, key=lambda h: h.start_token)


def normalize_domain(value: str) -> str:
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip().casefold())
    v = v.split("/")[0].split("?")[0].split("@")[-1].split(":")[0]
    return v.removeprefix("www.").rstrip(".")


def is_owned(domain: str, hosts: Iterable[str]) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in hosts)
