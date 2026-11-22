"""All generated measurements in this module are synthetic test fixtures."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import shutil

import pytest

from gasops_app.italian_network import (ASSETS, CATEGORIES, applicable, filter_infrastructure,
    load_network_assets, map_kpis, merge_observations, selected_id, validate_geometry, valid_position,
    evidence_status, kpi_status, point_metrics)
from gasops_app.italian_network_sources import parse_observations, Snapshot, encode_snapshot, decode_snapshot

DAY = date(2026,11,20)
NOW = datetime(2026,11,22,2,tzinfo=timezone.utc)


@pytest.fixture
def network():
    return load_network_assets()


@pytest.fixture
def binding(network):
    return next(b for b in network.bindings_for("INET_BP_65", "ENTSOG") if b.direction == "entry")


def row(binding, indicator="Physical Flow", value=2_000_000, **kwargs):
    return {"operatorKey":binding.operator_id,"pointKey":binding.external_id,"directionKey":binding.direction,
        "indicator":indicator,"unit":"kWh/d","periodType":"day","value":value,"id":"synthetic-only",
        "periodFrom":"2026-11-20T06:00:00+01:00","periodTo":"2026-11-21T06:00:00+01:00", **kwargs}


def observations(binding, rows):
    return parse_observations(rows,binding,DAY,DAY,NOW)


def test_kpi_dates_ignore_unrelated_indicator_and_gas_day(network,binding):
    source = observations(binding,[row(binding),row(binding,"Firm Technical",4_000_000)])
    older = NOW-timedelta(hours=2)
    source = tuple(replace(o,retrieved_at=older,publication_status="Confirmed") for o in source)
    # Synthetic fresh records must not freshen the older measures being shown.
    flow = next(o for o in source if o.indicator == "Physical Flow")
    unrelated = (replace(flow,indicator="Nomination",retrieved_at=NOW),
                 replace(flow,gas_day=DAY-timedelta(days=1),retrieved_at=NOW))
    visible = tuple(i for i in network.infrastructure if i.id == binding.infrastructure_id)
    metrics = map_kpis(network,visible,(*source,*unrelated),DAY)
    snapshot = Snapshot(binding.point_direction,source,DAY,DAY,older)
    status = kpi_status(metrics,(snapshot,),DAY,NOW,current_day=DAY)
    assert status["status"] == "Aggiornato" and status["complete"]
    assert status["oldest"] == status["newest"] == older
    assert status["age"] == timedelta(hours=2)
    assert {o.indicator for o in metrics["observations"]} == {"Physical Flow","Firm Technical"}


def test_one_recent_point_does_not_freshen_the_other_points(network,binding):
    other = next(b for b in network.bindings if b.provider == "ENTSOG" and b.direction == "entry"
                 and b.external_id.startswith("ITP-") and b.infrastructure_id != binding.infrastructure_id)
    old = replace(observations(binding,[row(binding)])[0],retrieved_at=NOW-timedelta(hours=18),publication_status="Confirmed")
    new = replace(observations(other,[row(other)])[0],retrieved_at=NOW,publication_status="Confirmed")
    visible = tuple(i for i in network.infrastructure if i.id in (binding.infrastructure_id,other.infrastructure_id))
    metrics = map_kpis(network,visible,(old,new),DAY)
    snapshots = (Snapshot(binding.point_direction,(old,),DAY,DAY,old.retrieved_at),Snapshot(other.point_direction,(new,),DAY,DAY,NOW))
    status = kpi_status(metrics,snapshots,DAY,NOW,current_day=DAY)
    assert status["status"] == "Storico" and status["age"] == timedelta(hours=18)
    assert status["oldest"] == old.retrieved_at and status["newest"] == NOW


@pytest.mark.parametrize("case,expected",[("partial","Parziale"),("failed","Parziale"),("missing_snapshot","Parziale"),
    ("unconfirmed","Parziale"),("future_acquisition","Parziale"),("older_day","Storico"),("fresh","Aggiornato")])
def test_data_status_requires_current_complete_confirmed_evidence(network,binding,case,expected):
    record = replace(observations(binding,[row(binding)])[0],publication_status="Confirmed")
    if case == "unconfirmed":record = replace(record,publication_status="Provisional")
    if case == "future_acquisition":record = replace(record,retrieved_at=NOW+timedelta(hours=1))
    snap = Snapshot(binding.point_direction,(record,),DAY,DAY,record.retrieved_at,partial=case == "partial")
    visible = tuple(i for i in network.infrastructure if i.id == binding.infrastructure_id)
    metrics = map_kpis(network,visible,(record,),DAY)
    status = kpi_status(metrics,() if case == "missing_snapshot" else (snap,),DAY,NOW,
        current_day=DAY+timedelta(days=1) if case == "older_day" else DAY,
        failures={binding.point_direction:NOW} if case == "failed" else {})
    assert status["status"] == expected


def test_missing_evidence_and_missing_publication_are_explicit(binding):
    missing = evidence_status((),DAY,NOW,complete=True,current_day=DAY)
    assert missing["status"] == "Non disponibile" and missing["age"] is None and not missing["complete"]
    record = observations(binding,[row(binding)])[0]
    status = evidence_status((replace(record,observed_at=None),),DAY,NOW,current_day=DAY)
    assert status["published_oldest"] is None
    published = evidence_status((replace(record,observed_at="2026-11-21T14:00:00+01:00"),),DAY,NOW,current_day=DAY)
    assert published["published_oldest"] == datetime(2026,11,21,13,tzinfo=timezone.utc)


def test_point_summary_uses_latest_valid_flow_day_and_only_comparable_capacity(binding):
    current = observations(binding,[row(binding,value=0),row(binding,"Firm Technical",4_000_000),
        row(binding,"Firm Available",1_000_000),row(binding,"Nomination",3_000_000),row(binding,"Renomination",2_000_000)])
    flow = next(o for o in current if o.indicator == "Physical Flow")
    nomination = next(o for o in current if o.indicator == "Nomination")
    previous = replace(flow,gas_day=DAY-timedelta(days=1),period_from=flow.period_from-timedelta(days=1),
                       period_to=flow.period_to-timedelta(days=1),value=Decimal("2"))
    unrelated = replace(nomination,gas_day=DAY+timedelta(days=1),retrieved_at=NOW+timedelta(hours=1))
    result = point_metrics((*current,previous,unrelated),binding.point_direction,DAY-timedelta(days=1),DAY+timedelta(days=1))
    assert result["day"] == DAY and result["values"]["Physical Flow"] == 0
    assert result["utilization_pct"] == 0 and result["change_gwh_d"] == -2
    assert result["values"]["Firm Available"] == 1 and result["values"]["Renomination"] == 2
    assert unrelated not in result["observations"]
    assert previous in result["observations"]  # The displayed delta has its own evidence too.
    missing = point_metrics((),binding.point_direction,DAY,DAY)
    assert missing["values"] == {} and missing["utilization_pct"] is None and missing["change_gwh_d"] is None


def test_public_assets_have_real_ids_provenance_and_italy_only(network):
    counts = Counter(i.category for i in network.infrastructure)
    assert counts == dict(pipeline=163,node=177,entry=7,lng=5,storage=20,compressor=15,power=69)
    assert len({i.id for i in network.infrastructure}) == 456
    assert all(g.source and g.source_url.startswith("https://") and g.source_id and g.observed_at
               and g.retrieved_at and g.license and g.dataset_version and g.geometry_accuracy and g.quality_status for g in network.geography)
    for g in network.geography:
        validate_geometry(g.geometry)
    assert "Creative Commons" in (ASSETS/"LICENSE-SciGRID.txt").read_text()
    assert any("Sardegna" in i.regions for i in network.infrastructure)
    assert any("Sicilia" in i.regions for i in network.infrastructure)
    assert all(i.metadata.get("schematic") is True for i in network.infrastructure if i.category == "pipeline")


def test_catalog_verified_mapping_no_aggregates_and_current_lng_geometry(network):
    expected = {"INET_BP_65":"ITP-00093", "INET_BP_34":"ITP-00074", "INET_BP_84":"ITP-00008",
                "INET_BP_89":"ITP-00040", "INET_BP_78":"ITP-00136"}
    assert all(network.bindings_for(k,"ENTSOG")[0].external_id == v for k,v in expected.items())
    assert len([b for b in network.bindings if b.provider == "ENTSOG"]) == 16
    assert len([b for b in network.bindings if b.provider == "ALSI"]) == 5
    assert [b.infrastructure_id for b in network.bindings if b.provider == "AGSI+"] == ["INET_SR_35"]
    assert not any(b.external_id.startswith(("UGS-","PRD-")) for b in network.bindings)
    for b in network.bindings:
        if b.provider == "ENTSOG":
            assert any(r["pointKey"] == b.external_id and r["directionKey"] == b.direction and r["hasData"]
                       for r in network.sources["opd"]["rows"])
        else:
            assert any(r["eic"] == b.external_id and r["company"] == b.operator_id and not r["is_group"]
                       for r in network.sources["gie_facilities"])
    geo = {g.infrastructure_id:g for g in network.geography}
    assert geo["INET_LG_6"].geometry["coordinates"] == [12.584719,45.090639]
    assert geo["INET_LG_33"].geometry["coordinates"] == [9.988889,43.644444]
    assert geo["it-lng-piombino"].geometry["coordinates"] == [10.559217,42.939431]
    assert geo["it-lng-ravenna"].geometry["coordinates"] == [12.398189,44.464033]
    assert all("tpMap" not in str(g.geometry) for g in network.geography)


@pytest.mark.parametrize("position", [[-68,12], [12,-68], [19.1,42], [12,48], [True,42],
                                        [float("nan"),42], [12,float("inf")], [12], "12,42"])
def test_invalid_wgs84_or_non_italian_positions_rejected(position):
    assert not valid_position(position)
    with pytest.raises(ValueError):
        validate_geometry({"type":"Point","coordinates":position})


@pytest.mark.parametrize("change", ["foreign","duplicate","group","unconfirmed"])
def test_assets_reject_foreign_duplicate_or_ambiguous_mapping(tmp_path,change):
    for name in ("infrastructure.geojson","catalog.json"):
        shutil.copyfile(ASSETS/name,tmp_path/name)
    if change in ("foreign","duplicate"):
        path=tmp_path/"infrastructure.geojson"
        p=json.loads(path.read_text())
        if change == "foreign":
            p["features"][0]["properties"]["country_code"]="FR"
        else:
            p["features"].append(p["features"][0])
    else:
        path=tmp_path/"catalog.json"
        p=json.loads(path.read_text())
        if change == "group":
            b=next(b for b in p["bindings"] if b["provider"] == "AGSI+")
            b.update(external_id="21Z000000000274I",operator_id="21X000000001250I")
        else:
            p["bindings"][0]["mapping_confidence"]="uncertain"
    path.write_text(json.dumps(p))
    with pytest.raises(ValueError):
        load_network_assets(tmp_path)


def test_filters_are_intersections_and_do_not_mutate_assets(network):
    found=filter_infrastructure(network,["entry","lng"],regions=["Sicilia"],operators=["Snam Rete Gas"])
    assert {i.id for i in found} == {"INET_BP_65","INET_BP_34"}
    assert not filter_infrastructure(network,["production"])
    assert not filter_infrastructure(network,[])
    assert [i.id for i in filter_infrastructure(network,CATEGORIES,event_ids={"INET_LG_6"})] == ["INET_LG_6"]
    assert len(network.infrastructure) == 456


def test_native_selection_accepts_points_and_geojson_only_when_visible():
    assert selected_id({"selection":{"objects":{"points":[{"infra_id":"x"}]}}},{"x"}) == "x"
    event={"selection":{"objects":{"lines":[{"properties":{"infra_id":"y"}}]}}}
    assert selected_id(event,{"y"}) == "y"
    assert selected_id(event,{"x"}) is None
    assert selected_id({"selection":{"objects":"invalid"}},{"x"}) is None


def test_kpis_scoped_to_distinct_covered_frontier_entry_and_comparable_capacity(network,binding):
    binding=next(b for b in network.bindings_for("INET_BP_84","ENTSOG") if b.direction == "entry")
    lng=next(b for b in network.bindings if b.provider == "ENTSOG" and b.external_id == "LNG-00015")
    exit_binding=next(b for b in network.bindings_for(binding.infrastructure_id,"ENTSOG") if b.direction == "exit")
    obs=(*observations(binding,[row(binding,value=100_000_000),row(binding,"Firm Technical",200_000_000)]),
         *observations(lng,[row(lng,value=50_000_000)]),*observations(exit_binding,[row(exit_binding,value=99_000_000)]))
    m=map_kpis(network,network.infrastructure,obs,DAY)
    assert m["entry_flow_gwh_d"] == 100 and m["utilization_pct"] == 50
    assert m["valid_entry_points"] == 1 and m["mapped_entry_points"] == 6
    assert m["valid_points"] == 2 and m["mapped_points"] == 12
    empty=map_kpis(network,network.infrastructure,(),DAY)
    assert empty["entry_flow_gwh_d"] is None and empty["utilization_pct"] is None
    foreign_unit=tuple(replace(o,unit="m³/d") for o in obs)
    assert map_kpis(network,network.infrastructure,foreign_unit,DAY)["entry_flow_gwh_d"] is None


def test_capacity_preserves_source_clock_and_cannot_be_silently_shifted(binding):
    obs=observations(binding,[row(binding),row(binding,"Firm Booked",4_000_000,
        periodFrom="2026-11-20T07:00:00+01:00",periodTo="2026-11-21T07:00:00+01:00"),
        row(binding,"Firm Technical",4_000_000,periodFrom="2026-10-21T08:00:00+02:00",periodTo="2026-11-23T07:00:00+01:00")])
    assert applicable(obs,binding.point_direction,DAY,"Firm Booked") is None
    assert applicable(obs,binding.point_direction,DAY,"Firm Technical") == 4
    invalid=replace(next(o for o in obs if o.indicator == "Firm Technical"),value=None,quality_status="N/A")
    assert applicable((*obs,invalid),binding.point_direction,DAY,"Firm Technical") is None


def test_snapshot_roundtrip_and_newer_na_replaces_old_number_instead_of_filling_holes(binding):
    old=Snapshot(binding.point_direction,observations(binding,[row(binding)]),DAY,DAY,NOW)
    assert decode_snapshot(encode_snapshot(old)) == old
    later=replace(old,records=observations(binding,[row(binding,value=None)]),acquired=NOW+timedelta(hours=1))
    merged=merge_observations([later,old])
    assert len(merged) == 1 and merged[0].value is None
    assert applicable(merged,binding.point_direction,DAY,"Physical Flow") is None
    failed=replace(old,cached=True,failed=True)
    assert merge_observations([later,failed]) == later.records
