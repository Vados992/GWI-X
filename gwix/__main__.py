import argparse
import copy
import json
from pathlib import Path
from .config import load, scenario, NAMES
from .engine import paired
from .export import json_write, csv_write, result_write, input_write, compare, manifest
from .charts import charts


def main():
    parser=argparse.ArgumentParser(description="GWI-X v1.2 SYNTHETIC economic laboratory")
    parser.add_argument("command",choices=("run","all","sensitivity"))
    parser.add_argument("--config",default="configs/synthetic.json")
    parser.add_argument("--out",default="results")
    parser.add_argument("--scenario",choices=NAMES,default="reform")
    args=parser.parse_args()
    c=load(args.config); out=Path(args.out)
    if out.exists() and any(out.iterdir()):
        parser.error("Choose a new empty output folder; existing results are never overwritten")
    out.mkdir(parents=True,exist_ok=True)
    if args.command=="sensitivity":
        rows=[]
        for efficiency in (0,.6,.9):
            for phillips in (.06,.12,.24):
                cfg=copy.deepcopy(c)
                cfg["macro"]["public_investment_efficiency"]=efficiency
                cfg["macro"]["phillips_slope"]=phillips
                r,b=paired(cfg); cmp=compare(r,b)
                rows.append(dict(data_status="SYNTHETIC",efficiency=efficiency,phillips_slope=phillips,status=r.status,completed_years=len(r.annual),**({k:v for k,v in cmp[-1].items() if k not in ("scenario","data_status")} if cmp else {})))
                print(f"sensitivity efficiency={efficiency}, slope={phillips}: {r.status}",flush=True)
        csv_write(out/"sensitivity.csv",rows)
        json_write(out/"base_config.json",c)
        manifest(out)
        return 0
    results={}; summaries=[]; comparisons=[]
    input_write(out/"inputs",c)
    for name in (NAMES if args.command=="all" else (args.scenario,)):
        cfg=scenario(c,name)
        r,b=paired(cfg)
        results[name]=r
        result_write(out/name,r,cfg)
        control_cfg=copy.deepcopy(cfg); control_cfg["scenario"]["reform"]=False; control_cfg["scenario"]["name"]=b.name
        result_write(out/"controls"/name,b,control_cfg)
        cmp=compare(r,b); comparisons.extend(cmp)
        summaries.append(dict(scenario=name,data_status="SYNTHETIC",status=r.status,completed_years=len(r.annual),last_year=r.annual[-1]["year"] if r.annual else None,failure_year=r.failure.get("year"),funding_gap=r.failure.get("gap",0),last_debt_gdp=r.annual[-1]["debt_gdp"] if r.annual else None,control_status=b.status))
        print(f"{name}: {r.status}; {len(r.annual)}/{c['years']} financed years"+(f"; gap={r.failure['gap']:.2f} CU" if "gap" in r.failure else ""),flush=True)
    csv_write(out/"summary.csv",summaries)
    csv_write(out/"comparisons.csv",comparisons)
    if args.command=="all": charts(out/"charts",results,comparisons)
    json_write(out/"run_status.json",dict(data_status="SYNTHETIC",scenarios=summaries,policy="Failure scenarios are diagnostics, not successful ten-year projections."))
    manifest(out)
    # all is a diagnostic suite: blocked stresses are expected, persisted outcomes.
    if args.command=="run" and results[args.scenario].status!="complete": return 2
    return 0


if __name__=="__main__": raise SystemExit(main())
