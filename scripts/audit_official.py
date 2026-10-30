"""Independent check of published CSV/SQLite and selected raw official values.

Intentionally imports no gwix model or official-adapter code.
"""
import argparse
from contextlib import closing
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3


def audit(snapshot, results):
    snapshot, results = Path(snapshot), Path(results)
    manifest = json.loads((snapshot/'snapshot.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        if hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != expected:
            raise AssertionError('Snapshot changed: '+name)
    with (results/'observations.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    by_key = {(r['concept'], int(r['period'])): r for r in rows}
    if len(by_key) != len(rows):
        raise AssertionError('Duplicate CSV concept/year')
    with closing(sqlite3.connect('file:'+str((results/'official.sqlite').resolve()).replace('\\', '/')+'?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise AssertionError('SQLite integrity failed')
        database_rows = conn.execute('SELECT concept,period,country,value_decimal,unit,reference_year FROM observations').fetchall()
        if len(database_rows) != len(rows):
            raise AssertionError('Database/CSV count mismatch')
        for concept, period, country, value, unit, refyear in database_rows:
            r = by_key[(concept, period)]
            assert r['country'] == country == 'PT' and r['unit'] == unit and int(r['reference_year']) == refyear
            assert (r['value'] or None) == value
    raw_gdp = json.loads((snapshot/'raw/national_accounts_current.json').read_bytes(), parse_float=Decimal)
    raw_gov = json.loads((snapshot/'raw/government_accounts.json').read_bytes(), parse_float=Decimal)

    def cell(doc, selections):
        # Direct row-major position calculation, independent of adapter decoding.
        position = 0
        for dimension, size in zip(doc['id'], doc['size']):
            idx = doc['dimension'][dimension]['category']['index']
            wanted = selections[dimension]
            category_position = idx.index(wanted) if isinstance(idx, list) else idx[wanted]
            position = position*size+category_position
        return Decimal(str(doc['value'][str(position)]))*1000000

    profile = json.loads((snapshot/'profile.json').read_text())
    raw_checks, budget_checks = 0, 0
    max_residual = Decimal(0)
    for year in range(profile['first_year'], profile['last_year']+1):
        common = dict(freq='A', geo='PT', time=str(year))
        gdp = cell(raw_gdp, dict(common, unit='CP_MEUR', na_item='B1GQ'))
        assert Decimal(by_key[('gdp_nominal', year)]['value']) == gdp
        values = {}
        for concept, code in [('revenue', 'TR'), ('expenditure', 'TE'), ('net_lending', 'B9')]:
            value = cell(raw_gov, dict(common, unit='MIO_EUR', sector='S13', na_item=code))
            assert Decimal(by_key[(concept, year)]['value']) == value
            values[concept] = value
            raw_checks += 1
        raw_checks += 1
        residual = values['revenue']-values['expenditure']-values['net_lending']
        max_residual = max(max_residual, abs(residual))
        assert abs(residual) <= 150000
        budget_checks += 1
    state = json.loads((results/'readiness.json').read_text())
    assert state['full_real_data_policy_run'] == 'BLOCKED' and state['additional_programme_spending_eur'] == 0
    return dict(status='PASS_WITH_POLICY_RUN_BLOCKED', csv_database_rows_checked=len(rows),
                missing_values=sum(r['value'] == '' for r in rows),
                directly_reconciled_raw_official_values=raw_checks,
                independently_recomputed_budget_years=budget_checks,
                max_budget_identity_residual_eur=str(max_residual),
                source_snapshot_id=manifest['snapshot_id'],
                scope='Integrity and accounting checks; no empirical validation of causal reform effects')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('snapshot'); p.add_argument('results'); p.add_argument('--out')
    a = p.parse_args(); result = audit(a.snapshot, a.results)
    text = json.dumps(result, indent=2)+'\n'
    if a.out: Path(a.out).write_text(text, encoding='utf-8', newline='\n')
    print(text)
