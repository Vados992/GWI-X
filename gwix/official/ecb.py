"""ECB daily policy rates; complete-calendar-year means, never partial-year fill."""
import calendar
import csv
from datetime import date
from decimal import Decimal
import io


def normalize_ecb(raw, query, profile):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    required = {'KEY', 'FREQ', 'REF_AREA', 'CURRENCY', 'TIME_PERIOD', 'OBS_VALUE',
                'OBS_STATUS', 'OBS_CONF', 'UNIT', 'UNIT_MULT'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('Unexpected ECB CSV schema')
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('Duplicate ECB column')
    years, seen = {}, set()
    spec = query['series'][0]
    for row in reader:
        if row['KEY'] != spec['ecb_key'] or row['FREQ'] != 'D' or row['REF_AREA'] != 'U2' or row['CURRENCY'] != 'EUR':
            raise ValueError('ECB series identity mismatch')
        if row['UNIT'] != 'PCPA' or row['UNIT_MULT'] != '0':
            raise ValueError('ECB must return unscaled percent per annum')
        day = date.fromisoformat(row['TIME_PERIOD'])
        if day in seen:
            raise ValueError('Duplicate ECB day')
        seen.add(day)
        if not profile['first_year'] <= day.year <= profile['last_year']:
            raise ValueError('ECB returned a day outside requested period')
        if row['OBS_STATUS'] != 'A' or row['OBS_CONF'] != 'F' or row['OBS_VALUE'] == '':
            continue
        value = Decimal(row['OBS_VALUE'])
        if not value.is_finite() or not Decimal('-10') <= value <= 100:
            raise ValueError('Invalid ECB interest observation')
        years.setdefault(day.year, []).append(value)
    rows = []
    for year in range(profile['first_year'], profile['last_year']+1):
        values = years.get(year, [])
        complete = len(values) == (366 if calendar.isleap(year) else 365)
        mean = sum(values, Decimal(0))/len(values) if complete else None
        rows.append(dict(country='PT', concept=spec['concept'], period=year, reference_year=year,
                         unit=spec['unit'], basis=spec['basis'], query_id=query['id'], provider=query['provider'],
                         data_status='OFFICIAL_STATISTIC_DERIVED_ANNUAL_MEAN',
                         raw_value=str(mean) if mean is not None else None,
                         value=str(mean*Decimal(spec['multiplier'])) if mean is not None else None,
                         source_flags='A', missing_reason='' if complete else 'incomplete_official_daily_coverage'))
    if not any(row['value'] is not None for row in rows):
        raise ValueError('ECB has no complete calendar years')
    return rows, len(seen)
