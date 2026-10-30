"""Historical accounting checks and honest lag-only diagnostics of the actual core."""
import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics

from ..export import csv_write
from ..households import transition_rates
from ..macro import MacroState, advance
from .store import read_snapshot, write_json, database, SCHEMA

ROOT = Path(__file__).resolve().parents[2]
D = Decimal


class Observations:
    def __init__(self, rows):
        self.points = {}
        for row in rows:
            key = (row['concept'], row['period'])
            if key in self.points:
                raise ValueError('Duplicate concept/year')
            self.points[key] = row

    def get(self, concept, year, unit=None):
        point = self.points.get((concept, year))
        if point is None or point['value'] is None:
            return None
        if unit and point['unit'] != unit:
            raise ValueError('Unit mismatch for '+concept)
        return D(point['value'])

    def require(self, concept, year, unit=None):
        value = self.get(concept, year, unit)
        if value is None:
            raise ValueError(f'Missing official observation: {concept}/{year}')
        return value


def accounting(obs, profile):
    checks, debt = [], []
    for year in range(profile['first_year'], profile['last_year']+1):
        r, e, b = [obs.get(k, year, 'EUR') for k in ('revenue', 'expenditure', 'net_lending')]
        if all(v is not None for v in (r, e, b)):
            residual = r-e-b
            # Three independently rounded series at 0.1 million EUR precision.
            checks.append(dict(year=year, check='ESA_budget_balance', residual_eur=residual,
                               tolerance_eur=150000, status='PASS' if abs(residual) <= 150000 else 'FAIL'))
        else:
            checks.append(dict(year=year, check='ESA_budget_balance', residual_eur=None,
                               tolerance_eur=150000, status='MISSING'))
        names = ['gdp_nominal', 'household_consumption_nominal', 'government_consumption_nominal',
                 'gfcf_nominal', 'inventories_valuables_nominal', 'exports_nominal',
                 'imports_nominal', 'expenditure_discrepancy_nominal']
        vals = [obs.get(k, year, 'EUR') for k in names]
        if all(v is not None for v in vals):
            y, c, g, i, inventory, x, im, discrepancy = vals
            residual = y-(c+g+i+inventory+x-im+discrepancy)
            checks.append(dict(year=year, check='nominal_GDP_expenditure', residual_eur=residual,
                               tolerance_eur=400000, status='PASS' if abs(residual) <= 400000 else 'FAIL'))
        else:
            checks.append(dict(year=year, check='nominal_GDP_expenditure', residual_eur=None,
                               tolerance_eur=400000, status='MISSING'))
        opening, closing = obs.get('debt', year-1, 'EUR'), obs.get('debt', year, 'EUR')
        if all(v is not None for v in (opening, closing, b)):
            # This is an observed residual, NOT cash or an authorised funding source.
            adjustment = closing-opening+b
            debt.append(dict(year=year, debt_open_eur=opening, debt_close_eur=closing,
                             deficit_ESA_eur=-b, debt_change_eur=closing-opening,
                             implied_stock_flow_adjustment_eur=adjustment,
                             cash_bridge_status='REQUIRES_FINANCIAL_ACCOUNTS_AND_CASH_BRIDGE',
                             programme_funding_eur=None))
    return checks, debt


def panels(obs, profile):
    national, incomes = [], []
    concepts = ['gdp_nominal', 'gdp_real', 'revenue', 'expenditure', 'net_lending', 'debt',
                'interest_accrued', 'social_benefits_cash', 'social_contributions', 'public_gfcf_nominal',
                'subsidies_paid', 'household_income_tax', 'hicp_index', 'hicp_inflation',
                'employment_rate_20_64', 'employed_20_64', 'unemployment_rate_15_74',
                'household_gross_disposable', 'net_fixed_capital', 'gfcf_real',
                'labour_productivity_hour', 'labour_productivity_person',
                'population_january1', 'apparent_debt_interest_rate', 'ecb_main_refinancing_rate']
    base_price = obs.require('hicp_index', profile['real_price_reference_year'])
    income_names = ['median_equivalised_income', 'mean_equivalised_income',
                    'median_equivalised_A1', 'median_equivalised_A1_DCH',
                    'median_equivalised_A2_DCH2', 'median_equivalised_A1_GE65']
    for year in range(profile['first_year'], profile['last_year']+1):
        row = dict(year=year, country='PT', data_status='OFFICIAL_PUBLISHED_STATISTICS')
        row.update({key: obs.get(key, year) for key in concepts})
        y, real = row['gdp_nominal'], row['gdp_real']
        row['gdp_deflator_2020_1'] = y/real if y is not None and real else None
        row['hicp_2020_1'] = row['hicp_index']/base_price if row['hicp_index'] else None
        row['debt_gdp_fraction'] = row['debt']/y if row['debt'] is not None and y else None
        national.append(row)
        for name in income_names:
            value = obs.get(name, year)
            income_year = year-1
            price = obs.get('hicp_index', income_year)
            incomes.append(dict(survey_year=year, income_reference_year=income_year,
                                group_or_statistic=name, nominal_eur_equivalised=value,
                                hicp_income_year=price,
                                real_eur_2020_equivalised=value*base_price/price if value is not None and price else None,
                                data_status='OFFICIAL_STATISTIC_DERIVED_REAL_VALUE',
                                population_inference='Published equivalised statistic; not individual household records',
                                missing_reason='' if value is not None and price else 'Missing income or matching income-year HICP'))
    return national, incomes


