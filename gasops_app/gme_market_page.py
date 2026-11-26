"""GME workspace and session-only observations shared with existing views."""
from datetime import date, timedelta
from decimal import Decimal as D

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import gme_market as g
from .gas_calendar import closed_gas_day
from .italiano import data_it
from .models import utc_now
from .visuals import BLUE, TEAL, kpi_grid, local_time, mini_chart, plot

STATE = "gme_private_market_v2"
CACHE_TIME = timedelta(minutes=15)
CACHE_SIZE = 12
DEMO_STATE = "gme_demo_results"
FIELDS = {
    "MaxPurchaseSRGPrice": "Massimo acquisto SRG", "MinSaleSRGPrice": "Minimo vendita SRG",
    "WeightedAveragePrice": "Prezzo medio di remunerazione", "MGASVolumes": "Volumi MGAS",
    "Price": "Prezzo", "Volumes": "Volumi", "SRGPurchases": "Acquisti SRG", "SRGSales": "Vendite SRG",
    "Participants": "Operatori", "SRGVolumes": "Volume abbinato SRG", "PurchasesTSO": "Acquisti SRG",
    "SalesTSO": "Vendite SRG", "MWhVolumes": "Scambi", "MWVolumes": "Scambi",
    "TotalVolumesMWh": "Volume accettato", "TotalVolumesMW": "Volume accettato",
    "FirstPrice": "Primo prezzo", "LastPrice": "Ultimo prezzo", "MinPrice": "Prezzo minimo",
    "MaxPrice": "Prezzo massimo", "AveragePrice": "Prezzo medio",
    "CheckPrice": "Prezzo di controllo", "AuctionPrice": "Prezzo d’asta",
    "PurchasingPrice": "Prezzo di acquisto", "SellingPrice": "Prezzo di vendita",
    "OTCMWVolumes": "Scambi OTC", "OTCMWhVolumes": "Scambi OTC",
    "OpenPositions": "Posizione aperta", "Matches": "Abbinamenti",
    "VolumeOfferedByGSE": "Volume offerto da GSE", "RemunerationPrice": "Prezzo di remunerazione",
    "VolumeOfferedByParticipants": "Volume offerto dagli operatori", "VolumeAllocated": "Volume assegnato",
    "NumberOfAllocates": "Operatori assegnatari",
    "FlowDate": "Data di flusso", "SessionDate": "Data sessione", "GasDay": "Giorno gas",
    "Date": "Data sessione", "Market": "Mercato", "Product": "Prodotto",
    "StorageCompany": "Impresa di stoccaggio", "Type": "Tipo", "OfferPoint": "Punto di offerta",
    "Reason": "Motivazione",
}
PREFERRED = {"prices": "WeightedAveragePrice", "continuous": "AveragePrice", "pgr": "RemunerationPrice"}


def _private_cache():
    if not g.session_authorized():
        st.session_state.pop(STATE, None)
        return None
    return st.session_state.setdefault(STATE, {})


def snapshot(kind, segment=None, *, api_only=False):
    cache = _private_cache()
    if cache is None:
        return None
    item = cache.get((kind, segment or g.DATASETS[kind].segments[0]))
    return item if item and (not api_only or item["origin"] == "api") else None


def _save(item):
    cache = _private_cache()
    if cache is not None:
        key = item["kind"], item["segment"]
        cache.pop(key, None)
        cache[key] = item
        if len(cache) > CACHE_SIZE:
            del cache[next(iter(cache))]


def _label(field, spec, *, units=True):
    base = "IGI" if field == "Price" and spec.name == "GAS_IGIndex" else FIELDS[field]
    unit = spec.units.get(field)
    return f"{base} ({unit or 'unità n.d.'})" if units and field in spec.units else base


def _credit(item):
    if item["synthetic"]:
        st.caption("Demo sintetica · valori di esempio.")
        return
    source = g.DATASETS[item["kind"]].source_url(item["segment"])
    caption = (f"Fonte: {g.SOURCE} · {item['segment']} · "
               f"[{g.DATASETS[item['kind']].name}]({source})")
    if item["origin"] == "api":
        caption += f" · acquisito {local_time(item['acquired'])}"
    else:
        caption += " · estratto caricato manualmente · provenienza dichiarata"
    st.caption(caption)


