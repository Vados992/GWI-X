"""Independent audit of exported values, without importing any model function."""
import argparse
import csv
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def audit(root):
    root=Path(root); checked=0; household_rows=0; maximum_error=0.0
    def close(a,b):
        nonlocal checked,maximum_error
        err=abs(a-b); maximum_error=max(maximum_error,err); checked+=1
        if err>1e-4: raise AssertionError((a,b,err))
    for path in sorted(root.rglob("annual.csv")):
        totals=defaultdict(lambda:defaultdict(float)); ids=set()
        with path.with_name("households.csv").open(encoding="utf-8",newline="") as f:
            for row in csv.DictReader(f):
                household_rows+=1
                identity=(row["year"],row["household_id"])
                if identity in ids: raise AssertionError("duplicate household-year")
                ids.add(identity)
                if row["data_status"]!="SYNTHETIC": raise AssertionError("missing label")
                weight=float(row["weight"])
                close(float(row["disposable"]),float(row["gross"])-float(row["income_tax"])-float(row["employee_sc"])-float(row["business_sc"])+float(row["benefits"])+float(row["topup"]))
                for k in ("gross","disposable","real_disposable","benefits","topup","clearing","employee_sc"):
                    totals[row["year"]][k]+=float(row[k])*weight
        previous=None
        with path.open(encoding="utf-8",newline="") as f:
            for row in csv.DictReader(f):
                v=lambda k:float(row[k])
                close(v("debt_close")-v("debt_open")-v("reserve_close")+v("reserve_open")-v("treasury_close")+v("treasury_open"),v("expenditure")-v("revenue"))
                close(v("funding")+v("withdrawal"),v("income_fund")+v("social_clearing")+v("investment")+v("admin")+v("deposit")+v("return_to_treasury"))
                close(v("gdp_real"),sum(v(k) for k in ("consumption_real","private_investment_real","public_investment_real","government_consumption_real","other_demand_real")))
                close(v("expenditure"),sum(v(k) for k in ("government_consumption_nominal","legacy_subsidy","hh_benefits","interest","income_fund","investment","admin")))
                for k,total in totals[row["year"]].items(): close(total,v("hh_"+k))
                if previous:
                    close(v("cpi")/float(previous["cpi"])-1,v("inflation"))
                    close(v("debt_open"),float(previous["debt_close"]))
                    close(v("reserve_open"),float(previous["reserve_close"]))
                if min(v("debt_close"),v("reserve_close"),v("treasury_close")) < -1e-5: raise AssertionError("negative stock")
                previous=row
        status=json.loads(path.with_name("status.json").read_text(encoding="utf-8"))
        if status["status"]!="complete":
            if previous and int(previous["year"])>=status["failure"]["year"]: raise AssertionError("failed year committed")
    receipt=dict(status="PASS",independent_numeric_checks=checked,household_rows=household_rows,max_absolute_residual_CU=maximum_error,tolerance_CU=1e-4)
    return receipt


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("root"); p.add_argument("--receipt")
    args=p.parse_args(); receipt=audit(args.root)
    text=json.dumps(receipt,indent=2)
    if args.receipt: Path(args.receipt).write_text(text+"\n",encoding="utf-8")
    print(text)
