"""Management-oriented ACER benchmarking; published gas-year observations only."""
from statistics import median
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .acer_baf_2026 import all_baf_rows, zone_changes, SELECTED, PDF_SHA256
from .acer_market import REPORT_2025, REPORT_2026, BALANCING
from .italiano import numero
from .visuals import TEAL, BLUE, MUTED, kpi_grid, plot, info

CURRENT="2024/2025"
PREVIOUS="2023/2024"
LABELS={"imbalance_share":"Volumi di sbilanciamento / mercato fisico",
        "net_adjusted_neutrality":"Neutralità netta rettificata / volume",
        "tso_buy_share":"Quota acquisti TSO",
        "tso_action_days_share":"Giorni con azioni di bilanciamento TSO",
        "tso_action_volume_share":"Volume azioni TSO / mercato fisico"}
NOTES={"imbalance_share":"Rapporto tra volumi di sbilanciamento e mercato fisico. Un valore elevato non dimostra da solo inefficienza.",
       "net_adjusted_neutrality":"Neutralità positiva: surplus da attribuire agli utenti. Negativa: costo da recuperare. Non profitto TSO.",
       "tso_buy_share":"Quota di acquisti nelle azioni TSO; la vendita è il complemento al 100%. Solo zone con valori numerici espliciti.",
       "tso_action_days_share":"Quota di giorni con azioni TSO nel perimetro selezionato ACER.",
       "tso_action_volume_share":"Volume delle azioni TSO rispetto al mercato fisico nel perimetro selezionato ACER."}


def precision(metric):
    return 2 if metric in ("net_adjusted_neutrality","tso_action_volume_share") else 0 if metric in ("tso_buy_share","tso_action_days_share") else 1


def unit_of(metric):
    return "€/MWh" if metric=="net_adjusted_neutrality" else "%"


def display_value(v,metric,signed=False):
    return numero(v,precision(metric),signed=signed)


def selected_zones(rows,metric):
    """Rank only published numeric observations in the same gas year, ties share rank."""
    compare=zone_changes(rows,metric)
    current=sorted((r for r in compare if r[CURRENT] is not None),
                   key=lambda r:(-r[CURRENT],r["zone"]))
    values=[r[CURRENT] for r in current]
    it=next((r for r in current if r["zone"]=="IT"),None)
    rank=1+sum(v>it[CURRENT] for v in values) if it else None
    return compare,current,median(values) if values else None,it,rank


def zone_subset(current,view):
    if view=="Tutte":
        return current
    subset=current[:5] if view=="Valori più alti" else current[-5:]
    codes={r["zone"] for r in subset}|{"IT"}
    return [r for r in current if r["zone"] in codes]


def zone_figure(rows,metric,mid,previous=False):
    unit=unit_of(metric)
    names=[r["zone"] for r in rows]
    values=[float(r[CURRENT]) for r in rows]
    fig=go.Figure(go.Bar(name=CURRENT,y=names,x=values,orientation="h",
        marker_color=[TEAL if z=="IT" else BLUE for z in names],width=.55,
        text=[display_value(r[CURRENT],metric)+" "+unit for r in rows],
        textposition="outside",cliponaxis=False,
        textfont={"color":"#e7edf5","size":12},
        hovertemplate="%{y}: %{text}<extra>"+CURRENT+"</extra>"))
    old=[r for r in rows if r[PREVIOUS] is not None]
    if previous and old:
        fig.add_trace(go.Scatter(name=PREVIOUS,y=[r["zone"] for r in old],
            x=[float(r[PREVIOUS]) for r in old],mode="markers",
            marker={"size":9,"symbol":"diamond","color":"#f2be72","line":{"width":1,"color":"#101923"}},
            text=[display_value(r[PREVIOUS],metric)+" "+unit for r in old],
            hovertemplate="%{y}: %{text}<extra>"+PREVIOUS+"</extra>"))
    if mid is not None:
        fig.add_vline(x=float(mid),line_dash="dot",line_color=MUTED,line_width=1.5)
    domain=values+[0]+([float(mid)] if mid is not None else [])+([float(r[PREVIOUS]) for r in old] if previous else [])
    low,high=min(domain),max(domain)
    span=max(high-low,.01 if metric=="net_adjusted_neutrality" else 1)
    fig.update_layout(template="plotly_dark",separators=",.",paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",height=max(245,36*len(rows)+70),
        margin={"l":10,"r":18,"t":35,"b":35},font={"color":MUTED,"size":13},
        legend={"orientation":"h","x":0,"y":1.08},showlegend=bool(previous and old),
        xaxis={"range":[low-span*.22,high+span*.28],"nticks":6,"automargin":True,"title":unit,
               "gridcolor":"rgba(153,180,214,0.09)","zeroline":True,"zerolinecolor":"#637891"},
        yaxis={"categoryorder":"array","categoryarray":names,"autorange":"reversed","automargin":True,"showgrid":False})
    return fig


