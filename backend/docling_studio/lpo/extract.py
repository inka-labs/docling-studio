"""Reading an LPO's fields off Docling's result, without a template per buyer.

Docling gives text items and tables, each with a box on its page. The mapper turns both into
"tokens" (a text item, or one table cell) and then:

- header fields: finds a token that starts with one of the field's labels ("P.O. Date", "LPO No")
  and takes the value from the same token ("LPO No: P0423") or the nearest token to its right or
  just below it;
- line items: picks the tables whose header row names a description and a quantity or amount
  column, maps each column by its header, and appends headerless tables that continue them on later
  pages (same number of columns);
- when no table maps (scans often come out as one blob), reads lines of text instead and keeps the
  ones holding three numbers where quantity x price = amount.

Every value keeps where it was found (page and box, 0-1 of the page) for the review screen.
"""

import re
from dataclasses import dataclass, field
from itertools import combinations

from .checks import close
from .schema import DOCUMENT_TYPES, VAT_RATE, clean_code, clean_text, empty_record, normalise, parse_date, parse_number

# Bump when the mapping changes: experiments whose results came from an older mapper can be re-mapped.
MAPPER_VERSION = 5  # 5: values with the label's colon read into them (PaddleOCR); 2: labels ending in "#" or "."; LPO numbers mid-line
#                     3: quantities with units, headerless item tables, total chosen by the lines,
#                        "Total 184.00 Unit" is a count, not money
#                     4: money values only on the label's line (not under a "Total" column header)


@dataclass
class Tok:
    text: str
    page: int
    l: float
    t: float
    r: float
    b: float
    pw: float
    ph: float
    table: int | None = None
    row: int | None = None
    col: int | None = None
    order: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def h(self) -> float:
        return max(self.b - self.t, 1.0)

    def box(self) -> dict:
        return {"page": self.page, "box": [round(self.l / self.pw, 4), round(self.t / self.ph, 4),
                                           round(self.r / self.pw, 4), round(self.b / self.ph, 4)]}


def _rx(*patterns: str) -> re.Pattern:
    # (?![a-z]) rather than \b: a label can end in "#" or "." ("PURCHASE ORDER # 123", "LPO No.")
    return re.compile(r"^\W*(?:" + "|".join(patterns) + r")(?![a-z])\s*[:.\-=]*\s*", re.I)


# Field labels, most specific first. A label has to start its token.
LABELS: dict[str, re.Pattern] = {
    "lpo_number": _rx(r"l\.?\s?p\.?\s?o\.?\s*(?:number|no\.?|num|#|ref)",
                      r"local\s+purchase\s+order\s*(?:number|no\.?|#)?",
                      r"purchase\s+order\s*(?:number|no\.?|#)",
                      r"p\.?\s?o\.?\s*(?:number|no\.?|num|#)",
                      r"order\s*(?:number|no\.?|num|#|ref)",
                      r"order(?!\s*(?:date|qty|quantity|value|total|valid|type|status))"),
    "order_date": _rx(r"p\.?\s?o\.?\s*date", r"order\s*date", r"l\.?p\.?o\.?\s*date", r"date\s+of\s+order",
                      r"date\s*ordered", r"order\s*placed"),
    "delivery_date": _rx(r"delivery\s*date", r"expected\s*(?:delivery\s*)?date", r"deliver(?:y)?\s*by",
                         r"deadline", r"due\s*date", r"date\s*required", r"receipt\s*date", r"received\s*date"),
    "store": _rx(r"store\s*name", r"order\s+for\s+branch", r"ship\s*to", r"deliver(?:y|ed)?\s*to", r"delivery\s*(?:address|location|point|branch)",
                 r"branch(?:\s*name)?", r"location", r"outlet", r"store(?!\s*(?:/|details|keeper|manager))"),
    "supplier": _rx(r"supplier(?!\s*(?:id|code|no|number|ref|address|tel|email|#|account|\.\.))(?:\s*name)?",
                    r"vendor(?!\s*(?:id|code|no|number|ref|#|account))(?:\s*name)?", r"to\s*supplier", r"to(?=\s*:)"),
    "buyer": _rx(r"company\s*name", r"buyer(?:\s*name)?", r"customer(?:\s*name)?", r"bill\s*to", r"invoice\s*to"),
    "currency": _rx(r"currency"),
    "subtotal": _rx(r"sub\s*-?\s*total", r"total\s*(?:excl\.?|exclusive|before\s*(?:vat|tax)|b\.?\s*tax)",
                    r"net\s*total", r"amount\s*(?:excl\.?|before\s*(?:vat|tax))", r"total\s*net"),
    "vat": _rx(r"(?:total\s*)?v\.?a\.?t\.?(?!\s*(?:reg|no|pin|#|registered|code|rate|%|\d))(?:\s*amount)?",
               r"tax\s*amount", r"total\s*tax", r"tax(?!\s*(?:code|rate|pin|invoice|%))"),
    "total": _rx(r"(?:order|grand|invoice|po|lpo)\s*total", r"total\s*(?:amount|incl\.?|inclusive|value|payable|due|order)",
                 r"amount\s*(?:payable|due)", r"net\s*payable",
                 r"total(?!\s*(?:excl|exclusive|before|b\.?\s*tax|vat|tax|qty|quantity|items|lines|net|discount))"),
}
ANY_LABEL = [p for p in LABELS.values()]
INLINE_LPO = re.compile(r"(?:purchase\s+order|l\.?\s?p\.?\s?o\.?|p\.?\s?o\.?)\s*(?:number|no\.?|#)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9/\-]{3,24})", re.I)

