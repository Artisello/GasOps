from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from gasops_app import navigation


@pytest.mark.parametrize("active",[0,1,2,3,4,5,6,7])
def test_sidebar_navigation_home_unique_and_current_route(monkeypatch,active):
    pages=[SimpleNamespace(url_path=path) for path in ("","market","security-of-supply","balancing","ledger","risk","regulatory","operations")]
    rendered=[]
    headings=[]
    keys=[]

    @contextmanager
    def container(*,key):
        keys.append(key)
        yield
    monkeypatch.setattr(navigation.st,"container",container)
    monkeypatch.setattr(navigation.st,"page_link",lambda page:rendered.append(page.url_path))
    monkeypatch.setattr(navigation.st,"html",headings.append)
    navigation.sidebar_navigation(pages,pages[active])
    assert rendered==[page.url_path for page in pages]
    assert keys[0]==("gas_nav_home_active" if active==0 else "gas_nav_home_idle")
    assert len([key for key in keys if key.endswith("_active")])==1
    assert keys[active].endswith("_active")
    assert len(headings)==3
