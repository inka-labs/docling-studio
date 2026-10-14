import json
import time

import pytest
from fastapi.testclient import TestClient

from docling_studio import brand, cli_schema
from docling_studio.runs import document_key, index_outputs

from conftest import BASE


def wait(client, rid, timeout=30):
    rid = rid["id"] if isinstance(rid, dict) else rid
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{rid}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def convert(client, pdf, **values):
    resp = client.post("/api/runs", json={"tool": "convert", "values": values,
                                          "inputs": {"source": [{"kind": "path", "path": str(pdf)}]}})
    assert resp.status_code == 201, resp.json()
    return resp.json()


# Security ---------------------------------------------------------------------------------------


def test_api_needs_session_cookie(client):
    anonymous = TestClient(client.app, base_url=BASE)
    assert anonymous.get("/api/runs").status_code == 401


def test_auth_link_sets_cookie(client):
    fresh = TestClient(client.app, base_url=BASE)
    assert fresh.get("/auth?token=wrong", follow_redirects=False).status_code == 401
    resp = fresh.get(f"/auth?token={client.app_token}", follow_redirects=False)
    assert resp.status_code == 303
    assert "samesite=strict" in resp.headers["set-cookie"].lower()
    assert fresh.get("/api/runs").status_code == 200


def test_foreign_host_and_origin_refused(client):
    assert client.get("/api/runs", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/api/runs", json={}, headers={"origin": "https://evil.example"}).status_code == 403


def test_run_files_need_their_key(client, fake_docling, pdf):
    run = wait(client, convert(client, pdf)["id"])
    base = client.get(f"/api/runs/{run['id']}").json()["file_base"]
    anonymous = TestClient(client.app, base_url=BASE)
    assert anonymous.get(base + "output/report.md").text == "# report"
    assert anonymous.get(f"/files/{run['id']}/{'0' * 32}/output/report.md").status_code == 404
    assert anonymous.get(base + "../../session_token").status_code == 404


# Docling's options --------------------------------------------------------------------------------


def test_every_convert_option_is_in_the_form(client):
    schema = client.get("/api/schema").json()
    convert_tool = next(t for t in schema["tools"] if t["id"] == "convert")
    raw = cli_schema.raw()["commands"]["docling convert"]["params"]
    shown = {f["name"] for f in convert_tool["fields"]}
    managed = cli_schema.TOOLS_BY_ID["convert"].managed
    assert shown == {p["name"] for p in raw if p["name"] not in managed and not p["hidden"]}
    fields = {f["name"]: f for f in convert_tool["fields"]}
    assert fields["source"]["input"] == "sources"
    assert "chunks" in fields["to"]["choices"] and fields["to"]["initial"] == ["md", "json"]
    assert "granite_docling" in fields["vlm_model"]["suggestions"]
    assert fields["pdf_password"]["secret"]
    assert fields["vlm_model"]["when"] == {"pipeline": ["vlm"]}


def test_all_tools_available(client):
    tools = {t["id"]: t for t in client.get("/api/schema").json()["tools"]}
    assert set(tools) == {t.id for t in cli_schema.TOOLS}
    assert all(t["available"] for t in tools.values()), {k: t.get("error") for k, t in tools.items()}


def test_options_known_to_studio_get_a_section():
    """Options Studio has heard of land in a named section; a new one goes to Other options."""
    for tool in (cli_schema.get_tool("convert"), cli_schema.get_tool("convert-remote")):
        for p in cli_schema.raw()["commands"][tool.command]["params"]:
            if p["kind"] == "option" and p["name"] not in tool.managed:
                assert cli_schema.section(p["name"])[0] != "other", p["name"]


def test_command_line_has_only_changed_options():
    tool = cli_schema.get_tool("convert")
    args = cli_schema.option_args(tool, {
        "to": ["md", "json"], "ocr": False, "tables": True, "pipeline": "standard", "page_range": "1-3",
        "verbose": "2", "num_threads": "4", "html_image_headers_origin": ["https://a", "https://b"], "pdf_backend": "",
    })
    # in the order Docling lists its options
    assert args == ["--to", "md", "--to", "json", "--html-image-headers-origin", "https://a", "--html-image-headers-origin", "https://b",
                    "--no-ocr", "--page-range", "1-3", "-vv"]


@pytest.mark.parametrize("values, message", [
    ({"pipeline": "nope"}, "--pipeline must be one of"),
    ({"num_threads": "four"}, "--num-threads takes a whole number"),
    ({"no_such_option": 1}, "has no option no_such_option"),
    ({"output": "/tmp/x"}, "has no option output"),  # Studio's own
    ({"page_range": "1\n--x"}, "can't contain line breaks"),
])
def test_bad_values_refused(values, message):
    with pytest.raises(cli_schema.SchemaError, match=message):
        cli_schema.option_args(cli_schema.get_tool("convert"), values)


def test_preview_blanks_secrets(client):
    resp = client.post("/api/preview", json={"tool": "convert", "values": {"pdf_password": "hunter2", "headers": '{"Authorization": "Bearer tok"}'},
                                             "inputs": {"source": [{"kind": "url", "url": "https://x.org/a.pdf"}]}}).json()
    assert "hunter2" not in resp["command"] and "Bearer tok" not in resp["command"]
    assert resp["command"].startswith("docling convert https://x.org/a.pdf --headers")


# Runs ---------------------------------------------------------------------------------------------


def test_convert_run(client, fake_docling, pdf):
    run = wait(client, convert(client, pdf, to=["md", "json"], page_range="1-2"))
    assert run["status"] == "succeeded", run
    assert run["progress"]["done"] == 1 and run["progress"]["total"] == 1
    detail = client.get(f"/api/runs/{run['id']}").json()
    doc = detail["files"]["documents"][0]
    assert doc["name"] == "report" and {"markdown", "json", "image"} <= set(doc["kinds"])
    log = client.get(f"/api/runs/{run['id']}/log").json()["text"]
    assert f"args: convert {pdf} --to md --to json --page-range 1-2 --output" in log
    assert run["command"].startswith(f"docling convert {pdf} --to md --to json --page-range 1-2 --output ")


def test_secrets_never_written(client, fake_docling, pdf, studio_home):
    run = wait(client, convert(client, pdf, pdf_password="hunter2-secret"))
    assert run["status"] == "succeeded"
    folder = studio_home / "runs" / run["id"]
    assert "hunter2-secret" not in (folder / "run.json").read_text()
    log = (folder / "log.txt").read_text()
    assert "hunter2-secret" not in log and "--pdf-password ••••••" in log
    assert run["had_secrets"] == ["pdf_password"]
    again = client.get(f"/api/runs/{run['id']}/again").json()
    assert "pdf_password" not in again["values"] and again["had_secrets"] == ["pdf_password"]


def test_upload_is_taken_into_the_run(client, fake_docling, studio_home):
    up = client.post("/api/uploads?name=../../evil name.pdf", content=b"%PDF data").json()
    assert up["name"] == "evil name.pdf" and up["size"] == 9
    rid = client.post("/api/runs", json={"tool": "convert", "values": {}, "inputs": {"source": [up]}}).json()["id"]
    run = wait(client, rid)
    assert (studio_home / "runs" / rid / "input" / "evil name.pdf").read_bytes() == b"%PDF data"
    assert not (studio_home / "uploads" / up["id"]).exists()
    # run again: the kept copy, from this run's input folder
    again = client.get(f"/api/runs/{rid}/again").json()
    assert again["inputs"]["source"] == [{"kind": "run", "run": rid, "file": "input/evil name.pdf", "name": "evil name.pdf"}]
    second = wait(client, client.post("/api/runs", json={**again, "values": {}}).json()["id"])
    assert second["status"] == "succeeded" and run["status"] == "succeeded"


def test_inputs_checked(client, fake_docling, tmp_path):
    bad = [
        ({"kind": "path", "path": "relative/file.pdf"}, "full path"),
        ({"kind": "path", "path": str(tmp_path / "missing.pdf")}, "doesn't exist"),
        ({"kind": "url", "url": "file:///etc/passwd"}, "isn't a web address"),
        ({"kind": "upload", "id": "../../x", "name": "x"}, "isn't valid"),
        ({"kind": "run", "run": "20260101-000000-abcdef", "file": "../../session_token"}, "isn't a file"),
    ]
    for item, message in bad:
        resp = client.post("/api/runs", json={"tool": "convert", "values": {}, "inputs": {"source": [item]}})
        assert resp.status_code == 400 and message in resp.json()["detail"], (item, resp.json())
    resp = client.post("/api/runs", json={"tool": "convert", "values": {}, "inputs": {"source": []}})
    assert "Add at least one document" in resp.json()["detail"]


def test_failed_run(client, fake_docling, pdf, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "1")
    run = wait(client, convert(client, pdf))
    assert run["status"] == "failed" and run["exit_code"] == 2
    assert "could not convert" in run["error"]


def test_cancel_and_queue(client, fake_docling, pdf, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "30")
    first = convert(client, pdf)
    second = convert(client, pdf)  # one at a time: waits
    deadline = time.time() + 10
    while client.get(f"/api/runs/{first['id']}").json()["status"] != "running" and time.time() < deadline:
        time.sleep(0.05)
    assert client.get(f"/api/runs/{second['id']}").json()["status"] == "queued"
    assert client.post(f"/api/runs/{second['id']}/cancel").json()["status"] == "cancelled"
    client.post(f"/api/runs/{first['id']}/cancel")
    assert wait(client, first["id"], timeout=15)["status"] == "cancelled"
    assert client.delete(f"/api/runs/{first['id']}").status_code == 204
    assert client.get(f"/api/runs/{first['id']}").status_code == 404


def test_serialize_writes_into_the_run(client, fake_docling, pdf):
    source = wait(client, convert(client, pdf))
    resp = client.post("/api/runs", json={"tool": "serialize", "values": {"to": "markdown"},
                                          "inputs": {"source": [{"kind": "run", "run": source["id"], "file": "output/report.json"}]}})
    run = wait(client, resp.json()["id"])
    assert run["command"].startswith("docling-serialize ") and "--to markdown --output " in run["command"]
    assert run["command"].endswith("/output/report.md")


def test_doc_summary(client, fake_docling, pdf):
    run = wait(client, convert(client, pdf))
    summary = client.get(f"/api/runs/{run['id']}/doc", params={"file": "output/report.json"}).json()
    assert summary["name"] == "report" and summary["tables"] == 1 and summary["pictures"] == 1
    assert client.get(f"/api/runs/{run['id']}/doc", params={"file": "output/report.md"}).status_code == 400


# Services, presets, outputs -----------------------------------------------------------------------


def test_service_key_stays_in_keychain(client, fake_docling, pdf, studio_home, memory_keyring):
    resp = client.post("/api/services", json={"name": "gpu box", "url": "http://localhost:5001/", "api_key": "sk-123"})
    assert resp.json() == {**resp.json(), "name": "gpu box", "url": "http://localhost:5001", "has_key": True}
    assert "sk-123" not in json.dumps(client.get("/api/services").json())
    assert "sk-123" not in (studio_home / "services.json").read_text()
    rid = client.post("/api/runs", json={"tool": "convert-remote", "service": "gpu box", "values": {},
                                         "inputs": {"source": [{"kind": "path", "path": str(pdf)}]}}).json()["id"]
    wait(client, rid)
    log = client.get(f"/api/runs/{rid}/log").json()["text"]
    assert "service: http://localhost:5001 ••••••" in log and "sk-123" not in log
    # renaming keeps the key; "" removes it
    client.put("/api/services/gpu box", json={"name": "gpu", "url": "http://localhost:5001", "api_key": None})
    assert memory_keyring.items == {(brand.SLUG, "service:gpu"): "sk-123"}
    client.put("/api/services/gpu", json={"name": "gpu", "url": "http://localhost:5001", "api_key": ""})
    assert memory_keyring.items == {}


def test_presets_drop_secrets(client):
    p = client.post("/api/presets", json={"tool": "convert", "name": "Scans", "values": {"ocr_mode": "full_page", "pdf_password": "x"}}).json()
    assert p["values"] == {"ocr_mode": "full_page"}
    assert client.post("/api/presets", json={"tool": "convert", "name": "scans", "values": {}}).status_code == 400
    assert [x["name"] for x in client.get("/api/presets?tool=convert").json()] == ["Scans"]


@pytest.mark.parametrize("path, key", [
    ("paper.md", "paper"), ("paper.chunks.jsonl", "paper"), ("my.report.dclg.xml", "my.report"),
    ("paper_artifacts/image_000000_ab.png", "paper"), ("debug/debug_paper/layout_page_1.png", "paper"),
    ("paper-timings-2026-10-13_19-43-59.json", "paper"),
])
def test_outputs_grouped_by_document(path, key):
    assert document_key(path) == key


def test_index_skips_studio_files(tmp_path):
    (tmp_path / ".studio").mkdir()
    (tmp_path / ".studio" / "paper.split.html").write_text("x")
    (tmp_path / "paper.md").write_text("x")
    assert [f["path"] for f in index_outputs(tmp_path)["files"]] == ["paper.md"]
