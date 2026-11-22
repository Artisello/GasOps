from datetime import date
from decimal import Decimal as D
from gasops_app.finance import CommercialInput, SettlementInput, settle, settle_commercial, settlement_sensitivity
from gasops_app.operations_ledger import BalanceRow


def test_complete_commercial_balance_matches_ledger_and_units():
    inputs=CommercialInput(delivered="8,8",withdrawn="10",unit="GWh",
                           storage_net="0,3",psv_net="-0,2",buy_eur_mwh=42,sell_eur_mwh=38)
    result=settle_commercial(inputs)
    reference=BalanceRow("DEMO",date(2026,11,17),1,"provisional",D(8800),D(300),D(-200),D(10000),D(42),D(38))
    assert result.imbalance_mwh==reference.imbalance==D(-1100)
    assert result.cash_flow_eur==reference.cash==D(-46200)
    assert result.side=="buy" and result.direction=="charge"


def test_missing_terms_and_negative_prices():
    missing=settle_commercial(CommercialInput(storage_net=""))
    assert missing.imbalance_mwh is None and missing.cash_flow_eur is None and missing.problems
    result=settle_commercial(CommercialInput(delivered=9,withdrawn=10,buy_eur_mwh=-5,sell_eur_mwh=-8))
    assert result.imbalance_mwh==D(-1) and result.side=="buy"
    assert result.cash_flow_eur==D(5) and result.direction=="credit"
    assert settlement_sensitivity(result)==[(D(-15),D(15)),(D(-5),D(5)),(D(5),D(-5))]


def test_simple_unchanged_and_flat_has_no_price():
    inputs=SettlementInput()
    complete=CommercialInput(**inputs.model_dump())
    assert settle(inputs)==settle_commercial(complete)
    flat=settle_commercial(CommercialInput(delivered=10,withdrawn=12,storage_net=2,psv_net=0,buy_eur_mwh=None))
    assert flat.imbalance_mwh==D(0) and flat.cash_flow_eur==D(0)
    assert settlement_sensitivity(flat)==[]


def test_scenario_chart_preserves_observation_and_simulation():
    from gasops_app.finance import ScenarioCase,ScenarioInput,scenario
    from gasops_app.balancing_charts import scenario_comparison
    case=ScenarioCase(demand_gwh=100,supply_gwh=100,storage_gwh=20,price_eur_mwh=42)
    base=scenario(case,ScenarioInput(demand_pct=0))
    stress=scenario(case,ScenarioInput(demand_pct=25,supply_pct=-50))
    fig=scenario_comparison(base,stress,"GWh/mese")
    assert list(fig.data[0].x)==[100.,125.]
    assert list(fig.data[1].x)==[100.,60.]
    assert list(fig.data[0].y)==["Base","Scenario"]
    assert fig.layout.yaxis.automargin and not fig.layout.xaxis.visible


def test_daily_chart_keeps_missing_value_and_sign():
    import pandas as pd
    from gasops_app.balancing_charts import daily_bars
    frame=pd.DataFrame({"Giorno":pd.date_range("2026-11-15",periods=3),"DS":[-10,None,20]})
    fig=daily_bars(frame,["DS"],"MWh")
    assert pd.isna(fig.data[0].y[1])
    assert fig.data[0].marker.color[0]!=fig.data[0].marker.color[2]
