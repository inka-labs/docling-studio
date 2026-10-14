"""The everyday converter: jobs, the Word and Excel files, and what the plan allows."""

import json
import time

import pytest
from docx import Document
from openpyxl import load_workbook

from conftest_document import sample_document
from docling_studio import entitlements, exporters, simple


def wait(client, rid, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{rid}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture
def save_to(client, tmp_path):
    folder = tmp_path / "Converted"
    client.put("/api/settings", json={"save_to": str(folder)})
    return folder


@pytest.fixture
def doc_json(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(sample_document()))
    return path


# Word and Excel ---------------------------------------------------------------------------------


def test_word_has_the_body_in_reading_order(doc_json, tmp_path):
    counts = exporters.to_word(doc_json, tmp_path / "report.docx")
    assert counts == {"headings": 1, "paragraphs": 3, "tables": 1, "pictures": 1}
    word = Document(tmp_path / "report.docx")
    texts = [p.text for p in word.paragraphs if p.text]
    assert texts == ["Annual report", "Revenue grew in every region.", "North", "(2) South", "A bar chart of revenue.", "Figure 1: Growth"]
    assert word.paragraphs[0].style.name == "Heading 1"
    assert "Page 1 of 9" not in texts and "words inside the chart" not in texts  # furniture, text inside a picture
    table = word.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["Region", "Revenue", "Revenue"]  # merged across two columns
    assert table.rows[0].cells[0].paragraphs[0].runs[0].bold
    assert len(word.inline_shapes) == 1


def test_excel_has_a_sheet_per_table_with_numbers(doc_json, tmp_path):
    assert exporters.to_excel(doc_json, tmp_path / "report.xlsx") == {"tables": 1}
    sheet = load_workbook(tmp_path / "report.xlsx")["Table 1 (p2)"]
    assert [c.value for c in sheet[2]] == ["North", 1234, 5.5]
    assert "B1:C1" in {str(r) for r in sheet.merged_cells.ranges}
    assert sheet["A1"].font.bold and sheet.freeze_panes == "A2"


def test_csv_has_a_file_per_table(doc_json, tmp_path):
    doc = sample_document()
    doc["tables"].append({**doc["tables"][0], "self_ref": "#/tables/1"})
    doc_json.write_text(json.dumps(doc))
    written = exporters.to_csv(doc_json, lambda n, total: tmp_path / f"t{n}of{total}.csv")
    assert [p.name for p in written] == ["t1of2.csv", "t2of2.csv"]
    raw = written[0].read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # a BOM, so Excel reads it as UTF-8
    # the merged header fills both columns it spans; numbers stay as written
    assert raw.decode("utf-8-sig").splitlines() == ["Region,Revenue,Revenue", 'North,"1,234",5.5']


def test_excel_without_tables_says_so(doc_json, tmp_path):
    doc = sample_document()
    doc["tables"] = []
    doc_json.write_text(json.dumps(doc))
    with pytest.raises(exporters.ExportError, match="no tables"):
        exporters.to_excel(doc_json, tmp_path / "x.xlsx")


def test_not_a_docling_document(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    with pytest.raises(exporters.ExportError, match="isn't a Docling document"):
        exporters.to_word(tmp_path / "x.json", tmp_path / "x.docx")


# Jobs ---------------------------------------------------------------------------------------------


def test_job_saves_every_format(client, fake_docling, pdf, save_to):
    resp = client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}],
                                          "formats": ["word", "excel", "markdown", "text"], "scan": "always", "language": "de", "pages": "2-4"})
    assert resp.status_code == 201, resp.json()
    assert "--ocr-mode full_page --ocr-lang iso:de --page-range 2-4" in resp.json()["command"]
    run = wait(client, resp.json()["id"])
    assert run["status"] == "succeeded", run
    saved = {d["format"]: d["path"] for d in run["delivered"]}
    assert saved == {f: str(save_to / f"report{ext}") for f, ext in
                     [("word", ".docx"), ("excel", ".xlsx"), ("markdown", ".md"), ("text", ".txt")]}
    assert (save_to / "report.md").read_text() == "# report"
    # again: nothing is overwritten
    run2 = wait(client, client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["word"]}).json()["id"])
    assert run2["delivered"][0]["path"] == str(save_to / "report (2).docx")


