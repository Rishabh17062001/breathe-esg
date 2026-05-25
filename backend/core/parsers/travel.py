"""
Corporate Travel Parser — Concur expense report CSV export.

Format choice: CSV export from Concur Travel & Expense.
Concur is the dominant corporate travel platform in mid-to-large Indian
enterprises. Their API requires OAuth + enterprise IT setup that takes
weeks. Their CSV export is available to any travel manager or finance
admin in minutes. For a prototype, CSV is the right call; in production,
API integration would eliminate manual export steps and provide real-time
data.

Three categories handled:
 1. Air travel — origin + destination airport codes → distance lookup →
    emission factor varies by cabin class and haul length
 2. Hotel — nights × per-night factor (DEFRA 2023 average hotel)
 3. Ground transport — distance (if given) or amount-based proxy if distance
    is missing. Taxis, ride-hail, rental cars. Rail handled separately.

Key challenge: distance is often not in the Concur export.
 - For flights: we use a lookup table of great-circle distances for common
   city-pair routes. Unknown pairs are flagged.
 - For ground: if a distance column is present we use it; otherwise we flag
   the record for manual distance entry.

Emission factors — DEFRA 2023 (kgCO2e per passenger-km for air):
 - Short-haul economy (<3,700 km): 0.25520 (includes radiative forcing ×1.9)
 - Long-haul economy (≥3,700 km): 0.19493
 - Long-haul business (≥3,700 km): 0.42863 (business = 3× seat factor)
 - Average hotel night: 40.20 kgCO2e/night (DEFRA 2023 UK average — flagged
   as approximate; India hotel factors are not published by CEA)
 - Taxi/ground: 0.14877 kgCO2e/km (DEFRA 2023, average taxi)
"""

import csv
import io
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

# Great-circle distances for common city-pair routes (km).
# Symmetric: always add both directions.
AIRPORT_DISTANCES_KM: dict[tuple, int] = {
    # India domestic
    ('BOM', 'DEL'): 1148, ('DEL', 'BOM'): 1148,
    ('BOM', 'HYD'): 621,  ('HYD', 'BOM'): 621,
    ('BOM', 'BLR'): 842,  ('BLR', 'BOM'): 842,
    ('BOM', 'MAA'): 1062, ('MAA', 'BOM'): 1062,
    ('BOM', 'CCU'): 1654, ('CCU', 'BOM'): 1654,
    ('DEL', 'BLR'): 1741, ('BLR', 'DEL'): 1741,
    ('DEL', 'MAA'): 1755, ('MAA', 'DEL'): 1755,
    ('DEL', 'HYD'): 1251, ('HYD', 'DEL'): 1251,
    ('DEL', 'CCU'): 1307, ('CCU', 'DEL'): 1307,
    ('BOM', 'GOI'): 441,  ('GOI', 'BOM'): 441,
    ('BOM', 'PNQ'): 102,  ('PNQ', 'BOM'): 102,
    # International — India to hub cities
    ('BOM', 'LHR'): 7192, ('LHR', 'BOM'): 7192,
    ('DEL', 'LHR'): 6731, ('LHR', 'DEL'): 6731,
    ('BOM', 'DXB'): 1924, ('DXB', 'BOM'): 1924,
    ('DEL', 'DXB'): 2195, ('DXB', 'DEL'): 2195,
    ('BOM', 'SIN'): 5061, ('SIN', 'BOM'): 5061,
    ('DEL', 'SIN'): 4150, ('SIN', 'DEL'): 4150,
    ('DEL', 'JFK'): 11766,('JFK', 'DEL'): 11766,
    ('BOM', 'JFK'): 12550,('JFK', 'BOM'): 12550,
    ('DEL', 'CDG'): 6554, ('CDG', 'DEL'): 6554,
    ('BOM', 'FRA'): 6817, ('FRA', 'BOM'): 6817,
    ('DEL', 'NRT'): 5857, ('NRT', 'DEL'): 5857,
    ('BOM', 'HKG'): 4515, ('HKG', 'BOM'): 4515,
    ('DEL', 'SFO'): 12313,('SFO', 'DEL'): 12313,
    ('BOM', 'ORD'): 12960,('ORD', 'BOM'): 12960,
}

# DEFRA 2023 air emission factors (kgCO2e/km, per passenger, with RFI)
AIR_FACTORS = {
    'short_economy':   Decimal('0.25520'),
    'long_economy':    Decimal('0.19493'),
    'long_business':   Decimal('0.42863'),
    'short_business':  Decimal('0.37412'),
    'unknown':         Decimal('0.22500'),
}

HOTEL_FACTOR_PER_NIGHT = Decimal('40.20')   # DEFRA 2023, kgCO2e/night
TAXI_FACTOR_PER_KM     = Decimal('0.14877') # DEFRA 2023, kgCO2e/km

EF_SOURCE = 'DEFRA_2023'

