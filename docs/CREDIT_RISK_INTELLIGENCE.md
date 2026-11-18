# Credit Risk Intelligence (P0)

**Scope:** simulation only, one fictitious user; no SRG private data, no live
eligibility decisions, no automated notices. Inputs are illustrative or
operator-validated as of a single common snapshot. No private data upload.

- CdR XCII, chapter 5 §§1.4.1–1.4.5 (PDF pp. 68–80): signed VAT-inclusive
  Pfat/Pdet/Patt from system perspective; MEPSu = effective G – overdue unpaid
  balancing invoices C. Do not double-count C in Pfat. Strict EPSu < MEPSu;
  warning at 90%, loss of requirements at equality or above. For MEPSu <=0 no ratio.
- Payment regularity: percentages of amounts, separately balancing and transport;
  worse result determines applicable semester (3 days <=10%, 5 days >10% and
  <=20%, 7 days >20%, new or unverifiable). No automated semester/history validation.
- Patt stress is an incremental non-overlapping short scenario, not the
  regulatory Patt calculation. Full Patt requires point-level expected withdrawals,
  capacity/utilization coefficients, distribution allocation, programmed storage
  and interconnection exits, all registered PSV transactions (including beyond
  horizon), zero injection assumption, prior-month mean buy imbalance price
  rounded to six decimals in EUR/kWh, VAT and all relevant adjustments.
- G must be effective/recognized, not merely submitted. Eligibility, valuation of
  storage gas/rating, receipt/booking calendar, and contractual exceptions are not
  automated. At breach consult §1.4.5 for restrictions and restoration; no
  simulated action is submitted or considered an official notice.
- CdRig FSRU Piombino 2023-I, chapter 7 §§1, 1.1, 3 (PDF pp. 63–68):
  separate monetary capacity guarantee (max of three highest slots or 36% of
  highest annual commitment, plus transport commitments). Demo covers one
  thermal year only, valid net guarantee; no rating exemption or bid decision.
  PSV guarantee sale quantity = max(largest technical ship volume converted to
  MWh, advanced gas MWh). The registered sale can affect SRG Patt; never add
  LNG monetary guarantee to SRG guarantee automatically.
- The supplied document revisions are study references, not certification of
  current regulations. Operator confirmation is required for production use.

Run targeted tests: python -m pytest -q tests/test_credit_risk.py
