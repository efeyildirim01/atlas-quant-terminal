"""Deterministic SYNTHETIC market. Not market data and not calibrated to any real instrument.

All symbols start with ``D-`` so they cannot be confused with real BIST tickers or TEFAS fund
codes. The generator is a regime-switching factor model, so the analytics have realistic
structure to work on: fat tails, volatility clustering and correlated sectors.
"""

from __future__ import annotations

import hashlib
from datetime import date
from functools import cached_property

import numpy as np
import pandas as pd

from app.integrations.base import InstrumentNotFound, MarketDataProvider, ProviderInstrument, ProviderStatus, slice_dates
from app.models.enums import DataMode, SourceAvailability

START = date(2019, 1, 2)

# symbol, name, sector, beta, idio daily vol, base price, base volume
EQUITIES = [
    ("D-AIRL", "Demo Airline", "Transportation", 1.25, 0.022, 18.0, 4.0e7),
    ("D-BNK1", "Demo Bank One", "Banking", 1.30, 0.020, 6.5, 1.2e8),
    ("D-BNK2", "Demo Bank Two", "Banking", 1.20, 0.019, 9.0, 8.0e7),
    ("D-STEL", "Demo Steel Works", "Basic Materials", 1.05, 0.021, 14.0, 3.0e7),
    ("D-RFIN", "Demo Refinery", "Energy", 0.95, 0.017, 110.0, 6.0e6),
    ("D-DEFN", "Demo Defence Electronics", "Technology", 0.90, 0.023, 25.0, 2.5e7),
    ("D-TLCO", "Demo Telecom", "Telecommunications", 0.80, 0.016, 20.0, 2.0e7),
    ("D-RETL", "Demo Retail", "Consumer Staples", 0.70, 0.015, 55.0, 8.0e6),
    ("D-AUTO", "Demo Automotive", "Consumer Discretionary", 1.10, 0.020, 70.0, 5.0e6),
    ("D-GLAS", "Demo Glass Industries", "Basic Materials", 0.95, 0.018, 12.0, 2.0e7),
    ("D-ENRG", "Demo Power Utility", "Utilities", 0.85, 0.024, 8.0, 5.0e7),
    ("D-HOLD", "Demo Holding", "Holding", 1.00, 0.014, 30.0, 3.0e7),
]
SECTORS = sorted({e[2] for e in EQUITIES})

# symbol, name, category, fee, risk class, benchmark
FUNDS = [
    ("D-EQF", "Demo BIST Equity Fund", "Equity", 0.025, 6, "D-IDX"),
    ("D-PRT", "Demo Participation Equity Fund", "Participation", 0.022, 6, "D-IDX"),
    ("D-TCH", "Demo Technology Fund", "Equity (Technology)", 0.028, 7, "D-IDX"),
    ("D-FGN", "Demo Foreign Equity Fund", "Foreign Equity", 0.024, 6, None),
    ("D-GLD", "Demo Gold Fund", "Precious Metals", 0.018, 5, None),
    ("D-MMF", "Demo Money Market Fund", "Money Market", 0.010, 1, None),
]

LICENSE = "Synthetic data generated locally. Not market data. Do not use for investment decisions."


def _seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "little")


EXCHANGE = "FIXTURE"  # never a real MIC such as XIST
MANAGER = "Fixture Asset Management (synthetic)"


