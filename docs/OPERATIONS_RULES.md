# Regulatory operations — MVP slice

Independent educational demonstration. The source editions supplied for review are not asserted to be currently applicable; do not redistribute the PDFs.

| Rule | Source (printed section; one-based PDF page) | Implemented scope |
|---|---|---|
| User energy balance | Network Code XCII, 9 §3.1.2, pp. 370–373 | I+S+T-P, signed MWh |
| Storage term | same, p. 371 | Flag changed S across versions |
| Daily imbalance | 9 §4.4.2, p. 394 | Supplied buy/sell prices; signed cash |
| Provisional/definitive | 9 §§4.1–4.2, pp. 378–379 | Separate immutable demo rows; require full definitive month |
| Billing | 18 §4.1.2, p. 588 | Two DS groups; payment terms 15/30 days shown as metadata, not payment scheduling |
| LNG allocation | Piombino 2023-I, 9 §3.2.1, p. 96 | Proportional allocation of externally supplied net deviation; nonzero deviation on zero denominator blocked |

Scope limitations: T is the full supplied net term (not just bilateral trades); GME/GSE/correction components and special operator treatment are not implemented. No tariff/IVA or official invoice logic. Negative prices require review before interpreting billing directions. Decimal cent rounding and last-positive-user LNG precision residual are demo conventions. No current-law certification or live/production connections. No AI changes in this slice.

Next: verified daily price derivation and 30-day fallback (9 §4.4.1), versioned PSV transaction matching, invoice reconciliation including adjustments, real authorised data imports, source provenance and independent review, and supervisor integration. For Piombino, verify TIB agreement margins rather than assuming them; seven-day cancellation ambiguity remains blocked.
