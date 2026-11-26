"""Application rendering tests remain offline unless a test supplies a transport."""
import pytest


@pytest.fixture(autouse=True)
def offline_background_sources(monkeypatch):
    from gasops_app import operational_acquisition
    monkeypatch.setattr(operational_acquisition, "network_allowed", lambda: False)