KNOWN_BUYERS = ["naivas", "carrefour", "majid al futtaim", "quickmart", "quick mart", "chandarana", "magunas",
                "khetia", "tuskys", "cleanshelf", "eastmatt", "jazaribu", "mulleys", "uchumi", "game stores",
                "maathai", "kassmatt", "powerstar", "gilani", "budget supermarket", "mathai", "society stores",
                "choppies", "foodplus", "nakumatt", "tumaini", "woolmatt", "ukwala", "acacia"]

CURRENCIES = [(re.compile(r"\b(?:KES|KSHS?|KENYA[N]?\s+SHILLINGS?)\b", re.I), "KES"),
              (re.compile(r"\b(?:USD|US\s*DOLLARS?)\b", re.I), "USD"),
              (re.compile(r"\b(?:UGX|UGANDA[N]?\s+SHILLINGS?)\b", re.I), "UGX"),
              (re.compile(r"\b(?:TZS|TANZANIA[N]?\s+SHILLINGS?)\b", re.I), "TZS")]

# Item table columns: phrases a header may hold. The longest phrase that fits wins, so
# "Unit Price" is a price, not a unit, and "Item Description" isn't an item code.
COLUMNS: dict[str, list[str]] = {
    "line_no": ["no", "#", "line", "sn", "s no", "sr no", "line no", "s n"],
    "item_code": ["item code", "code", "item no", "item number", "article", "article no", "art no", "sku", "plu",
                  "product code", "supplier ref", "ref", "item", "material", "stock code", "item id", "prod code"],
    "barcode": ["barcode", "bar code", "ean", "gtin", "upc", "ean code"],
    "description": ["description", "item description", "descrition", "item descrition", "description of goods",
                    "product", "product name", "product description", "item name", "particulars", "details",
                    "article description", "goods", "item details", "product details"],
    "uom": ["uom", "unit", "units", "pack", "pack size", "uc", "unit of measure", "um", "u m", "packing", "pkg"],
    "quantity": ["qty", "quantity", "qty received", "received qty", "order qty", "qty ordered", "ordered qty",
                 "ordered", "cases", "qnty", "qty pcs", "quantity ordered", "order quantity", "qty rcvd"],
    "unit_price": ["unit price", "price", "unit cost", "cost", "p pri", "rate", "u price", "price per unit",
                   "cost price", "unit price excl", "price excl", "unit rate", "pri"],
    "amount": ["net amount", "amount", "total", "line total", "value", "net value", "b tax total", "total b tax",
               "total amount", "ext amount", "extended", "net", "gross amount", "total cost", "total value",
               "amount excl", "line amount", "net amt", "amt"],
    "ignore": ["vat", "tax", "tax amount", "vat amount", "vat %", "disc", "discount", "lv", "ty", "fam", "tax code",
               "vat rate", "b tax", "vat code", "tax %", "vat amt"],
}
LINE_FIELDS = ("item_code", "barcode", "description", "uom", "quantity", "unit_price", "amount")
NUMERIC = ("quantity", "unit_price", "amount")


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9#%]+", " ", text.lower()).strip() + " "


def classify_column(header: str) -> tuple[str | None, int]:
    """(column kind, how long the phrase that matched was); (None, 0) when nothing fits."""
    h = _words(header)
    best, length = None, 0
    for kind, phrases in COLUMNS.items():
        for phrase in phrases:
            if f" {phrase} " in h and len(phrase) > length:
                best, length = kind, len(phrase)
    return best, length


# Tokens ----------------------------------------------------------------------------------------


