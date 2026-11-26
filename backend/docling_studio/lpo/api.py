"""The LPO lab's HTTP API, under /api/lpo/ (so Studio's sign-in guard covers it)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import checks, convert, extract, pages, schema, store, testset
from .experiments import ExperimentError, Experiments, labels


class Lab:
    def __init__(self):
        self.jobs = testset.Jobs()
        self.experiments = Experiments()

    def stop(self):
        self.jobs.stop()
        self.experiments.stop_all()


def _bad(e: Exception):
    raise HTTPException(400, str(e))


def _doc(did: str) -> dict:
    try:
        did = store.safe_id(did)
    except ValueError as e:
        _bad(e)
    doc = testset.load()["docs"].get(did)
    if not doc:
        raise HTTPException(404, "That document isn't in the test set.")
    return doc


def router(lab: Lab) -> APIRouter:
    r = APIRouter(prefix="/api/lpo")
    exps = lab.experiments

    # The test set --------------------------------------------------------------------------------

    @r.get("/overview")
    def overview():
        return {"source": testset.source(), "clients": testset.clients(), "testset": testset.summary(),
                "job": lab.jobs.snapshot(), "schema": schema.describe(), "checks": checks.CHECK_LABELS,
                "options": {"choices": convert.CHOICES, "defaults": convert.DEFAULTS, "ocr_engines": convert.OCR_ENGINES},
                "mapper": extract.MAPPER_VERSION}

    @r.put("/source")
    def put_source(payload: dict):
        try:
            return testset.save_source(payload)
        except ValueError as e:
            _bad(e)

    @r.post("/listing")
    def refresh_listing():
        try:
            return lab.jobs.refresh_listing()
        except RuntimeError as e:
            _bad(e)

    @r.post("/testset")
    def build_testset(payload: dict):
        try:
            return lab.jobs.build(int(payload.get("size") or 0), int(payload.get("seed") or 7))
        except (RuntimeError, ValueError) as e:
            _bad(e)

    # Layouts in the bucket (survey.py) -----------------------------------------------------------

    @r.post("/survey")
    def start_survey(payload: dict):
        try:
            return lab.jobs.survey(int(payload.get("per_client") or 0))
        except (RuntimeError, ValueError) as e:
            _bad(e)

    @r.get("/survey/layouts")
    def survey_layouts():
        from . import survey

        return survey.layouts()

    @r.get("/survey/thumbs/{did}")
    def survey_thumb(did: str):
        try:
            path = store.path("survey", "thumbs", store.safe_id(did) + ".jpg")
        except ValueError as e:
            _bad(e)
        if not path.exists():
            raise HTTPException(404, "No picture for that document.")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @r.post("/survey/layouts/{lid}/add")
    def add_layout(lid: str, payload: dict):
        from . import survey

        if lab.jobs.busy():
            _bad(RuntimeError("Wait for the running job to finish."))
        try:
            added = survey.add_to_testset(store.safe_id(lid), max(1, min(50, int(payload.get("count") or 5))))
        except ValueError as e:
            _bad(e)
        return {"added": added}

    @r.post("/job/stop")
    def stop_job():
        lab.jobs.stop()
        return lab.jobs.snapshot()

    @r.get("/docs")
    def list_docs(exp: str | None = None):
        """Every test-set document, with its label state and, given an experiment, its result there."""
        ts = testset.load()
        have = set(labels())
        out = []
        results = {}
        if exp:
            try:
                results = {x["doc"]: x for x in exps.results(exp)}
            except (ValueError, ExperimentError) as e:
                _bad(e)
        for d in sorted(ts["docs"].values(), key=lambda d: d["id"]):
            if not d.get("kind"):
                continue
            row = {k: d.get(k) for k in ("id", "key", "client", "kind", "pages", "size", "modified", "excluded")}
            row["split"] = testset.split_of(d["id"])
            row["labelled"] = d["id"] in have
            res = results.get(d["id"])
            if res:
                row["result"] = {"error": res.get("error"), "ok": (res.get("checks") or {}).get("ok"),
                                 "checks": res.get("checks"), "lines": len((res.get("record") or {}).get("lines") or []),
                                 "lpo_number": ((res.get("record") or {}).get("fields") or {}).get("lpo_number"),
                                 "document_type": ((res.get("record") or {}).get("fields") or {}).get("document_type")}
            out.append(row)
        return out

    @r.get("/docs/{did}")
    def get_doc(did: str):
        doc = _doc(did)
        label = store.read_json(store.path("labels", doc["id"] + ".json"), None)
        orient = store.read_json(store.path("orient", doc["id"] + ".json"), None)
        return {**doc, "label": label, "orientation": orient and orient.get("angles"), "split": testset.split_of(doc["id"])}

    @r.patch("/docs/{did}")
    def change_doc(did: str, payload: dict):
        doc = _doc(did)
        ts = testset.load()
        if "excluded" in payload:
            ts["docs"][doc["id"]]["excluded"] = bool(payload["excluded"])
        testset.save(ts)
        return ts["docs"][doc["id"]]

    @r.get("/docs/{did}/pages/{number}")
    def page_picture(did: str, number: int, straight: bool = True):
        doc = _doc(did)
        try:
            path = pages.picture(doc, number, straight)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @r.get("/docs/{did}/file")
    def original(did: str):
        doc = _doc(did)
        return FileResponse(store.path("files", doc["file"]), filename=doc["key"].rsplit("/", 1)[-1])

    @r.put("/docs/{did}/label")
    def save_label(did: str, payload: dict):
        doc = _doc(did)
        record = schema.normalise(payload)
        label = {**record, "not_lpo": bool(payload.get("not_lpo")), "notes": str(payload.get("notes") or "")[:2000],
                 "from_experiment": payload.get("from_experiment"), "saved": testset._now()}
        store.write_json(store.path("labels", doc["id"] + ".json"), label)
        return {**label, "checks": checks.run(record)}

    @r.delete("/docs/{did}/label", status_code=204)
    def delete_label(did: str):
        doc = _doc(did)
        store.path("labels", doc["id"] + ".json").unlink(missing_ok=True)

    @r.post("/check")
    def check_record(payload: dict):
        """The checks for a record being edited (the review form shows them as you type)."""
        record = schema.normalise(payload)
        return {"record": record, "checks": checks.run(record)}

    # Experiments ---------------------------------------------------------------------------------

    @r.get("/experiments")
    def list_experiments():
        return exps.all()

    @r.post("/experiments", status_code=201)
    def create_experiment(payload: dict):
        try:
            return exps.create(payload)
        except (ExperimentError, ValueError) as e:
            _bad(e)

    def _exp(fn, *args):
        try:
            return fn(*args)
        except ValueError as e:
            _bad(e)
        except ExperimentError as e:
            if str(e) == "No such experiment.":
                raise HTTPException(404, str(e))
            _bad(e)

    @r.get("/experiments/{eid}")
    def get_experiment(eid: str):
        return _exp(exps.get, eid)

    @r.patch("/experiments/{eid}")
    def change_experiment(eid: str, payload: dict):
        return _exp(exps.update, eid, payload)

    @r.delete("/experiments/{eid}", status_code=204)
    def delete_experiment(eid: str):
        _exp(exps.delete, eid)

    @r.post("/experiments/{eid}/stop")
    def stop_experiment(eid: str):
        return _exp(exps.stop, eid)

    @r.post("/experiments/{eid}/resume")
    def resume_experiment(eid: str):
        return _exp(exps.resume, eid)

    @r.post("/experiments/{eid}/remap")
    def remap_experiment(eid: str):
        return _exp(exps.remap, eid)

    @r.get("/experiments/{eid}/log")
    def experiment_log(eid: str, offset: int = 0):
        return _exp(exps.log, eid, offset)

    @r.get("/experiments/{eid}/docs/{did}")
    def experiment_result(eid: str, did: str):
        result = _exp(exps.result, eid, did)
        if not result:
            raise HTTPException(404, "No result for that document in this experiment.")
        label = store.read_json(store.path("labels", store.safe_id(did) + ".json"), None)
        if label and result.get("record") and not label.get("not_lpo"):
            result["comparison"] = schema.compare(result["record"], label)
        return result

    @r.get("/experiments/{eid}/export")
    def export(eid: str):
        """Every result as JSON lines: what was read from each document."""
        import json

        exp = _exp(exps.get, eid)
        docs = testset.load()["docs"]
        target = exps.root / exp["id"] / "export.jsonl"
        with open(target, "w") as f:
            for res in exps.results(eid):
                d = docs.get(res["doc"], {})
                f.write(json.dumps({"doc": res["doc"], "key": d.get("key"), "client": d.get("client"),
                                    "error": res.get("error"), "checks": res.get("checks"), **(res.get("record") or {})}) + "\n")
        return FileResponse(target, filename=f"{exp['name']} - lpo results.jsonl", media_type="application/x-ndjson")

    return r
