"""Lean HS1 study desk; inputs stay local to the Streamlit session."""
import csv
from decimal import Decimal as D
from io import StringIO
import streamlit as st
from .models import utc_now
from .italiano import numero
from .visuals import kpi_grid, rows, info
from .storage_balancing import (REFERENCE,system_balance,user_balance,mgs_limits,
                                template,parse_system_csv)


def _input(label,value,key,*,nonnegative=False,help=None):
    return D(str(st.number_input(label,min_value=0.0 if nonnegative else -1e9,
                                 max_value=1e9,value=float(value),step=0.1,
                                 format="%.3f",key="hs1_"+key,help=help)))


def _tone(x):
    return "rose" if x<0 else ""


def _findings(result):
    for finding in result["findings"]:st.warning(finding)


def _system():
    st.caption("Simulazione · F = ΔG + C · flusso positivo in iniezione, negativo in erogazione.")
    with st.container(border=True):
        a,b,c=st.columns(3)
        with a:opening=_input("Giacenza iniziale · GWh",800,"opening",nonnegative=True)
        with b:flow=_input("Flusso netto F · GWh",-40,"flow")
        with c:cons=_input("Consumi C · GWh",2,"cons",nonnegative=True)
        observed=renoms=snt=None
        with st.expander("Confronto con dati indipendenti e rinomine"):
            if st.checkbox("Giacenza finale osservata disponibile",key="hs1_has_observed"):
                observed=_input("Giacenza finale osservata · GWh",758,"observed",nonnegative=True)
            if st.checkbox("Totale rinomine confermate disponibile",key="hs1_has_renoms"):
                renoms=_input("Rinomine confermate · GWh",-35,"renoms")
                if st.checkbox("Programma SNT disponibile",key="hs1_has_snt"):
                    snt=_input("SNT · GWh",0,"snt")
            tolerance=_input("Tolleranza di controllo · GWh",.01,"tolerance",nonnegative=True)
        r=system_balance(opening,flow,cons,observed_closing=observed,
                         confirmed_renominations=renoms,snt=snt,tolerance=tolerance)
        kpi_grid([("Giacenza finale calcolata",r["closing"],"GWh","Iniziale + F − C",3,_tone(r["closing"])),
                  ("Variazione giacenza",r["delta"],"GWh","F − C",3,""),
                  ("Differenza di quadratura",r["residual"],"GWh",r["status"],3,"rose" if r["residual"] is not None and abs(r["residual"])>tolerance else "")])
        if renoms is not None:
            rows([("STOP · F − rinomine",numero(r["stop"],3)+" GWh"),
                  ("ST · SNT + STOP",numero(r["st"],3)+(" GWh" if r["st"] is not None else ""))])
            st.caption("STOP è una differenza energetica, non il costo MGS né il SAS di rete.")
        _findings(r)
    with st.expander("Controlla bilanci giornalieri da CSV"):
        st.caption("Solo estratti HS1 autorizzati e non riservati, medesimo perimetro e unità. Nessuna imputazione o invio all’AI.")
        st.download_button("Scarica modello CSV",template(),"igor-hs1-bilanci.csv","text/csv",key="hs1_template")
        file=st.file_uploader("Bilanci HS1 · GWh",type=["csv"],key="hs1_system_csv")
        st.caption("I primi quattro campi sono obbligatori; giacenza finale, rinomine e SNT possono essere vuoti. Giorni gas conclusi, senza duplicati.")
        if file is not None:
            try:data=parse_system_csv(file.getvalue(),utc_now(),tolerance)
            except (ValueError,UnicodeError,csv.Error,OverflowError) as error:
                st.warning("Importazione non valida: "+str(error))
            else:
                compared=[x for x in data if x["residual"] is not None]
                bad=sum(bool(x["findings"]) for x in data)
                kpi_grid([("Giorni importati",len(data),"","Nessuna copertura mensile presunta",0,""),
                          ("Giorni confrontabili",len(compared),"","Giacenza indipendente fornita",0,""),
                          ("Da verificare",bad,"","Controlli selezionati",0,"rose" if bad else "")])
                detail=[{"Giorno gas":x["gas_day"],"Giacenza calcolata (GWh)":str(x["closing"]),
                         "Differenza (GWh)":None if x["residual"] is None else str(x["residual"]),
                         "STOP (GWh)":None if x["stop"] is None else str(x["stop"]),
                         "ST (GWh)":None if x["st"] is None else str(x["st"]),
                         "Esito":x["status"],"Rilievi":"; ".join(x["findings"])} for x in data]
                st.dataframe(detail,hide_index=True,width="stretch")
                output=StringIO()
                writer=csv.DictWriter(output,fieldnames=list(detail[0]))
                writer.writeheader();writer.writerows(detail)
                st.download_button("Esporta verifiche CSV",output.getvalue(),"igor-hs1-verifiche.csv","text/csv",key="hs1_export")
    info("Formula e perimetro",REFERENCE+" · §3.1 e §3.2 (pp. 7-3–7-5).",
         "La quadratura richiede una giacenza finale fornita indipendentemente; senza questa si tratta solo di un calcolo.",
         "Il giorno gas HS1 usa le 06:00 in ora solare secondo il glossario.")