def tokens(doc, cells: list | None = None) -> list[Tok]:
    """Every line of text and every table cell, with its box (top-left origin), in reading order.
    Lines come from the page's text-line cells when the conversion kept them (convert.run_docling),
    otherwise from Docling's text items (which can merge a scan's lines into one paragraph)."""
    out: list[Tok] = []
    sizes = {n: (p.size.width, p.size.height) for n, p in doc.pages.items()}

    def add(text, prov_page, bbox, **kw):
        text = re.sub(r"\s+", " ", text or "").strip()  # keeps "*P0427*": barcode stars mark LPO numbers
        if not text or bbox is None:
            return
        pw, ph = sizes.get(prov_page, (1000.0, 1000.0))
        bb = bbox.to_top_left_origin(page_height=ph)
        out.append(Tok(text, prov_page, bb.l, bb.t, bb.r, bb.b, pw, ph, **kw))

    if cells:
        for page, text, l, t, r, b in cells:
            text = re.sub(r"\s+", " ", text).strip()
            pw, ph = sizes.get(page, (1000.0, 1000.0))
            if text:
                out.append(Tok(text, page, l, t, r, b, pw, ph, extra={"label": "cell"}))
    else:
        for item in doc.texts:
            if not item.prov:
                continue
            p = item.prov[0]
            add(item.text, p.page_no, p.bbox, extra={"label": str(getattr(item.label, "value", item.label))})
    for ti, table in enumerate(doc.tables):
        if not table.prov:
            continue
        page = table.prov[0].page_no
        for cell in table.data.table_cells:
            add(cell.text, page, cell.bbox, table=ti, row=cell.start_row_offset_idx, col=cell.start_col_offset_idx,
                extra={"header": bool(cell.column_header)})
    out.sort(key=lambda k: (k.page, round(k.t / 4), k.l))
    for i, tok in enumerate(out):
        tok.order = i
    return out


def _is_label(text: str) -> bool:
    return any(p.match(text) for p in ANY_LABEL)


def _right_and_below(tok: Tok, toks: list[Tok]) -> list[Tok]:
    """Tokens a label's value could be in: the next cell of its table row, then the same line to its
    right (nearest first), then just below it."""
    out: list[Tok] = []
    if tok.table is not None:
        out += sorted((o for o in toks if o.table == tok.table and o.row == tok.row and o.col is not None
                       and o.col > tok.col), key=lambda o: o.col)
    same_line = []
    below = []
    for o in toks:
        if o is tok or o.page != tok.page:
            continue
        overlap = min(o.b, tok.b) - max(o.t, tok.t)
        if overlap >= 0.45 * min(o.h, tok.h) and o.l >= tok.r - 0.5 * tok.h and o.l - tok.r <= tok.pw * 0.45:
            same_line.append(o)
        elif o.t >= tok.b - 0.3 * tok.h and o.t - tok.b <= 2.6 * tok.h and o.l < tok.r + tok.h and o.r > tok.l - tok.h:
            below.append(o)
    out += sorted(same_line, key=lambda o: o.l)
    out += sorted(below, key=lambda o: (o.t, abs(o.l - tok.l)))
    seen, unique = set(), []
    for o in out:
        if id(o) not in seen:
            seen.add(id(o))
            unique.append(o)
    return unique


# Values ---------------------------------------------------------------------------------------


def _accept(name: str, text: str):
    """The field's value in a piece of text, or None if it doesn't hold one."""
    # PaddleOCR (and RapidOCR, which runs its models) reads the label's colon into the value's
    # box: ": PO10001", ":20001234". Apple Vision leaves it with the label.
    text = re.sub(r"^[\s:;=#.]+", "", text or "")
    if not text:
        return None
    kind = {"order_date": "date", "delivery_date": "date", "subtotal": "number", "vat": "number", "total": "number"}.get(name)
    if kind == "date":
        return parse_date(text)
    if kind == "number":
        # "Total 184.00 Unit", "Total items: 12": a count, not money
        if re.search(r"\d\s*(?:" + UNITS + r"|items?|lines?|qty)\b|\b(?:items?|lines?|qty|quantity)\b", text, re.I):
            return None
        n = parse_number(text)
        if n is None:
            # "4,210.74 KES" or "KES 4,210.74"
            nums = [parse_number(w) for w in re.findall(r"[\d][\d,]*\.?\d*", text)]
            nums = [x for x in nums if x is not None]
            n = nums[-1] if len(nums) == 1 else None
        return n
    if name == "lpo_number":
        m = re.match(r"^\*?([A-Z0-9][A-Z0-9/\-]{3,24})\*?\b", text.strip(), re.I)
        if not m:
            return None
        code = clean_code(m.group(1))
        if code and sum(c.isdigit() for c in code) >= 3 and not parse_date(code) and not re.fullmatch(r"\d{1,3}(?:,\d{3})*\.\d\d", code):
            return code
        return None
    if name == "currency":
        for pattern, code in CURRENCIES:
            if pattern.search(text):
                return code
        return clean_text(text) if re.fullmatch(r"[A-Z]{3}", text.strip()) else None
    # names: some letters, not a date or an amount, not another label
    if _is_label(text) or parse_date(text) or parse_number(text) is not None or sum(c.isalpha() for c in text) < 2:
        return None
    return clean_text(text)


