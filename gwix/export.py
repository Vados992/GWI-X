"""Stable CSV/JSON outputs, file hashes and deterministic input receipts."""
import csv
import hashlib
import json
import platform
from pathlib import Path
from .households import generate


def json_write(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


def csv_write(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if not rows: return
    with path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def result_write(root,result,c):
    root=Path(root)
    csv_write(root/"annual.csv",result.annual)
    csv_write(root/"households.csv",result.households)
    csv_write(root/"groups.csv",result.groups)
    funds=[]
    for a in result.annual:
        for account,amount in (("income_fund",a["income_fund"]),("social_insurance_clearing_INTERNAL",a["social_clearing"]),("productive_capacity_fund",a["investment"]),("administration",a["admin"]),("reserve_deposit_ASSET",a["deposit"]),("reserve_withdrawal_ASSET",a["withdrawal"]),("unspent_return_INTERNAL",a["return_to_treasury"])):
            funds.append(dict(scenario=result.name,year=a["year"],data_status="SYNTHETIC",account=account,nominal_CU=amount))
    csv_write(root/"funds.csv",funds)
    json_write(root/"status.json",dict(name=result.name,status=result.status,completed_years=len(result.annual),failure=result.failure))
    json_write(root/"resolved_config.json",c)


def input_write(root,c):
    rows=[]
    for h in generate(c):
        for p in h.people:
            rows.append(dict(data_status="SYNTHETIC",household_id=h.id,person_id=p.id,group=h.group,children=h.children,weight=h.weight,wage_real_CU_hour=p.wage_real_hour,hours_year=p.hours_year,employed=int(p.employed),labor_eligible=int(p.labor_eligible),kind=p.kind,verified=int(h.verified)))
    csv_write(Path(root)/"synthetic_households.csv",rows)
    json_write(Path(root)/"provenance.json",dict(data_status="SYNTHETIC",generator="gwix.households.generate",seed=c["seed"],households=c["households"],population_households=c["population_households"],country=None,currency="CU - fictional currency unit",national_observations_used=False,behavioral_parameters="illustrative assumptions, not estimates",architecture_source="User-supplied GWI-X v1.2 specification, 2026-10-29"))


def manifest(root):
    root=Path(root)
    excluded={"__pycache__",".venv",".git","results-local","releases","private-data"}
    entries={str(p.relative_to(root)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and p!=root/"manifest.json" and not excluded.intersection(p.relative_to(root).parts) and p.suffix!=".pyc"}
    label="SYNTHETIC_LAB_AND_SEPARATE_OFFICIAL_OBSERVATIONS" if (root/"data/official").exists() else "SYNTHETIC"
    json_write(root/"manifest.json",dict(data_status=label,python=platform.python_version(),algorithm="SHA-256",files=entries))


def compare(reform,control):
    rows=[]
    by_year={a["year"]:a for a in control.annual}
    for a in reform.annual:
        b=by_year.get(a["year"])
        if b is None: continue
        rows.append(dict(scenario=reform.name,year=a["year"],data_status="SYNTHETIC",gdp_real_change_pct=100*(a["gdp_real"]/b["gdp_real"]-1),real_income_change_pct=100*(a["hh_real_disposable"]/b["hh_real_disposable"]-1),inflation_change_pp=100*(a["inflation"]-b["inflation"]),employment_change_pp=100*(a["employment_rate"]-b["employment_rate"]),debt_gdp_change_pp=100*(a["debt_gdp"]-b["debt_gdp"])))
    return rows
