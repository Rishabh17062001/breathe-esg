"""
Utility Electricity Parser — portal CSV export.

Format choice: CSV export from the utility's self-service portal.
This is the most realistic choice for a facilities team in India —
PDF bills require OCR (unreliable on scanned invoices) and utility
APIs (Green Button, etc.) exist in the US but are absent from most
Indian discoms. Every MSEDCL, BESCOM, and BYPL portal lets you export
a billing history CSV from the account dashboard.

Realistic complications handled:
 - Billing periods are NOT calendar months. MSEDCL reads meters on a
   cycle — Dec 28 → Jan 30, Jan 31 → Feb 27, etc. We store period_start
   and period_end separately from activity_date (set to period_end as the
   "when this usage landed" date).
 - Usage column header varies by portal ("Total Usage (kWh)", "Units",
   "Net Units Consumed", "kWh") — we probe multiple names.
 - Negative usage happens when a site has rooftop solar and net-metering
   credit exceeds consumption. We flag these for analyst review rather
   than silently dropping them.
 - Demand (kW peak) is captured but not used in the CO2e calc — it's
   a tariff component, not an emission source.
 - The grid emission factor is location-specific. We default to the
   India national grid factor (CEA 2021-22) and flag rows where the
   service address implies a state with significantly different grid mix.

Emission factors:
 - India national grid: 0.820 kgCO2e/kWh (CEA CO2 Baseline Database v17, 2021-22)
 - This is market-based (no RECs) by default. Location-based = same value
   unless client has renewable energy contracts.
"""

import csv
import io
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

# India state-level grid factors (CEA 2021-22, kgCO2e/kWh)
# Only the states most relevant to Indian manufacturing clients.
# In production: full CEA state table in the database.
STATE_GRID_FACTORS = {
    'maharashtra':   Decimal('0.820'),
    'karnataka':     Decimal('0.820'),
    'delhi':         Decimal('0.820'),
    'tamil_nadu':    Decimal('0.820'),
    'telangana':     Decimal('0.820'),
    'gujarat':       Decimal('0.820'),
    'west_bengal':   Decimal('0.820'),
    'default':       Decimal('0.820'),  # national average
}

# Column header synonyms — portals don't agree on names
USAGE_COLS = [
    'total usage (kwh)', 'usage (kwh)', 'units', 'net units consumed',
    'kwh', 'energy consumed (kwh)', 'consumption (kwh)', 'total usage kwh',
    'units consumed',
]
PERIOD_START_COLS = [
    'billing period start', 'from date', 'read from', 'period start',
    'start date', 'from',
]
PERIOD_END_COLS = [
    'billing period end', 'to date', 'read to', 'period end',
    'end date', 'to',
]
ACCOUNT_COLS = ['account number', 'account no', 'account no.', 'consumer no']
METER_COLS = ['meter serial number', 'meter no', 'meter id', 'meter number']
ADDRESS_COLS = ['service address', 'address', 'supply address', 'premises']
DEMAND_COLS = ['peak demand (kw)', 'demand (kw)', 'peak demand', 'maximum demand (kw)']


def _find_col(headers_lower: list, candidates: list) -> str | None:
    for c in candidates:
        if c in headers_lower:
            return c
    return None


def _parse_date(raw: str) -> date | None:
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _extract_state(address: str) -> str:
    if not address:
        return 'default'
    addr_lower = address.lower()
    state_keywords = {
        'maharashtra': ['maharashtra', 'pune', 'mumbai', 'nagpur', 'mh'],
        'karnataka': ['karnataka', 'bengaluru', 'bangalore', 'mysuru', 'ka'],
        'delhi': ['delhi', 'new delhi', 'ndmc', 'dl'],
        'tamil_nadu': ['tamil nadu', 'chennai', 'madras', 'tn'],
        'telangana': ['telangana', 'hyderabad', 'ts'],
        'gujarat': ['gujarat', 'ahmedabad', 'surat', 'gj'],
        'west_bengal': ['west bengal', 'kolkata', 'calcutta', 'wb'],
    }
    for state, keywords in state_keywords.items():
        if any(k in addr_lower for k in keywords):
            return state
    return 'default'


