"""The LPO lab: parsing, the mapper, the checks, scoring, and the API end to end.

Everything here is made up: a synthetic LPO built as a DoclingDocument, never a real one (real LPOs
stay in ~/.docling-studio/lpo/, outside the repo). Experiments run the real worker process, on
conversions seeded into the cache, so no Docling models are needed.
"""

import time

import pytest
from docling_core.types.doc import (BoundingBox, CoordOrigin, DocItemLabel, DoclingDocument, ProvenanceItem, Size,
                                    TableCell, TableData)

from docling_studio.lpo import checks, convert, extract, schema, store, testset

# Synthetic -------------------------------------------------------------------------------------

HEADER = [  # text, left, top, right
    ("ACME SUPERMARKETS LTD", 40, 40, 200),
    ("Purchase order", 400, 40, 520),
    ("*PO0012345*", 400, 60, 520),
    ("P.O. Date:", 380, 90, 430),
    ("3 March,", 440, 90, 490),
    ("2026", 440, 102, 470),
    ("Delivery Date:", 365, 120, 430),
    ("5 March, 2026", 440, 120, 520),
    ("Supplier:", 40, 150, 90),
    ("SAMPLE DRINKS LIMITED", 40, 162, 180),
    ("Ship To:", 300, 150, 340),
    ("TOWN CENTRE", 350, 150, 420),
    ("Sub total", 380, 400, 430),
    ("1,250.00", 480, 400, 530),
    ("VAT", 380, 415, 410),
    ("200.00", 480, 415, 530),
    ("Order total", 380, 430, 440),
    ("1,450.00", 480, 430, 530),
]
TABLE = [
    ["Item Code", "Item Description", "Unit", "Quantity", "Unit Price", "Net Amount"],
    ["A100", "SAMPLE JUICE 1L", "PCS", "10.00", "50.00", "500.00"],
    ["A200", "SAMPLE WATER 500ML", "PCS", "30.00", "25.00", "750.00"],
    ["", "Order total", "", "", "", "1,450.00"],
]


def _box(l, t, r, b):
    return BoundingBox(l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT)


def synthetic_lpo() -> DoclingDocument:
    doc = DoclingDocument(name="synthetic")
    doc.add_page(page_no=1, size=Size(width=600, height=800))
    for text, l, t, r in HEADER:
        doc.add_text(label=DocItemLabel.TEXT, text=text,
                     prov=ProvenanceItem(page_no=1, bbox=_box(l, t, r, t + 10), charspan=(0, len(text))))
    cells = []
    for ri, row in enumerate(TABLE):
        for ci, text in enumerate(row):
            l = 40 + ci * 90
            cells.append(TableCell(text=text, bbox=_box(l, 200 + ri * 20, l + 80, 210 + ri * 20), row_span=1, col_span=1,
                                   start_row_offset_idx=ri, end_row_offset_idx=ri + 1, start_col_offset_idx=ci,
                                   end_col_offset_idx=ci + 1, column_header=ri == 0))
    doc.add_table(data=TableData(num_rows=len(TABLE), num_cols=len(TABLE[0]), table_cells=cells),
                  prov=ProvenanceItem(page_no=1, bbox=_box(40, 200, 580, 280), charspan=(0, 0)))
    return doc


TRUTH = {
    "fields": {"document_type": "purchase_order", "lpo_number": "PO0012345", "order_date": "2026-03-03",
               "delivery_date": "2026-03-05", "buyer": "Acme Supermarkets Ltd", "store": "Town Centre",
               "supplier": "Sample Drinks Limited", "subtotal": 1250, "vat": 200, "total": 1450},
    "lines": [{"item_code": "A100", "description": "SAMPLE JUICE 1L", "uom": "PCS", "quantity": 10, "unit_price": 50, "amount": 500},
              {"item_code": "A200", "description": "SAMPLE WATER 500ML", "uom": "PCS", "quantity": 30, "unit_price": 25, "amount": 750}],
}

