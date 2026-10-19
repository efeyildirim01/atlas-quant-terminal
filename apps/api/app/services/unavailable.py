from app.integrations.catalog import CATALOG
from app.schemas.envelope import UnavailableData


def unavailable(dataset: str, source_id: str, extra: str = "") -> UnavailableData:
    """Explicit 'no data' payload. Used instead of empty or placeholder numbers."""
    reason = CATALOG[source_id]["licence_note"] + (f" {extra}" if extra else "")
    return UnavailableData(dataset=dataset, reason=reason, required_source=CATALOG[source_id]["name"])
