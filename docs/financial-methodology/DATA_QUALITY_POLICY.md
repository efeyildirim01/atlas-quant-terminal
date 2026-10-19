# Data Quality Policy

Implementation: `apps/api/app/services/data_quality.py`. Results are stored per row
(`quality_status`, `quality_flags`) and per run (`data_quality_issues`).

## Statuses
| Status | Meaning | Used in analytics |
|---|---|---|
| VERIFIED | Licensed or official source, passes every hard check, **and** agrees with an independent second source within tolerance (`check_source_conflict`, default 0.5%) | Yes |
| VALIDATED | Passes every hard check (single source) | Yes |
| PARTIAL | Row present but failed a hard check | **No** (counted as `rows_excluded`) |
| STALE | Series-level: last observation older than `ATLAS_STALE_AFTER_BDAYS` business days | Yes, with a visible STALE badge |
| CONFLICTED | Sources disagree beyond tolerance | No |
| UNAVAILABLE | No permitted source | n/a |

**No data in ATLAS today is VERIFIED.** Only one source per dataset exists, and fixture data can never be verified.

## Checks
Hard checks (row → PARTIAL): duplicate timestamp (all copies), missing OHLCV or NAV, non-positive price or NAV,
high/low not bounding open/close, negative volume, currency mismatch.

Soft checks (flag only): one-day move > 20% (possible unadjusted corporate action), volume > 10× trailing
20-session median, gaps > 5 business days, 5+ unchanged zero-volume closes, NAV change > 15%, missing
publication timestamps.

Nothing is interpolated or repaired. Re-ingestion replaces a source's rows and resolves the previous run's
issues. Every run is logged in `ingestion_runs`. The dashboard is at `/system/data-health`.

## Known gaps
- Exchange holidays are not modelled (freshness and gap checks count weekdays only).
- Corporate-action discontinuity is detected only heuristically (large move) until a corporate-action feed exists.