class FixtureProvider(MarketDataProvider):
    source_id = "fixture"
    data_mode = DataMode.FIXTURE

    def __init__(self, end: date):
        self.end = end

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            source_id=self.source_id,
            availability=SourceAvailability.AVAILABLE,
            datasets=["eod_bars", "fund_nav"],
            detail=f"Synthetic universe: {len(EQUITIES)} equities, 1 index, {len(FUNDS)} funds; {START} to {self.end}",
        )

    @cached_property
    def _dates(self) -> pd.DatetimeIndex:
        return pd.bdate_range(START, self.end)

    @cached_property
    def _factors(self) -> pd.DataFrame:
        n = len(self._dates)
        rng = np.random.default_rng(_seed("market"))
        # Two-state Markov volatility regime for the market factor.
        p_stay = {0: 0.985, 1: 0.95}
        state = np.zeros(n, dtype=int)
        for t in range(1, n):
            stay = rng.random() < p_stay[state[t - 1]]
            state[t] = state[t - 1] if stay else 1 - state[t - 1]
        vol = np.where(state == 0, 0.012, 0.027)
        shocks = rng.standard_t(df=4, size=n) / np.sqrt(2.0)  # unit-variance Student-t
        market = 0.0011 - 0.5 * vol**2 + vol * shocks  # ~30%/yr nominal TRY drift
        out = {"market": market, "regime": state}
        for s in SECTORS:
            r = np.random.default_rng(_seed("sector", s))
            out[f"sector:{s}"] = r.normal(0.0, 0.006, n)
        g = np.random.default_rng(_seed("global"))
        out["global"] = g.normal(0.0004, 0.010, n)
        out["fx"] = g.normal(0.0012, 0.006, n)  # TRY depreciation drift
        out["gold"] = g.normal(0.0002, 0.009, n)
        return pd.DataFrame(out, index=self._dates)

    def _equity_returns(self, symbol: str) -> pd.Series:
        _, _, sector, beta, idio, *_ = next(e for e in EQUITIES if e[0] == symbol)
        f = self._factors
        rng = np.random.default_rng(_seed("idio", symbol))
        r = beta * f["market"] + f[f"sector:{sector}"] + rng.normal(0, idio, len(f))
        return r.clip(-0.095, 0.095)  # keep within a typical daily price-limit band

    @cached_property
    def _index_returns(self) -> pd.Series:
        rets = pd.concat([np.expm1(self._equity_returns(e[0])) for e in EQUITIES], axis=1)
        return rets.mean(axis=1)  # equal-weight, daily rebalanced

    def _ohlcv(self, symbol: str, log_ret: pd.Series, base_price: float, base_volume: float) -> pd.DataFrame:
        rng = np.random.default_rng(_seed("ohlc", symbol))
        n = len(log_ret)
        close = base_price * np.exp(np.cumsum(log_ret.to_numpy()))
        prev = np.concatenate([[base_price], close[:-1]])
        open_ = prev * np.exp(rng.normal(0, 0.004, n))
        wick = np.abs(rng.normal(0, 0.006, (2, n)))
        high = np.maximum(open_, close) * np.exp(wick[0])
        low = np.minimum(open_, close) * np.exp(-wick[1])
        activity = 1.0 + 25.0 * np.abs(log_ret.to_numpy())
        volume = np.round(base_volume * activity * rng.lognormal(0, 0.35, n))
        return pd.DataFrame(
            {"open": open_.round(2), "high": high.round(2), "low": low.round(2), "close": close.round(2), "volume": volume},
            index=log_ret.index,
        ).assign(high=lambda d: d[["open", "high", "close"]].max(axis=1), low=lambda d: d[["open", "low", "close"]].min(axis=1))

    def _fund_nav(self, symbol: str) -> pd.DataFrame:
        _, _, category, fee, _, _ = next(f for f in FUNDS if f[0] == symbol)
        f = self._factors
        n = len(f)
        rng = np.random.default_rng(_seed("fund", symbol))
        idx = self._index_returns
        if symbol == "D-MMF":
            rate = np.interp(np.arange(n), [0, n * 0.3, n * 0.55, n * 0.8, n - 1], [0.22, 0.16, 0.35, 0.48, 0.42])
            r = (1 + rate) ** (1 / 252) - 1 + rng.normal(0, 2e-5, n)
        elif symbol == "D-GLD":
            r = f["gold"] + f["fx"] + rng.normal(0, 0.001, n)
        elif symbol == "D-FGN":
            r = f["global"] + f["fx"] + rng.normal(0, 0.002, n)
        elif symbol == "D-TCH":
            r = 0.8 * idx + 0.6 * f["sector:Technology"] + rng.normal(0.0002, 0.005, n)
        else:
            r = 0.92 * idx + rng.normal(0.0001, 0.004, n)
        r = np.asarray(r) - fee / 252
        nav = np.cumprod(1 + r)
        size = 5e8 * np.exp(np.cumsum(rng.normal(0.0008, 0.01, n)))
        investors = np.maximum(100, np.round(2000 * np.exp(np.cumsum(rng.normal(0.0006, 0.004, n)))))
        return pd.DataFrame({"nav": nav.round(6), "total_assets": size.round(0), "investor_count": investors}, index=f.index)

    def list_instruments(self) -> list[ProviderInstrument]:
        common = dict(exchange=EXCHANGE, currency="TRY")
        out = [ProviderInstrument(symbol="D-IDX", name="Fixture Equal-Weight Index", instrument_type="index", **common)]
        out += [
            ProviderInstrument(symbol=s, name=nm, instrument_type="equity", sector=sec, benchmark_symbol="D-IDX", **common)
            for s, nm, sec, *_ in EQUITIES
        ]
        out += [
            ProviderInstrument(
                symbol=s, name=nm, instrument_type="fund", benchmark_symbol=bm, **common,
                fund={"code": s, "management_company": MANAGER, "category": cat, "management_fee": fee,
                      "risk_classification": rc, "benchmark_text": bm or "None disclosed", "inception_date": START},
            )
            for s, nm, cat, fee, rc, bm in FUNDS
        ]
        return out

    def get_series(self, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        if symbol == "D-IDX":
            df = self._ohlcv(symbol, np.log1p(self._index_returns), 10_000.0, 5.0e9)
        elif any(e[0] == symbol for e in EQUITIES):
            e = next(e for e in EQUITIES if e[0] == symbol)
            df = self._ohlcv(symbol, self._equity_returns(symbol), e[5], e[6])
        elif any(f[0] == symbol for f in FUNDS):
            df = self._fund_nav(symbol)
        else:
            raise InstrumentNotFound(symbol)
        return slice_dates(df, start, end)

    def market_regime(self) -> pd.Series:
        """Ground-truth latent regime of the generator. Exposed for testing regime models only."""
        return self._factors["regime"]