def core_diagnostics(obs, profile, core_config):
    """Latest-vintage, lag-only one-step hindcast, not a counterfactual policy run.

    Only the private-investment share is estimated, using years <= training_end.
    Other core coefficients remain the published illustrative assumptions.
    State resets to the observed previous year for each prediction; no ten-year fit.
    """
    train_end = profile['training_end']
    c = copy.deepcopy(core_config)
    c['scenario'] = {key: [0.0] for key in ('supply_shocks', 'demand_shocks', 'inflation_shocks')}
    c['fiscal']['subsidy_pool_real'] = 0.0  # Reform/subsidy channel disabled in this diagnostic.
    y0 = float(obs.require('gdp_real', train_end, 'EUR2020_CHAIN'))
    k0 = float(obs.require('net_fixed_capital', train_end, 'EUR2020_CHAIN'))
    m = c['macro']
    m['gdp_real_initial'], m['capital_real_initial'] = y0, k0
    shares, training_years = [], []
    for year in range(profile['first_year']+1, train_end+1):
        real = obs.require('gdp_real', year)
        nominal = obs.require('gdp_nominal', year)
        public = obs.require('public_gfcf_nominal', year)*real/nominal
        private = obs.require('gfcf_real', year)-public
        shares.append(float(private/real))
        training_years.append(year)
    m['investment_gdp_share'] = statistics.fmean(shares)
    external = y0-float(obs.require('household_consumption_real', train_end))-float(obs.require('government_consumption_real', train_end))-float(obs.require('gfcf_real', train_end))
    parameter_record = dict(training_years=training_years, training_end=train_end,
                            evaluation_start=profile['evaluation_start'], latest_vintage=True,
                            original_core_sha256=hashlib.sha256(json.dumps(core_config, sort_keys=True).encode()).hexdigest(),
                            estimated_parameters={'investment_gdp_share': m['investment_gdp_share']},
                            external_anchor_eur2020=external,
                            external_anchor_definition='2018 chain-volume remainder Y-C-G-GFCF; includes nonadditivity, inventories and net exports; NOT observed NX',
                            assumptions={'other_macro_coefficients': 'unchanged illustrative v1.2 assumptions',
                                         'capital_mapping': 'observed net fixed assets including dwellings, proxy for model productive capital',
                                         'public_investment_volume': 'nominal government GFCF / previous-year GDP deflator; proxy',
                                         'potential': 'previous observed GDP; gap initialized to zero',
                                         'incentive': 'neutral 0.65; household tax incentives unobserved',
                                         'price_state': '1, because demand inputs are already in 2020 chain-volume euros',
                                         'consumption_and_government': 'previous-year official volumes held constant for one-year prediction',
                                         'labour': 'aggregate expected core transition at neutral gap/incentive; fixed previous labour force',
                                         'productivity': 'labour-productivity observations are retained, never relabelled TFP'},
                            diagnostic_config=c)
    forecasts, omissions = [], []
    for year in range(profile['evaluation_start'], profile['last_year']+1):
        prev = year-1
        needed = [('gdp_real', prev), ('net_fixed_capital', prev), ('hicp_inflation', prev),
                  ('household_consumption_real', prev), ('government_consumption_real', prev),
                  ('public_gfcf_nominal', prev), ('gdp_nominal', prev), ('gdp_real', year),
                  ('hicp_inflation', year), ('gfcf_real', year), ('public_gfcf_nominal', year), ('gdp_nominal', year)]
        missing = [f'{key}/{t}' for key, t in needed if obs.get(key, t) is None]
        if missing:
            omissions.append(dict(year=year, status='NOT_EVALUATED_MISSING_OFFICIAL_INPUT', missing=missing))
            continue
        prev_y = float(obs.require('gdp_real', prev))
        prev_k = float(obs.require('net_fixed_capital', prev))
        prev_pi = float(obs.require('hicp_inflation', prev))
        productivity = (prev_y/y0)/(prev_k/k0)**m['capital_share']
        state = MacroState(1.0, prev_pi, prev_k, productivity, 1.0, prev_y, 0.0, .65)
        prev_public = float(obs.require('public_gfcf_nominal', prev)*obs.require('gdp_real', prev)/obs.require('gdp_nominal', prev))
        try:
            next_state, calculated = advance(state, c, 0,
                float(obs.require('household_consumption_real', prev)), prev_public,
                float(obs.require('government_consumption_real', prev)), 0.0, external, .65)
        except ValueError as exc:
            omissions.append(dict(year=year, status='CORE_DOMAIN_FAILURE', reason=str(exc)))
            continue
        actual_y = float(obs.require('gdp_real', year))
        actual_public = float(obs.require('public_gfcf_nominal', year)*obs.require('gdp_real', year)/obs.require('gdp_nominal', year))
        actual_private = float(obs.require('gfcf_real', year))-actual_public
        prev_private = float(obs.require('gfcf_real', prev))-prev_public
        points = [
            ('gdp_growth', 'percentage_points', 100*(actual_y/prev_y-1),
             100*(calculated['gdp_real']/prev_y-1), 0.0),
            ('hicp_inflation', 'percentage_points', 100*float(obs.require('hicp_inflation', year)),
             100*next_state.inflation, 100*prev_pi),
            ('private_investment_volume_proxy', 'billion_EUR2020', actual_private/1e9,
             calculated['private_investment_real']/1e9, prev_private/1e9),
        ]
        actual_k = obs.get('net_fixed_capital', year)
        if actual_k is not None:
            points.append(('net_fixed_capital_proxy', 'billion_EUR2020', float(actual_k)/1e9, next_state.capital/1e9, prev_k/1e9))
        u0, u1 = obs.get('unemployment_rate_15_74', prev), obs.get('unemployment_rate_15_74', year)
        if u0 is not None and u1 is not None:
            sep, find = transition_rates(c, 0.0, .65, 0.0)
            predicted_unemployment = float(u0)*(1-find)+(1-float(u0))*sep
            points.append(('unemployment_15_74', 'percentage_points', 100*float(u1),
                           100*predicted_unemployment, 100*float(u0)))
        rate0, rate1 = obs.get('ecb_main_refinancing_rate', prev), obs.get('ecb_main_refinancing_rate', year)
        if rate0 is not None and rate1 is not None:
            points.append(('euro_area_policy_rate', 'percentage_points', 100*float(rate1),
                           100*calculated['policy_rate'], 100*float(rate0)))
        for metric, unit, actual, predicted, naive in points:
            forecasts.append(dict(year=year, input_last_year=prev, metric=metric, unit=unit,
                                  actual=actual, core_prediction=predicted, naive_prediction=naive,
                                  core_error=predicted-actual, naive_error=naive-actual,
                                  data_status='MODEL_DIAGNOSTIC_ON_OFFICIAL_AGGREGATES',
                                  prediction_type='latest-vintage_lag-only_one-year_hindcast_not_policy_effect'))
    scores = []
    for metric in sorted({r['metric'] for r in forecasts}):
        selected = [r for r in forecasts if r['metric'] == metric]
        mae = statistics.fmean(abs(r['core_error']) for r in selected)
        naive = statistics.fmean(abs(r['naive_error']) for r in selected)
        rmse = math.sqrt(statistics.fmean(r['core_error']**2 for r in selected))
        scores.append(dict(metric=metric, unit=selected[0]['unit'], observations=len(selected),
                           core_MAE=mae, naive_MAE=naive, core_RMSE=rmse,
                           comparison='BEATS_NAIVE' if mae < naive else 'DOES_NOT_BEAT_NAIVE',
                           interpretation='Small latest-vintage diagnostic sample; no causal or general forecast validation'))
    return forecasts, scores, omissions, parameter_record


