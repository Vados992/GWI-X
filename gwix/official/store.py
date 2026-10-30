"""JSON-stat decoding, exact-unit normalization, immutable raw receipts and SQLite."""
import concurrent.futures
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .catalog import sources
from .transport import get
from .ecb import normalize_ecb


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)+'\n'


def write_json(path, value):
    Path(path).write_text(dumps(value), encoding='utf-8', newline='\n')


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key: '+key)
            out[key] = value
        return out
    def bad_number(text):
        raise ValueError('Nonfinite JSON number: '+text)
    return json.loads(raw, parse_float=Decimal, parse_constant=bad_number, object_pairs_hook=pairs)


def category_codes(dimension):
    index = dimension['category']['index']
    if isinstance(index, list):
        codes = index
    elif isinstance(index, dict):
        if sorted(index.values()) != list(range(len(index))):
            raise ValueError('Invalid category positions')
        codes = [k for k, _ in sorted(index.items(), key=lambda item: item[1])]
    else:
        raise ValueError('Invalid JSON-stat category index')
    if len(codes) != len(set(codes)):
        raise ValueError('Duplicate dimension category')
    return codes


def decode(doc):
    """Yield values including explicit holes; the final dimension varies fastest."""
    if doc.get('class') != 'dataset' or doc.get('version') != '2.0' or doc.get('error'):
        raise ValueError('Successful JSON-stat 2.0 dataset required')
    ids, sizes = doc['id'], doc['size']
    if len(ids) != len(set(ids)) or len(ids) != len(sizes):
        raise ValueError('Invalid dimension list')
    codes = [category_codes(doc['dimension'][name]) for name in ids]
    if [len(v) for v in codes] != sizes:
        raise ValueError('Dimension shape mismatch')
    if any(not isinstance(n, int) or n <= 0 for n in sizes):
        raise ValueError('Empty dimension: no observations returned')
    count = math.prod(sizes)
    if count > 2000000:
        raise ValueError('Dataset too large; narrow the source query')
    values, flags = doc.get('value', {}), doc.get('status', {})
    for container in (values, flags):
        if isinstance(container, dict):
            if any(not str(k).isdigit() or int(k) >= count for k in container):
                raise ValueError('Observation position outside cube')
        elif isinstance(container, list):
            if len(container) != count:
                raise ValueError('Dense observation shape mismatch')
        else:
            raise ValueError('Unsupported value/status representation')
    for position in range(count):
        rem, dims = position, {}
        for name, choices, size in reversed(list(zip(ids, codes, sizes))):
            rem, item = divmod(rem, size)
            dims[name] = choices[item]
        value = values[position] if isinstance(values, list) else values.get(str(position))
        flag = flags[position] if isinstance(flags, list) else flags.get(str(position), '')
        yield dims, value, flag or ''


