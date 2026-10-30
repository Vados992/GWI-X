import copy
from dataclasses import replace
import math
from pathlib import Path
import unittest

from gwix.config import load, scenario, validate, NAMES
from gwix.households import Person, Household, calculate, tax, emtr, emtr_adults, generate, validate_population, check_contract, transition
from gwix.fiscal import PublicState, FundingShortfall, settle, allocate, max_cost_real
from gwix.engine import run, paired
from gwix.macro import initial, advance

ROOT=Path(__file__).resolve().parents[1]


class MicroTests(unittest.TestCase):
    def setUp(self):
        self.c=load(ROOT/"configs/synthetic.json")
        self.h=Household("test","single",(Person("p",10,2000,True),),0,1)

    def test_hand_calculated_household(self):
        # Gross 20k; tax .18*8k=1440; full SC 2k, relief400;
        # assistance .25*(20k-1440-2000)=4140 =>3860; topup960.
        r=calculate(self.h,self.c,admitted=True)
        self.assertEqual(r["gross"],20000)
        self.assertEqual(r["income_tax"],1440)
        self.assertEqual(r["employee_sc"],1600)
        self.assertEqual(r["clearing"],400)
        self.assertEqual(r["topup"],960)
        self.assertEqual(r["assistance"],3860)
        self.assertEqual(r["disposable"],21780)
        self.assertEqual(r["employer_cost"],24400)

    def test_tax_progressive_bands(self):
        self.assertEqual(tax(70000,1,self.c["household"]),18000*.18+30000*.28+10000*.38)
        self.assertEqual(tax(0,1,self.c["household"]),0)

    def test_emtr_independent_derivative(self):
        # Marginal tax .18 + SC .08 + assistance withdrawal .25*.72 + topup withdrawal .12.
        self.assertAlmostEqual(emtr(self.h,self.c,admitted=True),.56)

    def test_emtr_checks_second_adult(self):
        h=replace(self.h,people=(Person("one",10,1000,True),Person("two",35,2000,True)))
        rates=emtr_adults(h,self.c,admitted=True)
        self.assertEqual(len(rates),2)
        self.assertAlmostEqual(emtr(h,self.c,admitted=True),max(rates))
        self.assertGreater(rates[1],rates[0])

    def test_no_emtr_for_nonworker(self):
        h=replace(self.h,people=(replace(self.h.people[0],employed=False),))
        self.assertIsNone(emtr(h,self.c))
        self.assertEqual(calculate(h,self.c,admitted=True)["topup"],0)

    def test_no_employer_cost_increase_at_fixed_contract(self):
        a=calculate(self.h,self.c,admitted=False)
        b=calculate(self.h,self.c,admitted=True)
        self.assertEqual(a["employer_cost"],b["employer_cost"])
        self.assertEqual(a["employee_sc"],b["employee_sc"]+b["clearing"])
        self.assertEqual(a["benefits"],b["benefits"])
        self.assertGreater(b["disposable"],a["disposable"])

    def test_currency_and_price_dimensions(self):
        a=calculate(self.h,self.c,admitted=True)
        b=calculate(self.h,self.c,price=10,admitted=True)
        for k in ("gross","disposable","clearing","topup","benefits"):
            self.assertAlmostEqual(b[k],10*a[k])
        self.assertAlmostEqual(a["real_disposable"],b["real_disposable"])
        self.assertAlmostEqual(emtr(self.h,self.c,price=10,admitted=True),emtr(self.h,self.c,admitted=True))

    def test_continuous_topup_boundaries(self):
        for edge in (0,6000,18000,28000):
            a=calculate(self.h,self.c,admitted=True,earnings_override={0:max(0,edge-.001)})
            b=calculate(self.h,self.c,admitted=True,earnings_override={0:edge+.001})
            self.assertLess(abs(a["topup"]-b["topup"]),.01)

    def test_household_cap(self):
        h=replace(self.h,people=tuple(Person(str(i),9,2000,True) for i in range(4)))
        self.assertEqual(calculate(h,self.c,admitted=True)["topup"],2400)

    def test_unverified_new_claim_gets_no_gwi(self):
        r=calculate(replace(self.h,verified=False),self.c,admitted=True)
        self.assertEqual(r["topup"]+r["clearing"],0)

    def test_contract_review(self):
        p=self.h.people[0]
        with self.assertRaisesRegex(ValueError,"REVIEW_REQUIRED"): check_contract(p,replace(p,wage_real_hour=9))
        with self.assertRaisesRegex(ValueError,"REVIEW_REQUIRED"): check_contract(p,replace(p,hours_year=1000))
        check_contract(p,replace(p,hours_year=1000),True)

    def test_identity_and_time_fraud(self):
        with self.assertRaises(ValueError): validate_population([self.h,self.h])
        with self.assertRaises(ValueError): validate_population([self.h,replace(self.h,id="another")])
        with self.assertRaises(ValueError): validate_population([replace(self.h,people=(replace(self.h.people[0],hours_year=3000),))])
        with self.assertRaises(ValueError): validate_population([replace(self.h,weight=float("nan"))])

    def test_invalid_price_and_earnings(self):
        with self.assertRaises(ValueError): calculate(self.h,self.c,price=0)
        with self.assertRaises(ValueError): calculate(self.h,self.c,earnings_override={0:float("nan")})

    def test_population_weights_and_disjoint_groups(self):
        hs=generate(self.c)
        self.assertAlmostEqual(sum(h.weight for h in hs),1000000)
        self.assertEqual(len({h.id for h in hs}),1200)
        self.assertEqual(len({h.group for h in hs}),6)

    def test_employment_reproducible_and_bounded(self):
        hs=generate(self.c)
        a=transition(hs,self.c,2028,-.1,.5,.04)
        self.assertEqual(a,transition(hs,self.c,2028,-.1,.5,.04))
        self.assertTrue(all(not p.employed for h in a for p in h.people if not p.labor_eligible))