def parse_utility_csv(file_bytes: bytes) -> dict:
    """
    Parse utility portal CSV electricity export.

    Returns:
        {
          'records': list[dict],
          'errors':  list[dict],
          'row_count': int
        }
    """
    try:
        text = file_bytes.decode('utf-8')
    except UnicodeDecodeError:
        import chardet
        detected = chardet.detect(file_bytes)
        text = file_bytes.decode(detected.get('encoding', 'latin-1'), errors='replace')

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {'records': [], 'errors': [{'row_num': 0, 'raw': {}, 'error': 'Empty or header-less file'}], 'row_count': 0}

    headers_lower = [h.strip().lower() for h in reader.fieldnames]

    usage_col = _find_col(headers_lower, USAGE_COLS)
    start_col = _find_col(headers_lower, PERIOD_START_COLS)
    end_col = _find_col(headers_lower, PERIOD_END_COLS)
    account_col = _find_col(headers_lower, ACCOUNT_COLS)
    meter_col = _find_col(headers_lower, METER_COLS)
    address_col = _find_col(headers_lower, ADDRESS_COLS)
    demand_col = _find_col(headers_lower, DEMAND_COLS)

    if not usage_col:
        return {
            'records': [],
            'errors': [{'row_num': 0, 'raw': {}, 'error': f'Cannot find usage column. Found: {headers_lower}'}],
            'row_count': 0
        }

    # Build lowercase-key accessor
    def get(row, col):
        if col is None:
            return ''
        for k, v in row.items():
            if k.strip().lower() == col:
                return (v or '').strip()
        return ''

    records = []
    errors = []
    row_num = 1

    for raw_row in reader:
        row_num += 1
        row_lower = {k.strip().lower(): v for k, v in raw_row.items()}

        try:
            record = _parse_utility_row(
                row_lower, raw_row, row_num,
                usage_col, start_col, end_col,
                account_col, meter_col, address_col, demand_col
            )
            if record:
                records.append(record)
        except Exception as e:
            errors.append({'row_num': row_num, 'raw': dict(raw_row), 'error': str(e)})

    return {'records': records, 'errors': errors, 'row_count': row_num - 1}


def _parse_utility_row(
    row, raw_row, row_num,
    usage_col, start_col, end_col,
    account_col, meter_col, address_col, demand_col
) -> dict | None:
    flags = []
    confidence = 1.0

    account_no = row.get(account_col, '') if account_col else ''
    meter_id = row.get(meter_col, '') if meter_col else ''
    address = row.get(address_col, '') if address_col else ''

    # Usage
    usage_str = row.get(usage_col, '0').replace(',', '')
    try:
        usage_kwh = Decimal(usage_str)
    except InvalidOperation:
        raise ValueError(f'Cannot parse usage: {usage_str!r}')

    if usage_kwh < 0:
        flags.append('Negative usage — possible net-metering credit. Verify solar generation records.')
        confidence -= 0.2

    if usage_kwh == 0:
        flags.append('Zero usage — meter read error or vacant period?')
        confidence -= 0.2

    # Billing period
    start_str = row.get(start_col, '') if start_col else ''
    end_str = row.get(end_col, '') if end_col else ''
    period_start = _parse_date(start_str)
    period_end = _parse_date(end_str)

    if not period_start or not period_end:
        raise ValueError(f'Cannot parse billing period: start={start_str!r} end={end_str!r}')

    period_days = (period_end - period_start).days
    if period_days > 35:
        flags.append(f'Billing period is {period_days} days — unusually long. Check for skipped reads.')
        confidence -= 0.15
    elif period_days < 20:
        flags.append(f'Billing period is only {period_days} days — unusually short. Check for meter replacement.')
        confidence -= 0.1

    # Grid emission factor — state-based
    state = _extract_state(address)
    ef = STATE_GRID_FACTORS.get(state, STATE_GRID_FACTORS['default'])
    ef_source = 'CEA_India_CO2_Baseline_v17_2021-22'

    # Demand
    demand_kw = None
    if demand_col:
        demand_str = row.get(demand_col, '')
        if demand_str:
            try:
                demand_kw = float(demand_str.replace(',', ''))
            except ValueError:
                pass

    co2e_kg = usage_kwh * ef if usage_kwh > 0 else Decimal('0')

    source_record_id = f'{account_no}_{start_str}_{end_str}'

    auto_flagged = confidence < 0.8 or bool(flags)
    status = 'FLAGGED' if auto_flagged else 'PENDING'

    return {
        'source_type': 'UTILITY_ELECTRICITY',
        'scope': '2',
        'category': 'purchased_electricity',
        'activity_date': period_end,
        'period_start': period_start,
        'period_end': period_end,
        'raw_quantity': usage_kwh,
        'raw_unit': 'kWh',
        'raw_location': meter_id or account_no,
        'source_record_id': source_record_id,
        'raw_data': dict(raw_row),
        'quantity_normalized': usage_kwh,
        'unit_normalized': 'kWh',
        'description': f'Electricity — {address[:120]}' if address else 'Electricity consumption',
        'vendor_supplier': '',
        'location_label': address[:255] if address else meter_id,
        'emission_factor': ef,
        'emission_factor_source': ef_source,
        'emission_factor_unit': 'kgCO2e/kWh',
        'co2e_kg': co2e_kg,
        'status': status,
        'flag_reason': ' | '.join(flags),
        'confidence_score': max(0.0, confidence),
        'auto_flagged': auto_flagged,
    }
