from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from gasops_app import navigation


@pytest.mark.parametrize("demo",[False,True])
@pytest.mark.parametrize("active",range(11))
def test_sidebar_navigation_home_unique_and_current_route(monkeypatch,active,demo):
    pages=[SimpleNamespace(url_path=path) for path in ("","market","security-of-supply","balancing","ledger","risk","regulatory","operations","kpi")]
    if demo:
        pages.extend(SimpleNamespace(url_path=path) for path in ("connections","demo"))
    if active>=len(pages):
        pytest.skip("Route absent in workbench")
    rendered=[]
    headings=[]
    keys=[]

    @contextmanager
    def container(*,key):
        keys.append(key)
        yield
    monkeypatch.setattr(navigation.st,"container",container)
    monkeypatch.setattr(navigation.st,"page_link",lambda page,**kwargs:rendered.append(page.url_path))
    monkeypatch.setattr(navigation.st,"html",headings.append)
    navigation.sidebar_navigation(pages,pages[active])
    order=[0,2,3,4,8,1,5,6,7]+([9,10] if demo else [])
    assert rendered==[pages[i].url_path for i in order]
    assert keys[0]==("gas_nav_home_active" if active==0 else "gas_nav_home_idle")
    assert len([key for key in keys if key.endswith("_active")])==1
    assert keys[order.index(active)].endswith("_active")
    assert len(headings)==3
