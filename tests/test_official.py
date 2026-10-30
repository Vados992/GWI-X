"""Official-input invariants. Generated fixtures below are SYNTHETIC TEST FIXTURES.

Only SavedOfficialTests uses the real, hashed public snapshot shipped with the repo.
"""
import copy
from contextlib import closing
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from gwix.official.catalog import load_profile, sources
from gwix.official.ecb import normalize_ecb
from gwix.official.microdata import audit_microdata, FIELDS
from gwix.official.store import strict_json, decode, normalize, read_snapshot, database, fetch_snapshot
from gwix.official.transport import check_url, Response
from gwix.official.validation import Observations, accounting, panels, readiness, core_diagnostics

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT/'data/official/PT/2026-10-30-final'
PROFILE = load_profile(ROOT/'configs/official_portugal.json')


def fixture():
    return dict(version='2.0', **{'class': 'dataset'}, id=['geo', 'unit', 'time'], size=[1, 1, 2],
                dimension={'geo': {'category': {'index': {'PT': 0}}},
                           'unit': {'category': {'index': ['MIO_EUR']}},
                           'time': {'category': {'index': {'2010': 0, '2011': 1}}}},
                value={'0': 1.2}, status={})


def query():
    return dict(id='fixture', provider='Eurostat', time_dimension='time', series=[
        dict(concept='fixture_value', dimensions={'geo': 'PT', 'unit': 'MIO_EUR'},
             unit='EUR', multiplier='1000000', basis='SYNTHETIC_TEST_FIXTURE')])


