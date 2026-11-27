"""Conservative ENTSOG catalogue audit; never creates bindings or observations."""
import re
import unicodedata

from .italian_network import verified_bindings

def normalized(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c))))


def aliases(label):
    # Exact complete aliases only; no substring, fuzzy or proximity matching.
    parts = re.split(r"\s*/\s*|\s+-\s+", str(label or ""))
    return {name for part in parts
            if (name := normalized(re.sub(r"\s*\([A-Z]{2}\)\s*$", "", part)))}


def audit_nodes(network, catalog):
    """Report hypotheses from the supplied operator catalogue, not nationwide coverage."""
    nodes = tuple(i for i in network.infrastructure if i.category == "node")
    bindings = verified_bindings(network)
    owner = {b.point_direction:b.infrastructure_id for b in bindings}
    names = {i.id:i.name for i in network.infrastructure}
    verified = {b.infrastructure_id for b in bindings}
    rows = catalog.get("rows", ())
    usable = []
    for row in rows:
        if row.get("tSOCountry") != "IT" or row.get("isInvalid") is not False:
            continue
        if row.get("directionKey") not in ("entry","exit") or not row.get("operatorKey"):
            continue
        key = str(row.get("pointKey") or "")
        # Restrict hypotheses to named interconnections/LNG points. Aggregates,
        # virtual points and storage hubs cannot identify an internal node.
        if not key.startswith(("ITP-","LNG-")) or "aggregat" in str(row.get("pointType") or "").casefold():
            continue
        usable.append(row)
    results = []
    for item in nodes:
        candidates = []
        for row in usable:
            if normalized(item.name) not in aliases(row.get("pointLabel")):
                continue
            key = row["operatorKey"]+row["pointKey"]+row["directionKey"]
            mapped = owner.get(key)
            candidates.append({"operator":row.get("operatorLabel"),"operator_key":row["operatorKey"],
                "point":row["pointKey"],"label":row.get("pointLabel"),"direction":row["directionKey"],
                "has_data":row.get("hasData") is True,"mapped_id":mapped,"mapped_name":names.get(mapped),
                "status":"already_mapped" if mapped else "review_required"})
        state = ("verified" if item.id in verified else "review_required" if any(c["status"]=="review_required" for c in candidates)
                 else "already_mapped" if candidates else "no_exact_match")
        results.append({"id":item.id,"name":item.name,"state":state,"candidates":candidates})
    return {"nodes":results,"catalog_rows":len(rows),"operators":sorted({r["operatorKey"] for r in rows if r.get("operatorKey")}),
            "catalog_date":catalog.get("acquired") or catalog.get("retrieved_at"),
            "conflicts":len(catalog.get("conflicts",())),"failed":bool(catalog.get("failed")),
            "cached":bool(catalog.get("cached"))}