# Parsing ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, value", [
    ("3,730.41", 3730.41), ("1 234.50", 1234.5), ("(12.00)", -12.0), ("KES 4,210.74", 4210.74),
    ("16.00Y", None), ("12 34", None), ("abc", None), ("", None), (31.086729, 31.086729),
])
def test_parse_number(text, value):
    assert schema.parse_number(text) == value


@pytest.mark.parametrize("text, value", [
    ("13 July, 2026", "2026-07-13"), ("24/04/25", "2025-04-24"), ("2026-07-13", "2026-07-13"),
    ("23 Sep 2025", "2025-09-23"), ("July 13, 2026", "2026-07-13"), ("05/13/2026", "2026-05-13"),
    ("no date here", None), ("31/02/2026", None),
])
def test_parse_date(text, value):
    assert schema.parse_date(text) == value


def test_columns_take_the_most_specific_name():
    assert extract.map_columns(["No", "Item Code", "Item Description", "UOM", "Qty Received", "Unit Price", "Net Amount"]) == {
        0: "line_no", 1: "item_code", 2: "description", 3: "uom", 4: "quantity", 5: "unit_price", 6: "amount"}
    assert extract.map_columns(["BAR CODE", "ITEM DESCRITION", "QTY", "P.PRI", "B. TAX TOTAL", "VAT"]) == {
        0: "barcode", 1: "description", 2: "quantity", 3: "unit_price", 4: "amount"}


def test_ocr_line_is_read_by_its_arithmetic():
    # a dot-matrix row as OCR reads it: rules as "|" and "1", accents from the ribbon
    line = extract.line_from_text("6000000000017 ABC10001 101 SAMPLE CORDIAL 2L 61 270.7761 1624.656Ś 00 KG 16.00|")
    assert line["barcode"] == "6000000000017" and line["item_code"] == "ABC10001"
    assert line["description"] == "SAMPLE CORDIAL 2L"
    assert (line["quantity"], line["unit_price"], line["amount"]) == (6.0, 270.776, 1624.656)
    # a lost quantity comes back from price and amount when it's clearly an item line
    line = extract.line_from_text("6000000000024 ABC10002 101 SAMPLE WATER 10L 200-000| 1200.000 00 KG")
    assert (line["quantity"], line["unit_price"], line["amount"]) == (6.0, 200.0, 1200.0)
    assert extract.line_from_text("TEL 0800 221 322 FAX") is None


# The mapper and checks ---------------------------------------------------------------------------


def test_mapper_reads_a_synthetic_lpo():
    out = extract.extract(synthetic_lpo())
    record = out["record"]
    assert record["fields"] == {**schema.empty_record()["fields"], **schema.normalise(TRUTH)["fields"],
                                "buyer": "ACME SUPERMARKETS LTD", "store": "TOWN CENTRE", "supplier": "SAMPLE DRINKS LIMITED"}
    assert [x["description"] for x in record["lines"]] == ["SAMPLE JUICE 1L", "SAMPLE WATER 500ML"]  # not the total row
    assert out["where"]["lpo_number"]["page"] == 1
    assert checks.run(record)["ok"]
    assert schema.compare(record, TRUTH)["perfect"]


@pytest.mark.parametrize("text, number", [
    ("PURCHASE ORDER # 1234567", "1234567"), ("Backoffice PURCHASE ORDER # 012-00012345", "012-00012345"),
    ("LPO No. P0012345", "P0012345"), ("P.O. Box 12345-00100 Nairobi", None),
])
def test_lpo_number_labels(text, number):
    doc = DoclingDocument(name="t")
    doc.add_page(page_no=1, size=Size(width=600, height=800))
    doc.add_text(label=DocItemLabel.TEXT, text=text, prov=ProvenanceItem(page_no=1, bbox=_box(40, 40, 400, 50), charspan=(0, len(text))))
    assert extract.extract(doc)["record"]["fields"]["lpo_number"] == number


