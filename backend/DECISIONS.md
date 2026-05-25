# Decision Log — Breathe ESG Ingestion Prototype

Every ambiguity I resolved, what I chose, why, and what I'd ask the PM.

---

## SAP: Format Choice

**Ambiguity:** SAP exposes data through IDocs, OData services (S/4HANA), BAPIs, RFC calls, and flat-file exports. Which to target?

**Decision:** Semicolon-delimited flat file from transaction ME2N (purchase orders by material) and a custom MM60-based fuel consumption report.

**Why:**
- IDocs require an ALE/EDI middleware layer and an SAP Basis admin to configure outbound ports — weeks of IT work, not hours.
- OData/S/4HANA REST APIs are excellent but only available on S/4HANA (2019+). Many Indian manufacturing clients still run ECC 6.0.
- BAPIs require an RFC connection and a permanent network route from our server to the client's SAP landscape — a security conversation that adds weeks.
- ME2N flat-file export: any MM power user can run it in 5 minutes, set the column layout once, and email the .csv. Zero IT dependency. This is how 80% of SAP data actually moves between organizations in practice.

**Tradeoffs accepted:**
- Manual export means stale data. Production would use OData or a scheduled RFC extract.
- The column layout depends on the user's SAP GUI configuration, so we handle both German and English headers.

**What I'd ask the PM:**
- Is this client on ECC or S/4HANA? If S/4HANA, I'd evaluate OData for a v2 of the ingestion pipeline.
- Does their SAP Basis team allow outbound RFC connections to third-party systems? If yes, we could automate.

---

## SAP: German Headers

**Ambiguity:** SAP exports in German by default when the SAP system language is DE — common in globally deployed instances even for Indian subsidiaries.

**Decision:** Built a full German → internal key mapping (`GERMAN_HEADERS` dict in `parsers/sap.py`). The parser normalises headers before processing, so both DE and EN exports work without user intervention.

**What I'd ask the PM:**
- What SAP system language does this client use? If it's always EN, I can simplify the parser significantly.

---

## SAP: Which materials to ingest

**Ambiguity:** SAP procurement covers thousands of material types. Only some are emission-relevant.

**Decision:** Filter by material group (`Materialgruppe`). Groups containing `KRAFT` (fuel), `FUEL`, `ENERG` (energy), `LPG`, `GAS` are treated as Scope 1 combustion. Everything else is Scope 3 procurement, ingested but not given an emission factor automatically.

**Why:** Material group is the most reliable signal in an ME2N export. Material descriptions are free-text and inconsistent. Material codes are client-specific.

**Tradeoff:** We might misclassify if a client uses a non-standard material group naming scheme. The auto-flag on unknown groups surfaces this for analyst review.

---

## Utility: Format Choice

**Ambiguity:** Electricity data could come as PDF bills, portal CSV exports, Green Button API, or manual meter reads.

**Decision:** Portal CSV export.

**Why:**
- PDF bills require OCR, and Indian utility bill PDFs are often scanned images of printed paper. OCR error rates on those are unacceptable for audit-grade data.
- Green Button API exists in the US (ESPI standard) but Indian discoms (MSEDCL, BESCOM, TANGEDCO, BYPL) do not implement it.
- Every major Indian discom self-service portal allows CSV export of billing history. A facilities manager can export 12 months in 3 minutes.
- Manual meter reads are the fallback but introduce transcription errors.

**What I'd ask the PM:**
- Does the client use a third-party energy management platform (Engie, Schneider EcoStruxure)? Those often have their own APIs and could eliminate the CSV step.

---

## Utility: Billing period vs calendar month

**Decision:** Store `period_start` and `period_end` separately from `activity_date`. Set `activity_date` to `period_end` (the date the usage "landed" in the books).

**Why:** MSEDCL reads meters on cycles like Dec 28 → Jan 30. If we force calendar-month alignment, we either double-count or create gaps. Storing the actual billing window preserves accuracy. Downstream annual totals should sum `co2e_kg` grouped by `period_end` year, not by `activity_date` year — this is documented in the analyst UX.

---

## Utility: Emission factor choice

**Decision:** India CEA CO2 Baseline Database v17 (2021-22), national grid factor: 0.820 kgCO2e/kWh. State-level factors are in the parser but currently all set to the national average because CEA's state-level table uses the same value for most states.

