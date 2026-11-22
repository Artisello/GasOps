"""Offline ETL. Never called by Streamlit. See docs/ITALIAN_GAS_NETWORK_MAP.md."""
import argparse
from collections import Counter
from datetime import datetime
from hashlib import md5
from io import BytesIO
import json
from pathlib import Path
import zipfile

SCIGRID_URL = "https://zenodo.org/records/4750979"
SCIGRID_MD5 = "08a85a3aceb2d0736476244f2b4d3962"
NUTS = {"ITC1":"Piemonte", "ITC2":"Valle d’Aosta", "ITC3":"Liguria", "ITC4":"Lombardia",
        "ITH1":"Trentino-Alto Adige", "ITH2":"Trentino-Alto Adige", "ITH3":"Veneto", "ITH4":"Friuli-Venezia Giulia",
        "ITH5":"Emilia-Romagna", "ITI1":"Toscana", "ITI2":"Umbria", "ITI3":"Marche", "ITI4":"Lazio",
        "ITF1":"Abruzzo", "ITF2":"Molise", "ITF3":"Campania", "ITF4":"Puglia", "ITF5":"Basilicata",
        "ITF6":"Calabria", "ITG1":"Sicilia", "ITG2":"Sardegna"}
CATEGORIES = {"PipeSegments":"pipeline", "Nodes":"node", "BorderPoints":"entry", "LNGs":"lng",
              "Storages":"storage", "Compressors":"compressor", "Consumers":"power"}


def italy_boundary(archive):
    """Natural Earth admin-0 v5.1.1; no other country's geometry is exported."""
    import shapefile
    from shapely.geometry import shape, mapping
    with zipfile.ZipFile(archive) as zipped:
        prefix = "ne_10m_admin_0_countries."
        reader = shapefile.Reader(**{ext:BytesIO(zipped.read(prefix+ext)) for ext in ("shp","shx","dbf")}, encoding="utf-8")
        matches = [r for r in reader.iterShapeRecords() if r.record.as_dict().get("ADMIN") == "Italy"]
        if len(matches) != 1:
            raise ValueError("Natural Earth Italy feature not uniquely identified")
        geometry = shape(matches[0].shape.__geo_interface__).simplify(.008, preserve_topology=True)
    return {"type":"FeatureCollection", "features":[{"type":"Feature", "properties":{
        "name":"Italia", "source":"Natural Earth", "license":"Public Domain", "dataset_version":"5.1.1",
        "source_url":"https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/"},
        "geometry":mapping(geometry)}]}


def build(archive, boundary, *, retrieved_at):
    from shapely.geometry import shape, mapping
    data = Path(archive).read_bytes()
    if md5(data).hexdigest() != SCIGRID_MD5:
        raise ValueError("SciGRID version/checksum differs from the reviewed source")
    z = zipfile.ZipFile(archive)
    land = shape(boundary["features"][0]["geometry"])
    # Historical coordinates are approximate. This tolerance is not a legal border.
    mask = land.buffer(.025)
    features = []
    for component, category in CATEGORIES.items():
        for feature in json.loads(z.read("data/INET_" + component + ".geojson"))["features"]:
            props = feature["properties"]
            country = props.get("country_code")
            if country != "IT" and country != ["IT", "IT"]:
                continue
            params = props.get("param", {})
            if category == "power" and not any(params.get("is_gas_fuel" + str(i)) == 1 for i in (1, 2, 3)):
                continue
            geo = shape(feature["geometry"])
            if category == "pipeline":
                geo = geo.intersection(mask)
                if geo.is_empty or geo.geom_type not in ("LineString", "MultiLineString"):
                    continue
            elif not (6.4 <= geo.x <= 19 and 35.3 <= geo.y <= 47.3):
                continue
            code = params.get("nuts_id_2", [])
            codes = code if isinstance(code, list) else [code]
            regions = sorted({NUTS[c] for c in codes if c in NUTS})
            metadata = {k: params[k] for k in ("diameter_mm", "max_pressure_bar", "length_km", "start_year", "end_year",
                        "capacity_E_MW", "year_of_capacity_data", "max_workingGas_M_m3", "max_power_MW") if params.get(k) is not None}
            if category == "pipeline":
                metadata["length_note"] = "Lunghezza del segmento originale, non del ritaglio visualizzato"
                metadata["schematic"] = True
            if params.get("source"):
                metadata["upstream_reference"] = str(params["source"])
            operator = params.get("operator_name") or params.get("owner")
            if category == "entry":
                operator = params.get("from_TSO") if params.get("from_country") == "IT" else params.get("to_TSO")
            start = params.get("start_year")
            status = "Progetto nell’archivio" if start and start > 2021 else "Storico · stato attuale non verificato"
            features.append({"type":"Feature", "id":props["id"], "geometry":mapping(geo), "properties":{
                "name":props["name"].split("_[")[0], "category":category, "country_code":"IT", "operator":operator,
                "regions":regions, "status":status, "source":"SciGRID_gas INET_Raw", "source_url":SCIGRID_URL,
                "source_id":props["id"], "retrieved_at":retrieved_at, "observed_at":"2021-05-12",
                "geometry_accuracy":"Collegamento schematico storico, ritagliato al perimetro italiano" if category == "pipeline" else "Localizzazione storica indicativa",
                "license":"CC-BY-4.0", "dataset_version":"1.4", "quality_status":"historical_geometry", "metadata":metadata}})
    return {"type":"FeatureCollection", "features":features}, z.read("data/LICENSE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scigrid-zip", type=Path, required=True)
    boundary_input = parser.add_mutually_exclusive_group(required=True)
    boundary_input.add_argument("--italy-geojson", type=Path)
    boundary_input.add_argument("--natural-earth-zip", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--curated", type=Path)
    args = parser.parse_args()
    if datetime.fromisoformat(args.retrieved_at).tzinfo is None:
        parser.error("--retrieved-at requires a timezone offset")
    args.output.mkdir(parents=True, exist_ok=True)
    boundary = json.loads(args.italy_geojson.read_text()) if args.italy_geojson else italy_boundary(args.natural_earth_zip)
    data, license_text = build(args.scigrid_zip, boundary, retrieved_at=args.retrieved_at)
    if args.curated:
        indexed = {f["id"]: f for f in data["features"]}
        for update in json.loads(args.curated.read_text()):
            identifier = update["id"]
            if identifier in indexed:
                feature = indexed[identifier]
                if update.get("geometry"):
                    feature["geometry"] = update["geometry"]
                feature["properties"].update(update["properties"])
            else:
                indexed[identifier] = {"type":"Feature", **update}
        data["features"] = list(indexed.values())
    (args.output / "infrastructure.geojson").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (args.output / "italy.geojson").write_text(json.dumps(boundary, ensure_ascii=False, separators=(",", ":")))
    (args.output / "LICENSE-SciGRID.txt").write_bytes(license_text)
    print(json.dumps(Counter(f["properties"]["category"] for f in data["features"])))


if __name__ == "__main__":
    main()
