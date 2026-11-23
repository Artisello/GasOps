"""Deterministic balancing indicators, settlement and scenario calculations."""

from decimal import Decimal,localcontext
from datetime import date
import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

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


class CommercialInput(SettlementInput):
    """Complete illustrative commercial balance; signed additional components."""
    storage_net: Decimal | None = Field(default=D(0), ge=D("-1e12"), le=D("1e12"))
    psv_net: Decimal | None = Field(default=D(0), ge=D("-1e12"), le=D("1e12"))

    @field_validator("storage_net", "psv_net", mode="before")
    @classmethod
    def signed_decimal(cls,value):
        return SettlementInput.finite_decimal(value)


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
    return _settle(inputs,D(0),D(0))


def settle_commercial(inputs: CommercialInput) -> Settlement:
    return _settle(inputs,inputs.storage_net,inputs.psv_net)


def _settle(inputs: SettlementInput, storage_net: Decimal | None, psv_net: Decimal | None) -> Settlement:
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
    if storage_net is None or psv_net is None:
        result.problems.append("Indica entrambi i saldi netti; inserisci zero solo se effettivamente nulli.")
        return result
    result.imbalance_mwh = result.delivered_mwh + scale * (storage_net + psv_net) - result.withdrawn_mwh
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


def settlement_sensitivity(result: Settlement) -> list[tuple[Decimal,Decimal]]:
    """Illustrative price changes of +/- 10 EUR/MWh, holding the balance fixed."""
    if result.imbalance_mwh is None or result.price_eur_mwh is None:
        return []
    return [(result.price_eur_mwh+delta,
             (result.imbalance_mwh*(result.price_eur_mwh+delta)).quantize(CENT))
            for delta in (D(-10),D(0),D(10))]


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


def scenario(case: "ScenarioCase | SecurityScenarioCase", changes: "ScenarioInput | SecurityStress") -> "ScenarioOutput | dict":
    if isinstance(case, SecurityScenarioCase):
        return _security_scenario(SecurityScenarioCase.model_validate(case.model_dump()),
            SecurityStress.model_validate(changes.model_dump() if isinstance(changes,SecurityStress) else changes))
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


# Component-aware extension of the same deterministic scenario engine.
SECURITY_MODEL = "italian-availability-v1"
SECURITY_COMPONENTS = ("lng", "storage", "production", "demand", "exports", "injection")