def find_field(name: str, toks: list[Tok], all_hits: bool = False):
    """(value, token it came from) for a header field, or (None, None). With all_hits, every value
    found, in reading order."""
    pattern = LABELS[name]
    hits = []
    for tok in toks:
        m = pattern.match(tok.text)
        if not m:
            continue
        rest = tok.text[m.end():].strip()
        value = _accept(name, rest) if rest else None
        source = tok
        if value is None and len(rest) <= 3:
            value, source = _value_near(name, tok, toks)
        if value is not None:
            if not all_hits:
                return value, source
            if not any(str(v).lower() == str(value).lower() for v, _ in hits):  # a text item and its table cell
                hits.append((value, source))
    return hits if all_hits else (None, None)


def _below(tok: Tok, toks: list[Tok]) -> Tok | None:
    """The token on the next line straight under this one ("22 September" / "2026")."""
    under = [o for o in toks if o.page == tok.page and o is not tok and 0 <= o.t - tok.b <= 1.2 * tok.h
             and o.l < tok.r and o.r > tok.l and o.table == tok.table]
    return min(under, key=lambda o: o.t) if under else None


NAME_FIELDS = ("buyer", "store", "supplier", "currency")
MONEY_FIELDS = ("subtotal", "vat", "total")


def _value_near(name: str, label: Tok, toks: list[Tok]):
    """A field's value in the tokens next to its label: (value, token) or (None, label). A name is
    only taken from the very next token: further along the line is another column
    ("SUPPLIER: 95012   VAT REGISTERED")."""
    near = _right_and_below(label, toks)
    if name in MONEY_FIELDS:
        # "Order total   4,884.46": on the same line. Below a "Total" is a column of line amounts.
        near = [o for o in near if (o.table is not None and o.table == label.table and o.row == label.row)
                or (o.l >= label.r - 0.5 * label.h and min(o.b, label.b) - max(o.t, label.t) > 0)]
    if name in NAME_FIELDS:
        right = [o for o in near if o.l >= label.r - 0.5 * label.h and min(o.b, label.b) - max(o.t, label.t) > 0]
        under = [o for o in near if o not in right]
        near = right[:1] + under[:1]
    for o in near[:4]:
        if _is_label(o.text) and LABELS.get(name, re.compile("x^")).match(o.text) is None and _accept(name, o.text) is None:
            continue  # another field's label sits where the value would be
        value = _accept(name, o.text)
        if value is None and name in ("order_date", "delivery_date") and (nxt := _below(o, toks)):
            value = _accept(name, f"{o.text} {nxt.text}")  # a date broken over two lines
        if value is not None:
            return value, o
    return None, label


def document_type(toks: list[Tok]) -> str:
    first = [t.text.lower() for t in toks if t.page == min((x.page for x in toks), default=1)][:25]
    head = " | ".join(first)
    rules = [("goods_received_note", r"goods\s+receiv|\bgrn\b|receiving\s+note|received\s+note"),
             ("credit_note", r"credit\s+note"), ("delivery_note", r"delivery\s+note(?!\s*/)"),
             ("invoice", r"tax\s+invoice|^invoice\b|\| invoice\b"),
             ("purchase_order", r"purchase\s+order|\blpo\b|l\.p\.o|local\s+purchase|\border\b")]
    for kind, rx in rules:
        if re.search(rx, head):
            return kind
    everything = " ".join(t.text.lower() for t in toks)
    return "purchase_order" if re.search(r"purchase\s+order|\blpo\b", everything) else "other"


def find_buyer(toks: list[Tok], supplier: str | None):
    value, source = find_field("buyer", toks)
    if value:
        return value, source
    page1 = [t for t in toks if t.page == min((x.page for x in toks), default=1)]
    known = [t for t in page1[:60] if any(b in t.text.lower() for b in KNOWN_BUYERS) and len(t.text) <= 60]
    # the printed company name ("NAIVAS LTD") over the logo read as text ("naivas")
    for tok in sorted(known, key=lambda t: not re.search(r"\b(ltd|limited|supermarkets?|stores|llc)\b", t.text, re.I)):
        return clean_text(tok.text), tok
    for tok in page1[:30]:
        if re.search(r"\b(ltd|limited|supermarkets?|stores)\b", tok.text, re.I) and len(tok.text) <= 60 \
                and not (supplier and supplier.lower() in tok.text.lower()) and not _is_label(tok.text):
            return clean_text(tok.text), tok
    return None, None


# Line items ------------------------------------------------------------------------------------


def _grid(doc, ti: int) -> list[list[str]]:
    table = doc.tables[ti]
    grid = [["" for _ in range(table.data.num_cols)] for _ in range(table.data.num_rows)]
    for cell in table.data.table_cells:
        for r in range(cell.start_row_offset_idx, cell.end_row_offset_idx):
            for c in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                if r < len(grid) and c < len(grid[r]):
                    grid[r][c] = (cell.text or "").strip()  # newlines kept: a blob cell is split on them
    return grid