def test_headerless_quantity_only_table():
    # a price-less order whose header Docling missed: packing before quantity, both with units
    grid = [["100001", "SAMPLE MILK 500ML", "1 PCS", "1,200.00 PCS"],
            ["100002", "SAMPLE YOGHURT 150ML", "1 CTN * 24 PCS", "12.00 CTN"],
            ["100003", "SAMPLE BUTTER 250G", "1PCS", "108.00 PCS"]]
    mapping = extract.infer_columns(grid)
    assert mapping == {0: "item_code", 1: "description", 2: "uom", 3: "quantity"}
    line = extract._row_to_line(grid[1], mapping)
    assert (line["quantity"], line["uom"]) == (12.0, "CTN")


def test_a_count_is_not_a_total():
    assert extract._accept("total", "184.00 Unit") is None
    assert extract._accept("total", "Items: 12") is None
    assert extract._accept("total", "KES 4,210.74") == 4210.74


def test_label_colon_read_into_the_value():
    # PaddleOCR boxes the separator with the value
    assert extract._accept("lpo_number", ": PO10001") == "PO10001"
    assert extract._accept("lpo_number", ":20001234") == "20001234"
    assert extract._accept("total", ": 4,210.74") == 4210.74
    assert extract._accept("supplier", ": SAMPLE FOODS LTD") == "SAMPLE FOODS LTD"


def test_total_is_the_one_the_lines_add_up_to():
    hits = [(1250.0, "a"), (18.0, "b")]  # the money total, then "Total items: 18"
    assert extract.pick_total(hits, [500.0, 750.0], None, None)[0] == 1250.0
    assert extract.pick_total([(30.0, "x"), (1450.0, "y")], [500.0, 750.0], 1250.0, 200.0)[0] == 1450.0


def test_mapper_uses_line_cells_when_it_has_them():
    doc = synthetic_lpo()
    cells = [[1, text, l, t, r, t + 10] for text, l, t, r in HEADER]
    assert extract.extract(doc, cells)["record"]["fields"]["lpo_number"] == "PO0012345"


def test_checks_catch_numbers_that_dont_add_up():
    record = schema.normalise(TRUTH)
    record["lines"][0]["amount"] = 400.0
    result = checks.run(record)
    assert not result["lines_add_up"] and not result["lines_sum_to_total"] and result["totals_add_up"]
    assert not result["ok"]
    # VAT-inclusive line amounts are fine
    assert checks.line_ok({"quantity": 2, "unit_price": 100, "amount": 232})


def test_compare_scores_fields_and_lines():
    pred = schema.normalise(TRUTH)
    pred["fields"]["store"] = "Somewhere Else"
    pred["lines"][1]["quantity"] = 3
    result = schema.compare(pred, TRUTH)
    assert result["fields"]["store"] is False and result["fields"]["lpo_number"] is True
    assert result["lines"]["matched"] == 2 and result["lines"]["numbers_right"] == 5
    assert not result["perfect"]
    assert schema.same("text", "NAIVAS LTD", "Naivas Ltd.")


def test_allocation_favours_no_client_too_much():
    share = testset.allocate({"BIG": 120000, "MID": 15000, "SMALL": 40}, 300)
    assert sum(share.values()) == 300
    assert share["BIG"] > share["MID"] > share["SMALL"] >= 1
    assert share["BIG"] < 300 * 120000 / 135040  # less than in proportion
    assert testset.allocate({"A": 3, "B": 2}, 10) == {"A": 3, "B": 2}


def test_sample_skips_derived_files_copies_and_test_folders():
    rows = ["A/x1.pdf\t100\t2026-01-01", "A/x2.pdf\t100\t2026-01-02", "A/x3.pdf\t200\t2026-01-03",
            "A/preprocessed_1_tmp_processed.png\t50\t2026-01-01", "TEST/t.pdf\t300\t2026-01-01", "B/y.jpg\t400\t2026-01-01"]
    store.path("listing.tsv").write_text("\n".join(rows) + "\n")
    assert {c["name"]: c["on"] for c in testset.clients()} == {"A": True, "TEST": False, "B": True}
    keys = sorted(k for k, *_ in testset.sample(10))
    assert keys in (["A/x1.pdf", "A/x3.pdf", "B/y.jpg"], ["A/x2.pdf", "A/x3.pdf", "B/y.jpg"])