# Concur column name variants
TYPE_COLS    = ['expense type', 'category', 'type', 'transaction type']
DATE_COLS    = ['transaction date', 'date', 'expense date', 'travel date']
DESC_COLS    = ['description', 'expense description', 'memo', 'remarks']
ORIGIN_COLS  = ['departure airport code', 'origin', 'from', 'departure city/airport', 'from airport']
DEST_COLS    = ['arrival airport code', 'destination', 'to', 'arrival city/airport', 'to airport']
DIST_COLS    = ['distance (km)', 'trip miles/km', 'distance', 'miles', 'km', 'trip distance']
NIGHTS_COLS  = ['nights', 'number of nights', 'hotel nights', 'duration (nights)']
VENDOR_COLS  = ['vendor name', 'merchant name', 'supplier', 'vendor', 'merchant']
EMP_COLS     = ['employee name', 'traveller name', 'employee', 'traveler']
COST_COLS    = ['amount (inr)', 'amount', 'total amount', 'expense amount']
APPROVAL_COLS= ['manager approval', 'approval status', 'status', 'approved']


def _find_col(row_keys: list, candidates: list) -> str | None:
    keys_lower = [k.lower().strip() for k in row_keys]
    for c in candidates:
        if c in keys_lower:
            return c
    return None


def _get(row_lower: dict, candidates: list) -> str:
    for c in candidates:
        if c in row_lower:
            return (row_lower[c] or '').strip()
    return ''


def _parse_date(raw: str) -> date | None:
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _classify_expense_type(raw_type: str) -> str:
    t = raw_type.lower().strip()
    if any(k in t for k in ['airfare', 'air', 'flight', 'aviation', 'ticket']):
        return 'air'
    if any(k in t for k in ['hotel', 'accommodation', 'lodging', 'motel', 'stay']):
        return 'hotel'
    if any(k in t for k in ['rail', 'train', 'metro', 'subway', 'bus rapid']):
        return 'rail'
    if any(k in t for k in ['taxi', 'cab', 'ground', 'car', 'transport', 'transfer', 'auto', 'bus', 'uber', 'ola', 'lyft', 'rental']):
        return 'ground'
    return 'unknown'


def _parse_distance(dist_str: str) -> Decimal | None:
    if not dist_str:
        return None
    # Extract numeric part — handles "25km", "25 km", "25.5", "25 miles"
    clean = re.sub(r'[^\d.]', '', dist_str.split()[0])
    if not clean:
        # Try whole string
        clean = re.sub(r'[^\d.]', '', dist_str)
    try:
        val = Decimal(clean)
        # Convert miles to km if unit says miles
        if 'mile' in dist_str.lower() or 'mi' in dist_str.lower().split():
            val = val * Decimal('1.60934')
        return val if val > 0 else None
    except InvalidOperation:
        return None


def _air_factor(distance_km: Decimal, cabin: str) -> Decimal:
    is_long = distance_km >= 3700
    cabin_lower = cabin.lower()
    is_business = any(k in cabin_lower for k in ['business', 'first', 'biz', 'j class', 'c class'])
    if is_long and is_business:
        return AIR_FACTORS['long_business']
    if is_long:
        return AIR_FACTORS['long_economy']
    if is_business:
        return AIR_FACTORS['short_business']
    return AIR_FACTORS['short_economy']