def readiness(profile, receipts):
    requirements = [
        ('official_aggregate_sources', all(r['status'] == 'OK' for r in receipts),
         'Open official aggregates fetched; see individual receipts'),
        ('observed_licensed_microdata', profile.get('licensed_observed_microdata_available') is True,
         'Real EU-SILC scientific-use files or a licensed national household survey; public EU-SILC files are synthetic'),
        ('national_tax_benefit_engine', profile.get('national_tax_benefit_rules_verified') is True,
         'Versioned Portuguese IRS, contributions, pension and benefit rules plus national benchmark comparisons'),
        ('programme_funding_authorisation', profile.get('funding_authorisation_eur') is not None,
         'Verified appropriation/reallocation and legal authority; subsidies D3PAY are not free programme funding'),
        ('programme_opening_reserve', profile.get('programme_opening_reserve_eur') is not None,
         'Verified liquid reserve owned by the programme; general-government deposits cannot be assumed available'),
        ('cash_accrual_bridge', False,
         'Government cash execution, financial accounts, debt repayment schedule and full stock-flow bridge'),
        ('empirical_behaviour_and_policy_validation', False,
         'Estimated behaviour, productive-capital mapping and validated structural effects; small hindcast is insufficient'),
    ]
    return dict(full_real_data_policy_run='BLOCKED', production='NO_GO',
                payments_executed=0, additional_programme_spending_eur=0,
                requirements=[dict(requirement=name, satisfied=bool(ok), reason=reason) for name, ok, reason in requirements],
                household_microsimulation='NOT_VALIDATED_ON_REAL_MICRODATA',
                why='Official aggregates cannot identify individual tax/benefit schedules or authorise GWI-X payments')


