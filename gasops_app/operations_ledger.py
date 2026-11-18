"""Source-grounded, synthetic-only commercial accounting demonstration.

References: Network Code XCII, chapter 9 §§3.1.2, 4.1, 4.2, 4.4.2
(PDF pages 370–373, 378–379, 394); chapter 18 §4.1.2 (PDF p. 588).
Applicability and rounding conventions are not certified.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from calendar import monthrange

D = Decimal
CENT = D("0.01")
REFERENCE = "CdR XCII, cap. 9 §§3.1.2, 4.4.2; cap. 18 §4.1.2"


def monetary(value: Decimal) -> Decimal:
    # Demo convention only; not a certified invoicing rounding rule.
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class BalanceRow:
    user: str
    day: date
    version: int
    stage: str
    injected: Decimal  # I_k, MWh
    storage_net: Decimal  # S_k, withdrawal from storage positive
    psv_net: Decimal  # T^N_k, purchases positive; complete net term supplied
    withdrawn: Decimal  # P_k, MWh
    buy: Decimal | None
    sell: Decimal | None

    def __post_init__(self):
        if not self.user or self.stage not in ("provisional", "definitive") or self.version < 1:
            raise ValueError("Invalid user, stage or version")
        for value in (self.injected, self.storage_net, self.psv_net, self.withdrawn, self.buy, self.sell):
            if value is not None and (not isinstance(value, D) or not value.is_finite()):
                raise ValueError("Use finite Decimal inputs")
        if any(v is None for v in (self.injected, self.storage_net, self.psv_net, self.withdrawn)):
            raise ValueError("Missing energy component; never substitute zero")

    @property
    def imbalance(self) -> Decimal:
        return self.injected + self.storage_net + self.psv_net - self.withdrawn

    @property
    def cash(self) -> Decimal | None:
        if not self.imbalance:
            return D("0.00")
        price = self.buy if self.imbalance < 0 else self.sell
        return None if price is None else monetary(self.imbalance * price)


def revision_pairs(rows: list[BalanceRow]):
    """Validate version identity and keep each user's gas day separate."""
    groups = {}
    for row in rows:
        key = row.user, row.day
        versions = groups.setdefault(key, {})
        if row.version in versions:
            raise ValueError("Duplicate user/gas-day/version")
        versions[row.version] = row
    result = []
    for key, versions in sorted(groups.items()):
        ordered = [versions[i] for i in sorted(versions)]
        if any(v.storage_net != ordered[0].storage_net for v in ordered):
            raise ValueError("S_k changed: nominated=allocated under §3.1.2; review exception")
        if any(a.stage == "definitive" and b.stage == "provisional" for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Invalid stage regression")
        provisional = [v for v in ordered if v.stage == "provisional"]
        result.append((provisional[-1] if provisional else None, ordered[-1]))
    return result


def monthly_preview(rows: list[BalanceRow], user: str, year: int, month: int) -> dict:
    """Separate negative and positive DS groups; never treat net as invoice."""
    days = monthrange(year, month)[1]
    selected = [r for r in rows if r.user == user and (r.day.year, r.day.month) == (year, month)]
    pairs = revision_pairs(selected)
    if len(pairs) != days or any(last.stage != "definitive" or last.cash is None for _, last in pairs):
        return {"status": "BLOCKED_REVIEW", "reason": "Complete definitive daily balances and relevant prices required.", "days": len(pairs)}
    latest = [last for _, last in pairs]
    short = sum((-r.cash for r in latest if r.imbalance < 0), D("0"))
    long = sum((r.cash for r in latest if r.imbalance > 0), D("0"))
    negative_price = any(r.imbalance and (r.buy if r.imbalance < 0 else r.sell) < 0 for r in latest)
    return {"status": "REVIEW_REQUIRED" if negative_price else "SIMULATION_ONLY", "days": days,
            "short_group_eur": short, "long_group_eur": long, "net_user_cash_eur": long-short,
            "negative_price_review": negative_price, "reference": REFERENCE,
            "short_payment_days": 15, "long_payment_days": 30}


def sample_rows() -> list[BalanceRow]:
    """Fictitious users; fixed, reproducible September 2026 demonstration."""
    rows = []
    for i in range(30):
        day = date(2026, 9, 1) + timedelta(days=i)
        injected = D(8000 + 25 * i)
        storage = D(300 if i % 2 else -100)
        psv = D(200)
        withdrawn = injected + storage + psv + D(200 if i % 3 else -150)
        fields = ("DEMO-001", day)
        rows.append(BalanceRow(*fields, 1, "provisional", injected, storage, psv, withdrawn, D(42), D(38)))
        rows.append(BalanceRow(*fields, 2, "definitive", injected, storage, psv, withdrawn + D(100 if i == 4 else 0), D(42), D(38)))
    return rows


def allocate_lng_deviation(programmes: dict[str, Decimal], net_deviation: Decimal) -> dict[str, Decimal]:
    """Piombino 2023-I, cap. 9 §3.2.1, PDF p. 96.
    Deviation must already be net of the applicable TIB agreement margins.
    A final residual is assigned to the last positive programme for exact
    Decimal conservation; this is a demo precision convention, not a TIB rule.
    """
    if not isinstance(net_deviation, D) or not net_deviation.is_finite():
        raise ValueError("Invalid net deviation")
    if not programmes or any(not isinstance(v, D) or not v.is_finite() or v < 0 for v in programmes.values()):
        raise ValueError("Invalid programmes")
    total = sum(programmes.values(), D(0))
    if total == 0:
        if net_deviation == 0:
            return {k: D(0) for k in programmes}
        raise ValueError("Zero allocation denominator; manual review")
    if total + net_deviation < 0:
        raise ValueError("Negative resulting energy; manual review")
    result = {}
    keys = sorted(k for k, v in programmes.items() if v > 0)
    for key in programmes:
        result[key] = D(0)
    for key in keys[:-1]:
        result[key] = net_deviation * programmes[key] / total
    result[keys[-1]] = net_deviation - sum(result.values(), D(0))
    return result