def _header_rows(doc, ti: int) -> int:
    """How many rows at the top are headers (Docling's flags; the first row when it marked none)."""
    flagged = {c.start_row_offset_idx for c in doc.tables[ti].data.table_cells if c.column_header}
    n = 0
    while n in flagged:
        n += 1
    return n or 1


def map_columns(headers: list[str]) -> dict[int, str]:
    """{column index: kind} for an item table's header texts; each kind once, the best fit wins."""
    scored = [(classify_column(h), i) for i, h in enumerate(headers)]
    mapping: dict[int, str] = {}
    taken: dict[str, tuple[int, int]] = {}
    for (kind, length), i in scored:
        if not kind or kind == "ignore":
            continue
        if kind in taken:
            prev_len, prev_i = taken[kind]
            # same fit: the leftmost wins, except amounts (the line total is the rightmost)
            if length < prev_len or (length == prev_len and kind != "amount"):
                continue
            mapping.pop(prev_i, None)
        taken[kind] = (length, i)
        mapping[i] = kind
    return mapping


def is_item_table(mapping: dict[int, str]) -> bool:
    kinds = set(mapping.values())
    return "description" in kinds and bool(kinds & {"quantity", "amount", "unit_price"}) or \
        len(kinds & {"item_code", "barcode", "quantity", "unit_price", "amount"}) >= 3


UNITS = r"(?:PCS|PC|PIECES?|CTNS?|CARTONS?|KGS?|BOX(?:ES)?|PKTS?|PACKETS?|EA|EACH|DOZ(?:EN)?|BAGS?|BALES?|CS|CASES?|LTRS?|BTLS?|TINS?|OUTERS?|UNITS?|PACKS?|TRAYS?|BUNDLES?|ROLLS?|SETS?)"
QTY_WITH_UNIT = re.compile(r"^\s*([\d][\d,]*(?:\.\d+)?)\s*(" + UNITS + r")\.?\s*$", re.I)


def number_and_unit(text: str) -> tuple[float | None, str | None]:
    """'1,200.00 PCS' -> (1200.0, 'PCS'); '36' -> (36.0, None)."""
    n = parse_number(text)
    if n is not None:
        return n, None
    m = QTY_WITH_UNIT.match(text or "")
    return (parse_number(m.group(1)), m.group(2).upper()) if m else (None, None)


def _row_to_line(cells: list[str], mapping: dict[int, str]) -> dict | None:
    line: dict = {}
    for i, kind in mapping.items():
        if i >= len(cells) or kind in ("line_no",):
            continue
        text = cells[i]
        if kind in NUMERIC:
            value, unit = number_and_unit(text)
            line[kind] = value
            if unit and kind == "quantity":
                line.setdefault("_unit", unit)
        elif text:
            line[kind] = text
    if line.get("_unit"):
        line["uom"] = line["_unit"]  # "1.00 DOZ": ordered in dozens, whatever the packing column says
    desc = line.get("description") or ""
    has_number = any(line.get(k) is not None for k in NUMERIC)
    if not has_number:
        return None
    if not (sum(c.isalpha() for c in desc) >= 2 or line.get("item_code") or line.get("barcode")):
        return None
    if re.match(r"^\W*(sub\s*total|total|vat|tax|grand|amount|net)\b", desc, re.I) or \
            any(LABELS[k].match(c or "") for c in cells for k in ("subtotal", "total")):
        return None  # a totals row ("Order total", "Sub total")
    return {k: line.get(k) for k in LINE_FIELDS}


