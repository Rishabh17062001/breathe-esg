"""
SAP Flat-File Parser — MM/FI module CSV export.

Format choice: semicolon-delimited flat file from SAP transaction ME2N
(purchase orders by material) and a custom fuel consumption report built
on MM60 transaction data. This is the most universally accessible SAP export
method — it works across R/3, S/4HANA, and ECC without custom development
or IDoc infrastructure. The client's SAP admin can run ME2N, set the column
layout once, and email the .csv weekly.

SAP quirks handled here:
 - German column headers (Buchungsdatum, Menge, Mengeneinheit, Werk, Lieferant)
 - Date format: DD.MM.YYYY (European convention)
 - Semicolon delimiter (German regional CSV standard — commas conflict with
   German decimal notation where 1.234,56 means one-thousand-two-hundred...)
 - Plant codes (Werk) are internal 4-char codes; we map known ones to
   human-readable labels and flag unknowns
 - Unit codes: L (litres), KG (kilograms), M3 (cubic metres), ST (pieces),
   KWH (kilowatt-hours — rarely but possible in energy sub-ledgers)
 - Material groups (Materialgruppe): 010-KRAFTSTOFF = fuel, 020-ENERGIE = energy,
   030-SCHMIERSTOFFE = lubricants (not emission-relevant, flagged for review)
"""

import csv
import io
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Emission factors — DEFRA 2023 Conversion Factors (kgCO2e per unit)
# Source: UK DEFRA "Greenhouse gas reporting: conversion factors 2023"
# Using DEFRA because it's the most widely cited, freely available, and
# covers the fuel types we see in Indian manufacturing SAP exports.
EMISSION_FACTORS = {
    'diesel':       {'factor': Decimal('2.68801'), 'unit': 'kgCO2e/L',  'source': 'DEFRA_2023'},
    'petrol':       {'factor': Decimal('2.31446'), 'unit': 'kgCO2e/L',  'source': 'DEFRA_2023'},
    'natural_gas':  {'factor': Decimal('2.04040'), 'unit': 'kgCO2e/m3', 'source': 'DEFRA_2023'},
    'lpg':          {'factor': Decimal('1.55430'), 'unit': 'kgCO2e/kg', 'source': 'DEFRA_2023'},
    'hfo':          {'factor': Decimal('3.17900'), 'unit': 'kgCO2e/kg', 'source': 'DEFRA_2023'},
}

# Material description → fuel type mapping.
# In a production deployment this would be a database lookup table maintained
# by the client's sustainability team, since material codes are client-specific.
MATERIAL_TO_FUEL = {
    'diesel': 'diesel',
    'dies': 'diesel',
    'benzin': 'petrol',
    'benz': 'petrol',
    'erdgas': 'natural_gas',
    'gas': 'natural_gas',
    'lpg': 'lpg',
    'flüssiggas': 'lpg',
    'fluessiggas': 'lpg',
    'schweröl': 'hfo',
    'schweroil': 'hfo',
    'hfo': 'hfo',
    'heizöl': 'hfo',
}

# German column header → internal key mapping
GERMAN_HEADERS = {
    'einkaufsbeleg': 'order_id',
    'einkaufspos.': 'order_item',
    'material': 'material_code',
    'materialkurzbeschreibung': 'material_desc',
    'werk': 'plant_code',
    'einkaufsorg.': 'purch_org',
    'buchungsdatum': 'posting_date',
    'bestellmenge': 'quantity',
    'mengeneinheit': 'unit',
    'bestellpreismengeneinheit': 'unit',
    'nettowert': 'net_value',
    'währung': 'currency',
    'lieferant': 'vendor_id',
    'lieferantenname': 'vendor_name',
    'buchungskreis': 'company_code',
    'materialgruppe': 'material_group',
}

# SAP plant code → human label. Extend per client onboarding.
PLANT_LABELS = {
    'IN01': 'Pune Plant A',
    'IN02': 'Pune Plant B',
    'IN03': 'Mumbai Warehouse',
    'IN04': 'Delhi Facility',
    'IN05': 'Chennai Plant',
}

# Unit normalisation: SAP unit code → (canonical_unit, conversion_factor)
# Conversion factor is multiplier to reach canonical unit.
UNIT_MAP = {
    'L':   ('L',   Decimal('1')),
    'LTR': ('L',   Decimal('1')),
    'M3':  ('m3',  Decimal('1')),
    'KG':  ('kg',  Decimal('1')),
    'G':   ('kg',  Decimal('0.001')),
    'T':   ('kg',  Decimal('1000')),
    'KWH': ('kWh', Decimal('1')),
    'MWH': ('kWh', Decimal('1000')),
    'ST':  (None,  None),  # pieces — not normalizable, will flag
}

# Material groups that carry Scope 1 emission relevance
FUEL_GROUPS = {'010-KRAFTSTOFF', '010-FUEL', '020-ENERGIE', '020-ENERGY'}


def _parse_date(raw: str) -> datetime | None:
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _identify_fuel(material_desc: str, material_code: str) -> str | None:
    desc_lower = (material_desc or '').lower()
    for keyword, fuel_type in MATERIAL_TO_FUEL.items():
        if keyword in desc_lower:
            return fuel_type
    code_lower = (material_code or '').lower()
    for keyword, fuel_type in MATERIAL_TO_FUEL.items():
        if keyword in code_lower:
            return fuel_type
    return None


