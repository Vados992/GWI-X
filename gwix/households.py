"""Agent microsimulation. Money per household/year; weights expand to a nation."""
from dataclasses import dataclass, replace
import hashlib
import random
import math


@dataclass(frozen=True)
class Person:
    id: str
    wage_real_hour: float
    hours_year: float
    employed: bool
    labor_eligible: bool = True
    kind: str = "employee"


@dataclass(frozen=True)
class Household:
    id: str
    group: str
    people: tuple
    children: int
    weight: float
    verified: bool = True


def draw(seed, year, identity, event):
    """Common random numbers: independent of run order and policy admissions."""
    b = f"{seed}|{year}|{identity}|{event}".encode()
    return int.from_bytes(hashlib.sha256(b).digest()[:8],"big") / 2**64


def generate(c):
    r = random.Random(c["seed"])
    groups = ("single","couple_children","single_parent","self_employed","disability","retired")
    hs=[]
    for i in range(c["households"]):
        g = groups[i % len(groups)]
        adults = 2 if g in ("couple_children","retired") else 1
        ps=[]
        for a in range(adults):
            eligible=g not in ("retired","disability")
            ps.append(Person(f"P{i:05d}-{a}",round(r.uniform(9,36),2),r.choice((1040,1560,2080)),eligible and r.random()<0.87,eligible,"self_employed" if g=="self_employed" else "employee"))
        hs.append(Household(f"H{i:05d}",g,tuple(ps),2 if g=="couple_children" else int(g=="single_parent"),c["population_households"]/c["households"]))
    validate_population(hs)
    return hs


def validate_population(hs):
    ids=set(); pids=set()
    for h in hs:
        if h.id in ids or not math.isfinite(h.weight) or h.weight <= 0: raise ValueError("duplicate household or invalid weight")
        ids.add(h.id)
        for p in h.people:
            if p.id in pids: raise ValueError("person counted in multiple households")
            pids.add(p.id)
            if not math.isfinite(p.wage_real_hour) or not math.isfinite(p.hours_year) or p.wage_real_hour < 0 or not 0 <= p.hours_year <= 2500:
                raise ValueError("unverified earnings or impossible hours")
            if p.employed and not p.labor_eligible: raise ValueError("ineligible employment")


def check_contract(old, new, documented_reason=False):
    """Reject a proposed unreviewed wage/hours substitution, never alter wages."""
    if old.id != new.id: raise ValueError("identity changed")
    if not documented_reason and (new.wage_real_hour < old.wage_real_hour or new.hours_year < old.hours_year):
        raise ValueError("REVIEW_REQUIRED: wage/hours reduction; subsidy substitution risk")


def tax(gross,p,h):
    bounds=[0.0]+[b*p for b in h["tax_thresholds_real"]]+[float("inf")]
    return sum(max(0.0,min(gross,bounds[i+1])-bounds[i])*rate for i,rate in enumerate(h["tax_rates"]))