class FiscalTests(unittest.TestCase):
    def setUp(self): self.c=load(ROOT/"configs/synthetic.json")

    def test_consolidated_identity_independent(self):
        old=PublicState(100,20,10)
        c=copy.deepcopy(self.c); c["fiscal"]["debt_hard_ratio"]=10
        new,flow=settle(old,c,1,1000,80,100,25)
        self.assertEqual(new,PublicState(125,25,10))
        self.assertEqual(new.debt-old.debt-(new.reserve-old.reserve)-(new.treasury-old.treasury),20)
        self.assertEqual(flow["deficit"],20)

    def test_reserve_draw_is_not_revenue(self):
        old=PublicState(100,20,10)
        new,flow=settle(old,self.c,1,1000,80,100,0)
        self.assertEqual(new.debt,old.debt)
        self.assertEqual(flow["deficit"],20)

    def test_repay_debt_then_hold_cash(self):
        new,_=settle(PublicState(10,0,5),self.c,1,1000,100,20,0)
        self.assertEqual(new,PublicState(0,0,75))

    def test_no_automatic_national_financing(self):
        c=copy.deepcopy(self.c); c["fiscal"]["annual_borrowing_limit_real"]=0
        with self.assertRaises(FundingShortfall): settle(PublicState(100,0,0),c,1,1000,0,1,0)

    def test_protected_payments_before_investment(self):
        c=copy.deepcopy(self.c); c["scenario"]["funding_multipliers"]=[0]*10
        hs=generate(c); admitted={h.id for h in hs}
        rows,_,fund=allocate(hs,c,0,1,1,admitted,1e10,{"test":False})
        self.assertEqual(fund["investment"],0)
        self.assertEqual(fund["deposit"],0)
        self.assertGreater(fund["withdrawal"],0)
        self.assertGreater(fund["income_fund"],0)

    def test_unfunded_claim_fails_without_mutation(self):
        c=copy.deepcopy(self.c); c["scenario"]["funding_multipliers"]=[0]*10
        hs=generate(c); ids={h.id for h in hs}; before=ids.copy()
        with self.assertRaises(FundingShortfall): allocate(hs,c,0,1,1,ids,0,{"test":True})
        self.assertEqual(ids,before)

    def test_multiyear_ceiling_not_forecast_savings(self):
        c=scenario(self.c,"funding_loss"); hs=generate(c)
        _,ids,f=allocate(hs,c,0,1,1,set(),0,{"test":True})
        self.assertLessEqual(sum(max_cost_real(h,c) for h in hs if h.id in ids),1.5e9)
        self.assertGreaterEqual(f["multiyear_margin_real"],0)

    def test_closed_gate_stops_new_not_existing(self):
        hs=generate(self.c); ids={hs[0].id}
        rows,new,f=allocate(hs,self.c,0,1,1,ids,0,{"test":False})
        self.assertEqual(ids,new)
        self.assertEqual(f["new_households"],0)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=load(ROOT/"configs/synthetic.json")
        cls.c["households"]=120  # fixed test population; weights still sum to 1m
        cls.results={n:paired(scenario(cls.c,n)) for n in NAMES}

    def test_complete_ten_year_core(self):
        for n in ("baseline","reform","funding_loss","recession","supply_inflation","combined"):
            with self.subTest(n=n): self.assertEqual(len(self.results[n][0].annual),10)

    def test_all_stress_stock_flow_identities(self):
        for pair in self.results.values():
            for r in pair:
                for a in r.annual:
                    with self.subTest(s=r.name,y=a["year"]):
                        self.assertAlmostEqual(a["debt_close"]-a["debt_open"]-(a["reserve_close"]-a["reserve_open"])-(a["treasury_close"]-a["treasury_open"]),a["expenditure"]-a["revenue"],delta=1e-4)
                        self.assertLessEqual(a["withdrawal"],a["reserve_open"]+1e-4)
                        self.assertGreaterEqual(a["reserve_close"],0)
                        self.assertAlmostEqual(a["social_clearing"],a["hh_clearing"],delta=1e-4)

    def test_micro_macro_budget_aggregation(self):
        r=self.results["reform"][0]
        for a in r.annual:
            rs=[x for x in r.households if x["year"]==a["year"]]
            for key in ("disposable","benefits","gross","topup","employee_sc"):
                self.assertAlmostEqual(sum(x["weight"]*x[key] for x in rs),a["hh_"+key],delta=1e-4)
            self.assertAlmostEqual(a["consumption_real"]*a["cpi"],a["hh_disposable"]*.85,delta=1e-4)
            self.assertAlmostEqual(a["gdp_real"],sum(a[k] for k in ("consumption_real","private_investment_real","public_investment_real","government_consumption_real","other_demand_real")),delta=1e-4)

    def test_price_inflation_timing(self):
        a=self.results["reform"][0].annual
        for prev,cur in zip(a,a[1:]):
            self.assertAlmostEqual(cur["cpi"]/prev["cpi"]-1,cur["inflation"])
            self.assertAlmostEqual(prev["inflation_next"],cur["inflation"])

    def test_group_totals(self):
        r=self.results["reform"][0]
        for a in r.annual:
            groups=[x for x in r.groups if x["year"]==a["year"]]
            self.assertEqual(len(groups),6)
            self.assertAlmostEqual(sum(g["real_disposable_mean"]*g["households"] for g in groups),a["hh_real_disposable"],delta=1e-4)

    def test_zero_funding_blocks_instead_of_fake_payment(self):
        r=self.results["zero_funding"][0]
        self.assertEqual(r.status,"blocked_unfunded")
        self.assertGreater(r.failure["gap"],0)
        self.assertLess(r.annual[-1]["year"],r.failure["year"])
        self.assertTrue(all(a["new_households"]==0 for a in r.annual))

    def test_debt_stress_stops_expansion(self):
        r=self.results["debt_stress"][0]
        self.assertTrue(all(a["gate_debt"]==0 and a["new_households"]==0 for a in r.annual))

    def test_no_counterfactual_no_risk_gate_pass(self):
        r=run(scenario(self.c,"reform"))
        self.assertEqual(r.annual[0]["gate_inflation"],0)
        self.assertEqual(r.annual[0]["new_households"],0)

    def test_all_three_links_respond(self):
        r,b=self.results["reform"]
        self.assertNotEqual(r.annual[0]["hh_disposable"],b.annual[0]["hh_disposable"])
        self.assertNotEqual(r.annual[0]["debt_close"],b.annual[0]["debt_close"])
        self.assertNotEqual(r.annual[0]["gdp_real"],b.annual[0]["gdp_real"])
        self.assertNotEqual(r.annual[1]["cpi"],b.annual[1]["cpi"])

    def test_repeatability(self):
        c=copy.deepcopy(self.c); c["years"]=2
        for k,v in c["scenario"].items():
            if isinstance(v,list): c["scenario"][k]=v[:2]
        a,b=paired(c); x,y=paired(c)
        self.assertEqual(a,x); self.assertEqual(b,y)

    def test_inflation_gate_threshold(self):
        c=copy.deepcopy(self.c)
        c["macro"]["inflation_gate_increment"]=-1
        r,b=paired(c)
        self.assertTrue(all(a["gate_inflation"]==0 and a["new_households"]==0 for a in r.annual[1:]))


