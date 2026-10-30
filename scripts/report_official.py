"""Rebuild the Russian real-data addendum and its figures from published CSV."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gwix.charts import panel_chart

RESULTS = ROOT/'real-data/PT/2026-10-30-final'
SNAPSHOT = ROOT/'data/official/PT/2026-10-30-final'


def read(name):
    with (RESULTS/(name+'.csv')).open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    summary = json.loads((RESULTS/'validation.json').read_text())
    forecasts, accounts, incomes, debt = read('core_hindcast'), read('national_panel'), read('income_by_group'), read('debt_stock_flow')
    panels = []
    for heading, metric, unit in [('Real GDP growth', 'gdp_growth', '% year on year'),
                                  ('HICP inflation', 'hicp_inflation', '% annual average'),
                                  ('Unemployment, ages 15-74', 'unemployment_15_74', '% of labour force'),
                                  ('Private investment proxy', 'private_investment_volume_proxy', 'billion 2020 chain-volume EUR')]:
        selected = [r for r in forecasts if r['metric'] == metric]
        panels.append((heading, unit, [(name, [(int(r['year']), float(r[key])) for r in selected])
                                      for name, key in [('Official outcome', 'actual'), ('GWI-X core', 'core_prediction'), ('Naive baseline', 'naive_prediction')]]))
    footer = 'Official Portugal data | Latest-vintage diagnostics | No causal reform effect established | 30 Oct 2026'
    panel_chart(RESULTS/'charts/core_hindcast.svg', 'GWI-X | Portugal: actual outcomes and one-year core diagnostics', panels,
                '2019-2024; inputs stop at the preceding year; other core coefficients remain illustrative', footer, True)
    panels = [
        ('Government debt / GDP', '% of current-price GDP', [('Maastricht debt', [(int(r['year']), 100*float(r['debt_gdp_fraction'])) for r in accounts])]),
        ('Different price measures', '2020 = 100; separate concepts',
         [(name, [(int(r['year']), 100*float(r[key])) for r in accounts]) for name, key in [('HICP', 'hicp_2020_1'), ('GDP deflator', 'gdp_deflator_2020_1')]]),
        ('Median equivalised real income', 'thousand 2020 EUR; income reference year',
         [(title, [(int(r['income_reference_year']), float(r['real_eur_2020_equivalised'])/1000) for r in incomes
                   if r['group_or_statistic'] == group and r['real_eur_2020_equivalised']])
          for title, group in [('All persons', 'median_equivalised_income'), ('Single parent', 'median_equivalised_A1_DCH'), ('2 adults, 2 children', 'median_equivalised_A2_DCH2')]]),
        ('Debt change beyond ESA deficit', 'billion nominal EUR; implied residual', [('Stock-flow adjustment', [(int(r['year']), float(r['implied_stock_flow_adjustment_eur'])/1e9) for r in debt])]),
    ]
    panel_chart(RESULTS/'charts/official_accounts.svg', 'Portugal | Official budget, prices and published household income', panels,
                '2009-2025 aggregates; household groups overlap; stock-flow residual is not available programme funding', footer, True)
    labels = {'gdp_growth': 'Рост реального ВВП, п.п.', 'hicp_inflation': 'Инфляция HICP, п.п.',
              'unemployment_15_74': 'Безработица 15–74, п.п.', 'euro_area_policy_rate': 'Ставка ЕЦБ, п.п.',
              'private_investment_volume_proxy': 'Частные инвестиции: приближение, млрд EUR 2020',
              'net_fixed_capital_proxy': 'Чистый основной капитал: приближение, млрд EUR 2020'}
    table = '\n'.join(f"| {labels[r['metric']]} | {r['observations']} | {r['core_MAE']:.3f} | {r['naive_MAE']:.3f} | {'Ниже ориентира' if r['comparison']=='BEATS_NAIVE' else 'Выше ориентира'} |" for r in summary['kernel_metrics'])
    template = (ROOT/'docs/official_report_template_ru.md').read_text(encoding='utf-8')
    replacements = {'{{METRICS}}': table, '{{OBSERVED}}': str(summary['observed_values']), '{{MISSING}}': str(summary['explicit_missing']),
                    '{{SERIES}}': str(summary['series']), '{{QUERIES}}': str(summary['queries']), '{{SNAPSHOT}}': summary['snapshot_id']}
    for old, new in replacements.items(): template = template.replace(old, new)
    if '{{' in template: raise ValueError('Unresolved report placeholder')
    (ROOT/'docs/real_data_validation_ru.md').write_text(template, encoding='utf-8', newline='\n')
    print('Rebuilt official-data Russian addendum and two portable figures')


if __name__ == '__main__': main()
