"""Deterministic verification of numeric claims in a model answer (the "verification agent").

For every number in the answer, the sentence it sits in is checked for evidence citations like [E3]. The number
must match a value inside the cited evidence, allowing for display rounding, fraction↔percent conversion, sign
dropped for losses ("a 38% drawdown" for −0.38), magnitude suffixes and Turkish/English number formats.

Outcomes per claim:
- verified          number matches a value in the evidence it cites
- mismatch          it cites evidence, but no value there matches        → flagged
- uncited           no citation in the sentence; the number exists in some evidence → flagged (soft)
- unsupported       no citation and no evidence contains it              → flagged
Citations to evidence ids that do not exist are flagged too.

Skipped by design (not financial figures): dates, years, evidence ids, horizon labels such as 3Y/20D/RSI14,
and bare integers below 100 without a decimal or % sign (counts, ordinals, window lengths).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

CITE = re.compile(r"\[(E\d+(?:\s*,\s*E\d+)*)\]")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
NUM = re.compile(
    r"(?<![\w.,])(?P<pct_pre>%\s?)?(?P<sign>[-−+])?(?P<num>\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<pct_post>\s?%)?(?P<suffix>\s?(?:bn|mn|Mn|Mr|M|B|k|K|milyar|milyon)\b)?(?![\w])"
)
SUFFIX = {"k": 1e3, "K": 1e3, "M": 1e6, "mn": 1e6, "Mn": 1e6, "milyon": 1e6, "B": 1e9, "bn": 1e9, "Mr": 1e9, "milyar": 1e9}
SENTENCE = re.compile(r"(?<=[.!?:;])\s+(?=[A-ZÇĞİÖŞÜ0-9*\-•|])|\n+")


@dataclass
class Claim:
    text: str
    value: float
    decimals: int
    is_pct: bool
    cites: list[str]
    status: str = "unchecked"
    matched_in: str | None = None


@dataclass
class Report:
    claims: list[Claim] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.invalid_citations or any(c.status in ("mismatch", "unsupported") for c in self.claims):
            return "unverified_claims"
        if any(c.status == "uncited" for c in self.claims):
            return "partially_verified"
        return "verified" if self.claims else "no_numeric_claims"

    def to_dict(self) -> dict:
        counts: dict[str, int] = {}
        for c in self.claims:
            counts[c.status] = counts.get(c.status, 0) + 1
        return {"status": self.status, "counts": counts, "invalid_citations": self.invalid_citations,
                "cited_evidence": self.cited_ids,
                "claims": [{"text": c.text, "value": c.value, "is_pct": c.is_pct, "cites": c.cites, "status": c.status,
                            "matched_in": c.matched_in} for c in self.claims]}


def _parse(token: str) -> list[tuple[float, int]]:
    """All plausible (value, decimals) readings of a number token under English and Turkish conventions."""
    t = token.replace(" ", "").replace(" ", "").replace(" ", "")
    out = []
    for dec, grp in ((".", ","), (",", ".")):
        parts = t.split(dec)
        if len(parts) > 2:
            continue
        intpart = parts[0]
        if grp in intpart:
            groups = intpart.split(grp)
            if not all(len(g) == 3 for g in groups[1:]):
                continue
            intpart = "".join(groups)
        if not intpart.isdigit():
            continue
        frac = parts[1] if len(parts) == 2 else ""
        if frac and not frac.isdigit():
            continue
        out.append((float(f"{intpart}.{frac}" if frac else intpart), len(frac)))
    return list(dict.fromkeys(out))


def _numbers(obj, out: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)


def _matches(value: float, decimals: int, is_pct: bool, pool: list[float], mult: float = 1.0) -> bool:
    tol = 10 ** (-decimals) * mult * 1.0001  # one unit in the last shown digit (display rounding or truncation), scaled by suffix
    for v in pool:
        cands = [v * 100, abs(v) * 100] if is_pct else [v, abs(v), v * 100, abs(v) * 100]
        if is_pct and abs(v) > 1.5:  # already a percentage number in the evidence (e.g. RSI-like or "pct" fields)
            cands += [v, abs(v)]
        if any(abs(c - value) <= tol for c in cands):
            return True
    return False


def verify_answer(answer: str, evidence: dict[str, dict]) -> Report:
    """`evidence` maps id → the evidence record (its `data` is searched, plus as_of-free numeric metadata)."""
    rep = Report()
    pools: dict[str, list[float]] = {}
    for eid, ev in evidence.items():
        nums: list[float] = []
        _numbers(ev.get("data"), nums)
        pools[eid] = nums
    all_pool = [n for p in pools.values() for n in p]
    text = DATE.sub(" ", answer)
    seen_ids: set[str] = set()
    for sentence in SENTENCE.split(text):
        cites = [c.strip() for m in CITE.finditer(sentence) for c in m.group(1).split(",")]
        for c in cites:
            seen_ids.add(c)
            if c not in evidence and c not in rep.invalid_citations:
                rep.invalid_citations.append(c)
        body = CITE.sub(" ", sentence)
        for m in NUM.finditer(body):
            raw = m.group("num")
            is_pct = bool(m.group("pct_pre") or m.group("pct_post"))
            readings = _parse(raw)
            if not readings:
                continue
            value, decimals = readings[0]
            if not is_pct and decimals == 0 and len(readings) == 1 and (value < 100 or 1900 <= value <= 2100):
                continue  # counts, ordinals, years
            sign = -1.0 if m.group("sign") in ("-", "−") else 1.0
            mult = SUFFIX.get((m.group("suffix") or "").strip(), 1.0)
            claim = Claim(m.group(0).strip(), sign * value * mult, decimals, is_pct, [c for c in cites if c in evidence])
            valid = claim.cites
            hit = None
            for eid in valid:
                if any(_matches(abs(v) * mult, d, is_pct, pools[eid], mult) for v, d in readings):
                    hit = eid
                    break
            if hit:
                claim.status, claim.matched_in = "verified", hit
            elif valid:
                claim.status = "mismatch"
            elif any(_matches(abs(v) * mult, d, is_pct, all_pool, mult) for v, d in readings):
                claim.status = "uncited"
            else:
                claim.status = "unsupported"
            rep.claims.append(claim)
    rep.cited_ids = sorted(seen_ids & set(evidence), key=lambda s: int(s[1:]))
    return rep
