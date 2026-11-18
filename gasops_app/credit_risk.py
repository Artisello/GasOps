"""Credit exposure controls for CdR XCII and CdRig Piombino 2023-I.

Only operator-validated monetary inputs, or explicitly synthetic scenarios.
No assessment of eligibility of guarantees, no transactions or access decisions.
"""
from decimal import Decimal as D, ROUND_CEILING

CDR = "CdR XCII, cap. 5 §§1.4.1–1.4.5, PDF pp. 68–80"
LNG = "CdRig Piombino 2023-I, cap. 7 §§1, 1.1, 3, PDF pp. 63–68"
CENT = D("0.01")


def _decimal(value, *, nonnegative=False):
    if not isinstance(value, D) or not value.is_finite():
        raise ValueError("Importo o parametro mancante/non finito.")
    if nonnegative and value < 0:
        raise ValueError("Parametro non negativo richiesto.")
    return value


def patt_horizon(balancing_late_pct=None, transport_late_pct=None, *, verifiable):
    """Percentages of invoice amounts (not number of invoices), for applicable semester."""
    if not verifiable:
        return 7
    a, b = (_decimal(v, nonnegative=True) for v in
            (balancing_late_pct, transport_late_pct))
    if max(a, b) > 100:
        raise ValueError("Percentuali di irregolarità tra 0 e 100.")
    worst = max(a, b)
    return 7 if worst > 20 else 5 if worst > 10 else 3


def credit_position(pfat, pdet, patt, guarantees, overdue):
    """Pfat/Pdet/Patt signed from system perspective, inclusive of applicable VAT.

    Guarantees must already be effective, eligible and valued for this user/date.
    Overdue is C only: do not include the same invoices in Pfat.
    """
    pfat, pdet, patt = map(_decimal, (pfat, pdet, patt))
    g = sum((_decimal(v, nonnegative=True) for v in guarantees), D(0))
    c = _decimal(overdue, nonnegative=True)
    eps, meps = pfat+pdet+patt, g-c
    ratio = eps/meps*100 if meps > 0 else None
    status = ("LIMITE" if eps >= meps else
              "VERIFICA MEPSu" if meps <= 0 else
              "ATTENZIONE" if eps >= meps*D(".90") else "OK")
    return {"pfat":pfat,"pdet":pdet,"patt":patt,"g":g,"c":c,"eps":eps,
            "meps":meps,"headroom":meps-eps,"ratio":ratio,"status":status,
            "condition_met":eps<meps,"reference":CDR}


def stress_patt(horizon, daily_extra_mwh, estimated_eur_mwh, vat_pct, extra_psv_mwh):
    """Illustrative incremental short exposure, NOT official Patt reconstruction.

    Extra PSV is a non-overlapping incremental short position, including future
    registered transactions beyond the horizon, where applicable.
    Price supplied by operator; no substitution with spot/forecast price.
    """
    if horizon not in (3, 5, 7):
        raise ValueError("Orizzonte Patt non valido.")
    q, price, vat, psv = (_decimal(v, nonnegative=True) for v in
                           (daily_extra_mwh, estimated_eur_mwh, vat_pct, extra_psv_mwh))
    if vat > 100:
        raise ValueError("IVA non valida.")
    return (q*horizon+psv)*price*(1+vat/100)


def additional_guarantee_90(position):
    """Theoretical extra effective G for <=90%, not a collateral demand."""
    eps, meps = position["eps"], position["meps"]
    target = max(CENT, (max(D(0), eps)/D(".90")).quantize(CENT, rounding=ROUND_CEILING))
    return max(D(0), (target-meps).quantize(CENT, rounding=ROUND_CEILING))


def lng_security(top_slots, annual_commitment, transport_commitment, effective_guarantee):
    """One thermal year, already validated economic obligations; no rating exemption.

    Effective guarantee must be valid for the bid period, net of calls.
    Does not decide bid acceptance or net multiple thermal years.
    """
    slots = sorted((_decimal(v, nonnegative=True) for v in top_slots), reverse=True)
    annual, transport, g = (_decimal(v, nonnegative=True) for v in
                             (annual_commitment, transport_commitment, effective_guarantee))
    top = sum(slots[:3], D(0))
    if annual < top:
        raise ValueError("Il corrispettivo annuo deve comprendere almeno gli slot indicati.")
    required = max(top, annual*D(".36"))+transport
    return {"required":required,"headroom":g-required,"top_three":top,
            "annual_36":annual*D(".36"),"transport":transport,"reference":LNG}


def lng_psv_security(largest_ship_mwh, advanced_gas_mwh):
    """Quantity of the guarantee sale under cap. 7 §3; not a monetary guarantee."""
    return max(_decimal(largest_ship_mwh, nonnegative=True),
               _decimal(advanced_gas_mwh, nonnegative=True))