def normalize(doc, query, profile):
    series = query['series']
    expected_dims = set(series[0]['dimensions']) | {query['time_dimension']}
    if query['provider'] == 'Banco de Portugal':
        metadata = doc.get('extension', {}).get('series', [])
        if len(metadata) != 1 or metadata[0]['id'] != series[0]['bp_series_id']:
            raise ValueError('BPstat must return exactly the requested series')
        dims = {str(v['dimension_id']): str(v['category_id']) for v in metadata[0]['dimension_category']}
        if doc['dimension']['40']['category']['label'].get(dims['40']) != 'Annual':
            raise ValueError('BPstat periodicity is not annual')
        if doc['dimension']['70']['category']['label'].get(dims['70']) != 'Percentage':
            raise ValueError('Unexpected BPstat rate unit')
        if doc['dimension']['63']['category']['label'].get(dims['63']) != 'Portugal':
            raise ValueError('BPstat geography mismatch')
        series = [dict(series[0], dimensions=dims)]
        expected_dims = set(dims) | {query['time_dimension']}
    if set(doc['id']) != expected_dims:
        raise ValueError('Unreviewed source schema dimensions: '+str(doc['id']))
    by_concept = {s['concept']: {} for s in series}
    for dims, raw, flag in decode(doc):
        time = dims[query['time_dimension']]
        if query['time_dimension'] == 'reference_date':
            if not time.endswith('-12-31'):
                raise ValueError('Annual BPstat stock/rate must use December 31')
            year = int(time[:4])
        else:
            if len(time) != 4 or not time.isdigit():
                raise ValueError('Annual period required')
            year = int(time)
        if not profile['first_year'] <= year <= profile['last_year']:
            continue
        for spec in series:
            if not all(dims.get(key) == value for key, value in spec['dimensions'].items()):
                continue
            values = by_concept[spec['concept']]
            if year in values:
                raise ValueError('Duplicate concept/year after selection')
            numeric = None if raw is None else Decimal(str(raw))
            if numeric is not None and not numeric.is_finite():
                raise ValueError('Nonfinite observation')
            if set(str(flag).replace(' ', '')) & {'f', 'c', 'm', 'u'}:
                # Forecast/confidential/missing/unreliable is not an observed zero.
                numeric = None
            value = numeric*Decimal(spec['multiplier']) if numeric is not None else None
            if spec['unit'] == 'FRACTION' and value is not None:
                low = Decimal('-0.5') if spec['concept'] == 'hicp_inflation' else Decimal(0)
                if not low <= value <= 1:
                    raise ValueError('Rate outside its reviewed domain')
            values[year] = dict(raw_value=None if raw is None else str(raw), value=None if value is None else str(value),
                                source_flags=str(flag), missing_reason='' if value is not None else 'source_missing_or_excluded_flag')
    out = []
    for spec in series:
        for year in range(profile['first_year'], profile['last_year']+1):
            point = by_concept[spec['concept']].get(year, dict(raw_value=None, value=None, source_flags='', missing_reason='period_not_reported'))
            out.append(dict(country=profile['country'], concept=spec['concept'], period=year,
                            reference_year=year-1 if 'survey_year_income_previous_year' in spec['basis'] else year,
                            unit=spec['unit'], basis=spec['basis'], query_id=query['id'],
                            provider=query['provider'], data_status='OFFICIAL_PUBLISHED_STATISTICS', **point))
    if not any(row['value'] is not None for row in out):
        raise ValueError('Source returned no usable observations for selected series')
    return out


def parse_response(raw, query, profile):
    if query.get('format') == 'ECB_CSV':
        rows, count = normalize_ecb(raw, query, profile)
        return rows, dict(source_updated=None, shape={'daily_observations': count})
    doc = strict_json(raw)
    rows = normalize(doc, query, profile)
    return rows, dict(source_updated=doc.get('updated') or doc.get('extension', {}).get('obs_updated_at'),
                      shape=dict(zip(doc['id'], doc['size'])))


def fetch_snapshot(profile, destination, downloader=get):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    (root/'raw').mkdir()
    write_json(root/'profile.json', profile)
    queries = sources(profile)
    write_json(root/'queries.json', queries)

    def one(query):
        receipt = dict(query_id=query['id'], requested_url=query['url'],
                       retrieved_at=datetime.now(timezone.utc).isoformat(), status='UNAVAILABLE')
        try:
            try:
                response = downloader(query['url'])
            except Exception as exc:
                receipt['first_attempt_error'] = type(exc).__name__+': '+str(exc)
                response = downloader(query['url'])
            # One retry for an upstream transient; never substitute another series.
            if response.status in (429, 500, 502, 503, 504):
                receipt['first_attempt_http_status'] = response.status
                response = downloader(query['url'])
            raw_path = 'raw/'+query['id']+('.csv' if query.get('format') == 'ECB_CSV' else '.json')
            (root/raw_path).write_bytes(response.raw)
            receipt.update(http_status=response.status, effective_url=response.final_url,
                           content_type=response.content_type, transport=response.transport,
                           raw_path=raw_path, bytes=len(response.raw),
                           sha256=hashlib.sha256(response.raw).hexdigest())
            if response.status != 200:
                raise ValueError('HTTP '+str(response.status))
            rows, metadata = parse_response(response.raw, query, profile)
            receipt.update(status='OK', **metadata,
                           observations=sum(r['value'] is not None for r in rows),
                           missing=sum(r['value'] is None for r in rows))
            return receipt
        except Exception as exc:
            receipt.update(error=type(exc).__name__+': '+str(exc))
            return receipt

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(one, queries))
    write_json(root/'receipts.json', receipts)
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(root.rglob('*')) if p.is_file()}
    identity = hashlib.sha256(dumps(hashes).encode()).hexdigest()
    write_json(root/'snapshot.json', dict(schema_version=1, snapshot_id=identity,
                                        status='COMPLETE' if all(r['status'] == 'OK' for r in receipts) else 'PARTIAL_SOURCE_FAILURE',
                                        data_status='OFFICIAL_PUBLISHED_STATISTICS', files=hashes))
    return receipts


