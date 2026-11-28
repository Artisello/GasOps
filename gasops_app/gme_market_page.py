"""GME workspace and session-only observations shared with existing views."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import BoundedSemaphore
from decimal import Decimal as D

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import gme_market as g
from .gas_calendar import closed_gas_day
from .italiano import data_it
from .models import utc_now
from .public_data import network_allowed
from .visuals import BLUE, TEAL, kpi_grid, local_time, mini_chart, plot

STATE = "gme_private_market_v2"
REFRESH_STATE = "gme_automatic_refresh_v1"
RECENT_TTL = timedelta(hours=1)
HISTORICAL_TTL = timedelta(hours=12)
ERROR_TTL = timedelta(minutes=30)
_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gasops-gme")
_SLOT = BoundedSemaphore()
CACHE_SIZE = 12
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
    "Reason": "Motivazione", "Zone": "Zona", "Hour": "Ora di flusso",
}
PREFERRED = {"prices": "WeightedAveragePrice", "continuous": "AveragePrice", "pgr": "RemunerationPrice"}


def _session_cache():
    cache = st.session_state.setdefault(STATE, {})
    if not g.api_configured():
        for key in tuple(cache):
            if cache[key]["origin"] == "api":
                del cache[key]
    return cache


def snapshot(kind, segment=None, *, api_only=False):
    item = _session_cache().get((kind, segment or g.DATASETS[kind].segments[0]))
    return item if item and (not api_only or item["origin"] == "api") else None


def _save(item):
    cache = _session_cache()
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
    source = g.DATASETS[item["kind"]].source_url(item["segment"])
    caption = (f"Fonte: {g.SOURCE} · {item['segment']} · "
               f"[{g.DATASETS[item['kind']].name}]({source})")
    if item["origin"] == "api":
        caption += f" · acquisito {local_time(item['acquired'])}"
    else:
        caption += " · estratto caricato manualmente · provenienza dichiarata"
    st.caption(caption)


def _window(kind, segment, ending, days):
    return kind, segment, max(g.FIRST_DAY, ending-timedelta(days=days-1)), ending


def _submit(window, cutoff):
    from .gme_api import session_client
    if not _SLOT.acquire(blocking=False):
        return None
    try:
        future = _WORKER.submit(session_client().fetch, *window, cutoff)
    except Exception:
        _SLOT.release()
        raise
    future.add_done_callback(lambda _: _SLOT.release())
    return future


def _next_window(windows, cache, attempts, now, cutoff):
    for kind, segment, first, last in windows:
        item = cache.get((kind,segment))
        covered = item and item["origin"]=="api" and item["first"]<=first<=last<=item["last"]
        if covered:
            first, last = item["first"], item["last"]
        window = kind, segment, first, last
        ttl = RECENT_TTL if last >= cutoff-timedelta(days=6) else HISTORICAL_TTL
        checked, error = attempts.get(window, (None,None))
        if checked and ((error and now-checked<ERROR_TTL) or (covered and now-checked<ttl)):
            continue
        if covered and not error and now-item["acquired"]<ttl:
            continue
        return window
    return None


def _finished(window, result, attempts):
    # Preserve the previous edition if the publisher returns an empty response.
    previous = snapshot(*window[:2], api_only=True)
    error = None
    try:
        item = result.result()
        if item["rows"] or not previous or not previous["rows"]:
            _save(item)
        else:
            error = "Nessuna osservazione nel nuovo periodo."
    except ValueError as exc:
        error = str(exc)
    attempts[window] = (utc_now(),error)
    if len(attempts)>32:
        del attempts[next(iter(attempts))]


@st.fragment(run_every=15)
def _automatic_sources(windows):
    if not g.api_configured() or not windows:
        st.session_state.pop(REFRESH_STATE, None)
        return
    state = st.session_state.setdefault(REFRESH_STATE, {"attempts":{}})
    attempts = state["attempts"]
    if state.get("working"):
        window, job = state["working"]
        if not job.done():
            st.caption("Acquisizione GME in corso.")
            return
        state.pop("working")
        _finished(window,job,attempts)
        st.rerun()
    now = utc_now()
    cutoff = closed_gas_day(now)
    window = _next_window(windows,_session_cache(),attempts,now,cutoff)
    if window and network_allowed():
        try:
            job = _submit(window,g.pun_closed_day(now) if window[0]=="pun" else cutoff)
        except ValueError as exc:
            attempts[window] = (now,str(exc))
        else:
            if job is not None:
                state["working"] = (window,job)
                st.caption("Acquisizione GME in corso.")
                return
    for request in windows:
        errors = [error for key, (_,error) in attempts.items()
                  if key[:2]==request[:2] and key[2]<=request[2]<=request[3]<=key[3]]
        if errors and errors[-1]:
            st.caption(g.DATASETS[request[0]].label + " · " + errors[-1])


def _panel_period(kind, segment, prefix, cutoff, day):
    spec = g.DATASETS[kind]
    ending = min(day or cutoff,cutoff)
    _,_,first,last = _window(kind,segment,ending,31 if kind in ("igi","prices","pun") else 7)
    if kind=="pun":
        first=max(first,g.PUN_FIRST_DAY)
        last=max(last,first)
    context = f"{prefix}_{kind}_{segment}" + (f"_{day.isoformat()}" if day else "")
    period = st.date_input("Periodo · "+FIELDS[spec.date_field].lower(),value=(first,last),
        min_value=g.PUN_FIRST_DAY if kind=="pun" else g.FIRST_DAY,max_value=cutoff,format="DD/MM/YYYY",key=context+"_period")
    if len(period)!=2 or not 0 <= (period[1]-period[0]).days < 31:
        st.caption("Seleziona un intervallo fino a 31 giorni.")
        return None
    return period


def panel(kind=None, *, prefix="gme", day=None):
    if kind is None:
        st.subheader("Mercato GME · gas ed elettricità")
        kind = st.selectbox("Dataset", tuple(k for k in g.DATASETS if k!="pun")+("pun",),
                            format_func=lambda k: g.DATASETS[k].label, key="gme_dataset")
    spec = g.DATASETS[kind]
    cutoff = g.pun_closed_day(utc_now()) if kind=="pun" else closed_gas_day(utc_now())
    segment = spec.segments[0]
    if len(spec.segments) > 1:
        segment = st.selectbox("Segmento", spec.segments, key=prefix+"_segment_"+kind)
    if g.api_configured():
        period = _panel_period(kind,segment,prefix,cutoff,day)
        if period:
            _automatic_sources(((kind,segment,*period),))
        item = snapshot(kind,segment,api_only=True)
        if item:
            _credit(item)
            if period:
                rows = tuple(row for row in item["rows"] if
                             period[0].isoformat() <= row[spec.date_field] <= period[1].isoformat())
                _results({**item,"rows":rows,"first":max(period[0],item["first"]),
                          "last":min(period[1],item["last"])},prefix=prefix,day=day)
        if kind == "pgr":
            st.caption("PGR indicato come inattivo nel manuale API.")
    else:
        st.info("Fonte API GME non configurata. Consulta gli esiti ufficiali.")
    if prefix == "gme":
        with st.expander("Fonti e quote"):
            if g.api_configured():
                from .gme_api import QUOTAS, session_client
                try:
                    quota = session_client().last_quota
                except ValueError:
                    quota = None
                if quota is not None:
                    counts,checked = quota
                    st.caption("Quote verificate alle "+local_time(checked))
                    st.dataframe([{"Quota":label,"Uso":counts[field][0],"Limite":counts[field][1]}
                                  for field,_,label in QUOTAS],hide_index=True,width="stretch")
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
    if kind=="pun":
        first,last=item["first"],item["last"]
        value=g.pun_mean(item,first,last)
        if value is not None:
            kpi_grid([("PUN Index GME · media oraria",value,g.EUR_MWH,
                       data_it(first)+" – "+data_it(last),2,"")])
        else:
            st.info("Media non disponibile: periodo orario incompleto.")
        with st.expander("Prezzi orari"):
            st.dataframe(pd.DataFrame(rows).rename(columns={"FlowDate":"Data","Hour":"Ora","Price":"€/MWh"}),hide_index=True,width="stretch")
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


def _prices(day, *, include_extremes=False, kinds=("igi","prices")):
    fields = [("igi","Price","IGI · GME"),("prices","WeightedAveragePrice","Prezzo medio di remunerazione · GME")]
    if include_extremes:
        fields.extend(("prices",field,FIELDS[field]) for field in ("MaxPurchaseSRGPrice","MinSaleSRGPrice"))
    cards = []
    for kind, field, label in fields:
        if kind not in kinds:
            continue
        item = snapshot(kind,api_only=True)
        if not item:
            continue
        rows = [row for row in item["rows"] if row["FlowDate"]==day.isoformat() and row[field] is not None]
        if len(rows)!=1:
            continue
        row = rows[0]
        product = row.get("Product")
        previous = next((r[field] for r in item["rows"] if r["FlowDate"]==(day-timedelta(days=1)).isoformat()
                         and r.get("Product")==product),None)
        metadata = [product,data_it(day),f"Acquisito {local_time(item['acquired'])}"]
        if previous is not None:
            delta = format(row[field]-previous,"+.3f").replace(".",",")
            metadata.append(f"{delta} €/MWh su D−1")
        cards.append((label,row[field],g.EUR_MWH," · ".join(filter(None,metadata)),3,""))
    return cards


def _headline_windows(day, kinds=("igi","prices")):
    ending = min(day,closed_gas_day(utc_now()))
    return tuple(_window(kind,g.DATASETS[kind].segments[0],ending,31) for kind in kinds)


def overview_kpis(day):
    if not g.api_configured():
        return
    st.markdown("**Prezzi gas**")
    _automatic_sources(_headline_windows(day))
    cards = _prices(day,include_extremes=True)
    if cards:
        kpi_grid(cards)
        st.caption("Fonte: " + g.SOURCE)
    else:
        st.caption("Nessun prezzo GME disponibile per il giorno gas selezionato.")


def daily_context(period):
    """Pair a dated Italian operating readout with market evidence in the browser."""
    if not g.api_configured():
        return
    try:
        day = date.fromisoformat(period or "")
    except (TypeError,ValueError):
        return
    if not g.FIRST_DAY<=day<=closed_gas_day(utc_now()):
        return
    with st.expander("Prezzi GME del giorno gas · consultazione locale"):
        _automatic_sources(_headline_windows(day))
        cards = _prices(day)
        if cards:
            kpi_grid(cards)
            st.caption("Fonte: " + g.SOURCE)
        else:
            st.caption("Nessun prezzo GME disponibile per "+data_it(day)+".")


def assistant_prices(request, as_of, *, report_id, refresh=False):
    """Question-specific local readout; never reacquire when reading history."""
    key="assistant_gme_readouts_v1"
    saved=st.session_state.get(key,{})
    result=saved.get(report_id)
    if refresh and result is None:
        result=_assistant_price_readout(request,as_of)
        saved={**saved,report_id:result}
        st.session_state[key]=dict(list(saved.items())[-12:])
    st.markdown("**Prezzi GME richiesti · dati locali**")
    if result is None:
        st.caption("Nessuna copia dei prezzi conservata per questa analisi.")
    elif result["cards"]:
        kpi_grid(result["cards"])
        st.caption("Fonte: "+g.SOURCE+" · dati della risposta originale")
    if result is not None and result.get("message"):
        st.caption(result["message"])
    st.markdown("[Mercato e previsioni](/market)")


def _assistant_price_readout(request, as_of):
    if not g.api_configured():
        return {"cards":[],"message":"API GME non configurata."}
    requested=request.get("day")
    pun_cards=[]
    pun_message=""
    if "pun" in request.get("kinds",()):
        item=snapshot("pun",api_only=True)
        end=g.pun_closed_day(as_of)
        first=last=None
        if request.get("pun_unsupported"):
            pun_message="PUN Index: indica un giorno o un mese concluso; confronto e altre granularità non supportati."
        elif request.get("pun_month"):
            from calendar import monthrange
            first=date.fromisoformat(request["pun_month"])
            last=first.replace(day=monthrange(first.year,first.month)[1])
        elif requested:
            first=last=date.fromisoformat(requested)
        elif item:
            candidates=sorted({date.fromisoformat(row["FlowDate"]) for row in item["rows"]},reverse=True)
            first=last=next((d for d in candidates if d<=end and g.pun_mean(item,d,d) is not None),None)
        if not pun_message:
            value=g.pun_mean(item,first,last) if first and last and last<=end else None
            if value is not None:
                period=data_it(first) if first==last else data_it(first)+" – "+data_it(last)
                pun_cards.append(("PUN Index GME · elettricità",value,g.EUR_MWH,
                    period+" · media oraria · acquisito "+local_time(item["acquired"]),2,""))
            else:
                pun_message="PUN Index GME non disponibile per il periodo completo. Acquisisci il dataset PUN in Mercato e previsioni."
        if not any(k in request.get("kinds",()) for k in ("igi","prices")):
            return {"cards":pun_cards,"message":pun_message}
    ending=date.fromisoformat(requested) if requested else closed_gas_day(as_of)
    if not g.FIRST_DAY<=ending<=closed_gas_day(utc_now()):
        return {"cards":pun_cards,"message":" ".join(filter(None,(pun_message,"La data richiesta non è un giorno gas concluso del periodo supportato.")))}
    kinds=tuple(kind for kind in ("igi","prices") if kind in request.get("kinds",()))
    # Price acquisition belongs to the market workspace. Only use the existing
    # validated session cache for explicitly requested GME readouts.
    cards=[]
    for kind in kinds:
        day=ending
        if not requested:
            item=snapshot(kind,api_only=True)
            field="Price" if kind=="igi" else "WeightedAveragePrice"
            latest=max((row["FlowDate"] for row in item["rows"]
                        if row["FlowDate"]<=ending.isoformat() and row[field] is not None),default=None) if item else None
            if latest:
                day=date.fromisoformat(latest)
        cards.extend(_prices(day,include_extremes=True,kinds=(kind,)))
    return {"cards":pun_cards+cards,"message":" ".join(filter(None,(pun_message,"Nessun dato gas GME già acquisito per il periodo richiesto. Aggiorna i prezzi in Mercato e previsioni." if not cards else "")))}


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
    if g.api_configured():
        _automatic_sources((_headline_windows(balance.day)[1],))
    item = snapshot("prices", api_only=True)
    if not item or not any(row["FlowDate"] == balance.day.isoformat() for row in item["rows"]):
        return
    with st.expander("Stima economica con parametri GME"):
        _credit(item)
        _valuation(item, balance.day, "gme_settlement", balance)


def risk():
    from .gme_analysis import price_backtest
    st.subheader("Rischio prezzo IGI")
    _automatic_sources((_headline_windows(closed_gas_day(utc_now()))[0],))
    item = snapshot("igi", api_only=True)
    if not item or not item["rows"]:
        st.info("Serie IGI in attesa di osservazioni validate.")
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


