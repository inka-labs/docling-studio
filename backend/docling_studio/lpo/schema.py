"""What we read off an LPO, how values are normalised, and how a result is scored against ground truth.

A record is {"fields": {name: value | None}, "lines": [{column: value | None}, ...]}. Dates are ISO
(YYYY-MM-DD), amounts are floats, everything else is text.
"""

import re
from datetime import date, datetime
from difflib import SequenceMatcher

DOCUMENT_TYPES = {
    "purchase_order": "Purchase order",
    "goods_received_note": "Goods received note",
    "invoice": "Invoice",
    "delivery_note": "Delivery note",
    "credit_note": "Credit note",
    "other": "Something else",
}

# name, label, kind (text | date | number | choice), group
FIELDS = [
    ("document_type", "Document type", "choice", "header"),
    ("lpo_number", "LPO number", "text", "header"),
    ("order_date", "Order date", "date", "header"),
    ("delivery_date", "Delivery date", "date", "header"),
    ("buyer", "Buyer", "text", "parties"),
    ("store", "Store / ship to", "text", "parties"),
    ("supplier", "Supplier", "text", "parties"),
    ("currency", "Currency", "text", "parties"),
    ("subtotal", "Subtotal", "number", "totals"),
    ("vat", "VAT", "number", "totals"),
    ("total", "Total", "number", "totals"),
]
FIELD_KIND = {name: kind for name, _, kind, _ in FIELDS}

LINE_COLUMNS = [
    ("item_code", "Item code", "text"),
    ("barcode", "Barcode", "text"),
    ("description", "Description", "text"),
    ("uom", "Unit", "text"),
    ("quantity", "Quantity", "number"),
    ("unit_price", "Unit price", "number"),
    ("amount", "Amount", "number"),
]
LINE_KIND = {name: kind for name, _, kind in LINE_COLUMNS}

# VAT in Kenya: line amounts and totals are sometimes shown with it, sometimes without.
VAT_RATE = 0.16


def describe() -> dict:
    """The schema, for the review screen's form."""
    return {
        "fields": [{"name": n, "label": l, "kind": k, "group": g} for n, l, k, g in FIELDS],
        "lines": [{"name": n, "label": l, "kind": k} for n, l, k in LINE_COLUMNS],
        "document_types": DOCUMENT_TYPES,
    }


def empty_record() -> dict:
    return {"fields": {name: None for name, *_ in FIELDS}, "lines": []}


# Parsing ---------------------------------------------------------------------------------------

NUMBER = re.compile(r"^\(?-?(?:KES|KSH|KSHS|SH|SHS)?\.?\s*-?\d[\d,\s]*(?:\.\d+)?\)?-?$", re.I)