def infer_columns(grid: list[list[str]]) -> dict[int, str]:
    """{column: kind} for a table without a header Docling recognised, from what the cells hold:
    long text is the description, a number with a unit ("12.00 PCS") the quantity, a short code
    column (digits or letters and digits) the item code, 8-14 digit numbers the barcode, money
    columns price and amount (the last one: amount)."""
    rows = [r for r in grid if any(c.strip() for c in r)]
    if len(rows) < 2 or len(rows[0]) < 3:
        return {}

    def share(col, test):
        vals = [r[col].strip() for r in rows if col < len(r) and r[col].strip()]
        return sum(1 for v in vals if test(v)) / len(rows) if vals else 0

    mapping: dict[int, str] = {}
    cols = range(len(rows[0]))
    text_col = max(cols, key=lambda c: share(c, lambda v: sum(ch.isalpha() for ch in v) >= 8))
    if share(text_col, lambda v: sum(ch.isalpha() for ch in v) >= 8) < 0.6:
        return {}
    mapping[text_col] = "description"
    # number-with-unit columns: the packing ("1 PCS", "1 CTN * 24 PCS") comes before the quantity
    with_unit = [c for c in cols if c != text_col and share(c, lambda v: QTY_WITH_UNIT.match(v) is not None) >= 0.6]
    if with_unit:
        mapping[with_unit[-1]] = "quantity"
    money = []
    for c in cols:
        if c in mapping:
            continue
        if share(c, lambda v: re.fullmatch(r"\d{8,14}", v) is not None) >= 0.6:
            mapping[c] = "barcode"
        elif c in with_unit:
            if "uom" not in mapping.values():
                mapping[c] = "uom"
        elif share(c, lambda v: parse_number(v) is not None and ("." in v or "," in v)) >= 0.6:
            money.append(c)
        elif c < text_col and share(c, lambda v: re.fullmatch(r"[A-Z0-9][A-Z0-9/\-]{2,16}", v, re.I) is not None) >= 0.6 \
                and "item_code" not in mapping.values():
            mapping[c] = "item_code"
        elif share(c, lambda v: re.fullmatch(r"\d+(?:\.\d+)?\s*" + UNITS + r"(?:\s*\*\s*\d+\s*" + UNITS + r")?", v, re.I) is not None) >= 0.6:
            mapping.setdefault(c, "uom") if "uom" not in mapping.values() else None
    if "quantity" not in mapping.values() and money:
        mapping[money.pop(0)] = "quantity"
    if money:
        mapping[money.pop()] = "amount"
    if money:
        mapping[money.pop()] = "unit_price"
    return mapping if {"description"} < set(mapping.values()) and set(mapping.values()) & {"quantity", "amount"} else {}


def lines_from_tables(doc) -> tuple[list[dict], list[dict]]:
    """(lines, where each came from) from the item tables and the tables that continue them."""
    lines, sources = [], []
    main: tuple[int, dict[int, str], int] | None = None  # (table, mapping, columns)
    for ti, table in enumerate(doc.tables):
        grid = _grid(doc, ti)
        if not grid:
            continue
        n_head = _header_rows(doc, ti)
        headers = [" ".join(grid[r][c] for r in range(min(n_head, len(grid)))) for c in range(len(grid[0]))]
        mapping = map_columns(headers)
        page = table.prov[0].page_no if table.prov else None
        if is_item_table(mapping):
            main = (ti, mapping, len(grid[0]))
            body = grid[n_head:]
        elif main is not None and len(grid[0]) == main[2]:
            mapping, body = main[1], grid  # a continuation: same columns, no (or a garbled) header
        elif main is not None and len(grid[0]) == main[2] - 1 and main[1].get(0) == "line_no":
            # continuation whose first two columns ran together ("11 N000612")
            mapping = {i - 1: k for i, k in main[1].items() if i > 0}
            body = []
            for row in grid:
                first = row[0].split(None, 1)
                body.append([first[1] if len(first) == 2 and first[0].isdigit() else row[0], *row[1:]])
        elif main is None and (mapping := infer_columns(grid)):
            # no header Docling recognised (it was in the text above): columns from their contents
            main = (ti, mapping, len(grid[0]))
            body = grid
        else:
            continue
        for r, row in enumerate(body):
            line = _row_to_line(row, mapping)
            if line:
                lines.append(line)
                sources.append({"page": page, "table": ti, "row": r})
    return lines, sources


def _text_lines(toks: list[Tok]) -> list[tuple[str, Tok]]:
    """Text items (not table cells) grouped into lines across the page, left to right."""
    rows: list[list[Tok]] = []
    for tok in sorted((t for t in toks if t.table is None), key=lambda t: (t.page, t.t)):
        cy = (tok.t + tok.b) / 2
        for row in rows:
            ref = row[0]
            if ref.page == tok.page and abs((ref.t + ref.b) / 2 - cy) <= 0.5 * min(ref.h, tok.h):
                row.append(tok)
                break
        else:
            rows.append([tok])
    return [(" ".join(t.text for t in sorted(row, key=lambda t: t.l)), row[0]) for row in rows]


OCR_JUNK = "|Il![]{}:;,'\"`"


def ocr_word(word: str) -> str:
    """A word from OCR without the table rules and stray marks around it ("36|", "380.28Ûîę")."""
    return re.sub(r"[^\x20-\x7e]", "", word).strip(OCR_JUNK)


def number_readings(word: str) -> list[tuple[float, int]]:
    """What an OCR'd number could be, as (value, how much was assumed): table rules read as a
    trailing 1 ("270.7761" for "270.776|", "61" for "6|") and decimal points read as dashes
    ("200-000"). The arithmetic decides which reading was right."""
    w = ocr_word(word)
    if not w or not any(c.isdigit() for c in w):
        return []
    out: dict[float, int] = {}
    for text, cost in ((w, 0), (re.sub(r"(?<=\d)-(?=\d{3}\b)", ".", w), 1), (w[:-1] if len(w) > 1 and w[-1] in "1Il" else "", 1)):
        n = parse_number(text) if text else None
        if n is not None and (n not in out or cost < out[n]):
            out[n] = cost
    return list(out.items())


