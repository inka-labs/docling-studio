"""HTTP API + static UI.

Studio only listens on 127.0.0.1. On top of that every /api call needs the session cookie, which is
set by opening the one-time link printed at startup (/auth?token=...). That keeps other websites
open in the same browser from driving the API (it runs commands on your files), and the Host check
blocks DNS-rebinding.

A run's files are served under /files/<run id>/<key>/, where the key is derived from the session
token: unguessable, so no cookie is needed. That's what lets a result page shown in a sandboxed
frame (its scripts run, but not as Studio) load its own pictures.
"""

import hashlib
import hmac
import os
import secrets
import subprocess
import sys
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import cli_schema, docview, inputs, models, presets, services
from .core import settings
from .core.store import home
from .runs import STUDIO_DIR, RunError, RunManager, redact

COOKIE = "docling_studio_session"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
UI_DIST = Path(os.environ.get("DOCLING_STUDIO_UI") or Path(__file__).resolve().parents[2] / "frontend" / "dist")
SANDBOX = "sandbox allow-scripts allow-popups allow-downloads"


def _hostname(host: str) -> str:
    """'127.0.0.1:8766' -> '127.0.0.1', '[::1]:8766' -> '[::1]'."""
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0]


def session_token() -> str:
    """Stable across restarts so an open tab keeps working; rotate by deleting the file."""
    path = home() / "session_token"
    if path.exists():
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    path.write_text(token)
    os.chmod(path, 0o600)
    return token