class DecoderTests(unittest.TestCase):
    def test_sparse_missing_does_not_become_zero(self):
        r = normalize(fixture(), query(), PROFILE)
        self.assertEqual(next(p['value'] for p in r if p['period'] == 2010), '1200000.0')
        self.assertIsNone(next(p['value'] for p in r if p['period'] == 2011))

    def test_dimension_order_and_dense_values(self):
        d = fixture(); d['value'] = [1, 2]; d['status'] = ['', 'p']
        decoded = list(decode(d))
        self.assertEqual(decoded[1], ({'time': '2011', 'unit': 'MIO_EUR', 'geo': 'PT'}, 2, 'p'))

    def test_last_dimension_varies_fastest(self):
        d = fixture(); d['id'] = ['unit', 'geo', 'time']; d['size'] = [2, 1, 2]
        d['dimension']['unit']['category']['index'] = ['MIO_EUR', 'PC_GDP']; d['value'] = [1, 2, 3, 4]
        self.assertEqual(list(decode(d))[2][0], {'time': '2010', 'geo': 'PT', 'unit': 'PC_GDP'})

    def test_bad_source_dimension_is_rejected(self):
        d = fixture(); d['id'][0] = 'region'; d['dimension']['region'] = d['dimension'].pop('geo')
        with self.assertRaises(ValueError): normalize(d, query(), PROFILE)

    def test_unit_drift_is_not_silently_converted(self):
        d = fixture(); d['dimension']['unit']['category']['index'] = ['THS_PER']
        with self.assertRaises(ValueError): normalize(d, query(), PROFILE)

    def test_forecast_and_confidential_values_are_excluded(self):
        for flag in ('f', 'c', 'm', 'u'):
            d = fixture(); d['value'] = [1, 9]; d['status'] = ['', flag]
            rows = normalize(d, query(), PROFILE)
            self.assertIsNone(next(p['value'] for p in rows if p['period'] == 2011))

    def test_observed_zero_remains_zero(self):
        d = fixture(); d['value'] = [0, 1]
        self.assertEqual(next(r['value'] for r in normalize(d, query(), PROFILE) if r['period'] == 2010), '0')

    def test_duplicate_json_and_nonfinite_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.assertRaises(ValueError): strict_json(raw)

    def test_malformed_shape_and_positions_rejected(self):
        for change in ('shape', 'position', 'empty', 'duplicate', 'dense'):
            d = fixture()
            if change == 'shape': d['size'][-1] = 3
            if change == 'position': d['value']['8'] = 2
            if change == 'empty': d['size'][-1] = 0
            if change == 'duplicate': d['dimension']['time']['category']['index'] = ['2010', '2010']
            if change == 'dense': d['value'] = [1]
            with self.assertRaises(ValueError): list(decode(d))

    def test_no_http_or_arbitrary_hosts(self):
        for url in ('http://ec.europa.eu/x', 'https://example.org/x', 'https://a@ec.europa.eu/x', 'https://ec.europa.eu:8443/x'):
            with self.assertRaises(ValueError): check_url(url)
        check_url('https://ec.europa.eu/eurostat/x')

    def test_source_failure_saves_receipt_without_fabrication(self):
        def unavailable(url):
            return Response(403, url, 'text/plain', b'access unavailable', 'SYNTHETIC_TEST_TRANSPORT')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'snapshot'
            receipts = fetch_snapshot(PROFILE, out, downloader=unavailable)
            self.assertTrue(all(r['status'] == 'UNAVAILABLE' for r in receipts))
            _, _, rows, meta = read_snapshot(out)
            self.assertEqual(rows, [])
            self.assertEqual(meta['status'], 'PARTIAL_SOURCE_FAILURE')

    def test_profile_cannot_hide_country_or_unknown_funding(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'profile.json'
            for updates in ({'country': 'UA'}, {'currency': 'CU'}, {'funding_authorisation_eur': -1},
                            {'funding_authorisation_eur': float('nan')}, {'evaluation_start': 2018}):
                p.write_text(json.dumps(dict(PROFILE, **updates)))
                with self.assertRaises(ValueError): load_profile(p)


class ECBTests(unittest.TestCase):
    def document(self, dates):
        buffer = io.StringIO(); fields = ['KEY', 'FREQ', 'REF_AREA', 'CURRENCY', 'TIME_PERIOD', 'OBS_VALUE', 'OBS_STATUS', 'OBS_CONF', 'UNIT', 'UNIT_MULT']
        w = csv.DictWriter(buffer, fieldnames=fields); w.writeheader()
        for day in dates:
            w.writerow(dict(KEY='FM.D.U2.EUR.4F.KR.MRR_FR.LEV', FREQ='D', REF_AREA='U2', CURRENCY='EUR',
                            TIME_PERIOD=day, OBS_VALUE='2', OBS_STATUS='A', OBS_CONF='F', UNIT='PCPA', UNIT_MULT='0'))
        return buffer.getvalue().encode()

    def test_calendar_year_mean_and_leap_coverage(self):
        from datetime import date, timedelta
        dates = [(date(2012, 1, 1)+timedelta(days=i)).isoformat() for i in range(366)]
        q = next(q for q in sources(PROFILE) if q['id'] == 'ecb_policy_rate')
        rows, count = normalize_ecb(self.document(dates), q, PROFILE)
        self.assertEqual(count, 366)
        self.assertEqual(Decimal(next(r['value'] for r in rows if r['period'] == 2012)), Decimal('.02'))
        with self.assertRaises(ValueError): normalize_ecb(self.document(dates[:-1]), q, PROFILE)

    def test_ecb_duplicate_or_unit_drift_rejected(self):
        q = next(q for q in sources(PROFILE) if q['id'] == 'ecb_policy_rate')
        with self.assertRaises(ValueError): normalize_ecb(self.document(['2012-01-01']*2), q, PROFILE)
        with self.assertRaises(ValueError): normalize_ecb(self.document(['2012-01-01']).replace(b'PCPA', b'EUR'), q, PROFILE)


class SavedOfficialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile, cls.receipts, cls.rows, cls.meta = read_snapshot(SNAPSHOT)
        cls.obs = Observations(cls.rows)

    def test_real_snapshot_counts_and_explicit_missingness(self):
        self.assertEqual(sum(r['status'] == 'OK' for r in self.receipts), 15)
        self.assertEqual(len({r['concept'] for r in self.rows}), 41)
        self.assertEqual(sum(r['value'] is not None for r in self.rows), 678)
        self.assertEqual(sum(r['value'] is None for r in self.rows), 19)

    def test_source_currency_and_rate_dimensions(self):
        self.assertGreater(self.obs.require('gdp_nominal', 2024, 'EUR'), Decimal('100000000000'))
        with self.assertRaises(ValueError): self.obs.require('gdp_nominal', 2024, 'CU')
        self.assertTrue(0 < self.obs.require('apparent_debt_interest_rate', 2024) < Decimal('.10'))

    def test_actual_accounting_identities(self):
        checks, _ = accounting(self.obs, self.profile)
        self.assertEqual(len(checks), 34)
        self.assertTrue(all(c['status'] == 'PASS' for c in checks))

    def test_debt_stock_flow_difference_is_not_programme_money(self):
        _, debt = accounting(self.obs, self.profile)
        year = next(r for r in debt if r['year'] == 2024)
        self.assertEqual(year['implied_stock_flow_adjustment_eur'], Decimal('11077300000'))
        self.assertIsNone(year['programme_funding_eur'])

    def test_silc_deflation_matches_previous_income_year(self):
        _, incomes = panels(self.obs, self.profile)
        r = next(r for r in incomes if r['survey_year'] == 2025 and r['group_or_statistic'] == 'median_equivalised_income')
        expected = self.obs.require('median_equivalised_income', 2025)*self.obs.require('hicp_index', 2020)/self.obs.require('hicp_index', 2024)
        self.assertEqual(r['income_reference_year'], 2024)
        self.assertEqual(r['real_eur_2020_equivalised'], expected)

    def test_hicp_is_not_replaced_with_gdp_deflator(self):
        national, _ = panels(self.obs, self.profile)
        r = next(r for r in national if r['year'] == 2024)
        self.assertNotEqual(r['gdp_deflator_2020_1'], r['hicp_2020_1'])

    def test_readiness_does_not_allow_unfunded_policy_execution(self):
        result = readiness(self.profile, self.receipts)
        self.assertEqual(result['full_real_data_policy_run'], 'BLOCKED')
        self.assertEqual(result['additional_programme_spending_eur'], 0)
        self.assertFalse(next(r for r in result['requirements'] if r['requirement'] == 'programme_funding_authorisation')['satisfied'])

    def test_core_really_runs_and_bad_accuracy_is_reported(self):
        core = json.loads((ROOT/'configs/synthetic.json').read_text())
        forecasts, scores, omissions, params = core_diagnostics(self.obs, self.profile, core)
        self.assertEqual(len(forecasts), 35)
        self.assertEqual(omissions[0]['year'], 2025)
        self.assertLessEqual(max(params['training_years']), 2018)
        gdp = next(s for s in scores if s['metric'] == 'gdp_growth')
        self.assertGreater(gdp['core_MAE'], gdp['naive_MAE'])
        self.assertEqual(gdp['comparison'], 'DOES_NOT_BEAT_NAIVE')

    def test_held_out_target_does_not_enter_its_own_prediction(self):
        core = json.loads((ROOT/'configs/synthetic.json').read_text())
        before, _, _, _ = core_diagnostics(self.obs, self.profile, core)
        changed = copy.deepcopy(self.rows)
        for r in changed:
            if r['concept'] == 'gdp_real' and r['period'] == 2019:
                r['value'] = str(Decimal(r['value'])*Decimal('1.01'))
        after, _, _, _ = core_diagnostics(Observations(changed), self.profile, core)
        a = next(r for r in before if r['year'] == 2019 and r['metric'] == 'gdp_growth')
        b = next(r for r in after if r['year'] == 2019 and r['metric'] == 'gdp_growth')
        self.assertEqual(a['core_prediction'], b['core_prediction'])
        self.assertNotEqual(a['actual'], b['actual'])

    def test_database_exact_decimal_and_immutable_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'official.sqlite'
            self.assertEqual(database(SNAPSHOT, path), 697)
            with closing(sqlite3.connect(path)) as con, con:
                count = con.execute('SELECT count(*) FROM observations WHERE value_decimal IS NULL').fetchone()[0]
                self.assertEqual(count, 19)
                with self.assertRaises(sqlite3.IntegrityError): con.execute("UPDATE observations SET value_decimal='0'")
                with self.assertRaises(sqlite3.IntegrityError): con.execute('DELETE FROM observations')

    def test_tampered_raw_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp)/'snapshot'; shutil.copytree(SNAPSHOT, copied)
            (copied/'raw/government_accounts.json').write_bytes(b'{}')
            with self.assertRaises(ValueError): read_snapshot(copied)