def _acquisition(kind, segment, prefix, cutoff, day=None):
    from .gme_api import session_client
    previous = snapshot(kind, segment)
    context = f"{prefix}_{kind}_{segment}" + (f"_{day.isoformat()}" if day else "")
    with st.expander("Carica dati GME", expanded=previous is None):
        spec = g.DATASETS[kind]
        ending = min(day or cutoff, cutoff)
        period = st.date_input("Periodo · " + FIELDS[spec.date_field].lower(),
                               value=(max(g.FIRST_DAY, ending - timedelta(days=6)), ending), min_value=g.FIRST_DAY,
                               max_value=cutoff, format="DD/MM/YYYY", key=context+"_period")
        key = context+"_notice"
        controls, quota = st.columns([2, 1])
        if controls.button("Carica dall’API", type="primary", key=context+"_fetch"):
            try:
                if not isinstance(period, tuple) or len(period) != 2:
                    raise ValueError("Seleziona l’inizio e la fine dell’intervallo.")
                first, last = period
                g.validate_window(kind, segment, first, last, cutoff)
                if (previous and previous["origin"] == "api" and previous["first"] == first
                        and previous["last"] == last and utc_now() - previous["acquired"] < CACHE_TIME):
                    st.session_state[key] = ("caption", "Copia della sessione già aggiornata.")
                else:
                    with st.spinner("Acquisizione GME…"):
                        refreshed = session_client().fetch(kind, segment, first, last, cutoff)
                    if not refreshed["rows"] and previous and previous["rows"]:
                        st.session_state[key] = ("warning", "Nessuna osservazione nel nuovo periodo · ultima copia conservata.")
                    else:
                        _save(refreshed)
                        st.session_state[key] = ("caption", f"{len(refreshed['rows'])} osservazioni validate.")
            except ValueError as error:
                message = str(error) + (" · ultima copia conservata." if previous else "")
                st.session_state[key] = ("warning", message)
        with quota, st.popover("Quote", width="stretch"):
            _quota_panel(prefix)
        if key in st.session_state:
            severity, notice = st.session_state[key]
            getattr(st, severity)(notice)
        if kind == "pgr":
            st.caption("PGR indicato come inattivo nel manuale API. La disponibilità dipende dalla fonte.")
    return snapshot(kind, segment)


def _quota_panel(prefix):
    from .gme_api import QUOTAS, session_client
    key = prefix + "_gme_quota"
    if st.button("Controlla quote", key=key):
        try:
            st.session_state[key+"_result"] = (session_client().quotas(), utc_now())
        except ValueError as error:
            st.warning(str(error))
    state = st.session_state.get(key+"_result")
    if state:
        quotas, checked = state
        st.dataframe([{"Quota": label, "Utilizzo corrente": quotas[field][0], "Limite": quotas[field][1]}
                      for field, _, label in QUOTAS], hide_index=True)
        st.caption("Verifica " + local_time(checked))


