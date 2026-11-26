"""Checks that need no ground truth: an LPO's numbers have to add up.

Every extracted record gets these, so a strategy can be scored on the whole test set, not just the
documents someone has labelled. A check that can't be made (no subtotal printed, say) is left out
rather than failed.
"""

from .schema import VAT_RATE


def close(a: float, b: float, rel: float = 0.005, floor: float = 0.06) -> bool:
    return abs(a - b) <= max(floor, abs(b) * rel)


def line_ok(line: dict) -> bool | None:
    """quantity x unit price = amount, with or without VAT. None: can't tell."""
    q, p, a = line.get("quantity"), line.get("unit_price"), line.get("amount")
    if q is None or p is None or a is None:
        return None
    return close(q * p, a) or close(q * p * (1 + VAT_RATE), a)


def run(record: dict) -> dict:
    """{check: True | False} for the checks that apply, plus "ok" (all of them passed)."""
    fields, lines = record["fields"], record["lines"]
    out: dict[str, bool] = {
        "has_lpo_number": bool(fields.get("lpo_number")),
        "has_lines": bool(lines),
    }
    verdicts = [v for v in (line_ok(line) for line in lines) if v is not None]
    if verdicts:
        out["lines_add_up"] = all(verdicts)
    amounts = [line["amount"] for line in lines if line.get("amount") is not None]
    subtotal, vat, total = fields.get("subtotal"), fields.get("vat"), fields.get("total")
    if amounts and (subtotal is not None or total is not None):
        s = sum(amounts)
        targets = [t for t in (subtotal, total) if t is not None]
        if total is not None:
            targets.append(total / (1 + VAT_RATE))
        out["lines_sum_to_total"] = any(close(s, t, rel=0.002, floor=1.0) for t in targets)
    if subtotal is not None and vat is not None and total is not None:
        out["totals_add_up"] = close(subtotal + vat, total, rel=0.002, floor=1.0)
    out["ok"] = all(out.values())
    return out


CHECK_LABELS = {
    "has_lpo_number": "Found an LPO number",
    "has_lines": "Found line items",
    "lines_add_up": "Quantity × price = amount on every line",
    "lines_sum_to_total": "Lines add up to the subtotal or total",
    "totals_add_up": "Subtotal + VAT = total",
    "ok": "Passed every check",
}