def calculate(hh, c, price=1.0, wage_index=1.0, admitted=False, earnings_override=None):
    if not math.isfinite(price) or price<=0 or not math.isfinite(wage_index) or wage_index<=0:
        raise ValueError("positive finite price/wage index required")
    h=c["household"]
    gross=[]; taxes=[]; contributions=[]; reliefs=[]; tops=[]
    for i,p in enumerate(hh.people):
        g=p.wage_real_hour*p.hours_year*price*wage_index if p.employed else 0.0
        if earnings_override is not None and i in earnings_override: g=earnings_override[i]
        if not math.isfinite(g) or g < 0: raise ValueError("negative/nonfinite earnings")
        eligible=admitted and hh.verified and p.employed and p.labor_eligible
        relief=min(g,h["relief_earnings_cap_real"]*price)*h["contribution_relief"] if eligible else 0.0
        top=min(1,g/(h["topup_phasein_real"]*price))*max(0,h["topup_max_real"]*price-h["topup_taper"]*max(0,g-h["topup_taper_start_real"]*price)) if eligible else 0.0
        gross.append(g); taxes.append(tax(g,price,h)); contributions.append(g*h["employee_contribution"]-relief); reliefs.append(relief); tops.append(top)
    g=sum(gross); it=sum(taxes); sc=sum(contributions)
    pension=len(hh.people)*h["pension_real"]*price if hh.group=="retired" else 0.0
    disability=h["disability_real"]*price if hh.group=="disability" else 0.0
    child=hh.children*h["child_benefit_real"]*price
    # Coordinated means test uses pre-GWI income; GWI cannot cancel existing benefits.
    assess=max(0,g-it-g*h["employee_contribution"])+pension+disability
    assistance=max(0,h["assistance_real"]*price-h["assistance_taper"]*assess)
    top=min(sum(tops),h["household_topup_cap_real"]*price)
    benefit=pension+disability+child+assistance
    net=g-it-sc+benefit+top
    employer=sum(v*(1+h["employer_contribution"]) for p,v in zip(hh.people,gross) if p.kind=="employee")
    employer_sc=sum(v*h["employer_contribution"] for p,v in zip(hh.people,gross) if p.kind=="employee")
    # Self-employed pay an analogous business contribution, separate from employer costs.
    business_sc=sum(v*h["employer_contribution"] for p,v in zip(hh.people,gross) if p.kind=="self_employed")
    net-=business_sc
    return dict(gross=g,income_tax=it,employee_sc=sc,employer_sc=employer_sc,business_sc=business_sc,clearing=sum(reliefs),topup=top,benefits=benefit,pension=pension,disability=disability,child=child,assistance=assistance,disposable=net,real_disposable=net/price,employer_cost=employer,earnings=gross)


def emtr_adults(hh,c,price=1.0,wage_index=1.0,admitted=False):
    """Forward differences on each adult separately; household policy held fixed."""
    r=calculate(hh,c,price,wage_index,admitted)
    d=c["household"]["emtr_step_real"]*price
    result=[]
    for k,p in enumerate(hh.people):
        if not p.employed:
            result.append(None); continue
        up=calculate(hh,c,price,wage_index,admitted,{k:r["earnings"][k]+d})
        result.append(1-(up["disposable"]-r["disposable"])/d)
    return result


def emtr(hh,c,price=1.0,wage_index=1.0,admitted=False):
    """Worst marginal rate among employed adults; no worker => undefined."""
    return max((x for x in emtr_adults(hh,c,price,wage_index,admitted) if x is not None),default=None)


def transition(hs,c,year,gap,incentive,labor_shock):
    m=c["macro"]
    clamp=lambda v:max(0,min(1,v))
    sep=clamp(m["separation_rate"]-0.15*gap+labor_shock)
    find=clamp(m["job_finding_rate"]+m["labor_gap_sensitivity"]*gap+m["incentive_sensitivity"]*(incentive-0.65))
    result=[]
    for h in hs:
        people=[]
        barrier=0.7 if h.group=="single_parent" else 1.0
        for p in h.people:
            employed=p.employed
            u=draw(c["seed"],year,p.id,"employment")
            if p.labor_eligible: employed=u>=sep if p.employed else u<find*barrier
            people.append(replace(p,employed=employed))
        result.append(replace(h,people=tuple(people)))
    return result


def summarize(hs,rows):
    keys=("gross","income_tax","employee_sc","employer_sc","business_sc","clearing","topup","benefits","pension","disability","child","assistance","disposable","real_disposable","employer_cost")
    result={k:sum(h.weight*r[k] for h,r in zip(hs,rows)) for k in keys}
    result["employment"]=sum(h.weight*sum(p.employed for p in h.people) for h in hs)
    result["labor_force"]=sum(h.weight*sum(p.labor_eligible for p in h.people) for h in hs)
    result["employment_rate"]=result["employment"]/result["labor_force"]
    return result
