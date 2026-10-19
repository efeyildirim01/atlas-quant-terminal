"""Instrument search: exact/prefix/substring matching with Turkish-aware normalisation and typo tolerance.

In-memory scoring is adequate for the current universe (well under 10k instruments). At larger scale this moves to
PostgreSQL ``pg_trgm`` indexes. Symbols are not globally unique, so every hit carries its type and exchange.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Instrument
from app.schemas.envelope import SearchHit, SearchResult

# Length-preserving fold so highlight offsets map back onto the original string.
_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g", "Ö": "o", "ö": "o",
                       "Ş": "s", "ş": "s", "Ü": "u", "ü": "u"})
GROUPS = {"equity": "equities", "fund": "funds", "index": "indices"}
FUZZY_THRESHOLD = 0.72


def fold(text: str) -> str:
    out = text.translate(_FOLD).lower()
    return out if len(out) == len(text) else text.lower()


def _score(q: str, field: str, base_exact: float, base_prefix: float, base_sub: float, word_prefix: bool = True):
    f = fold(field)
    if f == q:
        return base_exact, [(0, len(field))]
    if f.startswith(q):
        return base_prefix - 0.1 * (len(f) - len(q)) / max(len(f), 1), [(0, len(q))]
    if word_prefix:
        pos = 0
        for word in f.split():
            if word.startswith(q):
                return base_sub + 5, [(pos, pos + len(q))]
            pos += len(word) + 1
    i = f.find(q)
    if i >= 0:
        return base_sub, [(i, i + len(q))]
    return None


def _fuzzy(q: str, field: str) -> float:
    f = fold(field)
    best = SequenceMatcher(None, q, f).ratio()
    for word in f.split():
        best = max(best, SequenceMatcher(None, q, word).ratio())
    return best


def search_instruments(db: Session, query: str, limit_per_group: int = 8, types: set[str] | None = None) -> SearchResult:
    q = fold(query.strip())
    result = SearchResult(query=query, groups={})
    if not q:
        return result
    stmt = select(Instrument).options(selectinload(Instrument.fund)).where(Instrument.listing_status != "delisted")
    candidates = list(db.scalars(stmt))
    hits: list[SearchHit] = []
    fuzzy_hits: list[SearchHit] = []
    for inst in candidates:
        if types and inst.instrument_type not in types:
            continue
        company = inst.fund.management_company if inst.fund else None
        subtitle = company or inst.sector
        is_fixture = inst.exchange == "FIXTURE"
        best = None
        for field_name, text, scores in (("symbol", inst.symbol, (100, 90, 70)), ("name", inst.name, (80, 75, 60)),
                                         ("management_company", company, (55, 50, 45))):
            if not text:
                continue
            r = _score(q, text, *scores)
            if r and (best is None or r[0] > best[0]):
                best = (r[0], field_name, r[1])
        common = dict(instrument_id=inst.instrument_id, symbol=inst.symbol, name=inst.name, instrument_type=inst.instrument_type,
                      exchange=inst.exchange, subtitle=subtitle, is_fixture=is_fixture)
        if best:
            hits.append(SearchHit(**common, score=round(best[0], 3), match_field=best[1], highlight=best[2]))
        elif len(q) >= 3:
            ratio = max(_fuzzy(q, inst.symbol), _fuzzy(q, inst.name))
            if ratio >= FUZZY_THRESHOLD:
                fuzzy_hits.append(SearchHit(**common, score=round(40 * ratio, 3), match_field="name", highlight=[]))
    chosen = hits or fuzzy_hits
    result.corrected = not hits and bool(fuzzy_hits)
    for hit in sorted(chosen, key=lambda h: (-h.score, h.symbol)):
        group = GROUPS.get(hit.instrument_type, "other")
        bucket = result.groups.setdefault(group, [])
        if len(bucket) < limit_per_group:
            bucket.append(hit)
    return result