def _barcode(word: str) -> str | None:
    m = re.fullmatch(r"\D?(\d{8,14})\D?", ocr_word(word))
    return m.group(1) if m else None


def line_from_text(text: str) -> dict | None:
    """A line item from free text: three numbers with quantity x price = amount (with or without
    VAT), a description, and a barcode or code when there is one. With only a price and an amount
    whose ratio is a whole number, and a barcode or code to show it's an item line, the quantity
    is that ratio."""
    words = text.split()
    if len(words) > 40:
        return None  # a paragraph, not an item line
    barcode_at = {i for i, w in enumerate(words) if _barcode(w)}
    nums = [(i, n, c) for i, w in enumerate(words) if i not in barcode_at for n, c in number_readings(w)]
    best, best_key = None, None
    for (i, q, cq), (j, p, cp), (k, a, ca) in combinations(nums, 3):
        if not i < j < k or q <= 0 or p <= 0 or a <= 0 or q > 100000:
            continue
        if close(q * p, a) or close(q * p * (1 + VAT_RATE), a):
            # exact arithmetic first (6 x 270.776 = 1624.656, not 6 x 270.7761), then fewest
            # assumptions, then the rightmost
            exact = min(abs(q * p - a), abs(q * p * (1 + VAT_RATE) - a)) <= 0.0002
            key = (not exact, cq + cp + ca, -k)
            if best_key is None or key < best_key:
                best, best_key = (i, q, p, k, a), key
    inferred = False
    if not best and barcode_at:
        for (j, p, cp), (k, a, ca) in combinations(nums, 2):
            if j < k and 0 < p < a and abs(a / p - round(a / p)) < 0.002 and round(a / p) <= 100000:
                best, inferred = (j, float(round(a / p)), p, k, a), True
        if not best:
            return None
    if not best:
        return None
    i, q, p, k, a = best
    barcode = next((_barcode(words[n]) for n in sorted(barcode_at)), None)
    start = 0
    code = None
    for n, w in enumerate(words[:i]):
        cw = ocr_word(w)
        if n in barcode_at or not cw:
            continue
        if sum(c.isalpha() for c in cw) >= 2 and not re.fullmatch(r"(?=.*\d)[A-Z]{1,4}\d{4,}", cw):
            start = n
            break
        if code is None and re.fullmatch(r"(?=.*\d)[A-Za-z0-9/\-]{4,16}", cw) and len(cw) >= 5:
            code = cw
    else:
        return None
    desc_words = [ocr_word(w) for w in words[start:i]]
    description = clean_text(" ".join(w for w in desc_words if w))
    if not description or sum(c.isalpha() for c in description) < 3:
        return None
    uom = next((ocr_word(w) for w in words[i + 1:k] if re.fullmatch(r"(?:PCS|PC|CTN|CTNS|KG|BOX|PKT|EA|EACH|DOZ|BAG|BALE|CS)", ocr_word(w), re.I)), None)
    line = {"item_code": code, "barcode": barcode, "description": description, "uom": uom,
            "quantity": q, "unit_price": p, "amount": a}
    if inferred:
        line["_inferred"] = "quantity"
    return line


def lines_from_text(doc, toks: list[Tok]) -> tuple[list[dict], list[dict]]:
    out, sources = [], []
    candidates = _text_lines(toks)
    for ti in range(len(doc.tables)):
        grid = _grid(doc, ti)
        page = doc.tables[ti].prov[0].page_no if doc.tables[ti].prov else None
        # cells holding several lines (a scan read as one blob) are split back into lines
        for row in grid:
            parts = [c.split("\n") for c in row]
            candidates += [(" ".join(row), Tok("", page or 1, 0, 0, 0, 0, 1, 1))]
            if any(len(p) > 1 for p in parts):
                candidates += [(p, Tok("", page or 1, 0, 0, 0, 0, 1, 1)) for c in row for p in c.split("\n")]
    seen = set()
    for text, tok in candidates:
        line = line_from_text(text)
        if line:
            key = (line["description"], line["quantity"], line["amount"])
            if key not in seen:
                seen.add(key)
                out.append(line)
                sources.append({"page": tok.page})
    return out, sources


# The whole record ------------------------------------------------------------------------------


