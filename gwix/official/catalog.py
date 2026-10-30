"""Explicit concepts, dimensions and units for a Portugal evidence profile."""
import json
import math
from pathlib import Path
from urllib.parse import urlencode

EUROSTAT = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
BPSTAT = 'https://bpstat.bportugal.pt/data/v1/'


def load_profile(path):
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    if profile.get('data_status') != 'OFFICIAL_OBSERVATIONS' or profile.get('country') != 'PT':
        raise ValueError('Only the reviewed Portugal official-data profile is implemented')
    if not (1995 <= profile['first_year'] < profile['training_end'] < profile['last_year'] <= 2025):
        raise ValueError('Invalid historical/training range; this profile ends in 2025')
    if profile.get('evaluation_start') != profile['training_end']+1 or profile.get('currency') != 'EUR':
        raise ValueError('Evaluation must begin after training; EUR profile required')
    for key in ('funding_authorisation_eur', 'programme_opening_reserve_eur'):
        value = profile.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError('Unknown financial evidence stays null; known amounts must be finite and nonnegative')
    return profile


def sources(profile):
    """A query can supply several series; every selected dimension is checked."""
    first, last = profile['first_year'], profile['last_year']
    result = []

    def add(name, dataset, fixed, selections):
        # Each selection: concept, dimensions, normalized unit, multiplier, basis.
        selectors = dict(fixed)
        for _, dims, _, _, _ in selections:
            for key, value in dims.items():
                selectors.setdefault(key, [])
                if not isinstance(selectors[key], list):
                    if selectors[key] != value:
                        raise ValueError('Conflicting fixed selection')
                elif value not in selectors[key]:
                    selectors[key].append(value)
        params = [('lang', 'EN'), ('freq', 'A'), ('geo', 'PT'),
                  ('sinceTimePeriod', first), ('untilTimePeriod', last)]
        for key, vals in selectors.items():
            params.extend((key, v) for v in (vals if isinstance(vals, list) else [vals]))
        specs = [dict(concept=concept, dimensions=dict(freq='A', geo='PT', **fixed, **dims),
                      unit=unit, multiplier=str(multiplier), basis=basis)
                 for concept, dims, unit, multiplier, basis in selections]
        result.append(dict(id=name, provider='Eurostat', dataset=dataset,
                           url=EUROSTAT+dataset+'?'+urlencode(params),
                           time_dimension='time', series=specs))

    gdp = [('gdp_nominal', 'B1GQ'), ('household_consumption_nominal', 'P31_S14_S15'),
           ('government_consumption_nominal', 'P3_S13'), ('gfcf_nominal', 'P51G'),
           ('inventories_valuables_nominal', 'P52_P53'), ('exports_nominal', 'P6'),
           ('imports_nominal', 'P7'), ('expenditure_discrepancy_nominal', 'YA0'),
           ('wages_nominal', 'D11')]
    add('national_accounts_current', 'nama_10_gdp', {'unit': 'CP_MEUR'},
        [(name, {'na_item': code}, 'EUR', 1000000, 'ESA2010_accrual_flow') for name, code in gdp])
    add('national_accounts_volume', 'nama_10_gdp', {'unit': 'CLV20_MEUR'},
        [(name, {'na_item': code}, 'EUR2020_CHAIN', 1000000, 'chain_volume_nonadditive')
         for name, code in [('gdp_real', 'B1GQ'), ('household_consumption_real', 'P31_S14_S15'),
                            ('government_consumption_real', 'P3_S13'), ('gfcf_real', 'P51G')]])
    fiscal = [('revenue', 'TR'), ('expenditure', 'TE'), ('net_lending', 'B9'),
              ('interest_accrued', 'D41PAY'), ('social_benefits_cash', 'D62PAY'),
              ('social_contributions', 'D61REC'), ('public_gfcf_nominal', 'P51G'),
              ('subsidies_paid', 'D3PAY'), ('household_income_tax', 'D51A_C1REC')]
    add('government_accounts', 'gov_10a_main', {'sector': 'S13', 'unit': 'MIO_EUR'},
        [(name, {'na_item': code}, 'EUR', 1000000, 'ESA2010_accrual_flow') for name, code in fiscal])
    add('government_debt', 'gov_10dd_edpt1', {'sector': 'S13', 'unit': 'MIO_EUR'},
        [('debt', {'na_item': 'GD'}, 'EUR', 1000000, 'Maastricht_nominal_year_end_stock')])
    add('hicp_legacy_annual', 'prc_hicp_aind', {'coicop': 'CP00'},
        [('hicp_index', {'unit': 'INX_A_AVG'}, 'INDEX_SOURCE_BASE', 1, 'annual_average_legacy_ECOICOP'),
         ('hicp_inflation', {'unit': 'RCH_A_AVG'}, 'FRACTION', '.01', 'annual_average_legacy_ECOICOP')])
    add('employment', 'lfsi_emp_a', {'indic_em': 'EMP_LFS', 'sex': 'T', 'age': 'Y20-64'},
        [('employment_rate_20_64', {'unit': 'PC_POP'}, 'FRACTION', '.01', 'resident_LFS_population_20_64'),
         ('employed_20_64', {'unit': 'THS_PER'}, 'PERSONS', 1000, 'resident_LFS_population_20_64')])
    add('unemployment', 'une_rt_a', {'sex': 'T', 'age': 'Y15-74', 'unit': 'PC_ACT'},
        [('unemployment_rate_15_74', {}, 'FRACTION', '.01', 'LFS_labour_force_15_74')])
    add('household_disposable', 'nasa_10_nf_tr',
        {'unit': 'CP_MEUR', 'sector': 'S14_S15', 'direct': 'RECV'},
        [('household_gross_disposable', {'na_item': 'B6G'}, 'EUR', 1000000, 'ESA2010_accrual_households_and_NPISH')])
    add('equivalised_income', 'ilc_di03', {'unit': 'EUR', 'sex': 'T', 'age': 'TOTAL'},
        [('median_equivalised_income', {'statinfo': 'MED_EI'}, 'EUR_EQUIVALISED', 1, 'EU_SILC_survey_year_income_previous_year'),
         ('mean_equivalised_income', {'statinfo': 'MEAN_EI'}, 'EUR_EQUIVALISED', 1, 'EU_SILC_survey_year_income_previous_year')])
    groups = ['A1', 'A1_DCH', 'A2_DCH2', 'A1_GE65']
    add('income_groups', 'ilc_di04', {'unit': 'EUR', 'statinfo': 'MED_EI'},
        [('median_equivalised_'+group, {'hhcomp': group}, 'EUR_EQUIVALISED', 1,
          'EU_SILC_overlapping_groups_survey_year_income_previous_year') for group in groups])
    add('productivity', 'nama_10_lp_ulc', {'unit': 'I20'},
        [('labour_productivity_hour', {'na_item': 'RLPR_HW'}, 'INDEX2020_100', 1, 'national_accounts_labour_productivity_not_TFP'),
         ('labour_productivity_person', {'na_item': 'RLPR_PER'}, 'INDEX2020_100', 1, 'national_accounts_labour_productivity_not_TFP')])
    add('capital', 'nama_10_nfa_st', {'nace_r2': 'TOTAL', 'asset10': 'N11N', 'unit': 'CLV20_MEUR'},
        [('net_fixed_capital', {}, 'EUR2020_CHAIN', 1000000, 'net_fixed_assets_year_end_includes_dwellings')])
    add('population', 'demo_pjan', {'sex': 'T', 'age': 'TOTAL', 'unit': 'NR'},
        [('population_january1', {}, 'PERSONS', 1, 'population_on_January_1_not_annual_average')])
    result.append(dict(id='bp_debt_interest', provider='Banco de Portugal',
                       dataset='28/e2bc3b33d169f2d0885cffb9183fb48e',
                       url=BPSTAT+'domains/28/datasets/e2bc3b33d169f2d0885cffb9183fb48e/?lang=EN&series_ids=13169604',
                       time_dimension='reference_date',
                       series=[dict(concept='apparent_debt_interest_rate', dimensions={},
                                    bp_series_id=13169604,
                                    unit='FRACTION', multiplier='.01',
                                    basis='published_implicit_annual_rate_not_market_borrowing_offer')]))
    result.append(dict(id='ecb_policy_rate', provider='European Central Bank', dataset='FM',
                       format='ECB_CSV', time_dimension='TIME_PERIOD',
                       url='https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.MRR_FR.LEV?'
                           +urlencode(dict(startPeriod=f'{first}-01-01', endPeriod=f'{last}-12-31', format='csvdata')),
                       series=[dict(concept='ecb_main_refinancing_rate', dimensions={},
                                    ecb_key='FM.D.U2.EUR.4F.KR.MRR_FR.LEV', unit='FRACTION', multiplier='.01',
                                    basis='ECB_euro_area_daily_rate_full_calendar_year_mean_derived_not_sovereign_yield')]))
    return result