def parse_number(text) -> float | None:
    """'3,730.41' -> 3730.41; '(12.00)' and '12.00-' -> -12.0; anything that isn't one number -> None."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    s = str(text).strip().replace(" ", " ")
    if not s or not NUMBER.match(s):
        return None
    negative = s.startswith("(") or s.endswith("-") or "-" in s.lstrip("(")[:1]
    digits = re.sub(r"[^\d.]", "", s)
    if digits.count(".") > 1 or not any(c.isdigit() for c in digits):
        return None
    # "1 234" is a thousands gap; "12 34" (two numbers) isn't one number
    if re.search(r"\d\s+\d", s) and not re.fullmatch(r"\D*\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?\D*", s):
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_PATTERNS = [
    # 13 July, 2026 / 13-Jul-2026 / 13 Jul 26
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]+([A-Za-z]{3,9})[\s\-/.,]+(\d{2,4})\b"), "dmy_name"),
    # July 13, 2026
    (re.compile(r"\b([A-Za-z]{3,9})[\s\-/.]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-/.]+(\d{4})\b"), "mdy_name"),
    # 2026-07-13
    (re.compile(r"\b(\d{4})[\-/.](\d{1,2})[\-/.](\d{1,2})\b"), "ymd"),
    # 13/07/2026, 13.07.26 (day first: Kenyan documents)
    (re.compile(r"\b(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{2,4})\b"), "dmy"),
]


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def parse_date(text) -> str | None:
    """The first date in a piece of text, as YYYY-MM-DD (day first when it's ambiguous)."""
    if text is None:
        return None
    s = str(text)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        return s.strip()
    for pattern, kind in DATE_PATTERNS:
        for m in pattern.finditer(s):
            try:
                if kind == "dmy_name":
                    month = MONTHS.get(m.group(2)[:3].lower())
                    if not month:
                        continue
                    d = date(_year(m.group(3)), month, int(m.group(1)))
                elif kind == "mdy_name":
                    month = MONTHS.get(m.group(1)[:3].lower())
                    if not month:
                        continue
                    d = date(_year(m.group(3)), month, int(m.group(2)))
                elif kind == "ymd":
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    day, month = int(m.group(1)), int(m.group(2))
                    if month > 12 and day <= 12:  # clearly month first
                        day, month = month, day
                    d = date(_year(m.group(3)), month, day)
            except ValueError:
                continue
            if 2000 <= d.year <= datetime.now().year + 2:
                return d.isoformat()
    return None


def clean_text(text) -> str | None:
    if text is None:
        return None
    s = re.sub(r"\s+", " ", str(text)).strip(" :;,-*|\t")
    return s or None


def clean_code(text) -> str | None:
    """An LPO number or item code: no spaces, no barcode stars."""
    s = clean_text(text)
    if not s:
        return None
    s = re.sub(r"\s+", "", s).strip("*#:").upper()
    return s or None


def normalise(record: dict) -> dict:
    """A record from anywhere (an extractor, the review form) in its canonical shape."""
    out = empty_record()
    fields = (record or {}).get("fields") or {}
    for name, kind in FIELD_KIND.items():
        out["fields"][name] = _norm_value(name, kind, fields.get(name))
    for line in (record or {}).get("lines") or []:
        row = {name: _norm_value(name, kind, (line or {}).get(name)) for name, kind in LINE_KIND.items()}
        if any(v not in (None, "") for v in row.values()):
            out["lines"].append(row)
    return out


def _norm_value(name: str, kind: str, value):
    if value in (None, ""):
        return None
    if kind == "number":
        return parse_number(value)
    if kind == "date":
        return parse_date(value)
    if kind == "choice":
        v = str(value).strip().lower().replace(" ", "_")
        return v if v in DOCUMENT_TYPES else None
    if name in ("lpo_number", "item_code", "barcode"):
        return clean_code(value)
    return clean_text(value)


# Comparing with ground truth ---------------------------------------------------------------------


def _key(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def same(kind: str, a, b) -> bool:
    """Whether an extracted value matches the true one."""
    if a is None or b is None:
        return a is None and b is None
    if kind == "number":
        # unit prices come with many decimals on some POs (31.086729) and rounded on others
        return abs(a - b) <= max(0.011, abs(b) * 0.001)
    if kind in ("date", "choice"):
        return a == b
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return True
    # names: "Naivas Ltd" vs "NAIVAS LIMITED", "WESTLANDS" vs "Westlands Store"
    return bool(ka and kb) and (ka in kb or kb in ka or SequenceMatcher(None, ka, kb).ratio() >= 0.85)


def _line_similarity(a: dict, b: dict) -> float:
    for code in ("barcode", "item_code"):
        if a.get(code) and b.get(code) and _key(a[code]) == _key(b[code]):
            return 1.0
    da, db = _key(a.get("description")), _key(b.get("description"))
    return SequenceMatcher(None, da, db).ratio() if da and db else 0.0


def match_lines(pred: list[dict], truth: list[dict]) -> list[tuple[int, int]]:
    """Pairs (pred index, truth index), best first, each line used once."""
    scored = sorted(((s, i, j) for i, p in enumerate(pred) for j, t in enumerate(truth)
                     if (s := _line_similarity(p, t)) >= 0.6), reverse=True)
    used_p, used_t, pairs = set(), set(), []
    for _, i, j in scored:
        if i not in used_p and j not in used_t:
            used_p.add(i)
            used_t.add(j)
            pairs.append((i, j))
    return pairs


def compare(pred: dict, truth: dict) -> dict:
    """Field by field and line by line: what was right."""
    pred, truth = normalise(pred), normalise(truth)
    fields = {}
    for name, kind in FIELD_KIND.items():
        p, t = pred["fields"][name], truth["fields"][name]
        if p is None and t is None:
            continue  # nothing to find, nothing found
        fields[name] = same(kind, p, t)
    pairs = match_lines(pred["lines"], truth["lines"])
    cells_right = cells_total = 0
    for i, j in pairs:
        for name in ("quantity", "unit_price", "amount"):
            t = truth["lines"][j][name]
            if t is not None:
                cells_total += 1
                cells_right += same("number", pred["lines"][i][name], t)
    n_pred, n_truth = len(pred["lines"]), len(truth["lines"])
    lines = {
        "predicted": n_pred, "true": n_truth, "matched": len(pairs),
        "recall": len(pairs) / n_truth if n_truth else (1.0 if not n_pred else 0.0),
        "precision": len(pairs) / n_pred if n_pred else (1.0 if not n_truth else 0.0),
        "numbers_right": cells_right, "numbers_total": cells_total,
    }
    perfect = all(fields.values()) and len(pairs) == n_truth == n_pred and cells_right == cells_total
    return {"fields": fields, "lines": lines, "perfect": perfect}