def parse_sap_csv(file_bytes: bytes) -> dict:
    """
    Parse SAP ME2N / fuel consumption CSV export.

    Returns:
        {
          'records': list[dict],   # each dict = kwargs for ActivityRecord
          'errors':  list[dict],   # {row_num, row_data, error}
          'row_count': int
        }
    """
    try:
        text = file_bytes.decode('utf-8')
    except UnicodeDecodeError:
        import chardet
        detected = chardet.detect(file_bytes)
        text = file_bytes.decode(detected.get('encoding', 'latin-1'), errors='replace')

    # SAP uses semicolons for German locale exports
    dialect = 'excel' if ',' in text.split('\n')[0] and ';' not in text.split('\n')[0] else None
    delimiter = ',' if dialect else ';'

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    # Normalise headers: strip whitespace, lowercase, map German → internal
    raw_headers = reader.fieldnames or []
    header_map = {}
    for h in raw_headers:
        normalised = h.strip().lower()
        mapped = GERMAN_HEADERS.get(normalised, normalised)
        header_map[h] = mapped

    records = []
    errors = []
    row_num = 1

    for raw_row in reader:
        row_num += 1
        row = {header_map.get(k, k.lower().strip()): v.strip() if v else '' for k, v in raw_row.items()}

        try:
            record = _parse_sap_row(row, row_num)
            if record:
                records.append(record)
            # None means the row was intentionally skipped (non-fuel material)
        except Exception as e:
            errors.append({'row_num': row_num, 'raw': dict(raw_row), 'error': str(e)})

    return {'records': records, 'errors': errors, 'row_count': row_num - 1}


def _parse_sap_row(row: dict, row_num: int) -> dict | None:
    flags = []
    confidence = 1.0

    order_id = row.get('order_id', '')
    material_code = row.get('material_code', '')
    material_desc = row.get('material_desc', '')
    plant_code = row.get('plant_code', '')
    material_group = row.get('material_group', '').upper()
    vendor_id = row.get('vendor_id', '')
    vendor_name = row.get('vendor_name', '')

    # Skip non-fuel/non-energy material groups silently
    # Lubricants (030-*) and other indirect materials are procurement records,
    # not direct emission sources — we still ingest them but mark as SAP_PROCUREMENT.
    is_fuel_group = any(g in material_group for g in ['KRAFT', 'FUEL', 'ENERG', 'LPG', 'GAS'])

    # Date
    raw_date = row.get('posting_date', '')
    parsed_date = _parse_date(raw_date)
    if not parsed_date:
        raise ValueError(f'Cannot parse date: {raw_date!r}')

    # Quantity
    raw_qty_str = row.get('quantity', '0').replace('.', '').replace(',', '.')
    try:
        raw_qty = Decimal(raw_qty_str)
    except InvalidOperation:
        raise ValueError(f'Cannot parse quantity: {row.get("quantity")!r}')

    if raw_qty <= 0:
        raise ValueError(f'Non-positive quantity: {raw_qty}')

    # Unit
    raw_unit = row.get('unit', '').upper().strip()
    unit_entry = UNIT_MAP.get(raw_unit)
    if unit_entry is None:
        flags.append(f'Unknown unit code: {raw_unit}')
        confidence -= 0.3
        canonical_unit = raw_unit
        qty_normalised = raw_qty
    elif unit_entry[0] is None:
        flags.append(f'Unit {raw_unit} (pieces) is not normalizable — check if this is a fuel record')
        confidence -= 0.4
        canonical_unit = raw_unit
        qty_normalised = raw_qty
    else:
        canonical_unit, conv = unit_entry
        qty_normalised = raw_qty * conv

    # Plant label
    location_label = PLANT_LABELS.get(plant_code, plant_code)
    if plant_code and plant_code not in PLANT_LABELS:
        flags.append(f'Unknown plant code: {plant_code} — add to plant lookup table')
        confidence -= 0.1

    # Fuel identification and emission factor
    fuel_type = _identify_fuel(material_desc, material_code)
    ef_info = EMISSION_FACTORS.get(fuel_type) if fuel_type else None

    if is_fuel_group and not fuel_type:
        flags.append(f'Fuel material group but cannot identify fuel type from: {material_desc!r}')
        confidence -= 0.3

    source_type = 'SAP_FUEL' if is_fuel_group and fuel_type else 'SAP_PROCUREMENT'
    scope = '1' if source_type == 'SAP_FUEL' else '3'
    category = 'stationary_combustion' if source_type == 'SAP_FUEL' else 'purchased_goods_services'

    co2e_kg = None
    ef_factor = None
    ef_source = ''
    ef_unit = ''

    if ef_info and qty_normalised:
        ef_factor = ef_info['factor']
        ef_source = ef_info['source']
        ef_unit = ef_info['unit']
        co2e_kg = qty_normalised * ef_factor

    auto_flagged = confidence < 0.7 or bool(flags)
    status = 'FLAGGED' if auto_flagged else 'PENDING'

    return {
        'source_type': source_type,
        'scope': scope,
        'category': category,
        'activity_date': parsed_date.date(),
        'period_start': parsed_date.date(),
        'period_end': parsed_date.date(),
        'raw_quantity': raw_qty,
        'raw_unit': raw_unit,
        'raw_location': plant_code,
        'source_record_id': order_id,
        'raw_data': row,
        'quantity_normalized': qty_normalised,
        'unit_normalized': canonical_unit,
        'description': material_desc,
        'vendor_supplier': vendor_name or vendor_id,
        'location_label': location_label,
        'emission_factor': ef_factor,
        'emission_factor_source': ef_source,
        'emission_factor_unit': ef_unit,
        'co2e_kg': co2e_kg,
        'status': status,
        'flag_reason': ' | '.join(flags),
        'confidence_score': max(0.0, confidence),
        'auto_flagged': auto_flagged,
    }
