"""Short session-only reuse of already validated public source bundles.

Never shared across users, never refresh an acquisition timestamp, never
replace a newer bundle known by the shared public-source coordinator.
"""
from datetime import timedelta

STATE="public_source_render_cache_v1"
TTL=timedelta(seconds=60)


def recent_source(state,name,now,shared):
    entry=state.get(STATE,{}).get(name)
    if entry is None:return None
    at,bundle,warning=entry
    if not timedelta(0)<=now-at<TTL:return None
    if bundle.origin.refresh_failed:return None
    if shared is not None and shared is not bundle:return None
    return bundle,warning


def remember_source(state,name,bundle,warning,now):
    if bundle is not None and not bundle.origin.refresh_failed:
        state[STATE]={**state.get(STATE,{}),name:(now,bundle,warning)}


def forget_source(state,name):
    entries=dict(state.get(STATE,{}))
    entries.pop(name,None)
    state[STATE]=entries