**Why:** CEA is the statutory authority for India grid factors. DEFRA's India factor (0.82) matches CEA, confirming our choice. We do not use IEA or other international databases for Indian electricity — CEA is the source verifiers will expect.

**What I'd ask the PM:**
- Does the client have any renewable energy contracts (PPAs, RECs)? If yes, the market-based factor would differ from the location-based factor, which changes Scope 2 reporting significantly.

---

## Travel: Format Choice

**Decision:** Concur expense report CSV export.

**Why:**
- Concur's OAuth API requires enterprise IT setup (admin consent flow, application registration) that takes 2-4 weeks. For a prototype, that's a blocker.
- Every Concur deployment allows travel managers and finance admins to export the expense report to CSV from the Reports module in minutes.
- Navan (formerly TripActions) has a similar CSV export from their reporting module.
- The CSV contains all the data needed: expense type, dates, routes, employee names, approval status.

**What I'd ask the PM:**
- For production: Is this client's IT team willing to provision an OAuth app for Concur? That would enable automated daily ingestion rather than manual exports.

---

## Travel: Distance calculation for flights

**Ambiguity:** Concur CSV often doesn't include distance. It has origin and destination airport codes.

**Decision:** Great-circle distance lookup table for ~30 common city-pair routes. Unknown pairs are auto-flagged for manual entry.

**Why:** 
- Great-circle distance is the standard for aviation emission calculations (DEFRA, ICAO Carbon Calculator all use it).
- A full global airport-pair table would be 10k+ entries — overkill for a prototype.
- The 30 routes in our table cover the routes realistic for an Indian enterprise (domestic + BOM/DEL to major international hubs).

**Tradeoff:** Any unlisted route gets flagged. An analyst must enter the distance manually. In production, we'd integrate the `openflights` or `airportgap` dataset for full coverage.

**What I'd ask the PM:**
- Does this client have unusual travel patterns (e.g., frequent routes to African or Southeast Asian cities not in our table)?

---

## Travel: Radiative Forcing Index (RFI)

**Decision:** Include RFI multiplier of ~1.9 in the DEFRA 2023 factors we use (DEFRA's published per-km factors already include it).

**Why:** DEFRA 2023 short/long-haul economy factors (0.25520 and 0.19493 kgCO2e/km) already incorporate RFI at the recommended level. We use the factors as-is. This is noted in the parser docstring. GHG Protocol Scope 3 guidance recommends including RFI for business travel air; some clients exclude it for comparability — this should be a configurable option in production.

---

## Review Workflow: Status States

**Decision:** PENDING → APPROVED → LOCKED (with FLAGGED and REJECTED as branches).

**Why this sequence:**
- `PENDING` is the default — all parsed records start here. An analyst must actively review.
- `FLAGGED` is for "needs attention but keep it in the queue." Auto-flags from the parser also use this state.
- `APPROVED` means an analyst signed off on the value and calculation. It's a reversible state.
- `LOCKED` is final — it means "this record is part of a submitted inventory." Locked records become read-only. This maps to the concept of a "locked period" in financial accounting.
- `REJECTED` removes a record from the inventory without deleting it. The data is preserved for audit purposes.

**What I'd ask the PM:**
- Is there a two-level approval flow (analyst → manager)? If yes, we'd need a second approval state before `LOCKED`.

---

## Multi-tenancy

**Decision:** Foreign key on every model, enforced at the queryset level in every API view. No row-level security at the database level (that would require PostgreSQL's RLS feature, which adds complexity not needed for a prototype).

**What I'd ask the PM:**
- How many clients will share a single deployment? If >10, database-level RLS becomes worth the complexity for defense-in-depth.

---

## Deployment

**Decision:** Render (single web service + PostgreSQL add-on).

**Why:** 
- Railway and Fly.io are good alternatives, but Render's free PostgreSQL tier is sufficient for a prototype, and their buildpack detects Django automatically.
- The `build.sh` script handles `collectstatic`, `migrate`, and `seed_demo` in sequence.
- A single `Procfile` runs Gunicorn with the correct worker count.

**What I ignored:** Redis, Celery, background task queues. File parsing happens synchronously in the upload request. For files with thousands of rows this would cause request timeouts — a known tradeoff documented in TRADEOFFS.md.