def panel(kind=None, *, prefix="gme", day=None):
    authorized = g.session_authorized()
    if kind is not None and not authorized:
        return
    if kind is None:
        st.subheader("Mercato gas · GME")
        if authorized:
            kind = st.selectbox("Dataset", tuple(g.DATASETS),
                                format_func=lambda k: g.DATASETS[k].label, key="gme_dataset")
        else:
            kind = st.radio("Analisi", g.DEMO_KINDS, format_func=lambda k: g.DATASETS[k].label,
                            horizontal=True, key="gme_view", label_visibility="collapsed")
    spec = g.DATASETS[kind]
    cutoff = closed_gas_day(utc_now())
    segment = spec.segments[0]
    if authorized and len(spec.segments) > 1:
        segment = st.selectbox("Segmento", spec.segments, key=prefix+"_segment_"+kind)
    if authorized:
        if g.credentials() is not None:
            item = _acquisition(kind, segment, prefix, cutoff, day)
        else:
            item = snapshot(kind, segment)
            st.caption("Configura la sezione GME nei Secrets per acquisire dati dall’API.")
        if prefix == "gme":
            with st.expander("Importa estratto autorizzato"):
                file = st.file_uploader("JSON, XML o risposta API JSON", type=["json", "xml"],
                                        key=f"gme_file_{kind}_{segment}")
                if st.button("Valida estratto", key=f"gme_import_{kind}_{segment}") and file is not None:
                    try:
                        if file.size > g.MAX_BYTES:
                            raise ValueError("Estratto GME oltre 4 MiB.")
                        item = g.parse(file.getvalue(), kind, cutoff, segment=segment)
                    except ValueError as error:
                        st.warning(str(error))
                    else:
                        _save(item)
    else:
        _private_cache()
        st.caption("Esempi sintetici dei mercati del gas.")
        if st.button("Mostra demo", key="gme_demo"):
            st.session_state.setdefault(DEMO_STATE, {})[kind] = g.demo(kind, cutoff)
        item = st.session_state.get(DEMO_STATE, {}).get(kind)
    if item is not None:
        _credit(item)
        if prefix == "gme" and st.button("Rimuovi estratto", key="gme_clear_"+kind):
            if authorized:
                _private_cache().pop((kind, segment), None)
            else:
                st.session_state[DEMO_STATE].pop(kind, None)
            st.rerun()
        _results(item, prefix=prefix, day=day)
    else:
        st.caption("Nessun estratto caricato. Consulta gli esiti ufficiali o acquisisci un periodo.")
    if prefix == "gme":
        with st.expander("Fonti e accesso"):
            st.markdown(f"[Riferimento GME]({spec.source_url(segment)}) · "
                        f"[Manuale API]({g.MANUAL}) · [Condizioni GME]({g.TERMS})")


def _results(item, *, prefix, day=None):
    kind = item["kind"]
    spec = g.DATASETS[kind]
    rows = item["rows"]
    key = f"{prefix}_{kind}_{item['segment']}"
    if day is not None:
        day_col = spec.dates[-1]
        rows = [row for row in rows if row[day_col] == day.isoformat()]
    if not rows:
        st.info("Nessuna osservazione GME nel periodo selezionato.")
        return
    if item["missing"]:
        st.caption(f"{item['missing']} misure assenti nell’estratto.")
    if kind != "curve" and spec.dimensions:
        scopes = sorted({tuple(row[field] for field in spec.dimensions) for row in rows},
                        key=lambda parts: tuple(part or "" for part in parts))
        scope = st.selectbox("Perimetro", scopes,
                             format_func=lambda parts: " · ".join(part or FIELDS[field]+" non indicato"
                                 for field, part in zip(spec.dimensions, parts)),
                             key=key+"_scope")
        rows = [row for row in rows if tuple(row[field] for field in spec.dimensions) == scope]
    fields = [field for field in spec.units if any(row[field] is not None for row in rows)]
    if not fields:
        st.info("Tutte le misure del perimetro sono assenti.")
    elif kind == "curve":
        selected = st.selectbox("Data di flusso", sorted({row["FlowDate"] for row in rows}, reverse=True),
                                key=key+"_curve_day")
        rows = [row for row in rows if row["FlowDate"] == selected]
        _curve(rows, key)
    else:
        latest = rows[-1]
        main_field = PREFERRED.get(kind, "Price")
        highlights = {
            "prices": ("WeightedAveragePrice", "MaxPurchaseSRGPrice", "MinSaleSRGPrice"),
            "continuous": ("AveragePrice", "MWhVolumes"),
            "mgas": ("Price", "TotalVolumesMWh", "PurchasesTSO", "SalesTSO"),
            "mgs": ("Price", "Volumes", "SRGPurchases", "SRGSales"),
            "mpl": ("Price", "Volumes", "SRGVolumes"),
        }.get(kind, (main_field,))
        kpi_grid([(_label(field, spec, units=False), latest[field], spec.units[field] or "",
                   data_it(date.fromisoformat(latest[spec.date_field])) +
                   (" · unità non indicata" if spec.units[field] is None else ""), 3, "")
                  for field in highlights if latest[field] is not None])
        if day is None and len({row[spec.date_field] for row in rows}) == len(rows) and len(rows) > 1:
            field = st.selectbox("Serie", fields, index=fields.index(main_field) if main_field in fields else 0,
                                 format_func=lambda k: _label(k, spec), key=key+"_metric")
            _series(rows, spec, field, item, key)
    with st.expander("Osservazioni e provenienza", expanded=day is not None or kind == "curve"):
        st.dataframe(pd.DataFrame(rows).rename(columns={field: _label(field, spec) for field in rows[0]}),
                     hide_index=True, width="stretch")
        if item.get("request_id"):
            st.text("Richiesta GME · " + item["request_id"])
        if item["origin"] == "api":
            st.caption(f"Periodo richiesto {data_it(item['first'])} – {data_it(item['last'])} · data di pubblicazione assente nello schema.")
        st.caption("SHA-256 · " + item["sha"])
    if kind == "prices" and prefix == "gme":
        with st.expander("Stima dei prezzi di sbilanciamento"):
            selected = st.selectbox("Giorno gas", [row["FlowDate"] for row in reversed(rows)], key=key+"_calc_day")
            _valuation(item, date.fromisoformat(selected), key)


