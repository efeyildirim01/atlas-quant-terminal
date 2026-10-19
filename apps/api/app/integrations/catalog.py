"""Source catalog: the machine-readable form of docs/data-sources/SOURCE_INVENTORY.md.

``NV`` marks facts that were not verified from primary documentation. They are never presented as known.
"""

from __future__ import annotations

from app.core.config import Settings
from app.integrations.base import MarketDataProvider
from app.integrations.csv_provider import CsvProvider
from app.integrations.evds import EvdsProvider
from app.integrations.fixture import FixtureProvider
from app.integrations.gates import UnavailableSource
from app.models.enums import DataMode

NV = "not verified"

CATALOG: dict[str, dict] = {
    "fixture": {
        "name": "Development fixtures", "provider": "ATLAS (local synthetic generator)", "data_mode": DataMode.FIXTURE,
        "datasets": ["eod_bars", "fund_nav"],
        "capabilities": {"api": "in-process", "auth": "none", "history": "2019-01-02 onward", "frequency": "daily",
                         "latency": "n/a (fixed end date)", "limits": "none", "cost": "free"},
        "licence_note": "Synthetic data generated locally. NOT market data. Never use for investment decisions.",
        "attribution": "ATLAS synthetic fixture generator v1", "redistribution_allowed": True, "documentation_url": None,
    },
    "csv": {
        "name": "User-supplied files", "provider": "User", "data_mode": DataMode.USER_SUPPLIED,
        "datasets": ["eod_bars", "fund_nav"],
        "capabilities": {"api": "file import", "auth": "none", "history": "as supplied", "frequency": "as supplied",
                         "latency": "as supplied", "limits": "none", "cost": "per user's own licence"},
        "licence_note": "The user asserts they hold the rights to use and display these files.",
        "attribution": "User-supplied", "redistribution_allowed": False, "documentation_url": None,
    },
    "evds": {
        "name": "TCMB EVDS", "provider": "Central Bank of the Republic of Türkiye", "data_mode": DataMode.OFFICIAL,
        "datasets": ["macro_series"],
        "capabilities": {"api": "keyed REST web service (EVDS 2 documented; EVDS 3 beta 2026)", "auth": "API key in HTTP header",
                         "history": "series-dependent", "frequency": "series-dependent (daily FX, monthly CPI)",
                         "latency": NV, "limits": NV, "cost": "free registration"},
        "licence_note": "EVDS terms permit reuse with source attribution.",
        "attribution": "Source: CBRT (TCMB) Electronic Data Delivery System (EVDS)", "redistribution_allowed": True,
        "documentation_url": "https://evds2.tcmb.gov.tr/help/videos/EVDS_Web_Service_Usage_Guide.pdf",
    },
    "bist": {
        "name": "Borsa Istanbul market data", "provider": "Borsa İstanbul via licensed vendors", "data_mode": DataMode.LICENSED,
        "datasets": ["eod_bars", "intraday_bars", "indices", "corporate_actions"],
        "capabilities": {"api": "vendor-specific; VERDA HTTP-REST for licensed EOD files", "auth": "vendor contract",
                         "history": NV, "frequency": "real-time / delayed / EOD per licence", "latency": NV, "limits": NV,
                         "cost": "paid licence (an undated fee schedule lists an EOD package; re-verify)"},
        "licence_note": "Requires a Borsa Istanbul data licence. Derived index calculation is licensed separately.",
        "attribution": None, "redistribution_allowed": False,
        "documentation_url": "https://borsaistanbul.com/en/data/data-dissemination",
    },
    "kap": {
        "name": "KAP disclosures", "provider": "Kamuyu Aydınlatma Platformu (MKK)", "data_mode": DataMode.LICENSED,
        "datasets": ["disclosures", "financial_statements", "fund_portfolio_reports"],
        "capabilities": {"api": "no documented public API", "auth": NV, "history": NV, "frequency": "event-driven",
                         "latency": NV, "limits": NV, "cost": NV},
        "licence_note": "Requires a data-distribution agreement with MKK or a licensed vendor. No scraping.",
        "attribution": None, "redistribution_allowed": False, "documentation_url": None,
    },
    "tefas": {
        "name": "TEFAS fund data", "provider": "TEFAS / Takasbank", "data_mode": DataMode.LICENSED,
        "datasets": ["fund_nav", "fund_profile", "fund_allocation"],
        "capabilities": {"api": "no official developer API", "auth": NV, "history": NV, "frequency": "daily NAV",
                         "latency": NV, "limits": "community reports ~6 req/min on web endpoints (anecdotal)", "cost": NV},
        "licence_note": "Requires written permission from TEFAS/Takasbank or a vendor licence. No scraper ships.",
        "attribution": None, "redistribution_allowed": False, "documentation_url": None,
    },
    "tuik": {
        "name": "TÜİK statistics", "provider": "Turkish Statistical Institute", "data_mode": DataMode.OFFICIAL,
        "datasets": ["cpi", "gdp", "labour"],
        "capabilities": {"api": "no official API documentation found", "auth": NV, "history": NV, "frequency": "monthly/quarterly",
                         "latency": NV, "limits": NV, "cost": NV},
        "licence_note": "Not verified. CPI is used via the EVDS mirror instead.",
        "attribution": None, "redistribution_allowed": False, "documentation_url": None,
    },
}

UNAVAILABLE_REASONS = {
    "bist": CATALOG["bist"]["licence_note"],
    "kap": CATALOG["kap"]["licence_note"],
    "tefas": CATALOG["tefas"]["licence_note"],
    "tuik": CATALOG["tuik"]["licence_note"],
}


def build_providers(settings: Settings) -> list[MarketDataProvider]:
    """Providers in precedence order (first wins when two sources define the same instrument)."""
    providers: list[MarketDataProvider] = []
    if settings.csv_dir:
        providers.append(CsvProvider(settings.csv_dir))
    providers.append(EvdsProvider(settings.evds_api_key, settings.evds_base_url))
    if settings.enable_fixtures:
        providers.append(FixtureProvider(settings.fixture_end))
    for sid, reason in UNAVAILABLE_REASONS.items():
        providers.append(UnavailableSource(sid, CATALOG[sid]["datasets"], reason))
    return providers