def parse_travel_csv(file_bytes: bytes) -> dict:
    """
    Parse Concur expense report CSV.

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
        return {'records': [], 'errors': [{'row_num': 0, 'raw': {}, 'error': 'Empty file'}], 'row_count': 0}

    records = []
    errors = []
    row_num = 1

    for raw_row in reader:
        row_num += 1
        row_lower = {k.strip().lower(): (v or '').strip() for k, v in raw_row.items()}

        # Skip rows where approval is explicitly Pending/Rejected in source
        approval = _get(row_lower, APPROVAL_COLS).lower()
        if approval in ('pending', 'rejected', 'denied', 'not approved'):
            errors.append({
                'row_num': row_num,
                'raw': dict(raw_row),
                'error': f'Skipped — approval status in source: {approval!r}. '
                          'Only ingest approved travel records.'
            })
            continue

        try:
            result = _parse_travel_row(row_lower, raw_row, row_num)
            if result:
                records.append(result)
        except Exception as e:
            errors.append({'row_num': row_num, 'raw': dict(raw_row), 'error': str(e)})

    return {'records': records, 'errors': errors, 'row_count': row_num - 1}


def _parse_travel_row(row: dict, raw_row: dict, row_num: int) -> dict | None:
    flags = []
    confidence = 1.0

    raw_type = _get(row, TYPE_COLS)
    expense_type = _classify_expense_type(raw_type)

    if expense_type == 'unknown':
        flags.append(f'Cannot classify expense type: {raw_type!r} — skipping')
        return None  # Skip truly unclassifiable rows

    raw_date = _get(row, DATE_COLS)
    parsed_date = _parse_date(raw_date)
    if not parsed_date:
        raise ValueError(f'Cannot parse date: {raw_date!r}')

    desc = _get(row, DESC_COLS)
    vendor = _get(row, VENDOR_COLS)
    employee = _get(row, EMP_COLS)

    # --- Air travel ---
    if expense_type == 'air':
        origin = _get(row, ORIGIN_COLS).upper().strip()[:3]
        dest = _get(row, DEST_COLS).upper().strip()[:3]

        distance_km = AIRPORT_DISTANCES_KM.get((origin, dest))
        if distance_km is None:
            flags.append(
                f'No distance lookup for route {origin}-{dest}. '
                'Add to airport distance table or enter manually.'
            )
            confidence -= 0.4
            distance_km_decimal = None
            co2e_kg = None
            ef = AIR_FACTORS['unknown']
            ef_unit = 'kgCO2e/km'
        else:
            distance_km_decimal = Decimal(str(distance_km))
            ef = _air_factor(distance_km_decimal, desc)
            co2e_kg = distance_km_decimal * ef
            ef_unit = 'kgCO2e/km'

        return {
            'source_type': 'TRAVEL_AIR',
            'scope': '3',
            'category': 'business_travel_air',
            'activity_date': parsed_date,
            'period_start': parsed_date,
            'period_end': parsed_date,
            'raw_quantity': Decimal(str(distance_km)) if distance_km else Decimal('0'),
            'raw_unit': 'km',
            'raw_location': f'{origin}-{dest}',
            'source_record_id': f'{employee}_{parsed_date}_{origin}_{dest}',
            'raw_data': dict(raw_row),
            'quantity_normalized': Decimal(str(distance_km)) if distance_km else Decimal('0'),
            'unit_normalized': 'km',
            'description': desc or f'{origin} → {dest}',
            'vendor_supplier': vendor,
            'location_label': f'{origin} → {dest}',
            'emission_factor': ef if distance_km else None,
            'emission_factor_source': EF_SOURCE,
            'emission_factor_unit': ef_unit,
            'co2e_kg': co2e_kg,
            'status': 'FLAGGED' if confidence < 0.7 or flags else 'PENDING',
            'flag_reason': ' | '.join(flags),
            'confidence_score': max(0.0, confidence),
            'auto_flagged': bool(flags),
        }

    # --- Hotel ---
    elif expense_type == 'hotel':
        nights_str = _get(row, NIGHTS_COLS)
        try:
            nights = Decimal(nights_str) if nights_str else None
        except InvalidOperation:
            nights = None

        if not nights or nights <= 0:
            flags.append('Missing or invalid nights count — cannot calculate hotel emissions')
            confidence -= 0.5
            nights = Decimal('0')

        co2e_kg = nights * HOTEL_FACTOR_PER_NIGHT if nights > 0 else None

        return {
            'source_type': 'TRAVEL_HOTEL',
            'scope': '3',
            'category': 'business_travel_hotel',
            'activity_date': parsed_date,
            'period_start': parsed_date,
            'period_end': parsed_date,
            'raw_quantity': nights,
            'raw_unit': 'nights',
            'raw_location': '',
            'source_record_id': f'{employee}_{parsed_date}_hotel',
            'raw_data': dict(raw_row),
            'quantity_normalized': nights,
            'unit_normalized': 'nights',
            'description': desc or 'Hotel accommodation',
            'vendor_supplier': vendor,
            'location_label': '',
            'emission_factor': HOTEL_FACTOR_PER_NIGHT,
            'emission_factor_source': EF_SOURCE,
            'emission_factor_unit': 'kgCO2e/night',
            'co2e_kg': co2e_kg,
            'status': 'FLAGGED' if confidence < 0.7 or flags else 'PENDING',
            'flag_reason': ' | '.join(flags),
            'confidence_score': max(0.0, confidence),
            'auto_flagged': bool(flags),
        }

    # --- Ground transport / Rail ---
    else:
        source_type = 'TRAVEL_RAIL' if expense_type == 'rail' else 'TRAVEL_GROUND'
        category = 'business_travel_rail' if expense_type == 'rail' else 'business_travel_ground'

        dist_str = _get(row, DIST_COLS)
        distance_km = _parse_distance(dist_str)

        if distance_km is None:
            flags.append(
                'No distance provided for ground transport — '
                'enter manually or use expense amount as proxy (not done automatically).'
            )
            confidence -= 0.4

        ef = TAXI_FACTOR_PER_KM
        co2e_kg = distance_km * ef if distance_km else None

        return {
            'source_type': source_type,
            'scope': '3',
            'category': category,
            'activity_date': parsed_date,
            'period_start': parsed_date,
            'period_end': parsed_date,
            'raw_quantity': distance_km or Decimal('0'),
            'raw_unit': 'km',
            'raw_location': '',
            'source_record_id': f'{employee}_{parsed_date}_ground',
            'raw_data': dict(raw_row),
            'quantity_normalized': distance_km or Decimal('0'),
            'unit_normalized': 'km',
            'description': desc or 'Ground transport',
            'vendor_supplier': vendor,
            'location_label': '',
            'emission_factor': ef if distance_km else None,
            'emission_factor_source': EF_SOURCE,
            'emission_factor_unit': 'kgCO2e/km',
            'co2e_kg': co2e_kg,
            'status': 'FLAGGED' if confidence < 0.7 or flags else 'PENDING',
            'flag_reason': ' | '.join(flags),
            'confidence_score': max(0.0, confidence),
            'auto_flagged': bool(flags),
        }
