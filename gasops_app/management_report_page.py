"""Management report embedded in the existing KPI overview, read-only."""
import streamlit as st
from .management_report import report,markdown
from .visuals import kpi_grid

def panel(state,now,year,month,user,*,inspections=None):
    r=report(state,now,year,month,user,inspections=inspections)
    st.subheader("Report direzionale")
    st.caption(f'{r["month"]} · {r["generated_at"]} · {r["closed_days"]} giorni gas conclusi nel mese')
    high=sum(s["priority"]=="Alta" for s in r["signals"])
    medium=sum(s["priority"]=="Media" for s in r["signals"])
    info=sum(s["priority"]=="Informativa" for s in r["signals"])
    kpi_grid([("Priorità alte",high,"","Rilievi di revisione",0,"rose" if high else ""),
              ("Da verificare",medium,"","Priorità medie",0,""),
              ("Informative",info,"","Registri assenti / limiti",0,"")])
    if not r["signals"]:
        st.caption("Nessun rilievo nei controlli eseguiti; non certifica assenza di criticità.")
    else:
        st.dataframe([{"Priorità":s["priority"],"Area":s["area"],"Rilievo":s["title"],"Evidenza":s["detail"],"Azione proposta":s["action"]}
                      for s in r["signals"][:5]],hide_index=True,width="stretch")
        if len(r["signals"])>5:
            st.caption(f'Altri {len(r["signals"])-5} rilievi nel report completo.')
    st.caption(r["period_note"])
    st.download_button("Scarica report direzionale",markdown(r),"igor-report-bso-"+r["month"]+".md","text/markdown",key="management_report_export")
    st.caption("Solo registri già caricati. Nessuna demo automatica; priorità proposte, non classificazione ufficiale. Il report integra i dettagli e non sostituisce il Centro operativo.")
