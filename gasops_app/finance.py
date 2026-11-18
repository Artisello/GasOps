"""Deterministic balancing indicators, settlement and scenario calculations."""

from decimal import Decimal
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from gasops import number

D = Decimal
CENT = D("0.01")
MWH_PER_UNIT = {"kWh": D("0.001"), "MWh": D(1), "GWh": D(1000)}


class SettlementInput(BaseModel):
    delivered: Decimal | None = Field(default=D(8800), ge=0, le=D("1e12"))
    withdrawn: Decimal | None = Field(default=D(10000), ge=0, le=D("1e12"))
    unit: Literal["kWh", "MWh", "GWh"] = "MWh"
    buy_eur_mwh: Decimal | None = Field(default=D(42), ge=D("-1e6"), le=D("1e6"))
    sell_eur_mwh: Decimal | None = Field(default=D(38), ge=D("-1e6"), le=D("1e6"))

    @field_validator("delivered", "withdrawn", "buy_eur_mwh", "sell_eur_mwh", mode="before")
    @classmethod
    def finite_decimal(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+),\d+", value):
                value = value.replace(".", "").replace(",", ".")
        return None if value in (None, "") else number(value)


class Settlement(BaseModel):
    delivered_mwh: Decimal | None = None
    withdrawn_mwh: Decimal | None = None
    imbalance_mwh: Decimal | None = None
    side: Literal["buy", "sell", "flat"] | None = None
    price_eur_mwh: Decimal | None = None
    cash_flow_eur: Decimal | None = None
    direction: Literal["charge", "credit", "flat"] | None = None
    problems: list[str] = Field(default_factory=list)


def settle(inputs: SettlementInput) -> Settlement:
    result = Settlement()
    if inputs.buy_eur_mwh is not None and inputs.sell_eur_mwh is not None:
        if inputs.buy_eur_mwh < inputs.sell_eur_mwh:
            result.problems.append("Il prezzo di acquisto è inferiore a quello di vendita. Verifica i valori inseriti.")
    scale = MWH_PER_UNIT[inputs.unit]
    result.delivered_mwh = None if inputs.delivered is None else inputs.delivered * scale
    result.withdrawn_mwh = None if inputs.withdrawn is None else inputs.withdrawn * scale
    if result.delivered_mwh is None or result.withdrawn_mwh is None:
        result.problems.append("Inserisci sia l’energia immessa sia quella prelevata.")
        return result
    result.imbalance_mwh = result.delivered_mwh - result.withdrawn_mwh
    if result.imbalance_mwh == 0:
        result.side, result.cash_flow_eur, result.direction = "flat", D("0.00"), "flat"
        return result
    result.side = "buy" if result.imbalance_mwh < 0 else "sell"
    result.price_eur_mwh = inputs.buy_eur_mwh if result.side == "buy" else inputs.sell_eur_mwh
    if result.price_eur_mwh is None:
        side_label = "acquisto" if result.side == "buy" else "vendita"
        result.problems.append(f"Per questa posizione serve il prezzo di {side_label}.")
        return result
    cash = (result.imbalance_mwh * result.price_eur_mwh).quantize(CENT)
    result.cash_flow_eur = cash if cash else D("0.00")
    result.direction = "charge" if cash < 0 else "credit" if cash > 0 else "flat"
    return result


class ScenarioInput(BaseModel):
    demand_pct: Decimal = Field(default=D(10), ge=-100, le=300)
    supply_pct: Decimal = Field(default=D(0), ge=-100, le=300)
    storage_pct: Decimal = Field(default=D(0), ge=-100, le=300)
    price_delta_eur_mwh: Decimal = Field(default=D(0), ge=-1000, le=1000)


class ScenarioCase(BaseModel):
    demand_gwh: Decimal = Field(ge=0)
    supply_gwh: Decimal = Field(ge=0)
    storage_gwh: Decimal | None = Field(default=None, ge=0)
    price_eur_mwh: Decimal | None = None


class ScenarioOutput(BaseModel):
    demand_gwh: Decimal
    supply_gwh: Decimal
    storage_gwh: Decimal | None
    price_eur_mwh: Decimal | None
    imbalance_gwh: Decimal
    coverage_pct: Decimal | None
    gap_value_eur: Decimal | None


def balance(supply: Decimal, demand: Decimal) -> tuple[Decimal, Decimal | None]:
    return supply - demand, None if demand == 0 else D(100) * supply / demand


def scenario(case: ScenarioCase, changes: ScenarioInput) -> ScenarioOutput:
    if case.storage_gwh is not None and case.storage_gwh > case.supply_gwh:
        raise ValueError("Il contributo dello stoccaggio deve rientrare nell’offerta totale.")
    if case.storage_gwh is None and changes.storage_pct:
        raise ValueError("Per variare lo stoccaggio, indica un contributo iniziale osservato o di esempio.")
    demand = case.demand_gwh * (1 + changes.demand_pct / 100)
    base_storage = case.storage_gwh or D(0)
    storage = None if case.storage_gwh is None else base_storage * (1 + changes.storage_pct / 100)
    supply = (case.supply_gwh - base_storage) * (1 + changes.supply_pct / 100) + (storage or D(0))
    price = None if case.price_eur_mwh is None else case.price_eur_mwh + changes.price_delta_eur_mwh
    gap, coverage = balance(supply, demand)
    return ScenarioOutput(
        demand_gwh=demand, supply_gwh=supply, storage_gwh=storage, price_eur_mwh=price,
        imbalance_gwh=gap, coverage_pct=coverage,
        gap_value_eur=(gap * 1000 * price).quantize(CENT) if price is not None else None,
    )
