"""Small recursive annual demand/capacity model, not an estimated DSGE model."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MacroState:
    price: float
    inflation: float
    capital: float
    productivity: float
    wage_index: float
    gdp: float
    gap: float
    incentive: float


def initial(c):
    m=c["macro"]
    return MacroState(1.0,m["inflation_initial"],m["capital_real_initial"],1.0,1.0,m["gdp_real_initial"],0.0,0.65)


def advance(state,c,t,consumption_nominal,investment_public,government_real,legacy_subsidy,external_anchor,incentive):
    m,s=c["macro"],c["scenario"]
    p=state.price
    potential=m["gdp_real_initial"]*state.productivity*(state.capital/m["capital_real_initial"])**m["capital_share"]*(1+s["supply_shocks"][t])
    rate=m["policy_rate_base"]+m["policy_inflation_response"]*(state.inflation-m["inflation_target"])
    factor=1+m["investment_gap_sensitivity"]*state.gap-m["investment_rate_sensitivity"]*(rate-m["policy_rate_base"])
    raw_investment=m["investment_gdp_share"]*state.gdp*factor+m["subsidy_investment_pass_through"]*(legacy_subsidy/p-c["fiscal"]["subsidy_pool_real"])
    private_investment=max(0.0,raw_investment)
    external=external_anchor*state.productivity*(1+s["demand_shocks"][t])
    consumption=consumption_nominal/p
    public_investment=investment_public/p
    gdp=consumption+private_investment+public_investment+government_real+external
    gap=gdp/potential-1
    inflation_next=m["inflation_target"]+m["inflation_persistence"]*(state.inflation-m["inflation_target"])+m["phillips_slope"]*gap+s["inflation_shocks"][t]
    if not (-0.75 < gap < 0.75) or not (-0.5 < inflation_next < 1.0):
        raise ValueError("macro domain exceeded; no silent clipping of GDP/CPI")
    productive=m["public_investment_efficiency"]*public_investment
    capital=(1-m["depreciation"])*state.capital+private_investment+productive
    productivity=state.productivity*(1+m["productivity_growth"]+m["public_tfp_elasticity"]*productive/potential)
    # Nominal contracts adjust using the previous inflation rate. Unexpected
    # current price acceleration therefore reduces real wages, rather than
    # being neutralized by instantaneous full wage indexation.
    wage_index=state.wage_index*(1+state.inflation)*(1+m["wage_growth_share"]*(productivity/state.productivity-1))/(1+inflation_next)
    next_state=MacroState(p*(1+inflation_next),inflation_next,capital,productivity,wage_index,gdp,gap,incentive)
    if any(not math.isfinite(v) or v<=0 for v in (next_state.price,capital,productivity,gdp)):
        raise ValueError("nonfinite/nonpositive macro state")
    values=dict(cpi=p,inflation=state.inflation,inflation_next=inflation_next,gdp_real=gdp,gdp_nominal=gdp*p,potential_real=potential,output_gap=gap,capital_open_real=state.capital,capital_close_real=capital,productivity=state.productivity,productivity_next=productivity,policy_rate=rate,private_investment_real=private_investment,private_investment_floor=int(raw_investment<0),public_investment_real=public_investment,consumption_real=consumption,government_consumption_real=government_real,other_demand_real=external,gdp_identity_residual=gdp-consumption-private_investment-public_investment-government_real-external)
    return next_state,values
