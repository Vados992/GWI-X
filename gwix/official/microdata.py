"""Local-only accounting audit of a licensed, canonical household extract.

This is an input/audit interface, NOT a Portuguese tax-benefit rules engine.
It never exports household identifiers or unlocks a policy simulation.
"""
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path


MONEY = ('gross_earnings_eur', 'other_income_eur', 'income_tax_eur',
         'employee_contributions_eur', 'cash_benefits_eur', 'disposable_income_eur')
COUNTS = ('adults', 'children', 'employed_adults')
FIELDS = {'household_id', 'year', 'weight', 'group', *MONEY, *COUNTS}


def audit_microdata(data_path, metadata_path):
    raw = Path(data_path).read_bytes()
    meta = json.loads(Path(metadata_path).read_text(encoding='utf-8'))
    if meta.get('data_origin') != 'OBSERVED_LICENSED_MICRODATA' or meta.get('country') != 'PT':
        raise ValueError('Observed licensed Portuguese extract required; synthetic public-use files rejected')
    for key in ('source_owner', 'license_reference', 'income_definition', 'coverage_definition'):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise ValueError('Missing microdata metadata: '+key)
    digest = hashlib.sha256(raw).hexdigest()
    if meta.get('sha256') != digest:
        raise ValueError('Microdata hash mismatch')
    totals = {key: Decimal(0) for key in MONEY}
    totals.update(weight=Decimal(0), employed_adults=Decimal(0))
    seen, n, max_error = set(), 0, Decimal(0)
    with Path(data_path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or set(reader.fieldnames) != FIELDS or len(reader.fieldnames) != len(FIELDS):
            raise ValueError('Canonical microdata schema mismatch; no names/contact fields accepted')
        for row in reader:
            key = (row['household_id'], row['year'])
            if not key[0] or key in seen:
                raise ValueError('Missing/duplicate household-year')
            seen.add(key)
            if int(row['year']) != meta.get('income_year'):
                raise ValueError('Income year mismatch')
            if not row['group'].strip():
                raise ValueError('Missing group')
            vals = {name: Decimal(row[name]) for name in (*MONEY, 'weight')}
            if not all(v.is_finite() for v in vals.values()) or vals['weight'] <= 0:
                raise ValueError('Invalid weight or nonfinite monetary input')
            if any(vals[k] < 0 for k in ('gross_earnings_eur', 'income_tax_eur', 'employee_contributions_eur', 'cash_benefits_eur')):
                raise ValueError('Negative canonical earnings/tax/contribution/benefit')
            counts = {name: int(row[name]) for name in COUNTS}
            if counts['adults'] < 1 or counts['children'] < 0 or not 0 <= counts['employed_adults'] <= counts['adults']:
                raise ValueError('Invalid household counts')
            expected = vals['gross_earnings_eur']+vals['other_income_eur']-vals['income_tax_eur']-vals['employee_contributions_eur']+vals['cash_benefits_eur']
            error = abs(expected-vals['disposable_income_eur'])
            max_error = max(error, max_error)
            if error > Decimal('.02'):
                raise ValueError('Observed income components do not reconcile to two-cent rounding tolerance')
            for name in MONEY:
                totals[name] += vals[name]*vals['weight']
            totals['weight'] += vals['weight']
            totals['employed_adults'] += counts['employed_adults']*vals['weight']
            n += 1
    if n == 0:
        raise ValueError('Empty microdata extract')
    return dict(status='CANONICAL_ACCOUNTING_AUDIT_PASS', households=n, sha256=digest,
                weighted_totals_eur_or_counts={k: str(v) for k, v in totals.items()},
                max_unweighted_identity_error_eur=str(max_error),
                provenance='Caller-supplied licence/provenance attestation; independently authenticate with data owner',
                identifiers_exported=False, national_tax_benefit_rules_validated=False,
                full_policy_run='BLOCKED', emtr_status='Not identified from observed income totals; requires national policy rules')
