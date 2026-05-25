# Data Model — Breathe ESG Ingestion Prototype

## Core Design Principles

Four requirements drove every decision below:
1. **Multi-tenancy** — data from different clients must never mix, even accidentally.
2. **Source-of-truth tracking** — every record must know where it came from, when, whether it was changed, and by whom.
3. **Audit-readiness** — the state of any record at any point in time must be reconstructable for an external verifier.
4. **Realistic GHG accounting** — the model mirrors the GHG Protocol structure (Scope 1/2/3, activity data → emission factor → CO₂e), not a simplification of it.

---

## Entity Overview

```
Client
  └── IngestionBatch (one per file upload)
        └── ActivityRecord (one per discrete emission activity)
              └── AuditLog (append-only, one per state change)
```

---

## Client

The top-level tenant. Every object in the system belongs to exactly one `Client`.

```
id          UUID PK  — opaque, no sequential leakage of client count
name        string
slug        unique string  — used in URLs and API filtering
created_at
```

**Multi-tenancy enforcement:** Every view filters `queryset.filter(client=...)`. There is no cross-client API endpoint. The client context is passed as a query parameter (`?client=acme-industries`) and validated server-side on every request.

**Why UUID PK:** Sequential integer PKs leak business information (client onboarding rate, record counts). UUIDs are safe to expose in URLs.

---

## IngestionBatch

One batch = one file upload. It is the provenance record for a set of `ActivityRecord`s.

```
id              UUID PK
client          FK → Client
source_type     enum: SAP_FUEL | UTILITY_ELECTRICITY | TRAVEL
filename        original filename (preserved for audit)
file_hash       SHA-256 of the raw bytes — duplicate detection
raw_file        FileField — original bytes preserved for re-parsing
row_count       int — total rows in the file
success_count   int — rows that produced ActivityRecords
error_count     int — rows that failed parsing
parse_errors    JSON array — {row_num, raw_row_data, error_message}
status          enum: PROCESSING | COMPLETE | PARTIAL | FAILED
created_at
created_by      string — analyst who uploaded
```

**Why store `raw_file`:** If we improve a parser (better emission factor, unit conversion fix), we can re-parse the original file without asking the client to re-upload. The hash prevents re-ingesting the same file twice.

**Why `PARTIAL` status:** Real files have bad rows. An all-or-nothing import would force analysts to fix every data quality issue before any records are visible. `PARTIAL` lets the clean rows proceed while surfacing the errors.

**`parse_errors` as JSON:** Errors belong with the batch, not scattered in a separate table. The structure `{row_num, raw, error}` gives an analyst enough to find the bad row in the original file without opening a second screen.

---

## ActivityRecord

The canonical normalized emission record. One row = one discrete activity.

### Immutable raw fields (set at parse time, never changed)

```
raw_quantity       Decimal — exactly what the source file said
raw_unit           string  — the source's unit code (L, KWH, M3, KG, nights, km)
raw_location       string  — plant code, meter ID, airport pair
source_record_id   string  — the source system's own identifier (PO number, account+period)
raw_data           JSON    — the entire source row, verbatim
```

**Why keep raw values immutable:** An analyst who corrects `quantity_normalized` should not lose the ability to verify what the source actually said. The raw fields are the audit anchor.

### GHG classification

```
source_type   enum (7 values — see below)
scope         '1' | '2' | '3'
category      string — GHG Protocol category name
```

**Source type → Scope mapping (hardcoded, not configurable):**

| source_type         | scope | GHG Protocol category            |
|---------------------|-------|-----------------------------------|
| SAP_FUEL            | 1     | stationary_combustion             |
| SAP_PROCUREMENT     | 3     | purchased_goods_services          |
| UTILITY_ELECTRICITY | 2     | purchased_electricity             |
| TRAVEL_AIR          | 3     | business_travel_air               |
| TRAVEL_HOTEL        | 3     | business_travel_hotel             |
| TRAVEL_GROUND       | 3     | business_travel_ground            |
| TRAVEL_RAIL         | 3     | business_travel_rail              |

