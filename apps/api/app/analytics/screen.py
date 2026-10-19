"""Screen evaluation over a snapshot table. Pure: (DataFrame, filter tree) → boolean mask + diagnostics.

Missing-value rule: a condition on a missing value is False (the instrument does not pass). How many instruments
each condition excluded *only because the value was missing* is reported, so data gaps never hide silently.
NOT is deliberately absent. Every operator has an explicit complement (gt/lte, in/not_in, is_true/is_false), and a
negation that turned "missing" into "passes" would break the rule above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

NUMBER_OPS = {"gt", "gte", "lt", "lte", "between", "eq", "neq"}
CATEGORY_OPS = {"eq", "neq", "in", "not_in"}
BOOLEAN_OPS = {"is_true", "is_false"}
OPS_BY_TYPE = {"number": NUMBER_OPS, "category": CATEGORY_OPS, "boolean": BOOLEAN_OPS}
MAX_DEPTH = 3
MAX_CONDITIONS = 20


class ScreenError(ValueError):
    pass


@dataclass
class Diagnostics:
    missing_by_condition: list[dict] = field(default_factory=list)
    conditions: int = 0


def _condition(df: pd.DataFrame, c: dict, types: dict[str, str], diag: Diagnostics) -> pd.Series:
    fid, op = c["field"], c["operator"]
    if fid not in types:
        raise ScreenError(f"unknown or unavailable field '{fid}'")
    ftype = types[fid]
    if op not in OPS_BY_TYPE[ftype]:
        raise ScreenError(f"operator '{op}' is not valid for {ftype} field '{fid}' (allowed: {sorted(OPS_BY_TYPE[ftype])})")
    col = df[fid]
    present = col.notna()
    v, v2 = c.get("value"), c.get("value2")
    if ftype == "number":
        if op == "between":
            if not isinstance(v, (int, float)) or not isinstance(v2, (int, float)) or v > v2:
                raise ScreenError(f"'between' on '{fid}' needs numeric value ≤ value2")
            res = col.between(v, v2)
        else:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ScreenError(f"'{op}' on '{fid}' needs a numeric value")
            res = {"gt": col > v, "gte": col >= v, "lt": col < v, "lte": col <= v, "eq": col == v, "neq": col != v}[op]
    elif ftype == "category":
        if op in ("in", "not_in"):
            if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                raise ScreenError(f"'{op}' on '{fid}' needs a non-empty list of strings")
            res = col.isin(v) if op == "in" else ~col.isin(v)
        else:
            if not isinstance(v, str):
                raise ScreenError(f"'{op}' on '{fid}' needs a string value")
            res = col == v if op == "eq" else col != v
    else:
        res = col.astype("boolean") if op == "is_true" else ~col.astype("boolean")
    res = res.fillna(False).astype(bool) & present
    diag.missing_by_condition.append({"field": fid, "operator": op, "excluded_missing": int((~present).sum())})
    return res


def evaluate(df: pd.DataFrame, node: dict[str, Any] | None, types: dict[str, str]) -> tuple[pd.Series, Diagnostics]:
    diag = Diagnostics()
    if not node or not node.get("conditions"):
        return pd.Series(True, index=df.index), diag

    def walk(n: dict, depth: int) -> pd.Series:
        if depth > MAX_DEPTH:
            raise ScreenError(f"groups can be nested at most {MAX_DEPTH} levels")
        op = n.get("op", "and")
        if op not in ("and", "or"):
            raise ScreenError("group op must be 'and' or 'or'")
        parts = []
        for child in n.get("conditions", []):
            if "conditions" in child:
                parts.append(walk(child, depth + 1))
            else:
                diag.conditions += 1
                if diag.conditions > MAX_CONDITIONS:
                    raise ScreenError(f"at most {MAX_CONDITIONS} conditions per screen")
                parts.append(_condition(df, child, types, diag))
        if not parts:
            return pd.Series(True, index=df.index)
        out = parts[0]
        for p in parts[1:]:
            out = (out & p) if op == "and" else (out | p)
        return out

    return walk(node, 1), diag


def sort_rows(df: pd.DataFrame, field_id: str | None, descending: bool) -> pd.DataFrame:
    """Missing values always last, whatever the direction; ties broken by symbol for a stable order."""
    if not field_id:
        return df.sort_values("symbol")
    if field_id not in df.columns:
        raise ScreenError(f"cannot sort by unknown field '{field_id}'")
    present, missing = df[df[field_id].notna()], df[df[field_id].isna()]
    present = present.sort_values([field_id, "symbol"], ascending=[not descending, True])
    return pd.concat([present, missing.sort_values("symbol")])