def test_job_saves_csv(client, fake_docling, pdf, save_to):
    run = wait(client, client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["csv", "excel"]}).json()["id"])
    assert run["status"] == "succeeded", run
    assert [(d["format"], d["path"]) for d in run["delivered"]] == [("csv", str(save_to / "report.csv")), ("excel", str(save_to / "report.xlsx"))]
    assert "--to json" in run["command"]


def test_job_choices_checked(client, fake_docling, pdf):
    path = [{"kind": "path", "path": str(pdf)}]
    for request, message in [
        ({"inputs": [], "formats": ["word"]}, "Add a document"),
        ({"inputs": path, "formats": []}, "Choose what to save"),
        ({"inputs": path, "formats": ["word"], "pages": "1-x"}, "Pages are a number"),
        ({"inputs": path, "formats": ["word"], "language": "klingon"}, "Unknown language"),
        ({"inputs": path, "formats": ["word"], "scan": "sometimes"}, "Unknown scan"),
    ]:
        resp = client.post("/api/jobs", json=request)
        assert resp.status_code == 400 and message in resp.json()["detail"], (request, resp.json())


def test_single_page_and_pictures(fake_docling, pdf):
    built = simple.build({"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["markdown"], "pages": "5", "pictures": "describe"})
    assert built["values"]["page_range"] == "5-5" and built["values"]["enrich_picture_description"] is True
    assert built["values"]["to"] == ["json", "md"]
    dropped = simple.build({"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["word"], "pictures": "drop"})
    assert dropped["values"]["image_export_mode"] == "placeholder"


def test_only_saved_files_can_be_opened(client, fake_docling, pdf, save_to, monkeypatch):
    opened = []
    monkeypatch.setattr("docling_studio.native.open_file", opened.append)
    run = wait(client, client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["text"]}).json()["id"])
    assert client.post(f"/api/runs/{run['id']}/open", json={"path": str(save_to / "report.txt")}).status_code == 200
    assert client.post(f"/api/runs/{run['id']}/open", json={"path": "/etc/passwd"}).status_code == 404
    assert opened == [str(save_to / "report.txt")]


def test_runs_api_cant_set_where_files_go(client, fake_docling, pdf, tmp_path):
    resp = client.post("/api/runs", json={"tool": "convert", "values": {}, "inputs": {"source": [{"kind": "path", "path": str(pdf)}]},
                                          "finish": {"kind": "simple", "formats": ["text"], "folder": str(tmp_path / "elsewhere")}})
    run = wait(client, resp.json()["id"])
    assert run["finish"] is None and not (tmp_path / "elsewhere").exists()


def test_failed_conversion_saves_nothing(client, fake_docling, pdf, save_to, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "1")
    run = wait(client, client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["word"]}).json()["id"])
    assert run["status"] == "failed" and run["delivered"] is None
    assert not save_to.exists() or not any(save_to.iterdir())


def test_plan_gates_jobs(client, fake_docling, pdf, monkeypatch):
    assert client.get("/api/plan").json()["features"]["word"] is True
    free = {"name": "Free", "paid": False, "message": "", "features": {k: k not in ("word", "batch") for k in entitlements.FEATURES}}
    monkeypatch.setattr(entitlements, "plan", lambda: free)
    resp = client.post("/api/jobs", json={"inputs": [{"kind": "path", "path": str(pdf)}], "formats": ["word"]})
    assert resp.status_code == 400 and "Save as Word isn't part of your plan" in resp.json()["detail"]
    two = [{"kind": "path", "path": str(pdf)}, {"kind": "url", "url": "https://example.com/a.pdf"}]
    assert "isn't part of your plan" in client.post("/api/jobs", json={"inputs": two, "formats": ["text"]}).json()["detail"]
    assert client.post("/api/jobs", json={"inputs": two[:1], "formats": ["text"]}).status_code == 201


def test_options_for_the_page(client):
    o = client.get("/api/jobs/options").json()
    assert set(o["formats"]) == {"word", "excel", "csv", "markdown", "text", "html"}
    assert o["save_to"].endswith("Documents/DocuFlow") and o["save_to_label"] == "~/Documents/DocuFlow"
