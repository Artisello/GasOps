"""Catalog and validation for GME's PublicMarketResults gas datasets."""
import base64
import binascii
import io
import json
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256
from xml.etree import ElementTree

SOURCE = "Gestore dei Mercati Energetici S.p.A."
TERMS = "https://www.mercatoelettrico.org/Portals/0/Documents/it-IT/20261013CONDIZIONI_GENERALI_API.pdf"
MANUAL = "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20251015Manuale_tecnico_API.pdf"
PORTAL = "https://www.mercatoelettrico.org/Home/InterfacciaAPI"
ESITI = "https://www.mercatoelettrico.org/it-it/Home/Esiti/Gas/"
ENDPOINT = "https://api.mercatoelettrico.org/request/api/v1"
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 10000
MAX_DAYS = 31
FIRST_DAY = date(2000, 1, 1)
EUR_MWH = "€/MWh"
SPOT = ("MGP-GAS", "MI-GAS")


@dataclass(frozen=True)
class Dataset:
    name: str
    label: str
    segments: tuple[str, ...]
    dates: tuple[str, ...]
    dimensions: tuple[str, ...]
    units: dict[str, str | None]
    reference: str
    integers: tuple[str, ...] = ()
    # At the same offer price a curve can contain distinct volume points.
    point_fields: tuple[str, ...] = ()
    optional_dimensions: tuple[str, ...] = ()

    @property
    def date_field(self):
        return self.dates[0]

    def source_url(self, segment):
        if self.name == "GAS_ContinuousTrading" and segment == "MT-GAS":
            return ESITI + "MT-GAS/Esiti/MT-GAS"
        return self.reference.replace("{segment}", segment)


DATASETS = {
    "prices": Dataset("GAS_ImbalancePrice", "Parametri di sbilanciamento", ("GAS",),
        ("FlowDate",), (),
        {"MaxPurchaseSRGPrice": EUR_MWH, "MinSaleSRGPrice": EUR_MWH, "WeightedAveragePrice": EUR_MWH,
         "MGASVolumes": None},
        ESITI + "PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"),
    "igi": Dataset("GAS_IGIndex", "Indice IGI", ("IGI",), ("FlowDate",), ("Product",),
        {"Price": EUR_MWH},
        "https://www.mercatoelettrico.org/it-it/Home/Pubblicazioni/Indici-GME/IGIndexGmeEsiti"),
    "continuous": Dataset("GAS_ContinuousTrading", "Negoziazione continua", (*SPOT, "MT-GAS"),
        ("FlowDate",), ("Market", "Product"),
        {"FirstPrice": EUR_MWH, "LastPrice": EUR_MWH, "MinPrice": EUR_MWH, "MaxPrice": EUR_MWH,
         "AveragePrice": EUR_MWH, "CheckPrice": EUR_MWH, "MWVolumes": "MW", "MWhVolumes": "MWh",
         "PurchasingPrice": EUR_MWH, "SellingPrice": EUR_MWH, "OTCMWVolumes": "MW",
         "OTCMWhVolumes": "MWh", "OpenPositions": None, "Matches": "abbinamenti"},
        ESITI + "{segment}/Esiti/NegoziazioneContinua",
        ("OTCMWVolumes", "OTCMWhVolumes", "OpenPositions", "Matches")),
    "curve": Dataset("GAS_DemandAndSupply", "Curve domanda e offerta",
        (*SPOT, "MGS-Edison", "MGS-Stogit", "MGS-Adriatica", "PB-GAS", "PBZ-Edison stoccaggi",
         "PBZ-G+1", "PBZ-G+N", "PBZ-Import", "PBZ-Linepack", "PBZ-LNG", "PBZ-PSV",
         "PBZ-Reintegro Stogit", "PBZ-Risorse PSV", "PBZ-Stogit"),
        ("FlowDate",), ("Market", "Type"),
        {"Volumes": None, "AuctionPrice": EUR_MWH, "Price": EUR_MWH}, MANUAL, point_fields=("Price", "Volumes")),
    "mgas": Dataset("GAS_MGASAuctionResults", "Aste MGAS", SPOT, ("FlowDate",), ("Market", "Product"),
        {"Price": EUR_MWH, "TotalVolumesMW": "MW", "TotalVolumesMWh": "MWh",
         "PurchasesTSO": None, "SalesTSO": None},
        ESITI + "{segment}/Esiti/Asta"),
    "mgs": Dataset("GAS_MGSAuctionResults", "MGS · stoccaggio", ("MGS",),
        ("FlowDate",), ("StorageCompany", "Type"),
        {"Price": EUR_MWH, "Volumes": None, "SRGPurchases": None, "SRGSales": None, "Participants": "operatori"},
        ESITI + "MGS/Esiti/MGS", ("Participants",), optional_dimensions=("Type",)),
    "mpl": Dataset("GAS_MPLAuctionResults", "MPL · locational", ("MPL",),
        ("SessionDate", "GasDay"), ("Reason", "Type", "OfferPoint"),
        {"Price": EUR_MWH, "Volumes": None, "SRGVolumes": None, "Participants": "operatori"},
        ESITI + "MPL/Esiti", ("Participants",)),
    "pgr": Dataset("GAS_PGRResults", "Gas Release · PGR", ("PGR",), ("Date",), (),
        {"VolumeOfferedByGSE": None, "RemunerationPrice": None, "VolumeOfferedByParticipants": None,
         "VolumeAllocated": None, "NumberOfAllocates": "operatori"},
        "https://www.mercatoelettrico.org/it-it/Home/Mercati/Mercato-Gas/PiattaformaGasRelease",
        ("NumberOfAllocates",)),
}


