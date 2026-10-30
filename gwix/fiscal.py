"""Ring-fenced cash allocation and consolidated public stock/flow identities."""
from dataclasses import dataclass
from .households import calculate, emtr


class FundingShortfall(RuntimeError):
    def __init__(self, kind, required, available):
        self.kind,self.required,self.available=kind,required,available
        self.gap=max(0,required-available)
        super().__init__(f"{kind}: required={required:.2f}, available={available:.2f}, gap={self.gap:.2f} CU")


@dataclass(frozen=True)
class PublicState:
    debt: float
    reserve: float
    treasury: float


def max_cost_real(hh,c):
    h=c["household"]
    n=sum(p.labor_eligible for p in hh.people)
    return (min(n*h["topup_max_real"],h["household_topup_cap_real"])+n*h["relief_earnings_cap_real"]*h["contribution_relief"])*hh.weight*(1+c["fiscal"]["administration_share"])


def allocate(hs,c,t,price,wage_index,admitted,reserve,gates):
    f,s=c["fiscal"],c["scenario"]
    admitted=set(admitted)
    if not s["reform"]:
        rows=[calculate(h,c,price,wage_index,False) for h in hs]
        return rows,admitted,dict(funding=0.0,withdrawal=0.0,deposit=0.0,reserve_close=reserve,investment=0.0,admin=0.0,return_to_treasury=0.0,income_fund=0.0,social_clearing=0.0,new_households=0.0,multiyear_margin_real=0.0,programme_residual=0.0)
    funding=f["funding_real"]*price*s["funding_multipliers"][t]
    rows=[calculate(h,c,price,wage_index,h.id in admitted) for h in hs]
    def cost(rs):
        return sum((r["topup"]+r["clearing"])*h.weight for h,r in zip(hs,rs))*(1+f["administration_share"])
    protected=cost(rows)
    if protected > funding+reserve+1e-5:
        raise FundingShortfall("protected_programme_obligations",protected,funding+reserve)
    # Annual real floors are explicit scenario assumptions, never a forecast saving.
    floor=f["funding_real"]*min(s["funding_multipliers"][t:])
    committed=sum(max_cost_real(h,c) for h in hs if h.id in admitted)
    new_weight=0.0
    annual_admission_limit=c["population_households"]*f["initial_admission_share"]
    if all(gates.values()) and protected <= funding:
        for h in hs:
            if h.id in admitted or not h.verified or not any(p.labor_eligible and p.employed for p in h.people): continue
            extra=max_cost_real(h,c)
            if committed+extra > floor+1e-5 or new_weight+h.weight>annual_admission_limit+1e-5: continue
            # New claim admitted only if its complete tax/benefit schedule passes.
            rate=emtr(h,c,price,wage_index,True)
            if rate is not None and rate>c["household"]["emtr_gate"]: continue
            admitted.add(h.id); committed+=extra; new_weight+=h.weight
    rows=[calculate(h,c,price,wage_index,h.id in admitted) for h in hs]
    total=cost(rows)
    if total>funding+reserve+1e-5:
        raise FundingShortfall("programme_obligations",total,funding+reserve)
    income=sum(h.weight*r["topup"] for h,r in zip(hs,rows))
    clearing=sum(h.weight*r["clearing"] for h,r in zip(hs,rows))
    admin=(income+clearing)*f["administration_share"]
    withdrawal=max(0,total-funding)
    remaining=max(0,funding-total)
    deposit=min(remaining,f["reserve_deposit_share"]*funding,max(0,f["reserve_target_real"]*price-reserve))
    remaining-=deposit
    # Existing commitments have priority; reserve never finances new investment.
    invest=min(remaining,f["investment_share"]*funding) if all(gates.values()) else 0.0
    returned=remaining-invest
    close=reserve+deposit-withdrawal
    residual=funding+withdrawal-income-clearing-admin-deposit-invest-returned
    return rows,admitted,dict(funding=funding,withdrawal=withdrawal,deposit=deposit,reserve_close=close,investment=invest,admin=admin,return_to_treasury=returned,income_fund=income,social_clearing=clearing,new_households=new_weight,multiyear_margin_real=floor-committed,programme_residual=residual)


def settle(state,c,price,gdp_nominal,revenue,expenditure,reserve_close):
    """Reserve transfers are asset movements, never consolidated expenditure."""
    f=c["fiscal"]
    reserve_change=reserve_close-state.reserve
    need=expenditure+reserve_change-revenue
    borrowing=repayment=treasury_draw=treasury_deposit=0.0
    if need>=0:
        borrowing=min(need,f["annual_borrowing_limit_real"]*price,max(0,f["debt_hard_ratio"]*gdp_nominal-state.debt))
        treasury_draw=need-borrowing
        if treasury_draw>state.treasury+1e-5:
            raise FundingShortfall("national_financing",need,borrowing+state.treasury)
    else:
        repayment=min(state.debt,-need)
        treasury_deposit=-need-repayment
    new=PublicState(state.debt+borrowing-repayment,reserve_close,state.treasury-treasury_draw+treasury_deposit)
    if new.debt>f["debt_hard_ratio"]*gdp_nominal+1e-5:
        raise FundingShortfall("debt_stock_ceiling",new.debt,f["debt_hard_ratio"]*gdp_nominal)
    residual=(new.debt-state.debt)-(new.reserve-state.reserve)-(new.treasury-state.treasury)-(expenditure-revenue)
    return new,dict(borrowing=borrowing,debt_repayment=repayment,treasury_draw=treasury_draw,treasury_deposit=treasury_deposit,cash_residual=residual,deficit=expenditure-revenue,primary_balance=revenue-expenditure)