def validate_snapshot(snapshot, destination, core_config_path=ROOT/'configs/synthetic.json'):
    profile, receipts, rows, manifest = read_snapshot(snapshot)
    if any(r['status'] != 'OK' for r in receipts):
        raise ValueError('Incomplete official sources: inspect saved availability receipts; no synthetic fallback')
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    csv_write(out/'observations.csv', rows)
    database(snapshot, out/'official.sqlite')
    (out/'schema.sql').write_text(SCHEMA, encoding='utf-8', newline='\n')
    obs = Observations(rows)
    checks, debt = accounting(obs, profile)
    national, incomes = panels(obs, profile)
    core = json.loads(Path(core_config_path).read_text(encoding='utf-8'))
    forecasts, scores, omissions, parameters = core_diagnostics(obs, profile, core)
    for name, records in [('accounting_checks', checks), ('debt_stock_flow', debt),
                          ('national_panel', national), ('income_by_group', incomes),
                          ('core_hindcast', forecasts), ('core_metrics', scores)]:
        csv_write(out/(name+'.csv'), records)
    write_json(out/'core_parameters.json', parameters)
    write_json(out/'hindcast_omissions.json', omissions)
    readiness_result = readiness(profile, receipts)
    write_json(out/'readiness.json', readiness_result)
    quality = []
    for concept in sorted({r['concept'] for r in rows}):
        points = [r for r in rows if r['concept'] == concept]
        present = [r for r in points if r['value'] is not None]
        quality.append(dict(concept=concept, observed=len(present), missing=len(points)-len(present),
                            first_year=min((r['period'] for r in present), default=None),
                            last_year=max((r['period'] for r in present), default=None),
                            flagged_observations=sum(bool(r['source_flags']) for r in points),
                            unit=points[0]['unit'], basis=points[0]['basis']))
    csv_write(out/'coverage.csv', quality)
    summary = dict(snapshot_id=manifest['snapshot_id'], country='PT',
                   historical_period=[profile['first_year'], profile['last_year']],
                   fetched_sources=sum(r['status'] == 'OK' for r in receipts), queries=len(receipts),
                   observed_values=sum(r['value'] is not None for r in rows),
                   explicit_missing=sum(r['value'] is None for r in rows), series=len(quality),
                   accounting_checks=len(checks), accounting_passed=sum(r['status'] == 'PASS' for r in checks),
                   accounting_status='PASS' if all(r['status'] == 'PASS' for r in checks) else 'NEEDS_REVIEW',
                   source_status=manifest['status'], kernel_prediction_rows=len(forecasts),
                   kernel_metrics=scores, full_policy_run='BLOCKED', additional_spending_eur=0,
                   limits=['No licensed real household microdata', 'No validated national tax-benefit implementation',
                           'Accrual accounts and Maastricht debt are not a treasury cash ledger',
                           'No verified programme funding or reserve',
                           'Latest-vintage retrospective one-step checks, not real-time forecasts or causal reform evidence'])
    write_json(out/'validation.json', summary)
    return summary