def trend_figure(aggregate,italy,metric):
    fig=go.Figure()
    for rows,name,color in ((aggregate,"Zone comparabili ACER",BLUE),(italy,"Italia",TEAL)):
        if rows:
            rows=sorted(rows,key=lambda r:r["gas_year"])
            fig.add_trace(go.Scatter(x=[r["gas_year"] for r in rows],y=[float(r["value"]) for r in rows],
                name=name,mode="lines+markers",connectgaps=False,line={"color":color,"width":2.5},
                marker={"size":7},text=[display_value(r["value"],metric)+" %" for r in rows],
                hovertemplate="%{x}: %{text}<extra>"+name+"</extra>"))
    years=sorted({r["gas_year"] for r in aggregate+italy})
    fig.update_layout(template="plotly_dark",separators=",.",height=310,paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",margin={"l":10,"r":18,"t":45,"b":20},font={"color":MUTED,"size":12},
        xaxis={"type":"category","categoryorder":"array","categoryarray":years,"automargin":True},
        yaxis={"title":"%","nticks":6,"automargin":True,"gridcolor":"rgba(153,180,214,0.12)"},
        legend={"orientation":"h","y":1.1},showlegend=len(fig.data)>1)
    return fig


def panel():
    st.caption("Report ACER · ottobre 2026 · Anno gas 2024/2025 · dati pubblicati, non live")
    try:
        rows=all_baf_rows()
    except (OSError,ValueError):
        st.error("Archivio benchmark ACER non valido.")
        return
    frame=pd.DataFrame(rows)
    cards=[]
    for metric,label in (("imbalance_share","Sbilanciamenti / mercato fisico"),
                         ("net_adjusted_neutrality","Neutralità rettificata"),("tso_buy_share","Quota acquisti TSO")):
        _,_,_,it,_=selected_zones(rows,metric)
        if it is None:continue
        d=it["delta"]
        detail="Anno gas "+CURRENT
        if d is not None:
            detail=("Invariato alla precisione pubblicata" if d==0 else display_value(d,metric,True)+(" €/MWh" if metric=="net_adjusted_neutrality" else " pp"))+" · vs "+PREVIOUS
            if metric!="tso_buy_share":detail+="*"
        cards.append((label,it[CURRENT],unit_of(metric),detail,precision(metric),""))
    st.markdown("**Italia**")
    kpi_grid(cards)
    st.caption("* Confronto con la trascrizione dell’edizione precedente non verificata visivamente.")
    info("Indicatori e limiti",*(NOTES[k] for k in ("imbalance_share","net_adjusted_neutrality","tso_buy_share")),
         "Differenze tra zone dipendono anche da regole, liquidità e topologia. Nessun ranking di performance.")
    mode=st.radio("Vista",["Confronto zone","Trend europeo"],horizontal=True,key="acer_baf_view",label_visibility="collapsed")
    if mode=="Confronto zone":
        metric=st.selectbox("Indicatore",["imbalance_share","net_adjusted_neutrality","tso_buy_share"],
                            format_func=LABELS.__getitem__,key="acer_baf_metric_2026")
        compare,current,mid,it,rank=selected_zones(rows,metric)
        st.caption(NOTES[metric])
        if not current:
            st.info("Nessuna osservazione pubblicata per l’indicatore.")
            return
        detail="Mediana non ponderata delle "+str(len(current))+" zone con valore pubblicato"
        if it:
            diff=it[CURRENT]-mid
            delta_unit=" €/MWh" if metric=="net_adjusted_neutrality" else " pp"
            kpi_grid([("Italia",it[CURRENT],unit_of(metric),"Anno gas "+CURRENT,precision(metric),""),
                      ("Mediana zone",mid,unit_of(metric),str(len(current))+" zone osservate",precision(metric),""),
                      ("Posizione Italia",rank,"/ "+str(len(current)),"Ordine decrescente, pari merito",0,"")])
            st.caption("Italia: "+("in linea con la mediana alla precisione dei dati" if diff==0 else display_value(diff,metric,True)+delta_unit+" rispetto alla mediana")+" · "+detail+". Non è una media UE né una classifica di efficienza.")
        a,b=st.columns([3,2],vertical_alignment="center")
        view=a.radio("Zone mostrate",["Valori più alti","Valori più bassi","Tutte"],horizontal=True,key="acer_baf_zone_filter")
        previous=b.checkbox("Mostra "+PREVIOUS,key="acer_baf_previous")
        subset=zone_subset(current,view)
        st.caption(str(len(subset))+" zone mostrate · Italia sempre inclusa · linea tratteggiata: mediana di tutte le zone osservate.")
        plot(zone_figure(subset,metric,mid,previous),"acer_baf_comparison")
        with st.expander("Tabella completa delle zone"):
            st.dataframe(pd.DataFrame(compare).rename(columns={"zone":"Zona","unit":"Unità","delta":"Variazione"}),
                         hide_index=True,width="stretch")
            st.caption("Variazione in pp per quote; €/MWh per neutralità. Dato mancante ≠ zero. I confronti con il 2023/2024 di sbilanciamenti e neutralità hanno la limitazione indicata sopra.")
        visible=frame[(frame.zone!=SELECTED)&(frame.metric==metric)]
    else:
        metric=st.selectbox("Indicatore",["tso_action_days_share","tso_action_volume_share","imbalance_share"],
                            format_func=LABELS.__getitem__,key="acer_baf_eu_metric")
        aggregate=[r for r in rows if r["zone"]==SELECTED and r["metric"]==metric]
        aggregate.sort(key=lambda r:r["gas_year"])
        italy=[r for r in rows if r["zone"]=="IT" and r["metric"]==metric] if metric=="imbalance_share" else []
        st.caption(NOTES[metric])
        if aggregate:
            latest=aggregate[-1]
            before=aggregate[-2] if len(aggregate)>1 else None
            change=latest["value"]-before["value"] if before else None
            kpi_grid([("Zone comparabili ACER",latest["value"],"%",latest["gas_year"],precision(metric),""),
                      ("Variazione annua",change,"pp","vs "+before["gas_year"] if before else "Non disponibile",precision(metric),"")])
            plot(trend_figure(aggregate,italy,metric),"acer_baf_trend")
        else:
            st.info("Serie storica non disponibile per questo indicatore.")
        st.caption("Perimetro ACER comparabile nel tempo, non intera UE. Austria, Bulgaria, Germania, Finlandia, Francia, IGB e Portogallo escluse. La serie Italia, se presente, ha soltanto due anni disponibili e un perimetro distinto.")
        visible=frame[((frame.zone==SELECTED)|((frame.zone=="IT")&(metric=="imbalance_share")))&(frame.metric==metric)]
        with st.expander("Dati del trend"):
            st.dataframe(visible[["zone","gas_year","value","unit","page"]],hide_index=True,width="stretch")
    with st.expander("Fonti, dati e metodologia"):
        st.markdown(f"[Report 2026, pp. 9–11, 15–16, 19]({REPORT_2026}) · [Report 2025, pp. 16 e 19]({REPORT_2025}) · [Dashboard ACER]({BALANCING})")
        st.caption("83 osservazioni trascritte dalle etichette e dal testo del PDF 2026 fornito. Zero è arrotondato, non assenza. Il grafico scatter di p. 13 non riporta valori puntuali leggibili; nessuna stima. Conteggi delle categorie p. 16 incoerenti (22 dichiarate, 8+8+7=23), non importati. Quota acquisti: entrambi gli anni esplicitamente riportati a p. 16 del PDF 2026.")
        st.text("SHA-256 PDF 2026: "+PDF_SHA256)
        st.download_button("Scarica dati selezionati con fonte",visible.to_csv(index=False),"igor-acer-baf-selection.csv","text/csv",key="acer_baf_2026_selection")
        st.download_button("Scarica intero archivio BAF",frame.to_csv(index=False),"igor-acer-baf-all.csv","text/csv",key="acer_baf_2026_all")
