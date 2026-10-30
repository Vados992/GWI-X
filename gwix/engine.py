"""Coupling, timing, policy gates, diagnostics; no payments or external systems."""
from dataclasses import dataclass, field
import copy
import math
from .config import validate
from .households import generate, transition, calculate, summarize, emtr, emtr_adults
from .fiscal import PublicState, FundingShortfall, allocate, max_cost_real
from .fiscal import settle as settle_public
from .macro import initial, advance


@dataclass
class Result:
    name: str
    status: str = "complete"
    annual: list = field(default_factory=list)
    households: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    failure: dict = field(default_factory=dict)


def run(c,reference=None):
    validate(c)
    c=copy.deepcopy(c)
    result=Result(c["scenario"]["name"])
    hs=generate(c)
    f,m=c["fiscal"],c["macro"]
    macro=initial(c)
    public=PublicState(f["initial_debt"],f["initial_reserve"],f["initial_treasury"])
    admitted=set()
    if c["scenario"]["reform"]:
        candidates=[h for h in hs if any(p.labor_eligible for p in h.people)]
        admitted={h.id for h in candidates[:int(len(candidates)*f["initial_admission_share"]) ]}
    initial_rows=[calculate(h,c) for h in hs]
    initial_total=summarize(hs,initial_rows)
    C0=initial_total["disposable"]*c["household"]["consumption_propensity"]
    external_anchor=m["gdp_real_initial"]-C0-m["investment_gdp_share"]*m["gdp_real_initial"]-f["government_consumption_real"]
    if external_anchor<=0: raise ValueError("initial GDP decomposition requires positive other demand")
    for t in range(c["years"]):
        year=c["start_year"]+t
        try:
            if t>0:
                hs=transition(hs,c,year,macro.gap,macro.incentive,c["scenario"]["labor_shocks"][t-1])
            p=macro.price
            gates={"debt":public.debt/(macro.gdp*p)<=f["debt_gate_ratio"],"inflation":True,"employment":True,"real_income":True}
            floor=f["funding_real"]*min(c["scenario"]["funding_multipliers"][t:])
            gates["multiyear"]=floor+1e-5>=sum(max_cost_real(h,c) for h in hs if h.id in admitted)
            if t>0 and reference is not None:
                if len(reference.annual)<t:
                    gates.update(inflation=False,employment=False,real_income=False)
                else:
                    a,b=result.annual[-1],reference.annual[t-1]
                    gates["inflation"]=a["inflation_next"]-b["inflation_next"]<=m["inflation_gate_increment"]
                    gates["employment"]=a["employment_rate"]-b["employment_rate"]>=-m["employment_gate_loss"]
                    gates["real_income"]=all(next(x for x in result.groups if x["year"]==a["year"] and x["group"]==g)["real_disposable_mean"] >= (1-m["real_income_gate_loss"])*next(x for x in reference.groups if x["year"]==b["year"] and x["group"]==g)["real_disposable_mean"] for g in {h.group for h in hs})
            elif c["scenario"]["reform"] and reference is None:
                # No missing counterfactual may be interpreted as a passing risk gate.
                gates.update(inflation=False,employment=False,real_income=False)
            rows,next_admitted,program=allocate(hs,c,t,p,macro.wage_index,admitted,public.reserve,gates)
            total=summarize(hs,rows)
            rates=[emtr(h,c,p,macro.wage_index,h.id in next_admitted) for h in hs]
            labor_weights=[h.weight for h,r in zip(hs,rates) if r is not None]
            incentive=sum(h.weight*(1-r) for h,r in zip(hs,rates) if r is not None)/sum(labor_weights) if labor_weights else 0.0
            C=total["disposable"]*c["household"]["consumption_propensity"]
            gov_real=f["government_consumption_real"]*macro.productivity
            legacy=f["subsidy_pool_real"]*p-program["funding"]
            next_macro,mv=advance(macro,c,t,C,program["investment"],gov_real,legacy,external_anchor,incentive)
            vat=C*f["vat_rate"]/(1+f["vat_rate"])
            other_tax=f["other_tax_gdp_rate"]*mv["gdp_nominal"]
            revenue=total["income_tax"]+total["employee_sc"]+total["employer_sc"]+total["business_sc"]+vat+other_tax
            interest_rate=max(0,f["interest_rate"]+c["scenario"]["interest_shocks"][t]+0.02*max(0,public.debt/(macro.gdp*p)-f["debt_gate_ratio"]))
            interest=public.debt*interest_rate
            # Clearing is an internal transfer; it is not expenditure twice.
            expense=gov_real*p+legacy+total["benefits"]+interest+program["income_fund"]+program["investment"]+program["admin"]
            next_public,fv=settle_public(public,c,p,mv["gdp_nominal"],revenue,expense,program["reserve_close"])
            annual=dict(scenario=result.name,year=year,data_status="SYNTHETIC",**mv,**program,**fv,revenue=revenue,expenditure=expense,interest=interest,interest_rate=interest_rate,vat=vat,other_tax=other_tax,legacy_subsidy=legacy,government_consumption_nominal=gov_real*p,debt_open=public.debt,debt_close=next_public.debt,debt_gdp=next_public.debt/mv["gdp_nominal"],reserve_open=public.reserve,treasury_open=public.treasury,treasury_close=next_public.treasury,admitted_households=sum(h.weight for h in hs if h.id in next_admitted),gate_reasons="|".join(k for k,v in gates.items() if not v) or "OPEN",emtr_max=max((r for r in rates if r is not None),default=0),emtr_weighted=sum(h.weight*r for h,r in zip(hs,rates) if r is not None)/sum(labor_weights) if labor_weights else None,emtr_above_gate_households=sum(h.weight for h,r in zip(hs,rates) if r is not None and r>c["household"]["emtr_gate"]),**{"hh_"+k:v for k,v in total.items()})
            annual["employment_rate"]=total["employment_rate"]
            annual["labor_productivity_real_per_worker"]=mv["gdp_real"]/total["employment"] if total["employment"] else None
            annual.update({"gate_"+k:int(v) for k,v in gates.items()})
            annual["primary_balance"]=revenue-expense+interest
            annual["general_account_residual"]=(gov_real*p+legacy+total["benefits"]+interest+program["funding"]-revenue-program["social_clearing"]-program["return_to_treasury"])-(expense+next_public.reserve-public.reserve-revenue)
            assert_invariants(annual)
            micro=[]
            for h,r,rate in zip(hs,rows,rates):
                adult_rates=emtr_adults(h,c,p,macro.wage_index,h.id in next_admitted)
                micro.append(dict(scenario=result.name,year=year,data_status="SYNTHETIC",household_id=h.id,group=h.group,weight=h.weight,adults=len(h.people),children=h.children,employed=sum(p.employed for p in h.people),labor_eligible=sum(p.labor_eligible for p in h.people),admitted=int(h.id in next_admitted),emtr=rate,emtr_adults=";".join("NA" if x is None else str(x) for x in adult_rates),**{k:v for k,v in r.items() if k!="earnings"}))
            grouped=[]
            for group in sorted({h.group for h in hs}):
                rs=[r for r in micro if r["group"]==group]
                weight=sum(r["weight"] for r in rs)
                grouped.append(dict(scenario=result.name,year=year,data_status="SYNTHETIC",group=group,households=weight,real_disposable_mean=sum(r["real_disposable"]*r["weight"] for r in rs)/weight,nominal_disposable_mean=sum(r["disposable"]*r["weight"] for r in rs)/weight,employment=sum(r["employed"]*r["weight"] for r in rs),topup=sum(r["topup"]*r["weight"] for r in rs)))
            # Commit an entire year only after every constraint and financing check.
            result.annual.append(annual); result.households.extend(micro); result.groups.extend(grouped)
            public,macro,admitted=next_public,next_macro,next_admitted
        except FundingShortfall as e:
            result.status="blocked_unfunded"
            result.failure=dict(year=year,kind=e.kind,required=e.required,available=e.available,gap=e.gap,explanation="No transactions committed for failed year; no automatic cancellation or monetary financing.")
            break
        except ValueError as e:
            result.status="outside_model_domain"
            result.failure=dict(year=year,explanation=str(e))
            break
    return result


def assert_invariants(a):
    tol=1e-4
    for k in ("cash_residual","programme_residual","gdp_identity_residual","general_account_residual"):
        if abs(a[k])>tol: raise AssertionError((k,a[k]))
    for k in ("debt_close","reserve_close","treasury_close","hh_disposable","hh_employee_sc","income_fund","social_clearing","investment"):
        if a[k]<-tol or not math.isfinite(a[k]): raise AssertionError((k,a[k]))
    if not 0<=a["employment_rate"]<=1: raise AssertionError("employment range")
    if a["withdrawal"]>a["reserve_open"]+tol: raise AssertionError("reserve overdraft")
    if a["hh_clearing"]!=a["social_clearing"]: raise AssertionError("social clearing mismatch")


def paired(c):
    reference=copy.deepcopy(c)
    reference["scenario"]["reform"]=False
    reference["scenario"]["name"]+="_control"
    baseline=run(reference)
    return run(c,baseline),baseline
