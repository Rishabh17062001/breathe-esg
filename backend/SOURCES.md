# Sources Research — Three Data Sources

---

## 1. SAP Fuel & Procurement

### Real-world format researched

SAP's Materials Management (MM) module stores procurement data in tables EKKO (purchase order header) and EKPO (purchase order item). The standard export mechanism available without custom development is transaction ME2N ("Purchase Orders by Material"), which generates a tabular report that can be downloaded as a flat file (via SAP GUI's "spreadsheet" icon → .csv/.txt).

For fuel consumption data specifically, the closest standard SAP transaction is MM60 (Goods Movements), but many clients build a custom report using ABAP query on the MSEG table (material document segments) filtered by movement type 201 (goods issue for cost center) or 261 (goods issue for production order).

**Key things I learned:**
- SAP's standard German locale uses semicolons as CSV delimiters because German decimal notation uses commas (1.234,56 = one thousand two hundred thirty-four point fifty-six). A naïve comma-split on a German SAP export produces corrupted data.
- Column headers are determined by the user's SAP GUI display variant — the same transaction can produce different column sets depending on who configured it. "Einkaufsbeleg" (purchase document) and "Materialkurzbeschreibung" (material short description) are the most common German headers.
- Date format is DD.MM.YYYY in German locale, MM/DD/YYYY in US locale, YYYY-MM-DD in ISO mode.
- Plant codes (Werk) are 4-character internal codes (e.g., "IN01") that have no meaning outside the client's SAP configuration. They must be mapped to human-readable labels via a lookup table maintained by the client.
- Unit codes follow SAP's internal unit of measure table: L (litres), KG (kilograms), M3 (cubic metres), KWH (kilowatt-hours), ST (pieces = Stück in German).
- Material groups (Materialgruppe) are the most reliable signal for emission relevance. German-language material groups look like "010-KRAFTSTOFF" (fuel), "020-ENERGIE" (energy), "030-SCHMIERSTOFFE" (lubricants).

### What my sample data looks like and why

The sample file (`sap_fuel_procurement_sample.csv`) is semicolon-delimited with German column headers. It simulates a Q1 2024 ME2N export for a mid-size Indian manufacturer with five plant locations (IN01–IN05 = Pune, Mumbai, Delhi, Chennai facilities). 

Fuel types included: diesel (most common), petrol, natural gas (compressed, in M3), LPG (in KG), and heavy fuel oil (HFO). Material descriptions are in German as they would appear in a system configured by a German ERP implementation partner (common for large Indian manufacturing groups).

One row intentionally includes a lubricant (030-SCHMIERSTOFFE) to demonstrate the procurement vs. fuel classification logic.

Quantities use German notation with dots as thousand separators and commas as decimal separators (e.g., `2.500,000` = 2500.000 litres).

### What would break in a real deployment

- **Material group non-standardisation:** A new client's SAP might use "Z-FUEL" or "PETROL-GROUP" instead of "010-KRAFTSTOFF". The parser would classify these as procurement (Scope 3) rather than fuel (Scope 1). Mitigation: require the client's sustainability team to provide a material group mapping during onboarding.
- **Display variant drift:** If the ME2N display variant is changed (e.g., someone adds or removes columns), column positions shift and the parser may silently produce wrong data. Mitigation: validate expected columns on every upload and reject files that don't match.
- **Mixed plants across business units:** A large client might have plants from different legal entities in the same export. The parser currently uses a single plant lookup table. Mitigation: scoped plant tables per client.
- **Currency conversion for spend data:** NET_VALUE is in the client's SAP company code currency (INR in our sample). For global inventories, spend-based Scope 3 calculations would require FX conversion at the time of the transaction.

---

## 2. Utility Electricity

### Real-world format researched

Major Indian electricity distribution companies (discoms) offer self-service portals:
- **MSEDCL** (Maharashtra): web portal at mahadiscom.in — billing history CSV export available under "Consumer Services → Bill History"
- **BESCOM** (Karnataka): bescom.org portal — similar CSV export
- **TANGEDCO** (Tamil Nadu): tnebnet.org — CSV export from bill history
- **BYPL** (Delhi): bypl.co.in — CSV from account dashboard

Each portal's CSV has slightly different column headers. MSEDCL calls the usage column "Total Usage (kWh)"; BESCOM uses "Units Consumed"; some portals use just "kWh". The billing period columns also vary ("Billing Period Start" vs "From Date" vs "Read From").

**Key things I learned:**
- Billing cycles are NOT calendar months. Indian discoms read meters on fixed cycles, not on the 1st of each month. A typical MSEDCL cycle is 28-day periods starting from a date in late December. This means annual totals computed by calendar month are always slightly off.
- Net metering is live in several states: if a site has rooftop solar and generates more than it consumes, the "consumption" in the portal CSV may be negative (credit to the account). This is not an error but a valid data point — the solar generation is a Scope 2 offset.
- The same account may appear across multiple portals if a large facility has multiple service connections (e.g., a factory may have three MSEDCL account numbers for different supply points).
- HT (High Tension) customers above 100 kW get a maximum demand charge (kVA or kW) in addition to consumption. This is a billing component, not an emission driver, but it appears in the export.