def create_app() -> FastAPI:
    token = session_token()
    runs = RunManager()
    inputs.sweep_uploads()
    threading.Thread(target=cli_schema.warm, daemon=True, name="studio-schema").start()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        runs.stop_all()

    app = FastAPI(title="Docling Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.token = token
    app.state.runs = runs

    def file_key(rid: str) -> str:
        return hmac.new(token.encode(), f"files:{rid}".encode(), hashlib.sha256).hexdigest()[:32]

    def file_url(rid: str, path: Path) -> str:
        rel = path.resolve().relative_to((runs.root / rid).resolve()).as_posix()
        return f"/files/{rid}/{file_key(rid)}/{rel}"

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "Forbidden host."}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not hmac.compare_digest(request.cookies.get(COOKIE, ""), token):
                return JSONResponse({"detail": "Not signed in. Open Docling Studio again (or the sign-in link it printed)."}, status_code=401)
            origin = request.headers.get("origin")
            if request.method not in ("GET", "HEAD") and origin:
                if _hostname(origin.split("://", 1)[-1]) not in ALLOWED_HOSTS:
                    return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/auth")
    def auth(request: Request):
        if not hmac.compare_digest(request.query_params.get("token", ""), token):
            return HTMLResponse("<p>That sign-in link isn't valid. Open Docling Studio again from its app or shortcut (or use the link it printed).</p>", status_code=401)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 365)
        return resp

    def bad(e: Exception):
        raise HTTPException(400, str(e))

    def run_or_404(rid: str) -> dict:
        run = runs.get(rid)
        if not run:
            raise HTTPException(404, "No such run.")
        return run

    def output_file(rid: str, rel: str) -> Path:
        run_or_404(rid)
        try:
            return inputs.run_file(rid, rel)
        except inputs.InputError as e:
            raise HTTPException(404, str(e))

    # Studio -----------------------------------------------------------------------------------

    @app.get("/api/version")
    def get_version():
        from . import __version__, autostart, launch
        return {"version": __version__, "platform": sys.platform, "bundled": launch.bundled(), "home": str(home()),
                "autostart": {"supported": autostart.supported(), "enabled": autostart.enabled()}}

    @app.get("/api/summary")
    def summary():
        everything = runs.all()
        return {"runs": len(everything), "running": sum(r["status"] == "running" for r in everything),
                "queued": sum(r["status"] == "queued" for r in everything),
                "services": len(services.list_services())}

    @app.get("/api/settings")
    def get_settings():
        return settings.get()

    @app.put("/api/settings")
    def put_settings(payload: dict):
        try:
            return settings.update(payload)
        except ValueError as e:
            bad(e)

    @app.post("/api/autostart")
    def set_autostart(payload: dict):
        from . import autostart
        try:
            message = autostart.install() if payload.get("enabled") else autostart.uninstall(stop_now=False)
        except autostart.AutostartError as e:
            bad(e)
        return {"message": message, "enabled": autostart.enabled()}

    @app.post("/api/quit")
    def quit_studio(request: Request, force: bool = False):
        active = runs.active()
        if active and not force:
            raise HTTPException(409, f"{len(active)} run{'s are' if len(active) != 1 else ' is'} in progress. Stop {'them' if len(active) != 1 else 'it'} first, or quit anyway.")
        runs.stop_all()
        server = getattr(request.app.state, "server", None)
        if server is not None:
            threading.Timer(0.5, lambda: setattr(server, "should_exit", True)).start()
        return {"ok": True}

    # Docling's commands -----------------------------------------------------------------------

    @app.get("/api/schema")
    def get_schema(refresh: bool = False):
        try:
            return cli_schema.schema(refresh)
        except cli_schema.SchemaError as e:
            raise HTTPException(500, str(e))

    @app.post("/api/preview")
    def preview(payload: dict):
        """The command a form would run, as you'd type it (secrets blanked out)."""
        try:
            tool = cli_schema.get_tool(str(payload.get("tool", "")))
            values = payload.get("values") or {}
            options = cli_schema.option_args(tool, values)
        except cli_schema.SchemaError as e:
            return {"command": None, "error": str(e)}
        positional: list[str] = []
        for name, param in cli_schema.command_params(tool).items():
            if param["kind"] != "argument":
                continue
            if name in tool.inputs:
                for item in (payload.get("inputs") or {}).get(name) or []:
                    positional.append(str(item.get("url") or item.get("path") or item.get("name") or "?"))
            elif not cli_schema._empty(values.get(name)):
                positional += [str(v) for v in (values[name] if isinstance(values[name], list) else [values[name]])]
        managed = {"convert": ["--output", "<run folder>"], "convert-remote": ["--output", "<run folder>"],
                   "serialize": ["--output", "<run folder>/…"], "doclang-pack": ["--output", "<run folder>/….dclx"]}.get(tool.id, [])
        from .runs import _quote
        shown = [tool.command.split()[0], *cli_schema.subcommand(tool), *positional, *options, *managed]
        return {"command": redact(_quote(shown), cli_schema.secret_values(values)), "error": None}

    @app.get("/api/plugins")
    def external_plugins():
        """The plugins Docling can load: its own, and third-party ones (loaded only with
        --allow-external-plugins). Read from the "docling" entry points, as Docling finds them
        (`docling convert --show-external-plugins` fails in some versions)."""
        from importlib.metadata import entry_points
        found = [{"name": ep.name, "value": ep.value, "package": ep.dist.name if ep.dist else None,
                  "version": ep.dist.version if ep.dist else None, "builtin": ep.name == "docling_defaults"}
                 for ep in entry_points(group="docling")]
        return sorted(found, key=lambda p: (not p["builtin"], p["name"]))

    # Inputs -----------------------------------------------------------------------------------

    @app.post("/api/uploads")
    async def upload(request: Request, name: str):
        return await inputs.save_upload(name, request.stream())

    @app.delete("/api/uploads/{uid}", status_code=204)
    def discard_upload(uid: str):
        inputs.discard_upload(uid)

    @app.post("/api/inputs/check")
    def check_input(payload: dict):
        try:
            return inputs.check(payload, {"path", "url"})
        except inputs.InputError as e:
            bad(e)

    # Runs -------------------------------------------------------------------------------------

    @app.get("/api/runs")
    def list_runs():
        return runs.all()

    @app.post("/api/runs", status_code=201)
    def start_run(payload: dict):
        try:
            return runs.submit(payload)
        except (RunError, cli_schema.SchemaError) as e:
            bad(e)

    @app.get("/api/runs/{rid}")
    def get_run(rid: str):
        run = run_or_404(rid)
        return {**run, "files": runs.outputs(rid), "file_base": f"/files/{rid}/{file_key(rid)}/"}

    @app.patch("/api/runs/{rid}")
    def rename_run(rid: str, payload: dict):
        try:
            return runs.rename(rid, str(payload.get("title", "")))
        except RunError as e:
            bad(e)

    @app.delete("/api/runs/{rid}", status_code=204)
    def delete_run(rid: str):
        run_or_404(rid)
        try:
            runs.delete(rid)
        except RunError as e:
            bad(e)

    @app.get("/api/runs/{rid}/log")
    def run_log(rid: str, offset: int = 0):
        run_or_404(rid)
        return runs.log(rid, offset)

    @app.post("/api/runs/{rid}/cancel")
    def cancel_run(rid: str):
        run_or_404(rid)
        return runs.cancel(rid)

    @app.get("/api/runs/{rid}/again")
    def run_again(rid: str):
        run_or_404(rid)
        return runs.again(rid)

    @app.get("/api/runs/{rid}/doc")
    def doc_summary(rid: str, file: str):
        try:
            return docview.summary(output_file(rid, file))
        except docview.DocError as e:
            bad(e)

    @app.get("/api/runs/{rid}/tables")
    def doc_tables(rid: str, file: str):
        try:
            return docview.tables(output_file(rid, file))
        except docview.DocError as e:
            bad(e)

    @app.get("/api/runs/{rid}/pictures")
    def doc_pictures(rid: str, file: str):
        try:
            return docview.pictures(output_file(rid, file), lambda p: file_url(rid, p))
        except docview.DocError as e:
            bad(e)

    @app.post("/api/runs/{rid}/view")
    def doc_view(rid: str, payload: dict):
        path = output_file(rid, str(payload.get("file", "")))
        try:
            page = docview.view(path, runs.root / rid / "output", bool(payload.get("split", True)))
        except docview.DocError as e:
            bad(e)
        return {"url": file_url(rid, page)}

    @app.get("/api/runs/{rid}/zip")
    def run_zip(rid: str):
        run = run_or_404(rid)
        output = runs.root / rid / "output"
        target = output / STUDIO_DIR / "results.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        files = [p for p in sorted(output.rglob("*")) if p.is_file() and STUDIO_DIR not in p.relative_to(output).parts]
        newest = max((p.stat().st_mtime for p in files), default=0)
        if not target.exists() or target.stat().st_mtime < newest:
            part = target.with_suffix(".part")
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as zf:
                for p in files:
                    zf.write(p, p.relative_to(output).as_posix())
            part.replace(target)
        name = inputs.safe_name(run["title"]).rsplit(".", 1)[0] or rid
        return FileResponse(target, filename=f"{name} - docling.zip", media_type="application/zip")

    @app.post("/api/runs/{rid}/reveal")
    def reveal(rid: str, payload: dict | None = None):
        """Show the run's output folder (or one of its files) in Finder / Explorer."""
        run_or_404(rid)
        rel = (payload or {}).get("file")
        target = output_file(rid, rel) if rel else runs.root / rid / "output"
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        elif os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{target}"] if target.is_file() else ["explorer", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)])
        return {"path": str(target)}

    @app.get("/files/{rid}/{key}/{rel:path}")
    def serve_file(rid: str, key: str, rel: str):
        if not hmac.compare_digest(key, file_key(rid)):
            raise HTTPException(404, "Not found.")
        path = output_file(rid, rel)
        resp = FileResponse(path)
        if path.suffix.lower() in (".html", ".htm", ".svg", ".xml"):
            resp.headers["Content-Security-Policy"] = SANDBOX
        return resp

    # Presets ----------------------------------------------------------------------------------

    @app.get("/api/presets")
    def list_presets(tool: str | None = None):
        return presets.list_presets(tool)

    @app.post("/api/presets", status_code=201)
    def add_preset(payload: dict):
        try:
            return presets.save(str(payload.get("tool", "")), str(payload.get("name", "")), payload.get("values") or {})
        except (presets.PresetError, cli_schema.SchemaError) as e:
            bad(e)

    @app.put("/api/presets/{pid}")
    def change_preset(pid: str, payload: dict):
        try:
            return presets.save(str(payload.get("tool", "")), str(payload.get("name", "")), payload.get("values") or {}, pid)
        except (presets.PresetError, cli_schema.SchemaError) as e:
            bad(e)

    @app.delete("/api/presets/{pid}", status_code=204)
    def remove_preset(pid: str):
        if not presets.delete(pid):
            raise HTTPException(404, "No such preset.")

    # Services (docling-serve) -----------------------------------------------------------------

    @app.get("/api/services")
    def list_services():
        return services.list_services()

    @app.post("/api/services", status_code=201)
    def add_service(payload: dict):
        try:
            return services.save(str(payload.get("name", "")), str(payload.get("url", "")), payload.get("api_key") or None)
        except services.ServiceError as e:
            bad(e)

    @app.put("/api/services/{name}")
    def change_service(name: str, payload: dict):
        try:
            return services.save(str(payload.get("name", name)), str(payload.get("url", "")), payload.get("api_key"), original=name)
        except services.ServiceError as e:
            bad(e)

    @app.delete("/api/services/{name}", status_code=204)
    def remove_service(name: str):
        if not services.delete(name):
            raise HTTPException(404, "No such service.")

    @app.post("/api/services/{name}/check")
    def check_service(name: str):
        try:
            return services.check(name)
        except services.ServiceError as e:
            bad(e)

    # Models -----------------------------------------------------------------------------------

    @app.get("/api/models")
    def list_models():
        return models.list_models()

    @app.delete("/api/models/{where}/{folder}", status_code=204)
    def delete_model(where: str, folder: str):
        try:
            models.delete(where, folder)
        except models.ModelError as e:
            bad(e)

    # The UI -----------------------------------------------------------------------------------

    @app.get("/{path:path}")
    def ui(path: str):
        if path.startswith(("api/", "files/")):
            raise HTTPException(404, "Not found.")
        index = UI_DIST / "index.html"
        if not index.is_file():
            return HTMLResponse("<p>The UI isn't built yet. Run <code>pixi run build-ui</code> (or <code>pixi run start</code>).</p>", status_code=503)
        candidate = (UI_DIST / path).resolve()
        if path and UI_DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return app