def api_configured():
    return credentials() is not None


def credentials():
    """Read the server-side GME integration configuration."""
    import streamlit as st
    try:
        config = st.secrets["gme"]
        values = tuple(config[key] for key in ("username", "password", "base_url"))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return values if all(isinstance(value, str) and value.strip() for value in values) else None


def _object(pairs):
    result = {}
    for key, value in pairs:
        key = key.casefold()
        if key in result:
            raise ValueError("Campi GME duplicati.")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("Numero non finito.")


def json_object(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("JSON GME vuoto o oltre 4 MiB.")
    try:
        return json.loads(raw, parse_float=D, parse_int=D, parse_constant=_nonfinite,
                          object_pairs_hook=_object)
    except (UnicodeError, ValueError, InvalidOperation, RecursionError):
        raise ValueError("JSON GME non valido.") from None


def _text(value, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("Campo testuale GME non valido.")
    return value.strip()


def unpack_response(envelope):
    """Single-file archive used for market results. Never extract to disk."""
    if not isinstance(envelope, dict) or envelope.get("resultrequest") not in (None, ""):
        raise ValueError("Richiesta dati rifiutata da GME.")
    format_type = envelope.get("formattype")
    suffix = {".json.zip": ".json", ".xml.zip": ".xml"}.get(format_type) if isinstance(format_type, str) else None
    if not suffix:
        raise ValueError("Formato di risposta GME non supportato.")
    request_id = envelope.get("requestid")
    if request_id is not None:
        request_id = _text(request_id)
    try:
        content = base64.b64decode(envelope["contentresponse"], validate=True)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].is_dir() or not members[0].filename.lower().endswith(suffix):
                raise ValueError("Atteso un singolo documento nell’archivio GME.")
            if members[0].compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError("Compressione ZIP GME non supportata.")
            if members[0].file_size > MAX_BYTES:
                raise ValueError("Archivio GME oltre il limite di decompressione.")
            with archive.open(members[0]) as member:
                payload = member.read(MAX_BYTES + 1)
    except (KeyError, TypeError, binascii.Error, zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error):
        raise ValueError("Archivio GME non leggibile.") from None
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("Documento GME vuoto o troppo grande.")
    if (suffix == ".xml") != payload.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
        raise ValueError("Formato del documento GME incoerente.")
    return payload, request_id


def decode_response(raw):
    return unpack_response(json_object(raw))[0]


def _xml_rows(raw):
    # UTF-8 only and no declarations that can expand entities or reference files.
    try:
        decoded = raw.decode("utf-8-sig")
        upper = decoded.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise ValueError("Dichiarazioni XML GME non consentite.")
        root = ElementTree.fromstring(decoded)
    except (UnicodeError, ElementTree.ParseError):
        raise ValueError("XML GME non valido.") from None
    if len(root) > MAX_ROWS:
        raise ValueError("Troppe osservazioni GME.")
    def fields(record):
        if not len(record) or any(len(field) for field in record):
            raise ValueError("Attesi record XML GME con campi scalari.")
        return _object((field.tag.rsplit("}", 1)[-1], field.text or None) for field in record)
    return [fields(record) for record in root]


def _date(value):
    digits = str(value)
    if len(digits) != 8 or not digits.isascii() or not digits.isdigit():
        raise ValueError("Data GME non valida.")
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def _number(value):
    # Market results encode some unavailable measures as the string "null".
    if value is None or isinstance(value, str) and value.strip().casefold() == "null":
        return None
    if not isinstance(value, (D, str)) or isinstance(value, str) and len(value) > 64:
        raise ValueError("Valore numerico GME non valido.")
    try:
        number = D(value)
    except InvalidOperation:
        raise ValueError("Valore numerico GME non valido.") from None
    if not number.is_finite() or number.as_tuple().exponent < -12 or number.copy_abs() > D("1e15"):
        raise ValueError("Valore numerico GME fuori limite.")
    return number


def validate_window(kind, segment, first, last, cutoff):
    if kind not in DATASETS or segment not in DATASETS[kind].segments:
        raise ValueError("Dataset o segmento GME non supportato.")
    if (type(first) is not date or type(last) is not date or
            not FIRST_DAY <= first <= last <= cutoff or (last - first).days >= MAX_DAYS):
        raise ValueError(f"Scegli fino a {MAX_DAYS} giorni conclusi.")


def parse(raw, kind, cutoff, *, segment=None, first=None):
    """Validate one dataset and segment. Missing measures remain null."""
    spec = DATASETS[kind]
    segment = segment or spec.segments[0]
    if segment not in spec.segments or not raw or len(raw) > MAX_BYTES:
        raise ValueError("Estratto GME o segmento non valido.")
    payload = raw
    request_id = None
    if raw.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
        data = _xml_rows(raw)
    else:
        data = json_object(raw)
        if isinstance(data, dict) and "contentresponse" in data:
            payload, request_id = unpack_response(data)
            data = (_xml_rows(payload) if payload.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<")
                    else json_object(payload))
    if not isinstance(data, list) or len(data) > MAX_ROWS:
        raise ValueError("Atteso un elenco di osservazioni GME.")
    result = {}
    missing = 0
    identity = spec.dates + spec.dimensions
    required = tuple(field for field in identity if field not in spec.optional_dimensions)
    for item in data:
        if not isinstance(item, dict) or not all(key.casefold() in item for key in required):
            raise ValueError("Identificativi GME mancanti o schema non riconosciuto.")
        if not any(field.casefold() in item for field in spec.units):
            raise ValueError("Misure GME mancanti o schema non riconosciuto.")
        row = {}
        for field in spec.dates:
            day = _date(item[field.casefold()])
            if day < FIRST_DAY or field == spec.date_field and not (first or FIRST_DAY) <= day <= cutoff:
                raise ValueError("Data GME fuori intervallo.")
            row[field] = day.isoformat()
        for field in spec.dimensions:
            value = item.get(field.casefold())
            if field in spec.optional_dimensions and (value is None or isinstance(value, str) and not value.strip()):
                row[field] = None
            else:
                row[field] = _text(value)
        if "Market" in row:
            expected = segment.removesuffix("-GAS") if segment in (*SPOT, "MT-GAS") else segment
            if row["Market"].casefold() != expected.casefold():
                raise ValueError("Mercato GME diverso dal segmento richiesto.")
        for field, unit in spec.units.items():
            number = _number(item.get(field.casefold()))
            if number is None:
                missing += 1
            else:
                if (unit in ("MW", "MWh", "operatori", "abbinamenti") or
                        field in ("Volumes", "MGASVolumes", "SRGPurchases", "SRGSales",
                                  "SRGVolumes", "PurchasesTSO", "SalesTSO") or field.startswith("Volume")) and number < 0:
                    raise ValueError("Quantità GME negativa fuori schema.")
                if field in spec.integers and number != number.to_integral_value():
                    raise ValueError("Conteggio GME non intero.")
            row[field] = number
        key = tuple(row[field] for field in identity)
        if spec.point_fields:
            if row["Price"] is None:
                raise ValueError("Prezzo della curva GME mancante.")
            key += tuple(row[field] for field in spec.point_fields)
        if key in result:
            raise ValueError("Chiave GME duplicata. Verifica sessioni o revisioni alla fonte.")
        result[key] = row
    ordered = sorted(result, key=lambda key: tuple(part or "" for part in key[:len(identity)]))
    return {"kind": kind, "segment": segment, "rows": tuple(result[k] for k in ordered),
            "sha": sha256(payload).hexdigest(), "request_id": request_id, "missing": missing,
            "synthetic": False, "origin": "import"}


def study_prices(row, title_volume, rate, history=None, *, ordinary=True):
    from .commercial_controls import imbalance_prices
    return imbalance_prices(date.fromisoformat(row["FlowDate"]), title_volume, row["WeightedAveragePrice"],
                            row["MaxPurchaseSRGPrice"], row["MinSaleSRGPrice"], rate, history, ordinary=ordinary)


def fetch_private(kind, first, last, login, password, *, transport=None):
    """Compatibility entry point for authorized callers of the original importer."""
    from .gme_api import Client
    from .gas_calendar import closed_gas_day
    from .models import utc_now
    if kind not in DATASETS:
        raise ValueError("Dataset GME non supportato.")
    client = Client(login, password, ENDPOINT, transport=transport)
    _, payload = client.download(kind, DATASETS[kind].segments[0], first, last, closed_gas_day(utc_now()))
    return payload


def main():
    from .gme_api import main as probe
    probe()


if __name__ == "__main__":
    main()