class StressDatum(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str = Field(max_length=160)
    value: Decimal | None = Field(default=None, ge=0, le=D("1e9"))
    unit: str = "GWh/d"
    classification: Literal["OBSERVED", "FORECAST", "ASSUMPTION", "MODEL OUTPUT"] = "OBSERVED"
    source_id: str = Field(max_length=240)
    source_url: str | None = None
    period_from: AwareDatetime
    period_to: AwareDatetime
    observed_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime | None = None
    quality: str = "valid"
    complete: bool = True
    response_partial: bool = False
    scope: str = ""
    evidence_ids: tuple[str, ...] = ()
    source_unit: str | None = None
    derivation: str | None = None

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        from urllib.parse import urlsplit, urlunsplit
        if not value:return None
        url=urlsplit(value)
        if url.scheme!="https" or url.hostname not in (
                "transparency.entsog.eu","agsi.gie.eu","alsi.gie.eu","jarvis.snam.it"):
            return None
        return urlunsplit(("https",url.hostname,url.path,"",""))


class SecurityScenarioCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    gas_day: date
    reference_time: AwareDatetime
    mode: Literal["PUBLIC", "DEMO"] = "PUBLIC"
    entry_keys: tuple[str, ...]
    inputs: tuple[StressDatum, ...]

    @model_validator(mode="after")
    def identities(self):
        if len(set(self.entry_keys))!=len(self.entry_keys) or not self.entry_keys:
            raise ValueError("Ingressi duplicati o assenti")
        if any(not re.fullmatch(r"IT-TSO-\d{4}ITP-\d{5}entry",k) for k in self.entry_keys):
            raise ValueError("Serve un ingresso italiano verificato")
        object.__setattr__(self,"entry_keys",tuple(sorted(self.entry_keys)))
        by_key={}
        allowed={*self.entry_keys,*SECURITY_COMPONENTS,
                 *(prefix+k for k in self.entry_keys for prefix in ("technical:","available:"))}
        for item in self.inputs:
            if item.key not in allowed:raise ValueError("Componente estranea al modello")
            if item.key in by_key and by_key[item.key]!=item:raise ValueError("Input duplicati in conflitto")
            by_key[item.key]=item
        object.__setattr__(self,"inputs",tuple(by_key[k] for k in sorted(by_key)))
        if self.mode=="PUBLIC" and any(i.quality=="demo" for i in self.inputs):
            raise ValueError("Fixture escluse dalla modalità pubblica")
        return self


class SecurityStress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    demand_pct: Decimal = Field(default=D(10), ge=0, le=300)
    cold_deviation_c: Decimal = Field(default=D(0), ge=0, le=30)
    cold_sensitivity_pct_c: Decimal = Field(default=D(2), ge=0, le=10)
    entry_key: str | None = None
    entry_outage: bool = False
    capacity_reduction_pct: Decimal = Field(default=D(0), ge=0, le=100)
    lng_reduction_pct: Decimal = Field(default=D(0), ge=0, le=100)
    storage_withdrawal_limit: Decimal | None = Field(default=None, ge=0, le=D("1e9"))
    input_assumptions: dict[str, Decimal] = Field(default_factory=dict)

    @model_validator(mode="after")
    def assumptions_valid(self):
        with localcontext() as context:
            context.prec=28
            if (1+self.demand_pct/100)*(1+self.cold_deviation_c*self.cold_sensitivity_pct_c/100)>4:
                raise ValueError("Shock complessivo della domanda superiore al 300%")
        if (self.entry_outage or self.capacity_reduction_pct) and not self.entry_key:
            raise ValueError("Seleziona il punto d’ingresso")
        if any(not v.is_finite() or not 0<=v<=D("1e9") for v in self.input_assumptions.values()):
            raise ValueError("Ipotesi di base non valida")
        return self


def _security_scenario(case, changes):
    """One gas-day availability stress, never pressure, routing or a forecast."""
    from .gas_calendar import gas_day_bounds
    with localcontext() as context:
        context.prec=28
        start,stop=gas_day_bounds(case.gas_day)
        expected=(*case.entry_keys,*SECURITY_COMPONENTS)
        if changes.entry_key is not None and changes.entry_key not in case.entry_keys:
            raise ValueError("Il punto selezionato non appartiene agli ingressi verificati")
        if set(changes.input_assumptions)-set(expected):raise ValueError("Ipotesi su componente non ammessa")
        refs={i.key:i for i in case.inputs}
        def eligible(item):
            capacity=item.key.startswith(("technical:","available:"))
            period=(item.period_from<=start and item.period_to>=stop) if capacity else (item.period_from,item.period_to)==(start,stop)
            return (item.value is not None and item.unit=="GWh/d" and item.complete and period and item.source_id.strip()
                and item.quality in ("valid","capacity_interval","fresh","stale","partial","historical","observed","estimated","demo")
                and all(at is None or at<=case.reference_time for at in (item.observed_at,item.retrieved_at))
                and (item.classification in ("FORECAST","ASSUMPTION") or capacity or item.period_to<=case.reference_time)
                and (item.classification=="ASSUMPTION" or item.retrieved_at is not None))
        values={k:i.value if eligible(i) else None for k,i in refs.items()}
        base={k:values.get(k) for k in expected}
        base.update(changes.input_assumptions)
        stressed=dict(base)
        factor=(1+changes.demand_pct/100)*(1+changes.cold_deviation_c*changes.cold_sensitivity_pct_c/100)
        if base["demand"] is not None:stressed["demand"]=base["demand"]*factor
        if base["lng"] is not None:stressed["lng"]=base["lng"]*(1-changes.lng_reduction_pct/100)
        if base["storage"] is not None and changes.storage_withdrawal_limit is not None:
            stressed["storage"]=min(base["storage"],changes.storage_withdrawal_limit)
        point=changes.entry_key
        capacity=values.get("technical:"+point) if point else None
        reduced_capacity=capacity
        unresolved=[]
        if point and changes.entry_outage:
            if base[point] is not None:stressed[point]=D(0)
            reduced_capacity=D(0) if capacity is not None else None
        elif point and changes.capacity_reduction_pct:
            if capacity is None:
                stressed[point]=None
                unresolved.append("technical:"+point)
            else:
                reduced_capacity=capacity*(1-changes.capacity_reduction_pct/100)
                if base[point] is not None:stressed[point]=min(base[point],reduced_capacity)
        supply=(*case.entry_keys,"lng","storage","production")
        demand=("demand","exports","injection")
        def total(keys,vals):
            return sum((vals[k] for k in keys),D(0)) if all(vals[k] is not None for k in keys) else None
        def known(keys,vals):
            available=[vals[k] for k in keys if vals[k] is not None]
            return sum(available,D(0)) if available else None
        def readout(vals):
            a,b=total(supply,vals),total(demand,vals)
            nonstorage=total(tuple(k for k in supply if k!="storage"),vals)
            need=max(D(0),b-nonstorage) if b is not None and nonstorage is not None else None
            gap,ratio=balance(a,b) if a is not None and b is not None else (None,None)
            return {"supply":a,"demand":b,"domestic_demand":vals["demand"],"balance":gap,"demand_coverage_pct":ratio,
                "known_supply":known(supply,vals),"known_demand":known(demand,vals),"storage_withdrawal":vals["storage"],
                "storage_requirement":need,"additional_storage_requirement":max(D(0),need-vals["storage"])
                    if need is not None and vals["storage"] is not None else None}
        baseline,target=readout(base),readout(stressed)
        baseline["entry_flow"],target["entry_flow"]=base.get(point),stressed.get(point)
        margin=lambda c,f:max(D(0),c-f) if c is not None and f is not None else None
        baseline["technical_headroom"]=margin(capacity,base.get(point))
        target["technical_headroom"]=margin(reduced_capacity,stressed.get(point))
        missing=[k for k in expected if base[k] is None]
        valid=len(expected)-len(missing)
        return {"classification":"MODEL OUTPUT","name":"Stress Test","model_version":SECURITY_MODEL,
            "baseline":baseline,"stress":target,"unit":"GWh/d","components":{"baseline":base,"stress":stressed},
            "missing":missing,"unresolved_assumptions":unresolved,"coverage":{"valid":valid,"expected":len(expected)},
            "input_classes":{k:"ASSUMPTION" if k in changes.input_assumptions else refs[k].classification
                for k in expected if base[k] is not None},
            "status":"Non calcolabile" if not valid else "Parziale" if missing or unresolved else "Calcolabile sul perimetro dichiarato",
            "demand_factor":factor,"point_flow_loss":base[point]-stressed[point]
                if point and base[point] is not None and stressed[point] is not None else None,
            "available_capacity_input":values.get("available:"+point) if point else None,
            "topology":"Impatto topologico non determinabile"}


def stress_configuration(case, changes):
    """Allowlisted inputs only. No session state, portfolio records or credentials."""
    import json
    from hashlib import sha256
    case=SecurityScenarioCase.model_validate(case.model_dump())
    changes=SecurityStress.model_validate(changes.model_dump())
    parameters={"demand_shocks":"multiplicative; domestic demand only","capacity_shock":"min(flow, technical*(1-reduction))",
        "outage":"dominates capacity reduction; no double loss","lng":"one alternative source only",
        "storage":"min(observed withdrawal, explicit limit); no automatic redispatch",
        "other_offtakes":"exports and injection held fixed","linepack":"excluded; no linepack response model",
        "arithmetic":"Decimal precision 28; published gas-day rates are not rescaled by 24/hours"}
    inputs=case.model_dump(mode="json")
    canonical=json.dumps(inputs,sort_keys=True,separators=(",",":"))
    result=scenario(case,changes)
    return {"schema_version":1,"model_version":SECURITY_MODEL,"gas_day":case.gas_day.isoformat(),
        "inputs":inputs,"input_sha256":sha256(canonical.encode()).hexdigest(),
        "source_references":[i.model_dump(mode="json",exclude={"value"}) for i in case.inputs],
        "assumptions":changes.model_dump(mode="json"),"units":{"rates":"GWh/d","temperature_deviation":"°C"},
        "calculation_parameters":parameters,"model_output":result}