def read_snapshot(root):
    root = Path(root)
    manifest = strict_json((root/'snapshot.json').read_bytes())
    for path, digest in manifest['files'].items():
        target = (root/path).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError('Snapshot path outside root')
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Snapshot hash mismatch: '+path)
    profile = strict_json((root/'profile.json').read_bytes())
    queries = strict_json((root/'queries.json').read_bytes())
    receipts = strict_json((root/'receipts.json').read_bytes())
    receipt_map = {r['query_id']: r for r in receipts}
    rows = []
    for query in queries:
        receipt = receipt_map[query['id']]
        if receipt['status'] == 'OK':
            raw = (root/receipt['raw_path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
                raise ValueError('Receipt/raw hash mismatch')
            points, _ = parse_response(raw, query, profile)
            rows.extend(points)
    keys = [(r['country'], r['concept'], r['period']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate normalized observation key')
    return profile, receipts, sorted(rows, key=lambda r: (r['concept'], r['period'])), manifest


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE snapshots(snapshot_id TEXT PRIMARY KEY, country TEXT NOT NULL, data_status TEXT NOT NULL);
CREATE TABLE requests(query_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots,
 url TEXT NOT NULL, status TEXT NOT NULL, retrieved_at TEXT NOT NULL, source_updated TEXT, sha256 TEXT);
CREATE TABLE observations(concept TEXT NOT NULL, period INTEGER NOT NULL, country TEXT NOT NULL,
 reference_year INTEGER NOT NULL, value_decimal TEXT, raw_value_decimal TEXT, unit TEXT NOT NULL,
 accounting_basis TEXT NOT NULL, source_flags TEXT NOT NULL, missing_reason TEXT NOT NULL,
 query_id TEXT NOT NULL REFERENCES requests, data_status TEXT NOT NULL,
 PRIMARY KEY(country,concept,period), CHECK(value_decimal IS NOT NULL OR missing_reason <> ''));
CREATE VIEW observed_values AS SELECT * FROM observations WHERE value_decimal IS NOT NULL;
CREATE TRIGGER immutable_observation_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER immutable_observation_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
'''


def database(snapshot, destination):
    profile, receipts, rows, manifest = read_snapshot(snapshot)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Database already exists; use a new snapshot path')
    try:
        with closing(sqlite3.connect(destination)) as conn, conn:
            conn.executescript(SCHEMA)
            conn.execute('INSERT INTO snapshots VALUES (?,?,?)',
                         (manifest['snapshot_id'], profile['country'], 'OFFICIAL_PUBLISHED_STATISTICS'))
            for r in receipts:
                conn.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?)',
                             (r['query_id'], manifest['snapshot_id'], r['requested_url'], r['status'],
                              r['retrieved_at'], r.get('source_updated'), r.get('sha256')))
            for r in rows:
                conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                             (r['concept'], r['period'], r['country'], r['reference_year'], r['value'], r['raw_value'],
                              r['unit'], r['basis'], r['source_flags'], r['missing_reason'], r['query_id'], r['data_status']))
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return len(rows)
