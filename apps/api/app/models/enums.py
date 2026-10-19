from enum import StrEnum


class QualityStatus(StrEnum):
    """Record-level data quality. See docs/financial-methodology/DATA_QUALITY_POLICY.md."""

    VERIFIED = "VERIFIED"  # licensed/official source AND passes all checks AND cross-checked against a 2nd source
    VALIDATED = "VALIDATED"  # passes all hard checks (single source)
    PARTIAL = "PARTIAL"  # present but failed a hard check; excluded from analytics
    STALE = "STALE"  # series-level: last observation older than the freshness policy
    CONFLICTED = "CONFLICTED"  # sources disagree beyond tolerance; excluded until resolved
    UNAVAILABLE = "UNAVAILABLE"  # no permitted source


USABLE_FOR_ANALYTICS = (QualityStatus.VERIFIED, QualityStatus.VALIDATED)


class DataMode(StrEnum):
    FIXTURE = "fixture"  # synthetic development data, never market data
    USER_SUPPLIED = "user_supplied"
    LICENSED = "licensed"
    OFFICIAL = "official"


class SourceAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"  # implemented, missing configuration (e.g. API key)
    UNAVAILABLE = "unavailable"  # no licence / no permitted access


class InstrumentType(StrEnum):
    EQUITY = "equity"
    INDEX = "index"
    FUND = "fund"
    FX = "fx"
    COMMODITY = "commodity"
    MACRO = "macro"


class Role(StrEnum):
    USER = "user"
    PROFESSIONAL = "professional"
    RESEARCH_ANALYST = "research_analyst"
    ADMINISTRATOR = "administrator"


ROLE_RANK = {Role.USER: 0, Role.PROFESSIONAL: 1, Role.RESEARCH_ANALYST: 2, Role.ADMINISTRATOR: 3}


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    FEE = "fee"