class ConfigAndMacroTests(unittest.TestCase):
    def setUp(self): self.c=load(ROOT/"configs/synthetic.json")

    def test_config_rejects_unknown_national_claim(self):
        self.c["label"]="Official country"
        with self.assertRaises(ValueError): validate(self.c)

    def test_config_bad_units_rates_schedule(self):
        for change in (("household","employee_contribution",10),("household","contribution_relief",.5),("scenario","funding_multipliers",[1]),("fiscal","funding_real",3e9),("macro","capital_real_initial",float("nan"))):
            c=copy.deepcopy(self.c); c[change[0]][change[1]]=change[2]
            with self.assertRaises(ValueError): validate(c)

    def test_invalid_scenario(self):
        with self.assertRaises(ValueError): scenario(self.c,"unknown")

    def test_public_investment_lag_and_capital_identity(self):
        state=initial(self.c)
        a,x=advance(state,self.c,0,30e9,0,18e9,2e9,32e9,.65)
        b,y=advance(state,self.c,0,30e9,1e9,18e9,2e9,32e9,.65)
        self.assertEqual(x["potential_real"],y["potential_real"])
        self.assertAlmostEqual(b.capital-a.capital,.6e9)
        self.assertGreater(b.productivity,a.productivity)

    def test_surprise_inflation_erodes_real_wage(self):
        c=copy.deepcopy(self.c); c["scenario"]["inflation_shocks"][0]=.1
        a,_=advance(initial(self.c),self.c,0,30e9,0,18e9,2e9,32e9,.65)
        b,_=advance(initial(c),c,0,30e9,0,18e9,2e9,32e9,.65)
        self.assertLess(b.wage_index,a.wage_index)

    def test_macro_extreme_domain_fails_visible(self):
        with self.assertRaises(ValueError): advance(initial(self.c),self.c,0,1e15,0,18e9,2e9,32e9,.65)


if __name__=="__main__": unittest.main()