# The API ---------------------------------------------------------------------------------------


def seed_document(did: str = "abc123def456") -> dict:
    """A test-set entry whose conversion is already cached (default settings)."""
    doc = {"id": did, "key": f"ACME/{did}.pdf", "client": "ACME", "size": 1, "modified": "2026-01-01", "file": f"{did}.pdf",
           "pages": 1, "text_chars": 500, "kind": "digital", "excluded": False}
    store.path("files").mkdir(parents=True, exist_ok=True)
    store.path("files", doc["file"]).write_bytes(b"%PDF-1.4 synthetic")
    ts = testset.load()
    ts["docs"][did] = doc
    testset.save(ts)
    conv = convert.conversion_key(convert.check_config({}))
    path = convert.cache_path(conv, did)
    path.parent.mkdir(parents=True, exist_ok=True)
    synthetic_lpo().save_as_json(path)
    store.write_json(convert.cache_path(conv, did, "cells"), [])
    return doc


def wait_experiment(client, eid, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exp = client.get(f"/api/lpo/experiments/{eid}").json()
        if exp["status"] not in ("queued", "running"):
            return exp
        time.sleep(0.2)
    raise TimeoutError(eid)


def test_overview(client):
    data = client.get("/api/lpo/overview").json()
    assert data["testset"]["documents"] == 0
    assert data["options"]["defaults"]["extractor"] == "rules"
    assert {f["name"] for f in data["schema"]["fields"]} >= {"lpo_number", "total"}


def test_experiment_runs_scores_and_takes_labels(client):
    doc = seed_document()
    assert client.post("/api/lpo/experiments", json={"config": {"ocr": "sometimes"}}).status_code == 400
    assert client.post("/api/lpo/experiments", json={"subset": "scans"}).status_code == 400  # no scans in the set
    resp = client.post("/api/lpo/experiments", json={"name": "baseline", "subset": "all"})
    assert resp.status_code == 201, resp.text
    exp = wait_experiment(client, resp.json()["id"])
    assert exp["status"] == "finished", client.get(f"/api/lpo/experiments/{exp['id']}/log").json()["text"]
    assert exp["summary"]["ok_rate"] == 1.0 and exp["summary"]["labelled"] == 0
    result = client.get(f"/api/lpo/experiments/{exp['id']}/docs/{doc['id']}").json()
    assert result["record"]["fields"]["lpo_number"] == "PO0012345" and result["cached"]

    saved = client.put(f"/api/lpo/docs/{doc['id']}/label", json=TRUTH).json()
    assert saved["checks"]["ok"]
    exp = client.get(f"/api/lpo/experiments/{exp['id']}").json()
    assert exp["summary"]["labelled"] == 1 and exp["summary"]["perfect_rate"] == 1.0
    assert client.get(f"/api/lpo/experiments/{exp['id']}/docs/{doc['id']}").json()["comparison"]["perfect"]

    remapped = client.post(f"/api/lpo/experiments/{exp['id']}/remap").json()
    assert remapped["remapped"] == 1
    rows = client.get(f"/api/lpo/docs?exp={exp['id']}").json()
    assert rows[0]["labelled"] and rows[0]["result"]["ok"]
    assert client.get(f"/api/lpo/experiments/{exp['id']}/export").text.count("\n") == 1

    # a document that turns out not to be an LPO stops counting
    client.put(f"/api/lpo/docs/{doc['id']}/label", json={"not_lpo": True})
    assert client.get(f"/api/lpo/experiments/{exp['id']}").json()["summary"]["documents"] == 0


def test_ids_from_urls_are_checked(client):
    assert client.get("/api/lpo/docs/..%2F..%2Fsettings").status_code in (400, 404)
    assert client.get("/api/lpo/experiments/nope!").status_code in (400, 404)
    assert client.get("/api/lpo/docs?exp=../x").status_code == 400
