"""Lean synthetic credit risk desk; inputs never submitted to external services."""
from decimal import Decimal as D
import csv
import io

import streamlit as st

from .credit_risk import (CDR, LNG, additional_guarantee_90, credit_position,
                          lng_psv_security, lng_security, patt_horizon, stress_patt)
from .italiano import numero
from .visuals import info, kpi_grid


def _amount(label, value, key, *, signed=False, step=10000.):
    return D(str(st.number_input(label, min_value=-1e12 if signed else 0.,
                                 max_value=1e12, value=float(value),
                                 step=step, key="credit_"+key)))


def _lng_panel():
    with st.expander("Piombino · garanzie GNL"):
        st.caption("Un anno termico · caso sintetico · garanzia valida al netto delle escussioni.")
        a,b=st.columns(2)
        with a:
            slots=[_amount(f"Slot {i+1} di maggior valore (€)",v,f"slot_{i}")
                   for i,v in enumerate((200000,180000,150000))]
            annual=_amount("Impegni annui (€)",1300000,"lng_annual")
        with b:
            transport=_amount("Corrispettivi trasporto (€)",80000,"lng_transport")
            guarantee=_amount("Garanzia GNL efficace (€)",750000,"lng_guarantee")
            ship=_amount("Volume tecnico nave maggiore (MWh)",90000,"lng_ship")
            advanced=_amount("Gas anticipato (MWh)",105000,"lng_advanced")
        try:
            result=lng_security(slots,annual,transport,guarantee)
            kpi_grid([("Garanzia minima",result["required"],"€","max(3 slot; 36% annuo) + trasporto",2,""),
                      ("Capienza residua",result["headroom"],"€","Garanzia efficace − minimo",2,
                       "rose" if result["headroom"]<0 else ""),
                      ("Garanzia vendita PSV",lng_psv_security(ship,advanced),"MWh","Max nave / gas anticipato",1,"")])
        except ValueError as exc:
            st.warning(str(exc))
        info("Regole GNL",LNG,"La copertura GNL è distinta da G del bilanciamento. La vendita PSV registrata può incidere su Patt; non sommare automaticamente le due garanzie. Non verifica rating, validità, più anni termici o ammissibilità della richiesta.")


def credit_risk_panel():
    st.subheader("Credit Risk Intelligence")
    st.caption("DEMO-001 · simulazione · importi di bilanciamento IVA inclusa ove prevista.")
    a,b=st.columns(2)
    with a:
        pfat=_amount("Pfat · fatturato non scaduto (€)",420000,"pfat",signed=True)
        pdet=_amount("Pdet · non definitivo/non fatturato (€)",280000,"pdet",signed=True)
        patt=_amount("Patt · esposizione attesa (€)",220000,"patt",signed=True)
    with b:
        g=_amount("G · garanzie riconosciute (€)",1100000,"g")
        c=_amount("C · scaduto non pagato (€)",100000,"c")
        info("Componenti",CDR,"G deve includere solo garanzie riconosciute ed efficaci: deposito, fideiussione, gas in stoccaggio valorizzato e rating/garanzia societaria secondo il Codice. C esclude le fatture non scadute già in Pfat.")
    try:
        current=credit_position(pfat,pdet,patt,[g],c)
    except ValueError as exc:
        st.warning(str(exc))
        return None
    with st.container(border=True,key="panel_guarantee_usage"):
        st.caption("Utilizzo del limite MEPSu")
        ratio=current["ratio"]
        st.markdown("### "+(numero(ratio,1)+"%" if ratio is not None else "—"))
        if ratio is not None:
            st.progress(float(max(D(0),min(D(100),ratio))/100))
        if current["status"]=="LIMITE":
            st.error("EPSu ≥ MEPSu: condizione non rispettata nella simulazione.")
        elif current["status"]=="ATTENZIONE":
            st.warning("Soglia di attenzione del 90% raggiunta.")
        elif current["status"]!="OK":
            st.warning("MEPSu non positivo: verifica specialistica anche se la disuguaglianza è rispettata.")
    kpi_grid([("EPSu",current["eps"],"€","Pfat + Pdet + Patt",2,""),
              ("MEPSu",current["meps"],"€","G − C",2,""),
              ("Margine residuo",current["headroom"],"€","MEPSu − EPSu",2,
               "rose" if current["headroom"]<=0 else "")])
    with st.expander("Early warning · stress su Patt",expanded=True):
        check=st.checkbox("Regolarità dei pagamenti verificabile nel semestre applicabile",
                          value=True,key="credit_verified")
        a,b=st.columns(2)
        with a:
            bal=D(str(st.number_input("Importi irregolari bilanciamento (%)",0.,100.,0.,
                                      disabled=not check,key="credit_late_bal")))
        with b:
            tr=D(str(st.number_input("Importi irregolari trasporto (%)",0.,100.,0.,
                                     disabled=not check,key="credit_late_tr")))
        horizon=patt_horizon(bal,tr,verifiable=check)
        st.caption(f"Orizzonte Patt: {horizon} giorni · 3 se regolare; 5 oltre 10% fino a 20%; 7 oltre 20% o non verificabile/nuovo.")
        a,b=st.columns(2)
        with a:
            daily=_amount("Ulteriore deficit giornaliero (MWh)",500,"daily",step=100.)
            price=_amount("Prezzo stimato (€/MWh)",40,"price",step=1.)
        with b:
            vat=D(str(st.number_input("IVA applicabile (%)",0.,100.,22.,key="credit_vat")))
            psv=_amount("Ulteriore deficit PSV non incluso (MWh)",0,"psv",step=100.)
        delta=stress_patt(horizon,daily,price,vat,psv)
        projection=credit_position(pfat,pdet,patt+delta,[g],c)
        kpi_grid([("EPSu stress",projection["eps"],"€",projection["status"],2,""),
                  ("Margine stress",projection["headroom"],"€","MEPSu invariato",2,
                   "rose" if projection["headroom"]<=0 else ""),
                  ("G aggiuntiva teorica",additional_guarantee_90(projection),"€","Target utilizzo ≤90%",2,"")])
        info("Metodo",CDR,"Stress incrementale: non ricostruisce Patt ufficiale. Pr regolatorio = media dei prezzi di sbilanciamento di acquisto del mese precedente, €/kWh a sei decimali (convertire in €/MWh). Immettere solo deficit aggiuntivi non già compresi nel Patt di base; nessuna sostituzione con prezzi spot. Le transazioni PSV registrate possono riguardare date oltre l’orizzonte.")
    _lng_panel()
    st.divider()
    from .credit_snapshot_page import panel as analytical_panel
    analytical_panel()
    output=io.StringIO()
    fields=["scenario","pfat","pdet","patt","g","c","eps","meps","headroom","ratio","status",
            "condition_met","reference","horizon_days","mode"]
    writer=csv.DictWriter(output,fieldnames=fields)
    writer.writeheader()
    for name,row in (("base",current),("stress",projection)):
        writer.writerow({**row,"scenario":name,"horizon_days":horizon,"mode":"SIMULAZIONE"})
    st.download_button("Scarica controllo rischio CSV",output.getvalue(),
                       "igor-credit-risk.csv","text/csv",key="credit_export")
    info("Fonti e limiti",CDR,LNG,"Edizioni di studio fornite. A 100%: perdita dei requisiti e misure previste dal §1.4.5; il ripristino decorre dalla comunicazione, non dalla simulazione. Nessuna misura eseguita. Nessun dato utente SRG effettivo.")
    return current