class MicrodataTests(unittest.TestCase):
    def sample(self, folder, updates=None, metadata_updates=None):
        row = dict(household_id='SYNTHETIC_TEST_H1', year='2024', weight='2', group='test_fixture', adults='1', children='0', employed_adults='1',
                   gross_earnings_eur='10000', other_income_eur='200', income_tax_eur='1000',
                   employee_contributions_eur='1100', cash_benefits_eur='500', disposable_income_eur='8600')
        row.update(updates or {})
        path = folder/'fixture.csv'
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(FIELDS)); writer.writeheader(); writer.writerow(row)
        meta = dict(data_origin='OBSERVED_LICENSED_MICRODATA', country='PT', source_owner='SYNTHETIC TEST ATTESTATION',
                    license_reference='SYNTHETIC TEST ONLY', income_definition='wages + other - tax - contributions + cash benefits',
                    coverage_definition='SYNTHETIC TEST ONLY', income_year=2024, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        meta.update(metadata_updates or {})
        metadata = folder/'metadata.json'; metadata.write_text(json.dumps(meta))
        return path, metadata

    def test_weights_applied_once_and_no_identifiers_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_microdata(*self.sample(Path(tmp)))
            self.assertEqual(result['weighted_totals_eur_or_counts']['disposable_income_eur'], '17200')
            self.assertNotIn('SYNTHETIC_TEST_H1', json.dumps(result))
            self.assertEqual(result['full_policy_run'], 'BLOCKED')

    def test_synthetic_puf_not_accepted_as_observed_microdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.sample(Path(tmp), metadata_updates={'data_origin': 'SYNTHETIC_PUBLIC_USE_FILE'})
            with self.assertRaises(ValueError): audit_microdata(*paths)

    def test_microdata_identity_weight_and_counts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for updates in ({'weight': '0'}, {'weight': 'NaN'}, {'disposable_income_eur': '9999'}, {'employed_adults': '2'}):
                paths = self.sample(Path(tmp), updates=updates)
                with self.assertRaises(ValueError): audit_microdata(*paths)

    def test_microdata_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.sample(Path(tmp), metadata_updates={'sha256': '0'*64})
            with self.assertRaises(ValueError): audit_microdata(*paths)


if __name__ == '__main__':
    unittest.main()
