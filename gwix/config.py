"""Strict configuration: annual rates are fractions, all money in synthetic CU."""
import copy
import json
import math
from pathlib import Path


def load(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(cfg)
    return cfg


def validate(c):
    if c.get("label") != "SYNTHETIC / NOT A COUNTRY / NOT A FORECAST":
        raise ValueError("This release only accepts explicitly synthetic configuration")
    if not isinstance(c["years"], int) or not 1 <= c["years"] <= 100:
        raise ValueError("years must be an integer in [1,100]")
    if not isinstance(c["households"], int) or c["households"] < 20:
        raise ValueError("at least 20 synthetic households required")
    if c["population_households"] <= 0 or not isinstance(c["seed"], int):
        raise ValueError("invalid population or seed")
    def finite(x):
        if isinstance(x, dict):
            for v in x.values(): finite(v)
        elif isinstance(x, list):
            for v in x: finite(v)
        elif isinstance(x, (int,float)) and not isinstance(x, bool):
            if not math.isfinite(x): raise ValueError("nonfinite parameter")
    finite(c)
    f, h, m, s = (c[k] for k in ("fiscal","household","macro","scenario"))
    for k,v in f.items():
        if v < 0: raise ValueError("negative fiscal parameter: " + k)
    for k,v in h.items():
        if isinstance(v,(int,float)) and v < 0: raise ValueError("negative household parameter")
    rates = [h[k] for k in ("employee_contribution","employer_contribution","contribution_relief","topup_taper","assistance_taper","consumption_propensity","emtr_gate")] + h["tax_rates"]
    if any(not 0 <= v <= 1 for v in rates): raise ValueError("rate outside [0,1]")
    if h["contribution_relief"] > h["employee_contribution"]:
        raise ValueError("relief exceeds contributions")
    if len(h["tax_rates"]) != len(h["tax_thresholds_real"]) + 1:
        raise ValueError("tax band lengths")
    if sorted(set(h["tax_thresholds_real"])) != h["tax_thresholds_real"]:
        raise ValueError("tax thresholds must be strictly increasing")
    if min(h["topup_phasein_real"], h["emtr_step_real"]) <= 0:
        raise ValueError("positive phase-in and EMTR step required")
    for k in ("administration_share","investment_share","reserve_deposit_share","initial_admission_share"):
        if not 0 <= f[k] <= 1: raise ValueError("invalid allocation share")
    if f["investment_share"]+f["reserve_deposit_share"] > 1:
        raise ValueError("allocation shares exceed one")
    if f["funding_real"] > f["subsidy_pool_real"]:
        raise ValueError("reallocation exceeds existing subsidy pool")
    if f["debt_gate_ratio"] > f["debt_hard_ratio"]:
        raise ValueError("soft debt gate exceeds hard ceiling")
    for k in ("gdp_real_initial","capital_real_initial"):
        if m[k] <= 0: raise ValueError("positive macro stock required")
    for k in ("capital_share","depreciation","public_investment_efficiency","inflation_persistence","separation_rate","job_finding_rate"):
        if not 0 <= m[k] <= 1: raise ValueError("macro fraction outside [0,1]")
    if min(m["inflation_initial"],m["inflation_target"]) <= -0.95:
        raise ValueError("invalid inflation")
    for k in ("funding_multipliers","demand_shocks","supply_shocks","inflation_shocks","labor_shocks","interest_shocks"):
        if len(s[k]) != c["years"]: raise ValueError("scenario length: " + k)
    if any(not 0 <= x <= 1 for x in s["funding_multipliers"]):
        raise ValueError("funding fraction must be in [0,1]")
    if any(x <= -1 for x in s["supply_shocks"] + s["demand_shocks"]):
        raise ValueError("shock would make level nonpositive")


def scenario(c, name):
    c = copy.deepcopy(c)
    n = c["years"]
    s = c["scenario"]
    s["name"] = name
    s["reform"] = name != "baseline"
    start = min(2,n-1)
    end = min(start+3,n)
    if name in ("funding_loss","combined"):
        s["funding_multipliers"][start:end] = [0.75]*(end-start)
    if name in ("recession","combined"):
        s["demand_shocks"][start:end] = [-0.12,-0.06,-0.02][:end-start]
        s["labor_shocks"][start:end] = [0.04]*(end-start)
    if name in ("supply_inflation","combined"):
        s["supply_shocks"][start:end] = [-0.06,-0.03,-0.01][:end-start]
        s["inflation_shocks"][start:end] = [0.04,0.02,0.01][:end-start]
    if name == "debt_stress":
        c["fiscal"]["initial_debt"] = 95000000000
        s["interest_shocks"] = [0.03]*n
    if name == "zero_funding": s["funding_multipliers"] = [0.0]*n
    if name not in NAMES: raise ValueError("unknown scenario")
    validate(c)
    return c


NAMES = ("baseline","reform","funding_loss","recession","supply_inflation","debt_stress","combined","zero_funding")
