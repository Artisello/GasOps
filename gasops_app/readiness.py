"""Offline release gate. No live access, secret inspection, or production DB writes."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
from contextlib import closing

from .data import jrc_archive
from .quality import inspect
from .models import Run
from .store import Store
from .mase_archive import observations
from .acer_market import bundled_lng
from .acer_baf_2026 import all_baf_rows
from .terna_power import annual_rows
from .monitoring import Archive, run, write_report, parse_report
from .demo_forecast import load as load_demo_forecast


def verify():
    checks=[]
    now=datetime.now(timezone.utc)
    def check(code,fn):
        try:
            ok=bool(fn())
        except Exception:
            ok=False
        checks.append({"check":code,"passed":ok})
    def archive_check():
        b=jrc_archive()
        f=inspect(b,now).usable
        return b.origin.archive and len(f)==2557 and f["demand_gwh"].notna().sum()>2500
    check("jrc_public_archive",archive_check)
    check("demo_historical_snapshot",lambda:bool(load_demo_forecast()["result"]["records"]))
    check("mase_historical_extract",lambda:len(observations())==123)
    check("acer_lng_extract",lambda:len(bundled_lng().rows)==19)
    check("acer_baf_editions",lambda:len(all_baf_rows())==130)
    check("terna_annual_extract",lambda:len(annual_rows())==17)

    def italian_map_check():
        from hashlib import sha256
        from .italian_network import ASSETS, load_network_assets
        from .italian_network_sources import decode_snapshot
        network=load_network_assets()
        manifest=json.loads((ASSETS/"manifest.json").read_text())
        snapshots=json.loads((ASSETS/"operational.json").read_text())["snapshots"]
        return (len(network.infrastructure)==456 and len(network.bindings)==22 and len(snapshots)==11
                and all(decode_snapshot(s).records for s in snapshots)
                and all(sha256((ASSETS/name).read_bytes()).hexdigest()==digest
                        for name,digest in manifest["files"].items()))
    check("italian_network_public_assets",italian_map_check)

    def sqlite_check():
        # Test a real SQLite online backup and restore into a fresh temp DB.
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder)
            source=Store(d/"original.sqlite3")
            source.cache("release_probe",now.isoformat(),"fixture")
            datum=jrc_archive()
            r=Run(question="Synthetic release probe",source=datum.origin,
                  input_sha256=datum.fingerprint,assumptions={})
            source.save(r)
            with closing(sqlite3.connect(source.path)) as db,closing(sqlite3.connect(d/"restored.sqlite3")) as dest:
                db.backup(dest)
                if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    return False
            restored=Store(d/"restored.sqlite3")
            return restored.cached("release_probe")==source.cached("release_probe") and restored.recent()[0].id==r.id
    check("throwaway_sqlite_backup_restore",sqlite_check)

    def monitor_check():
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder)
            archive=Archive(d/"monitor.sqlite3")
            report=run(["entsog"],now,archive,collector=lambda *_:None)
            write_report(report,d/"report.json")
            return parse_report((d/"report.json").read_bytes())==report and archive.as_of("entsog",now)==[]
    check("monitor_isolation_and_report",monitor_check)
    return {"scope":"offline structural and fixture checks only","checks":checks,
            "passed":all(c["passed"] for c in checks),
            "not_verified":["live APIs and terms","deployed Streamlit","production backup/restore",
                            "Supabase authorization policies","dependency advisories","operational acceptance"]}


def main():
    report=verify()
    print(json.dumps(report,indent=2))
    return 0 if report["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
