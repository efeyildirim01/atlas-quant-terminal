# Data-Source Inventory & Capability Matrix

Last reviewed: **2026-10-16**. "Not verified" means no primary documentation was found. It never
means "assumed available". The machine-readable version of this table is
`apps/api/app/integrations/catalog.py`. It is seeded into the `data_sources` table and served at
`GET /api/v1/system/sources`.

## Capability matrix

| Source | Datasets | API | Auth | Licence / redistribution | Status in ATLAS |
|---|---|---|---|---|---|
| **Borsa Istanbul** (via licensed vendors) | EOD & intraday prices, indices, corporate actions | Vendor-specific; VERDA HTTP-REST for licensed EOD files | Vendor contract | Paid licence. Redistribution and derived-index calculation are licensed separately | `UNAVAILABLE`: adapter boundary only |
| **KAP** (operated by MKK) | Disclosures, financial statements (XBRL), fund portfolio reports | No documented public API found | — | Data-distribution agreement with MKK required (not verified) | `UNAVAILABLE` |
| **TEFAS** (Takasbank) | Fund NAV, size, investor count, allocation | **No official developer API**. Community tools scrape web endpoints | — | No published terms authorising automated collection | `UNAVAILABLE`: no scraper ships |
| **TCMB EVDS** | Policy rate, FX, CPI, yields, reserves | Yes, keyed web service. EVDS 3 launched in beta in Jan 2026; EVDS 2 still online | API key, now sent in an HTTP header (header name not verified) | Reuse permitted **with attribution** | `DISABLED` until `ATLAS_EVDS_API_KEY` is set. Not verified live |
| **TÜİK** | CPI, GDP, labour | Web data portal; **no official API documentation found** | — | Not verified | `UNAVAILABLE`. CPI is also available via EVDS |
| **Licensed market-data vendors** | Varies | Vendor APIs / files | Contract | Per contract (display vs non-display) | `UNAVAILABLE` until a contract exists |
| **User-supplied CSV** | EOD bars, NAVs | File import | — | The user asserts the rights | `AVAILABLE` when `ATLAS_CSV_DIR` is set |
| **Development fixtures** | Synthetic bars & NAVs | Local generator | — | Synthetic; not market data | `AVAILABLE` in development. Always labelled `FIXTURE` |

## Per-source detail

### Borsa Istanbul
- **Provider:** Borsa İstanbul A.Ş., via ~50+ licensed data vendors.
- **Historical coverage, latency, usage limits:** per vendor contract. Not verified.
- **Cost:** an undated BIST fee-schedule PDF lists an EOD package at 900 TL / 190 USD. This must be
  re-verified with BIST before budgeting.
- **Reliability:** primary exchange data, so the highest reliability once licensed.
- **Feasibility:** high, but it needs a commercial contract. This is the critical-path item for real equity data.

### KAP
- **Provider:** Kamuyu Aydınlatma Platformu, operated by MKK.
- **Datasets:** company disclosures, periodic financial reports, fund portfolio distribution reports.
- **API:** none documented publicly. Do not scrape kap.org.tr without written permission.
- **Feasibility:** medium. It needs an MKK agreement or a vendor that redistributes KAP data.

### TEFAS
- **Provider:** TEFAS (Türkiye Elektronik Fon Alım Satım Platformu), operated by Takasbank.
- **API:** no official developer API. One community project reports a rate limit of about
  6 requests/min on the web endpoints. This is anecdotal and does not grant permission.
- **Feasibility:** blocked until Takasbank grants written permission or a vendor licenses fund data.
  Fund NAVs are also disclosed on KAP, which could be an alternative licensed route.

### TCMB EVDS
- **Provider:** Central Bank of the Republic of Türkiye.
- **API:** documented for EVDS 2 (`series=…&startDate=dd-mm-yyyy&endDate=…&type=json`). The
  key moved to an HTTP header in a recent update, according to a client-library changelog.
  EVDS 3 is in beta. The exact header name and the EVDS 3 base URL must be confirmed with a real key.
- **Update frequency:** per series (daily FX, monthly CPI, policy-rate decisions).
- **Licence:** reuse with attribution, per the EVDS terms of use.
- **Feasibility:** **high**. This is the first real integration target. A registered key is required.

### TÜİK
- No official API reference found. A commercial intermediary offers a wrapper, which is not a primary
  source. For CPI, ATLAS uses the EVDS mirror series once EVDS is enabled.

## Sources consulted
- EVDS Web Service Usage Guide (EVDS 2): https://evds2.tcmb.gov.tr/help/videos/EVDS_Web_Service_Usage_Guide.pdf
- EVDS terms of use (EVDS 3): https://evds3.tcmb.gov.tr/igmevdsms-dis/documents/showDocument?docId=18
- EVDS 3 beta announcement (press): https://www.cnbce.com/veriler/tcmb-elektronik-veri-dagitim-sistemini-yeniledi-h23757
- evdspy changelog noting the header-based key: https://pypi.org/project/evdspy/1.1.20
- BIST data dissemination & vendor directory: https://borsaistanbul.com/en/data/data-dissemination
- BIST licence for index calculation on delayed/EOD data: https://borsaistanbul.com/en/announcement/13712/statement-about-index-calculation-borsa-istanbul-delayed-and-end-day-data
- BIST fee schedule (undated): https://www.borsaistanbul.com/files/borsa-istanbul-data-fee-schedule.pdf
- KAP membership undertaking (MKK): https://www.mkk.com.tr/sites/default/files/2021-12/KAP-Uyelik-Taahhütname.pdf
- TEFAS community tooling (not authoritative): https://github.com/maku-cpu/fonlar-mcp
- TÜİK portal relaunch (press): https://www.memurlar.net/haber/931457/tuik-in-yenilenen-internet-sitesi-ziyarete-acildi.html
