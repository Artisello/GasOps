"""Compact Terna charts with explicit units and localized labels."""
from datetime import date,datetime
import pandas as pd
import plotly.graph_objects as go
from .italiano import numero,data_it
from .visuals import TEAL,BLUE,MUTED,local_time,_frame

PALETTE=(BLUE,TEAL,"#b5a1ed","#f2be72","#94a3b8","#f6929d")

def day_label(value):
    try:return data_it(date.fromisoformat(str(value)[:10]))
    except (ValueError,TypeError):return str(value)

def acquisition_label(value):
    try:
        at=datetime.fromisoformat(str(value))
        if at.tzinfo is not None:return local_time(at)
    except (TypeError,ValueError):pass
    return "Data di acquisizione non indicata"

def comparison_bars(items,unit):
    names=[name for name,value,color in items]
    values=[float(value) for name,value,color in items]
    fig=go.Figure(go.Bar(y=names,x=values,orientation="h",
        marker_color=[color for name,value,color in items],width=.56,
        text=[numero(value)+" "+unit for value in values],textposition="outside",
        textfont=dict(color="#e7edf5",size=13),cliponaxis=False,
        hovertemplate="%{y}: %{x:,.1f} "+unit+"<extra></extra>"))
    fig.update_layout(template="plotly_dark",height=max(135,44*len(items)+34),
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",separators=",.",
        font=dict(color=MUTED,size=13),margin=dict(l=8,r=16,t=8,b=6),showlegend=False,
        xaxis=dict(visible=False,range=[0,max(values,default=1)*1.35 or 1],fixedrange=True),
        yaxis=dict(autorange="reversed",automargin=True,showgrid=False,showline=False,
                   tickfont=dict(size=12),fixedrange=True,categoryorder="array",categoryarray=names),
        bargap=.36)
    return fig

def timeseries(frame,unit,*,forecast=False,monthly=False,height=265):
    fig=go.Figure()
    index=pd.to_datetime(frame.index)
    order=index.argsort()
    for i,name in enumerate(frame.columns):
        values=pd.to_numeric(frame[name],errors="coerce").iloc[order]
        if not values.notna().any():continue
        fig.add_trace(go.Scatter(x=index[order],y=values.to_numpy(),name=str(name),mode="lines+markers",
            connectgaps=False,marker=dict(size=6),line=dict(color=PALETTE[i%len(PALETTE)],width=2.2,
                dash="dash" if forecast or "previst" in str(name).lower() else "solid"),
            hovertemplate="%{y:,.1f} "+unit+"<extra>"+str(name)+"</extra>",
            xhoverformat="%m/%Y" if monthly else "%d/%m/%Y"))
    _frame(fig,"monthly" if monthly else "daily",unit,height)
    fig.update_layout(showlegend=len(fig.data)>1)
    return fig