def _curve(rows, key):
    figure = go.Figure()
    for side, color in (("Acquisto", TEAL), ("Vendita", BLUE)):
        points = [row for row in rows if row["Type"].casefold() == side.casefold() and row["Volumes"] is not None]
        if points:
            figure.add_trace(go.Scatter(x=[float(row["Price"]) for row in points],
                                        y=[float(row["Volumes"]) for row in points],
                                        mode="markers", name=side, marker={"color": color}))
    if figure.data:
        figure.update_layout(template="plotly_dark", height=280, margin={"t": 16, "r": 16, "l": 48, "b": 50},
                             xaxis_title="Prezzo offerto (€/MWh)", yaxis_title="Volume (unità n.d.)")
        plot(figure, key+"_curve")


def _series(rows, spec, field, item, key):
    days = [date.fromisoformat(row[spec.date_field]) for row in rows]
    first, last = item.get("first", days[0]), item.get("last", days[-1])
    if (last - first).days > 3660:
        st.caption("Serie lunga. Seleziona un estratto più breve per il grafico.")
        return
    values = pd.Series([float(row[field]) if row[field] is not None else None for row in rows],
                       index=pd.to_datetime(days), dtype=float).reindex(pd.date_range(first, last, freq="D"))
    if values.notna().any():
        figure = mini_chart(values, _label(field, spec, units=False), "daily", spec.units[field] or "Unità n.d.", TEAL)
        figure.update_traces(mode="lines+markers", connectgaps=False)
        plot(figure.update_layout(height=280), key+"_series")


def overview_kpis(day):
    if not g.session_authorized():
        return
    cards = []
    for kind, field, caption in (("igi", "Price", "IGI · GME"),
                                 ("prices", "WeightedAveragePrice", "Prezzo medio di remunerazione · GME")):
        item = snapshot(kind, api_only=True)
        if item is None:
            continue
        rows = [row for row in item["rows"] if row["FlowDate"] == day.isoformat() and row[field] is not None]
        if len(rows) == 1:
            row = rows[0]
            metadata = " · ".join(part for part in (row.get("Product"), data_it(day),
                         f"Acquisito {local_time(item['acquired'])}") if part)
            cards.append((caption, row[field], g.EUR_MWH, metadata, 3, ""))
    if cards:
        kpi_grid(cards)
        st.caption("Fonte: " + g.SOURCE)