def pick_total(hits: list, amounts: list[float], subtotal: float | None, vat: float | None):
    """The order total among the values next to "Total" labels: the one the lines add up to (with
    or without VAT), or subtotal + VAT does; else the last one at least as big as the biggest line
    (a "Total" can also be the number of items or of units); else the last one."""
    targets = []
    if amounts:
        targets += [sum(amounts), sum(amounts) * (1 + VAT_RATE)]
    if subtotal is not None and vat is not None:
        targets.append(subtotal + vat)
    for value, source in reversed(hits):
        if any(close(value, t, rel=0.002, floor=1.0) for t in targets):
            return value, source
    biggest = max(amounts, default=0)
    for value, source in reversed(hits):
        if value >= biggest:
            return value, source
    return hits[-1]


def extract(doc, cells: list | None = None) -> dict:
    """An LPO record (schema.normalise shape) and where each value came from."""
    toks = tokens(doc, cells)
    record = empty_record()
    where: dict = {}
    f = record["fields"]

    f["document_type"] = document_type(toks)
    for name in ("lpo_number", "order_date", "delivery_date", "store", "supplier", "currency", "subtotal", "vat"):
        value, source = find_field(name, toks)
        if value is not None:
            f[name] = value
            where[name] = source.box()
    totals = find_field("total", toks, all_hits=True)  # chosen once the lines are read (below)
    if f["lpo_number"] is None:
        # mid-line: "Backoffice PURCHASE ORDER # 012-00012345" (but never "P.O. Box 1234")
        for tok in toks:
            m = INLINE_LPO.search(tok.text)
            if m and (value := _accept("lpo_number", m.group(1))):
                f["lpo_number"], where["lpo_number"] = value, tok.box()
                break
    if f["lpo_number"] is None:
        # a barcode's caption: *P000012345*
        for tok in toks:
            m = re.fullmatch(r"\*([A-Z0-9][A-Z0-9/\-]{4,24})\*", tok.text.strip(), re.I)
            if m:
                f["lpo_number"] = clean_code(m.group(1))
                where["lpo_number"] = tok.box()
                break
    if f["lpo_number"] is None:
        # the number printed under or beside the title ("Purchase order" / "P000067890")
        for tok in toks[:40]:
            if re.fullmatch(r"\W*(local\s+)?purchase\s+order\W*|\W*l\.?\s?p\.?\s?o\.?\W*", tok.text, re.I):
                value, source = _value_near("lpo_number", tok, toks)
                if value:
                    f["lpo_number"], where["lpo_number"] = value, source.box()
                    break
    if f["currency"] is None:
        for tok in toks:
            code = next((c for p, c in CURRENCIES if p.search(tok.text)), None)
            if code:
                f["currency"], where["currency"] = code, tok.box()
                break
    # GRNs: "Company Name" under the store's details, then again under the supplier's
    companies = find_field("buyer", toks, all_hits=True)
    if f["supplier"] is None and len(companies) >= 2:
        f["supplier"], source = companies[1]
        where["supplier"] = source.box()
    buyer, source = find_buyer(toks, f["supplier"])
    if buyer:
        f["buyer"], where["buyer"] = buyer, source.box()

    lines, line_sources = lines_from_tables(doc)
    how = "tables"
    if not lines:
        lines, line_sources = lines_from_text(doc, toks)
        how = "text" if lines else "none"
    record["lines"] = lines
    amounts = [x["amount"] for x in lines if x.get("amount") is not None]
    quantities = [x["quantity"] for x in lines if x.get("quantity") is not None]
    if totals:
        value, source = pick_total(totals, amounts, f["subtotal"], f["vat"])
        # an order without prices: its "Total" counts units, it isn't money
        if not (not amounts and quantities and close(value, sum(quantities), rel=0.001, floor=0.01)):
            f["total"], where["total"] = value, source.box()
    # no labelled total (dot-matrix POs print it bare under the amount column): a number on the
    # page equal to the sum of the lines is the total, and a sign the lines are complete
    if f["total"] is None and f["subtotal"] is None and len(amounts) >= 2:
        s = sum(amounts)
        for tok in reversed(toks):
            if any(close(n, s, rel=0.0005, floor=0.02) for w in tok.text.split() for n, _ in number_readings(w)):
                f["total"], where["total"] = s, tok.box()
                break
    out = normalise(record)
    return {"record": out, "where": where, "line_sources": line_sources, "lines_from": how,
            "tokens": len(toks), "tables": len(doc.tables), "mapper": MAPPER_VERSION}


def from_vlm(data: dict) -> dict:
    """A record from the VLM extractor's answer (DocumentExtractor fills a template shaped like ours)."""
    data = data or {}
    record = {"fields": {k: data.get(k) for k in data if k != "lines"}, "lines": data.get("lines") or []}
    dt = str(record["fields"].get("document_type") or "").lower().replace(" ", "_")
    record["fields"]["document_type"] = dt if dt in DOCUMENT_TYPES else None
    return {"record": normalise(record), "where": {}, "line_sources": [], "lines_from": "vlm", "mapper": MAPPER_VERSION}