def _user():
    st.caption("Simulazione singolo utente ordinario · Gk = G precedente + Sk × Ck + STk")
    with st.container(border=True):
        a,b,c=st.columns(3)
        with a:opening=_input("Giacenza iniziale · GWh",80,"user_open",nonnegative=True)
        with b:alloc=_input("Allocazione Sk · GWh",-4,"user_alloc",help="Positiva in iniezione, negativa in erogazione.")
        with c:exchange=_input("Scambi netti STk · GWh",1,"user_exchange",help="Acquisti positivi; vendite negative.")
        a,b=st.columns(2)
        with a:
            direction=st.radio("Flusso prevalente atteso",["injection","withdrawal"],index=1,
                               format_func={"injection":"Iniezione","withdrawal":"Erogazione"}.__getitem__,
                               horizontal=True,key="hs1_direction")
        with b:gamma=_input("Consumi γ · % (ipotesi)",.5,"user_gamma",nonnegative=True,help="Inserire il coefficiente approvato applicabile; il valore iniziale è fittizio.")
        with st.expander("Spazio, prestazioni e gas vincolato"):
            a,b=st.columns(2)
            with a:
                space=_input("Spazio conferito · GWh",100,"user_space",nonnegative=True)
                guarantee=_input("Gas vincolato · GWh",10,"user_guarantee",nonnegative=True)
            with b:
                injection=_input("Prestazione iniezione · GWh/g",8,"user_inj",nonnegative=True)
                withdrawal=_input("Prestazione erogazione · GWh/g",8,"user_with",nonnegative=True)
        try:r=user_balance(opening,alloc,exchange,direction,gamma,space=space,guarantee=guarantee,
                           injection_limit=injection,withdrawal_limit=withdrawal)
        except ValueError as error:st.warning(str(error));return
        kpi_grid([("Giacenza finale",r["closing"],"GWh","Ricostruzione",3,_tone(r["closing"])),
                  ("Effetto consumi",r["consumption_effect"],"GWh","Sk × (Ck − 1)",3,""),
                  ("Giacenza oltre il vincolo",r["free_stock"],"GWh","Non è capacità di erogazione",3,"")])
        rows([("Coefficiente Ck",numero(r["coefficient"],6)),("Spazio residuo geometrico",numero(r["space_remaining"],3)+" GWh")])
        st.caption(r["status"])
        _findings(r)
    info("Regole e limiti",REFERENCE+" · §3.2.1 (pp. 7-5–7-6) e cap. 6 §1.",
         "Ck = 1 − γI con prevalenza iniezione; 1 + γE con prevalenza erogazione, anche per allocazioni di segno opposto.",
         "Controlli semplificati sulle prestazioni dichiarate, non autorizzazione a movimentare gas. Non copre rettifiche specifiche SRG o gas strategico.")


def _mgs():
    st.caption("Simulazione limiti quantitativi MGS · singolo servizio ordinario · nessun ordine di mercato.")
    with st.container(border=True):
        a,b=st.columns(2)
        with a:
            space=_input("Spazio disponibile lordo · GWh",20,"mgs_space",nonnegative=True)
            injection=_input("Massimo programmabile in iniezione · GWh",8,"mgs_inj",nonnegative=True)
            guarantee=_input("Gas a garanzia da dedurre · GWh",10,"mgs_g",nonnegative=True)
        with b:
            stock=_input("Giacenza residua lorda · GWh",80,"mgs_stock",nonnegative=True)
            withdrawal=_input("Massimo programmabile in erogazione · GWh",8,"mgs_with",nonnegative=True)
            other=_input("Altro vincolo cap. 16 §4.5 · GWh",0,"mgs_other",nonnegative=True)
        r=mgs_limits(space,stock,injection,withdrawal,guarantee,other)
        kpi_grid([("Acquisto teorico massimo",r["buy"],"GWh","Spazio − iniezione",3,""),
                  ("Vendita teorica massima",r["sell"],"GWh","Giacenza − erogazione − vincoli",3,"")])
        _findings(r)
    info("Perimetro MGS",REFERENCE+" · §3.4 (pp. 7-6–7-7).",
         "Inserire valori dello stesso giorno gas e servizio, prima delle deduzioni; non sottrarre due volte le garanzie.",
         "Non include servizi di bilanciamento, aggregazioni multiservizio o verifiche di abilitazione e credito. Il limite ufficiale è determinato da Snam Stoccaggio.")


def panel():
    st.subheader("Bilanciamento stoccaggio · HS1")
    st.caption("Edizione di studio 2026-I · dati ipotetici salvo CSV esplicitamente importato · vigenza da verificare.")
    view=st.radio("Controllo",["Sistema","Utente","Limiti MGS"],horizontal=True,key="hs1_mode",label_visibility="collapsed")
    if view=="Sistema":_system()
    elif view=="Utente":_user()
    else:_mgs()