SAP_FUEL maps to Scope 1 because it represents direct combustion of fuel purchased through SAP's procurement module for on-site use (generators, boilers, vehicles). SAP_PROCUREMENT covers non-fuel purchased goods, which are Scope 3 Category 1.

### Normalized fields

```
quantity_normalized  Decimal — canonical unit per category
unit_normalized      string  — L (liquid fuels), kWh (electricity), km (travel), nights (hotel)
```

Normalization is applied at parse time. Changing `quantity_normalized` sets `is_edited = True` and creates an `AuditLog` entry.

### Emission calculation

```
emission_factor         Decimal — kgCO2e per unit_normalized
emission_factor_source  string  — 'DEFRA_2023', 'CEA_India_CO2_Baseline_v17_2021-22'
emission_factor_unit    string  — 'kgCO2e/L', 'kgCO2e/kWh', etc.
co2e_kg                 Decimal — quantity_normalized × emission_factor
```

**Why store the factor and its source:** An auditor will ask "how did you get 2.68801 for diesel?" The factor and its provenance are part of the audit trail, not just the result. Storing both allows the factor to be corrected if a newer version of DEFRA is published, and the correction is visible in the audit log.

### Review workflow

```
status           PENDING → APPROVED → LOCKED (happy path)
                 PENDING → FLAGGED → APPROVED → LOCKED
                 PENDING → REJECTED
flag_reason      text — required when flagging
confidence_score float 0–1 — parser's confidence in this record
auto_flagged     bool — parser set status=FLAGGED automatically
```

**State machine rules (enforced in model methods):**
- `approve()` → sets `approved_by`, `approved_at`
- `flag()` → requires reason string
- `lock()` → only callable on APPROVED records; sets `locked_at`; makes record read-only
- LOCKED records cannot be edited or transitioned by any API call

### Audit trail fields on the record itself

```
created_at    immutable
updated_at    auto-updated on every save
is_edited     True if any field changed after initial parse
approved_by   string
approved_at   datetime
locked_at     datetime
```

---

## AuditLog

Append-only. Never update or delete rows in this table.

```
id          UUID PK
record      FK → ActivityRecord (nullable — batch-level events have no record)
batch       FK → IngestionBatch (nullable — record-level events may not reference a batch directly)
action      enum: CREATED | EDITED | APPROVED | FLAGGED | REJECTED | LOCKED | BATCH_UPLOADED | BATCH_FAILED
actor       string — analyst name or system ('seed_demo', 'api_upload')
timestamp   auto-set on creation
old_values  JSON — values before the change (null for CREATED)
new_values  JSON — values after the change
note        text — optional free-text
```

**Why old_values + new_values instead of a diff:** An external auditor reading the table should not need to write a diff algorithm. Storing both makes the change self-documenting.

**Why nullable FKs:** A `BATCH_UPLOADED` event belongs to a batch but not yet to any record (records don't exist yet). A `CREATED` event can reference both.

---

## Indexes

```
(client, status)       — review queue filter
(client, scope)        — scope breakdown on dashboard
(client, source_type)  — source breakdown on dashboard
(batch, status)        — batch detail page record stats
source_record_id       — deduplication check against existing records
```

---

## What this model does not handle (deliberately)

- **User authentication:** The prototype uses analyst name as a plain string. Production would replace `actor` / `approved_by` with a FK to a User model.
- **Emission factor versioning:** Factors are hardcoded in parsers. Production would have a `EmissionFactor` table with version, effective_date, and source_document fields.
- **Multi-year inventories:** The model has `activity_date`, `period_start`, `period_end` but no explicit `inventory_year` field. Production would add one for annual reporting boundary enforcement.
- **Currency / spend data:** SAP procurement rows include `net_value` and `currency` in `raw_data` but spend-based Scope 3 calculation is not implemented. The fields are preserved for a future spend-based estimation module.