def balancing(day):
    kinds = ("prices", "mgas", "mgs", "mpl")
    kind = st.selectbox("Prezzi e interventi SRG", kinds,
                        format_func=lambda key: g.DATASETS[key].label, key="gme_balance_kind")
    if kind == "mpl":
        st.caption("La ricerca usa le date di sessione. Gli esiti mostrati si riferiscono al giorno gas selezionato.")
    panel(kind, prefix="gme_balance", day=day)


def _valuation(item, day, key, balance=None):
    from .gme_analysis import estimate_prices, settlement_preview
    st.caption("Stima · articolo 5 TIB e CdR XCII §4.4.1. Per volumi title inferiori a 2.000 MWh servono i 30 giorni precedenti.")
    with st.form(key+"_valuation"):
        left, right = st.columns(2)
        volume = left.number_input("Volume STSP title verificato (MWh)", min_value=0., value=None)
        rate = right.number_input("Small adjustment pubblicato (%)", min_value=0., max_value=10., value=None)
        ordinary = st.checkbox("Regime ordinario applicabile al giorno gas")
        calculate = st.form_submit_button("Calcola stima")
    if not calculate:
        return
    if volume is None or rate is None:
        st.info("Inserisci volume title e percentuale pubblicata per il periodo.")
        return
    try:
        if balance is not None:
            priced, value = settlement_preview(item, balance, D(str(volume)), D(str(rate)), ordinary=ordinary)
        else:
            priced = estimate_prices(item["rows"], day, D(str(volume)), D(str(rate)), ordinary=ordinary)
    except ValueError as error:
        st.warning(str(error))
        return
    cards = [(label, priced[field], g.EUR_MWH, priced["method"], 3, "") for label, field in (
             ("Prezzo acquisto stimato", "buy"), ("Prezzo vendita stimato", "sell"))]
    if balance is not None:
        cards.append(("Importo teorico", value, "€", "IVA esclusa · registro invariato", 2, ""))
    kpi_grid(cards)


def settlement(balance):
    item = snapshot("prices", api_only=True)
    if not item or not any(row["FlowDate"] == balance.day.isoformat() for row in item["rows"]):
        return
    with st.expander("Stima economica con parametri GME"):
        _credit(item)
        _valuation(item, balance.day, "gme_settlement", balance)


def risk():
    from .gme_analysis import price_backtest
    st.subheader("Rischio prezzo IGI")
    item = snapshot("igi", api_only=True)
    if not item or not item["rows"]:
        st.info("Carica fino a 31 giorni IGI in Mercato gas per calibrare il rischio prezzo.")
        return
    _credit(item)
    product = st.selectbox("Prodotto IGI", sorted({row["Product"] for row in item["rows"]}), key="gme_risk_product")
    try:
        result = price_backtest(item, product)
    except ValueError as error:
        st.info(str(error))
        return
    kpi_grid([
        ("Variazione D−1 · 10° percentile", result["lower"], g.EUR_MWH, "Calibrazione", 3, ""),
        ("Variazione D−1 · 90° percentile", result["upper"], g.EUR_MWH, "Calibrazione", 3, ""),
        ("Errore assoluto medio D−1", result["mae"], g.EUR_MWH, "Verifica fuori campione", 3, ""),
    ])
    st.caption(f"{result['train_days']} variazioni di calibrazione · test dal {data_it(result['test_start'])} · "
               f"{result['covered_days']}/{result['test_days']} variazioni nel range.")
    st.caption("Verifica retrospettiva sulla copia acquisita. La fonte non espone le versioni storiche disponibili a ogni data.")


def assistant():
    st.subheader("Indicatori GME · consultazione locale")
    cache = _private_cache()
    available = [key for key, item in (cache or {}).items() if item["origin"] == "api" and item["rows"]]
    if not available:
        st.caption("Carica un estratto in Mercato gas prima di consultare gli indicatori.")
        return
    kind, segment = st.selectbox("Indicatore", available,
                                 format_func=lambda key: g.DATASETS[key[0]].label + " · " + key[1],
                                 key="gme_assistant_indicator")
    item = snapshot(kind, segment, api_only=True)
    _credit(item)
    _results(item, prefix="gme_assistant")