### What my sample data looks like and why

The sample file (`utility_electricity_sample.csv`) simulates billing exports from four discoms: MSEDCL (Maharashtra, two plant addresses in Pune and Mumbai), BESCOM (Karnataka, Bangalore), TANGEDCO (Tamil Nadu, Chennai), and BYPL (Delhi).

Billing periods are non-calendar (e.g., Dec 28 to Jan 29) to reflect real meter-read cycles. Two rows are intentionally problematic:
- One row has negative usage (-850 kWh) to test the net-metering flag logic.
- One row has zero usage to test the vacant-period flag logic (this simulates a meter replacement or a period when a facility was idle).

Addresses include enough detail for the parser's state-detection logic to assign the correct grid factor.

### What would break in a real deployment

- **Portal format changes:** If MSEDCL updates their CSV column headers (they have done this at least once in the past three years), the parser would fail to find the usage column. Mitigation: fuzzy column matching with a synonym table (already implemented) and an alert if a known-good account suddenly produces errors.
- **Multi-currency international clients:** Our factors assume Indian grid kWh. A client with European facilities would need ENTSO-E or national grid factors.
- **PDF-only portals:** Some smaller state discoms (UPPCL, PSPCL) do not offer CSV exports — only PDF bills. These would require OCR, which we explicitly chose not to support.
- **Smart meter data:** High-frequency (15-minute interval) smart meter data is increasingly available and would give much more accurate demand-period analysis, but it requires a completely different data model.

---

## 3. Corporate Travel (Concur)

### Real-world format researched

SAP Concur is the dominant corporate travel and expense management platform for Indian enterprises with >500 employees. Alternative platforms include:
- **Navan (formerly TripActions):** popular with tech companies, has a similar CSV export
- **Happay / EnKash:** Indian-origin platforms for SME, simpler CSV formats
- **Manual spreadsheets:** common for companies without a formal T&E platform

Concur's standard expense report export ("Analyze → Reports → Standard Reports → Expense Detail Report") produces a CSV with one row per expense line item. Key columns: Expense Type, Transaction Date, Employee Name, Description, Amount, and for travel-specific types: departure/arrival city or airport code.

**Key things I learned:**
- Concur does not always include airport codes — it depends on whether the booking was made through Concur's booking tool or manually claimed as an expense. Direct bookings through Concur Travel populate origin/destination; manual expense claims often have only a description like "Mumbai to Delhi flight."
- Distance is almost never in a Concur CSV. You get airport codes at best.
- Hotel rows have a nightly rate and total amount, but the number of nights is a separate column that many Concur configurations don't include. A hotel billed as a lump sum needs an analyst to manually enter nights.
- The "Approval Status" column is critical: Concur expense reports go through an approval workflow. We must ingest only approved records; pending records may be rejected by the manager and would overstate emissions if included.
- Cabin class (economy / business / first) is sometimes in the description field, sometimes a separate column, sometimes absent entirely. This affects the emission factor significantly (business class ≈ 3× economy per seat due to seat-pitch factor).

### What my sample data looks like and why

The sample file (`concur_travel_sample.csv`) simulates Q1 2024 Concur expense exports for five employees at Acme Industries. Routes are realistic for an Indian manufacturing company: domestic routes between metro cities (BOM, DEL, BLR, MAA, HYD, CCU) and international routes to key business hubs (LHR, DXB, SIN, JFK, FRA).

All major expense types are represented: Airfare, Hotel, Taxi (ground transport). Two rows at the end have `Pending` approval status — the parser skips these, logging them as errors with a clear message. This tests the approval-filter logic.

One hotel row intentionally omits the nights count to test the missing-nights flag.

Long-haul international flights (DEL→JFK, BOM→SIN, DEL→LHR) use the long-haul emission factor; domestic flights use the short-haul factor. The parser determines haul length from the great-circle distance lookup, not from the booking description.

### What would break in a real deployment

- **Routes not in the lookup table:** A flight from BOM to Nairobi (NBO) would be auto-flagged because there's no entry in `AIRPORT_DISTANCES_KM`. An analyst must enter the distance manually. Production would use a full great-circle distance database (e.g., OpenFlights `routes.dat`).
- **Concur API vs. CSV:** The CSV export is manual. A production integration would use Concur's OAuth API (`/api/v3.0/expense/reportdetails`) for automated daily ingestion, eliminating the export step. The API also returns more structured data (cabin class as a proper field, booking reference).
- **Multi-currency amounts:** Our sample uses INR. International travel expenses may be claimed in foreign currency. The parser currently doesn't normalize amounts (we don't use amounts for emission calculations, only distance and nights), but a future spend-based Scope 3 module would need FX rates.
- **Rail/metro trips:** Ground transport in India increasingly uses metro, suburban rail, or intercity rail (Rajdhani, Vande Bharat). These have significantly lower emission factors than taxis but are often recorded as "Ground Transport" in Concur with no mode distinction.
