from datetime import datetime,timezone
import csv
import io

from gasops_app.iip_view import project_messages, filter_messages, display_row, export_rows, coverage

NOW=datetime(2026,11,18,tzinfo=timezone.utc)


def test_iip_projection_no_inferred_impact_or_country():
    rows=project_messages([{"messageId":"a","affectedAssetOrUnit":"Asset A",
                            "eventStatus":"Active","publicationDateTime":"2026-11-17T20:00:00Z",
                            "unavailableCapacity":10,"unitOfMeasurement":"GWh/d"},
                           {"messageId":"b","assetName":"Asset B","eventStatus":"Active",
                            "publicationDateTime":"2026-11-18T00:00:00Z",
                            "intervals":[{"unavailableCapacity":999}]}])
    assert [r["message_id"] for r in rows]==["b","a"]
    assert rows[0]["impact"]=="Consulta dettaglio"
    assert rows[0]["country"] is None
    assert rows[1]["impact"]=="10 GWh/d"
    assert rows[1]["published_label"]=="17/11/2026 21:00 CET"
    assert filter_messages(rows,query="asset a")==[rows[1]]


def test_iip_variants_conflicts_missing_and_csv_injection():
    rows=project_messages([{"messageId":"x","assetName":"=cmd()","countryCode":"IT",
                           "eventStatus":"Active","status":"Dismissed",
                           "publicationDate":"2026-11-18 10:00:00"},
                          {"messageId":"y","event":{"typeOfEvent":"Maintenance","countryCode":"DE"}}])
    assert rows[0]["status"] is None
    assert "fuso non indicato" in rows[0]["published_label"]
    assert filter_messages(rows,countries=["DE"],types=["Maintenance"])==[rows[1]]
    assert display_row(rows[0])["Stato UMM"]=="Non indicato"
    result={"acquired":NOW,"partial":False,"pagination_verified":True}
    exported=list(csv.DictReader(io.StringIO(export_rows(rows,result))))
    assert exported[0]["Asset"]=="'=cmd()"
    assert "Gas Infrastructure Europe" in exported[0]["Fonte"]


def test_iip_coverage_distinguishes_actual_metadata_verification():
    assert coverage({"pages":1,"pagination_verified":True,"partial":False})=="Completa"
    assert coverage({"pages":2,"pagination_verified":True,"partial":True})=="Parziale"
    assert coverage({"pages":None,"partial":True})=="Non verificata"
    assert coverage({"pages":1,"partial":False})=="Non verificata"


def test_nested_message_fields_and_sparse_table():
    from gasops_app.iip_view import visible_columns
    rows=project_messages([{"messageId":"a","status":"Active",
        "details":{"event":{"affectedAssetOrUnit":{"name":"Example"},
         "eventStartDateTimeUTC":"2026-11-18T20:00:00Z",
         "eventEndDateTime":"2026-11-20T20:00:00Z",
         "intervals":[{"unavailableCapacity":10},{"unavailableCapacity":20}]},
         "reportingEntity":{"name":"Operator"}}}])
    row=rows[0]
    assert row["asset"]=="Example" and row["operator"]=="Operator"
    assert row["start_label"]=="18/11/2026 21:00 CET"
    assert row["stop_label"]=="20/11/2026 21:00 CET"
    assert row["impact"]=="Consulta dettaglio" and row["country"] is None
    columns=visible_columns(rows)
    assert "Inizio evento" in columns and "Fine evento" in columns
    assert "Paese" not in columns and "Capacità indisponibile" not in columns
    assert "ID messaggio" in columns
