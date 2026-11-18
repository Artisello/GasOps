from pathlib import Path
from hashlib import sha256
import sqlite3

import pytest

from gasops_app.warehouse import JRC, MASE, Warehouse, inspect_csv, jrc_rows

FIXTURE = b"GASDAY,TOT,IND,GPP,DIS,PROC\n2021-01-01,100,20,30,50,O\n2021-01-02,110,NA,40,60,E\n"


def test_jrc_versions_and_idempotence(tmp_path):
    w = Warehouse(tmp_path / "public.db")
    first = w.ingest(JRC, FIXTURE)
    assert first["observations"] == 7
    assert first["sha256"] == sha256(FIXTURE).hexdigest()
    assert not w.ingest(JRC, FIXTURE)["new_snapshot"]
    assert w.ingest(JRC, FIXTURE.replace(b"110", b"120"))["new_snapshot"]
    assert len(w.manifest()) == 2
    assert all(row["observations"] == 7 for row in w.manifest())
    assert all(row["first_period"] == "2021-01-01" for row in w.manifest())
    with sqlite3.connect(w.path) as db:
        assert db.execute("select count(*) from public_observation").fetchone()[0] == 14
        assert db.execute("select payload from public_snapshot where digest=?", (first["sha256"],)).fetchone()[0] == FIXTURE


def test_real_bundled_jrc(tmp_path):
    raw = (Path(__file__).resolve().parents[1] / "data/jrc/IT.v1.1.csv").read_bytes()
    w = Warehouse(tmp_path / "public.db")
    result = w.ingest(JRC, raw)
    assert result["observations"] > 2000
    assert w.manifest()[0]["first_period"] == "2015-01-01"


@pytest.mark.parametrize("raw", [b"<html>error</html>", b"a;b\n1\n", b"a;b\n", b""])
def test_bad_csv_rejected(tmp_path, raw):
    w = Warehouse(tmp_path / "public.db")
    with pytest.raises(ValueError):
        w.ingest(MASE, raw)
    assert w.manifest() == []


def test_raw_mase_never_publishes_observations(tmp_path):
    # Synthetic structure only; not a claim about the native MASE schema.
    raw = b"campo;valore\nA;1,25\nB;2,50\n"
    w = Warehouse(tmp_path / "public.db")
    assert inspect_csv(raw)["delimiter"] == ";"
    assert w.ingest(MASE, raw)["status"] == "raw_pending"
    assert w.manifest()[0]["observations"] == 0
    assert w.manifest()[0]["first_period"] is None


def test_jrc_conflict_and_missing():
    assert len(jrc_rows(FIXTURE)) == 7
    with pytest.raises(ValueError):
        jrc_rows(FIXTURE + b"2021-01-01,1,2,3,4,O\n")
    with pytest.raises(ValueError):
        jrc_rows(FIXTURE.replace(b"110", b"NaN"))
