"""Build Russian technical report from saved outputs; no invented result values."""
import csv
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def rows(path):
    with (ROOT/path).open(encoding="utf-8",newline="") as f: return list(csv.DictReader(f))


def table(headers,data):
    return "| "+" | ".join(headers)+" |\n|"+"|".join("---" for _ in headers)+"|\n"+"\n".join("| "+" | ".join(map(str,row))+" |" for row in data)


def build():
    template=(ROOT/"docs/report_template_ru.md").read_text(encoding="utf-8")
    summary=rows("results/summary.csv"); cmp=rows("results/comparisons.csv")
    annual=rows("results/reform/annual.csv"); control=rows("results/controls/reform/annual.csv")
    last=annual[-1]; base=control[-1]
    final=next(x for x in cmp if x["scenario"]=="reform" and x["year"]==last["year"])
    headline=f"В базовом синтетическом варианте к {last['year']} году реальные располагаемые доходы семей выше контроля на {float(final['real_income_change_pct']):.2f}%, выпуск — на {float(final['gdp_real_change_pct']):.2f}%, а доля занятости — на {float(final['employment_change_pp']):.2f} п.п. Инфляция при этом **выше**, а не ниже контроля, на {float(final['inflation_change_pp']):.2f} п.п. Долг составляет {100*float(last['debt_gdp']):.2f}% ВВП против {100*float(base['debt_gdp']):.2f}% без реформы; относительно исходных 60% он всё равно растёт. Эти значения характеризуют только выбранные допущения."
    scen=table(["Сценарий","Успешно записанные годы","Статус","Не покрытый разрыв, млн CU"],[(r["scenario"],r["completed_years"],r["status"],f"{float(r['funding_gap'])/1e6:.2f}"+(f" в {r['failure_year']}" if r["failure_year"] else "")) for r in summary])
    compar=table(["Сценарий, 2036","Реальный ВВП, % к контролю","Реальные доходы, %","Инфляция, п.п.","Занятость, п.п."],[(r["scenario"],*[f"{float(r[k]):+.3f}" for k in ("gdp_real_change_pct","real_income_change_pct","inflation_change_pp","employment_change_pp")]) for r in cmp if r["year"]=="2036" and r["scenario"]!="baseline"])
    groups=rows("results/reform/groups.csv"); bgroups=rows("results/controls/reform/groups.csv")
    gtable=table(["Группа, 2036","Реальный доход на семью, CU/год","Разница к контролю, %"],[(r["group"],f"{float(r['real_disposable_mean']):.2f}",f"{100*(float(r['real_disposable_mean'])/float(next(b for b in bgroups if b['group']==r['group'] and b['year']==r['year'])['real_disposable_mean'])-1):+.2f}") for r in groups if r["year"]=="2036"])
    a=annual[0]
    ftable=table(["Поток программы, 2027","Млн текущих CU/год"],[(name,f"{float(a[key])/1e6:.3f}") for name,key in (("Ресурс из прежнего пула","funding"),("Надбавки семьям","income_fund"),("Страховой клиринг, внутренний перевод","social_clearing"),("Администрирование","admin"),("Проекты","investment"),("Пополнение резерва, актив","deposit"),("Возврат казначейству","return_to_treasury"))])
    sens=rows("sensitivity/sensitivity.csv")
    sensitivity="В девяти точках сетки разница реального выпуска к контролю в 2036 году находится от {:.3f}% до {:.3f}%, реального дохода — от {:.3f}% до {:.3f}%, инфляции — от +{:.3f} до +{:.3f} п.п. Все эти разницы инфляции положительны. Разброс сетки не является доверительным интервалом; чувствительность к другим коэффициентам и seed этим не исчерпывается.".format(*[fun(float(r[key]) for r in sens) for key in ("gdp_real_change_pct","real_income_change_pct","inflation_change_pp") for fun in (min,max)])
    receipt=ROOT/"verification/receipt.json"
    if receipt.exists():
        v=json.loads(receipt.read_text(encoding="utf-8"))
        n=v['tests']['run']; noun="тестов" if 11<=n%100<=14 else "тест" if n%10==1 else "теста" if n%10 in (2,3,4) else "тестов"
        verification=f"**Проверено: {n} {noun}, ошибок {v['tests']['errors']}, провалов {v['tests']['failures']}.** Независимый CSV-аудит выполнил {v['csv_audit']['independent_numeric_checks']} численных сверок по {v['csv_audit']['household_rows']} семейным строкам; максимальный абсолютный остаток — {v['csv_audit']['max_absolute_residual_CU']:.8f} CU при допуске 0.0001 CU. Повторный полный прогон без site-packages сравнен по {v['reproducibility']['matched_files']} численным CSV и JSON-конфигурациям: {v['reproducibility']['status']}. Проверенная среда: Python {v['python']}. Протоколы находятся в папке `verification/`."
    else:
        raise RuntimeError("Verification receipt required before final report")
    for key,value in dict(headline=headline,scenario_table=scen,comparison_table=compar,group_table=gtable,funding_table=ftable,sensitivity=sensitivity,verification=verification).items(): template=template.replace("{{"+key+"}}",value)
    if "{{" in template: raise RuntimeError("unresolved template marker")
    (ROOT/"docs/technical_report_ru.md").write_text(template,encoding="utf-8",newline="\n")


if __name__=="__main__": build()
