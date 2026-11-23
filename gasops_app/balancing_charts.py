"""Compact balancing charts; calculations remain in finance.py."""
import plotly.graph_objects as go
from .italiano import numero
from .visuals import BLUE,TEAL,ROSE,MUTED,_frame


def scenario_comparison(base,stress,unit):
    fig=go.Figure()
    for name,attribute,color in (("Domanda","demand_gwh",BLUE),("Offerta","supply_gwh",TEAL)):
        values=[getattr(base,attribute),getattr(stress,attribute)]
        fig.add_trace(go.Bar(name=name,y=["Base","Scenario"],x=[float(v) for v in values],
            orientation="h",marker_color=color,text=[numero(v,1) for v in values],
            textposition="outside",cliponaxis=False,
            hovertemplate="%{y} · "+name+": %{text} "+unit+"<extra></extra>"))
    high=max(float(base.demand_gwh),float(base.supply_gwh),float(stress.demand_gwh),float(stress.supply_gwh),1)
    fig.update_layout(template="plotly_dark",height=235,separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=MUTED,size=12),margin=dict(l=10,r=18,t=45,b=12),
        barmode="group",bargap=.40,legend=dict(orientation="h",x=0,y=1.12),
        xaxis=dict(range=[0,high*1.32],visible=False,fixedrange=True),
        yaxis=dict(categoryorder="array",categoryarray=["Base","Scenario"],autorange="reversed",automargin=True,fixedrange=True))
    return fig


def daily_bars(frame,fields,unit):
    fig=go.Figure()
    for i,field in enumerate(fields):
        if not frame[field].notna().any():continue
        v=frame[field]
        colors=[ROSE if p<0 else TEAL for p in v.fillna(0)] if len(fields)==1 else (BLUE,TEAL)[i%2]
        fig.add_trace(go.Bar(name=field,x=frame["Giorno"],y=v,marker_color=colors,
            hovertemplate="%{x|%d/%m/%Y} · %{y:,.2f} "+unit+"<extra>"+field+"</extra>"))
    _frame(fig,"daily",unit,250)
    fig.update_layout(barmode="group",showlegend=len(fig.data)>1,hovermode="closest")
    fig.update_yaxes(zeroline=True,zerolinecolor=MUTED)
    return fig


def point_indicators(row):
    """Four distinct rates on one gas day; absent measures stay absent."""
    fields=("Nomination","Renomination","Allocation","Physical Flow")
    labels=("Nomina","Rinomina","Allocazione","Flusso fisico")
    fig=go.Figure(go.Bar(y=labels,x=[float(row[k]) if row[k] is not None else None for k in fields],
        orientation="h",marker_color=[BLUE,BLUE,TEAL,TEAL],
        text=[numero(row[k],1) if row[k] is not None else None for k in fields],textposition="outside",cliponaxis=False,
        hovertemplate="%{y}: %{text} GWh/d<extra></extra>"))
    _frame(fig,"daily","GWh/d",235)
    fig.update_layout(margin={"l":10,"r":55,"t":10,"b":35},showlegend=False,hovermode="closest")
    fig.update_xaxes(type="linear",tickformat=",.0f",automargin=True)
    fig.update_yaxes(title=None,side="left",autorange="reversed",automargin=True)
    return fig


def security_comparison(result):
    """Comparable rates only; unavailable totals are absent bars, never zeros."""
    fields=("supply","demand","entry_flow","storage_withdrawal")
    labels=("Offerta totale","Fabbisogno totale","Flusso ingresso scelto","Prelievo storage")
    fig=go.Figure()
    for key,name,color in (("baseline","Baseline",BLUE),("stress","Stress Scenario",TEAL)):
        values=[result[key][field] for field in fields]
        fig.add_trace(go.Bar(name=name,y=labels,x=[float(v) if v is not None else None for v in values],
            orientation="h",marker_color=color,text=[numero(v,1) if v is not None else None for v in values],
            textposition="outside",cliponaxis=False,hovertemplate="%{y}: %{text} GWh/d<extra>"+name+"</extra>"))
    _frame(fig,"daily","GWh/d",280)
    fig.update_layout(barmode="group",margin=dict(l=10,r=65,t=30,b=35),
                      legend=dict(orientation="h",x=0,y=1.12),hovermode="closest")
    fig.update_xaxes(type="linear",automargin=True)
    fig.update_yaxes(side="left",title=None,autorange="reversed",automargin=True)
    return fig
