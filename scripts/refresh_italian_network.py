"""Prepare a small genuine ENTSOG extract offline; never invoked by the web app.

Run from the repository root, e.g. python -m scripts.refresh_italian_network --all-entry.
Existing successful observations survive failed source requests with their own dates.
"""
import argparse
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

from gasops_app.entsog import _last_completed
from gasops_app.italian_network import ASSETS, load_network_assets
from gasops_app.italian_network_sources import (load_catalog, load_point, encode_snapshot, decode_snapshot)
from gasops_app.italian_network_events import load_interruptions
from gasops_app.models import utc_now
from gasops_app.public_data import SourceUnavailable
from gasops_app.store import Store

FILES = ("infrastructure.geojson","italy.geojson","catalog.json","curated.json",
         "operational.json","interruptions.json","LICENSE-SciGRID.txt")


def manifest(directory):
    content = {name:sha256((directory/name).read_bytes()).hexdigest() for name in FILES}
    (directory/"manifest.json").write_text(json.dumps({"algorithm":"sha256","files":content},indent=2)+"\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-entry",action="store_true",help="At most 11 reviewed Italian entry points")
    parser.add_argument("--point",default="IT-TSO-0001ITP-00093entry")
    parser.add_argument("--days",type=int,default=7)
    parser.add_argument("--interruptions",action="store_true",help="Also update the bounded Mazara interruption extract")
    parser.add_argument("--output",type=Path,default=ASSETS)
    parser.add_argument("--cache",type=Path,default=Path(".gasops/italian-network-etl.sqlite3"))
    parser.add_argument("--manifest-only",action="store_true")
    args=parser.parse_args()
    if args.manifest_only:
        manifest(args.output)
        return 0
    if not 1 <= args.days <= 31:
        parser.error("--days must be between 1 and 31")
    network=load_network_assets(args.output)
    bindings=[b for b in network.bindings if b.provider == "ENTSOG"
              and (b.direction == "entry" if args.all_entry else b.point_direction == args.point)]
    if not bindings or len(bindings) > 11:
        parser.error("Select reviewed point directions; at most 11 entries")
    now=utc_now()
    last=_last_completed(now)
    first=last-timedelta(days=args.days-1)
    store=Store(args.cache)
    catalog=load_catalog(store,refresh=True)
    if catalog["failed"]:
        raise SystemExit("Catalog refresh failed; reviewed extract was not changed")
    path=args.output/"operational.json"
    previous=json.loads(path.read_text()) if path.exists() else {"snapshots":[]}
    snapshots={s["point_direction"]:s for s in previous["snapshots"]}
    diagnostics=[]
    updated=[]
    for binding in bindings:
        valid=[r for r in catalog["rows"] if r["operatorKey"] == binding.operator_id
               and r["pointKey"] == binding.external_id and r["directionKey"] == binding.direction
               and r["pointLabel"] == binding.expected_label and r["hasData"] is True and r["isInvalid"] is False]
        if len(valid) != 1:
            diagnostics.append({"point_direction":binding.point_direction,"error":"Identity not reconfirmed by catalog"})
            continue
        try:
            result=load_point(store,binding,first,last,refresh=True,now=now)
            if result.failed:
                diagnostics.append({"point_direction":binding.point_direction,"error":"Source refresh failed; previous copy retained"})
                continue
            snapshots[binding.point_direction]=json.loads(encode_snapshot(result))
            updated.append(binding.point_direction)
        except (SourceUnavailable,ValueError,OSError):
            diagnostics.append({"point_direction":binding.point_direction,"error":"Source unavailable or contract invalid"})
    payload={"source":"ENTSOG TP Transport Data","source_url":"https://transparency.entsog.eu/",
        "license":"ENTSOG TP conditions art.4; retain attribution and extraction date",
        "retrieved_at":max(decode_snapshot(s).acquired for s in snapshots.values()).isoformat() if snapshots else now.isoformat(),
        "snapshots":list(snapshots.values()),"diagnostic":diagnostics}
    # No synthetic or re-dated fallback records are written.
    if updated:
        path.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")))
    if args.interruptions:
        binding=next(b for b in network.bindings if b.point_direction == "IT-TSO-0001ITP-00093entry")
        try:
            result=load_interruptions(store,binding,first,last,refresh=True)
            if result["failed"]:
                raise SourceUnavailable("Refresh failed")
            cached_at,raw=store.cached(f"italian-map-interruptions-v1:{binding.point_direction}:{first}:{last}")
            (args.output/"interruptions.json").write_text(json.dumps({
                "source":"ENTSOG TP Interruptions","source_url":"https://transparency.entsog.eu/api/v1/interruptions",
                "license":"ENTSOG TP conditions, art.4; attribution required", "retrieved_at":cached_at,
                "point_direction":binding.point_direction,"first":str(first),"last":str(last),
                "raw_response":json.loads(raw)},ensure_ascii=False,separators=(",",":")))
        except (SourceUnavailable,ValueError,OSError):
            diagnostics.append({"point_direction":binding.point_direction,"error":"Interruptions not updated"})
    print(json.dumps({"updated":updated,"diagnostic":diagnostics},ensure_ascii=False))
    manifest(args.output)
    return 0 if not diagnostics else 1


if __name__ == "__main__":
    raise SystemExit(main())
