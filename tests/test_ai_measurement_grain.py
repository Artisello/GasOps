"""Regression: energy evidence must carry its own time denominator."""
import pytest

from gasops_app import assistant_sources as src
from gasops_app.ai_response import verify_measurements, InvalidSynthesis


def check(text, public, *, refs=None, tools=None):
    verify_measurements([{"text":text,"references":refs or ["src:"+key for key in public]}],
                        tools or {},public)


@pytest.mark.parametrize("grain",["daily","gas_day","giorno gas","giornaliero","giorno"])
def test_accept_daily_aliases(grain):
    public={src.DAILY:{"status":"available","grain":grain,"values":{"demand_gwh":123.4}}}
    check("Prelievi SRG: 123,4 GWh/giorno gas.",public)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("123,4 GWh/mese.",public)


@pytest.mark.parametrize("grain",["monthly","month","mensile","mese"])
def test_accept_monthly_aliases(grain):
    public={src.MONTHLY:{"status":"available","grain":grain,"values":{"imports_gwh":12000}}}
    check("Importazioni: 12.000 GWh/mese.",public)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("12.000 GWh/giorno.",public)


def test_same_section_mixed_daily_and_monthly_evidence():
    public={
        src.MONTHLY:{"status":"available","grain":"month","values":{"imports_gwh":12000}},
        src.DAILY:{"status":"available","grain":"daily","values":{"demand_gwh":500}},
    }
    check("12.000 GWh/mese e 500 GWh/giorno.",public)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("12.000 GWh/giorno e 500 GWh/mese.",public)


def test_stocks_are_not_flows_and_flow_suffix_is_daily():
    public={"ALSI":{"status":"available","gas_day":"2026-11-26",
                    "values":{"inventory_gwh":1200,"sendout_gwh_d":100}}}
    check("Inventario GNL: 1200 GWh; send-out: 100 GWh/g.",public)
    for answer in ("1200 GWh/g","100 GWh/mese"):
        with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
            check(answer,public)


def test_power_daily_denominator_preserved():
    public={src.POWER[0]:{"status":"available","unit":"GWh elettrici/giorno gas",
                          "values":{"load":{"value":700,"period":"2026-11-25"}}}}
    check("700 GWh elettrici/giorno gas.",public)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("700 GWh elettrici/mese.",public)


def test_unknown_value_is_not_misdiagnosed_as_period_error():
    public={src.DAILY:{"status":"available","grain":"giorno gas","values":{"demand_gwh":100}}}
    with pytest.raises(InvalidSynthesis,match="valore o un’unità"):
        check("999 GWh/giorno gas.",public)


def test_unknown_grain_does_not_authorize_denominator():
    public={"Altra fonte":{"status":"available","unit":"GWh","value":100}}
    check("100 GWh.",public)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("100 GWh/mese.",public)


def test_forecast_reference_cannot_authorize_wrong_frequency():
    tools={"forecast_balancing":{"status":"completed","grain":"monthly",
           "summary":"Previsione: 12000 GWh.","sources":[],
           "projection":{"unit":"GWh/mese","points":[{"estimate":12000,"lower_80":11000,"upper_80":13000}]}}}
    refs=["forecast_balancing"]
    check("Previsione di 12000 GWh/mese, fascia da 11000 a 13000 GWh/mese.",{},refs=refs,tools=tools)
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("12000 GWh/giorno.",{},refs=refs,tools=tools)


def test_lower_bound_must_match_frequency_too():
    public={
        src.MONTHLY:{"status":"available","grain":"mese","values":{"imports_gwh":100}},
        src.DAILY:{"status":"available","grain":"giorno gas","values":{"demand_gwh":200}},
    }
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("Da 100 a 200 GWh/giorno gas.",public)


def test_stale_and_uncited_values_are_not_recovered():
    public={
        src.MONTHLY:{"status":"available","grain":"mese","values":{"imports_gwh":100}},
        src.DAILY:{"status":"stale","grain":"giorno gas","values":{"demand_gwh":100}},
    }
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("100 GWh/giorno gas.",public)
    public[src.DAILY]["status"]="available"
    with pytest.raises(InvalidSynthesis,match="giornaliera e mensile"):
        check("100 GWh/giorno gas.",public,refs=["src:"+src.MONTHLY])
