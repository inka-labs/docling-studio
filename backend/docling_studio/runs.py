"""Running the Docling CLIs.

Each run gets runs/<run id>/ in the app's folder, holding run.json (what was asked and how it went),
log.txt (everything the command printed, secrets blanked out), input/ (uploaded files and files
taken from earlier runs) and output/ (what the command wrote; it also runs there, so Docling's
debug pictures land in output/debug/).

Runs wait in a queue and start when a slot is free (Settings: how many at once, 1 by default,
since conversions load large models). A run that was going when Studio stopped is marked
interrupted at the next start.
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cli_schema, inputs, services
from .core import settings
from .core.store import read_json, write_json

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
REDACTED = "••••••"
FINISHED_DOC = re.compile(r"Finished converting document (.+?) in ([\d.]+) sec")
PROCESSED = re.compile(r"Processed (\d+) docs?, of which (\d+) failed")
# what a run is doing, for people who don't read logs: fetching models (the first time), then reading
MODELS = re.compile(r"Fetching model|Downloading|Download size|download_file", re.I)
CONVERTING = re.compile(r"Processing document|Going to convert")
# Docling's output files, by the end of their name (longest first): what kind of result each is.
KINDS = [
    (".chunks.jsonl", "chunks"), (".dclg.xml", "doclang"), (".md", "markdown"), (".html", "html"),
    (".json", "json"), (".yaml", "yaml"), (".yml", "yaml"), (".txt", "text"), (".doctags", "doctags"),
    (".vtt", "vtt"), (".tex", "latex"), (".dclx", "dclx"), (".xml", "xml"), (".png", "image"),
    (".jpg", "image"), (".jpeg", "image"), (".webp", "image"), (".csv", "csv"),
]
TIMINGS = re.compile(r"^(.+)-timings-\d{4}-\d{2}-\d{2}_[\d-]+\.json$")
STUDIO_DIR = ".studio"  # Studio's own files in a run's output (the document view), not listed
# Studio's environment variables that would confuse a Docling run (none today, kept for clarity).
ENV_DROP = ("DOCLING_STUDIO_",)
# Where serialize / pack write, by --to.
EXTENSIONS = {"html": ".html", "markdown": ".md", "doctags": ".doctags", "text": ".txt", "json": ".json", "dclx": ".dclx"}


class RunError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _quote(args: list[str]) -> str:
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def kind_of(name: str) -> str:
    lower = name.lower()
    if TIMINGS.match(name):
        return "profiling"
    return next((kind for suffix, kind in KINDS if lower.endswith(suffix)), "file")


def document_key(rel: str) -> str:
    """Which document an output file belongs to: paper.md, paper.chunks.jsonl, paper_artifacts/…,
    debug/debug_paper/… and paper-timings-….json all belong to "paper"."""
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] == "debug" and parts[1].startswith("debug_"):
        return parts[1][len("debug_"):]
    if len(parts) > 1 and parts[0].endswith("_artifacts"):
        return parts[0][: -len("_artifacts")]
    name = parts[-1]
    if m := TIMINGS.match(name):
        return m.group(1)
    lower = name.lower()
    for suffix, _ in KINDS:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def index_outputs(output: Path) -> dict:
    """The files a run made, and the same grouped by document."""
    files = []
    if output.is_dir():
        for path in sorted(output.rglob("*")):
            rel = path.relative_to(output).as_posix()
            if path.is_file() and not rel.startswith(STUDIO_DIR + "/"):
                files.append({"path": rel, "size": path.stat().st_size, "kind": kind_of(path.name)})
    documents: dict[str, dict] = {}
    for f in files:
        key = document_key(f["path"])
        doc = documents.setdefault(key, {"name": key, "files": [], "kinds": []})
        doc["files"].append(f["path"])
        if f["kind"] not in doc["kinds"]:
            doc["kinds"].append(f["kind"])
    return {"files": files, "documents": sorted(documents.values(), key=lambda d: d["name"].lower()),
            "total_size": sum(f["size"] for f in files)}


class RunManager:
    def __init__(self):
        self.root = inputs.runs_dir()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._procs: dict[str, subprocess.Popen] = {}
        self._secrets: dict[str, list[str]] = {}
        # a queued run's command line: in memory only, as it can hold a PDF password or headers
        self._argv: dict[str, list[str]] = {}
        self._env: dict[str, dict] = {}
        self._cancelled: set[str] = set()
        self._runs: dict[str, dict] = {}
        for path in self.root.glob("*/run.json"):
            run = read_json(path, None)
            if not run:
                continue
            if run.get("status") in ("queued", "running"):
                run.update(status="interrupted", ended=run.get("ended") or _now(),
                           error="Studio stopped before this run finished.")
                write_json(path, run)
            self._runs[run["id"]] = run
        self._sweep_old()
        self._dispatcher = threading.Thread(target=self._dispatch, name="studio-runs", daemon=True)
        self._dispatcher.start()

    # Reading ----------------------------------------------------------------------------------

    def all(self) -> list[dict]:
        with self._lock:
            return sorted((dict(r) for r in self._runs.values()), key=lambda r: r["created"], reverse=True)

    def get(self, rid: str) -> dict | None:
        with self._lock:
            run = self._runs.get(rid)
            return dict(run) if run else None

    def dir(self, rid: str) -> Path:
        if rid not in self._runs:
            raise RunError("No such run.")
        return self.root / rid

    def active(self) -> list[dict]:
        return [r for r in self.all() if r["status"] in ("queued", "running")]

    def log(self, rid: str, offset: int = 0, limit: int = 512 * 1024) -> dict:
        path = self.dir(rid) / "log.txt"
        size = path.stat().st_size if path.exists() else 0
        offset = max(0, min(offset, size))
        if size - offset > limit and offset == 0:  # a long log: its end
            offset = size - limit
        with open(path, "rb") if path.exists() else _Empty() as f:
            f.seek(offset)
            data = f.read(limit)
        return {"text": data.decode("utf-8", errors="replace"), "offset": offset + len(data), "size": size,
                "truncated": offset > 0 and size > limit}

    def outputs(self, rid: str) -> dict:
        return index_outputs(self.dir(rid) / "output")

    # Starting ---------------------------------------------------------------------------------

    def submit(self, request: dict) -> dict:
        """Check a run request, take its inputs and queue it. request: {tool, values, inputs:
        {argument: [input, …]}, service?, title?}."""
        tool = cli_schema.get_tool(str(request.get("tool", "")))
        values = dict(request.get("values") or {})
        given = request.get("inputs") or {}
        params = cli_schema.command_params(tool)
        try:
            options = cli_schema.option_args(tool, values)
        except cli_schema.SchemaError as e:
            raise RunError(str(e))
        checked: dict[str, list[dict]] = {}
        for name, mode in tool.inputs.items():
            items = given.get(name) or []
            if not isinstance(items, list):
                raise RunError("Inputs must be a list.")
            allow = {"upload", "path", "url", "run"} if mode == "sources" else {"upload", "path", "run"}
            try:
                checked[name] = [inputs.check(i, allow) for i in items]
            except inputs.InputError as e:
                raise RunError(str(e))
            if params[name]["required"] and not checked[name]:
                raise RunError("Add at least one document to convert." if mode == "sources" else f"Choose the {cli_schema.label(name).lower()}.")
            if mode == "file" and len(checked[name]) > 1:
                raise RunError(f"{cli_schema.label(name)} takes one file.")
        env, secrets = {}, cli_schema.secret_values(values)
        service = None
        if tool.service:
            service = str(request.get("service") or "")
            try:
                env, keys = services.env_for(service)
            except services.ServiceError as e:
                raise RunError(str(e))
            secrets += keys

        rid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        run_dir = self.root / rid
        (run_dir / "output").mkdir(parents=True, mode=0o700)
        try:
            positional: list[str] = []
            for name, param in params.items():
                if param["kind"] != "argument":
                    continue
                if name in tool.inputs:
                    positional += [inputs.materialize(i, run_dir / "input") for i in checked[name]]
                elif not cli_schema._empty(values.get(name)):
                    raw = values[name] if isinstance(values[name], list) else [values[name]]
                    positional += [str(cli_schema._coerce(param, v)) for v in raw]
                elif param["required"]:
                    raise RunError(f"Choose {cli_schema.label(name).lower()}.")
            managed = self._managed_args(tool, values, run_dir / "output", positional)
        except (RunError, inputs.InputError, cli_schema.SchemaError) as e:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise RunError(str(e))

        shown = [tool.command.split()[0], *cli_schema.subcommand(tool), *positional, *options, *managed]
        title = str(request.get("title") or "").strip()[:120] or self._title(tool, checked)
        run = {
            "id": rid, "tool": tool.id, "tool_title": tool.title, "title": title, "status": "queued",
            "values": cli_schema.without_secrets(values),
            "had_secrets": sorted(k for k in cli_schema.SECRETS if not cli_schema._empty(values.get(k))),
            "inputs": checked, "service": service,
            # what to do with the results once the command is done (simple.py: save Word, Excel…)
            "finish": request.get("finish"), "delivered": None,
            "command": redact(_quote(shown), secrets),
            "created": _now(), "started": None, "ended": None, "exit_code": None, "error": None,
            "progress": {"done": 0, "failed": 0, "total": self._count(checked), "finished": [], "phase": "starting"}, "pid": None,
        }
        argv = self.command(tool, [*cli_schema.subcommand(tool), *positional, *options, *managed])
        with self._lock:
            self._argv[rid] = argv
            self._secrets[rid] = secrets
            self._env[rid] = env
            self._runs[rid] = run
            self._save(run)
            self._wake.notify_all()
        return self.get(rid)

    @staticmethod
    def command(tool: cli_schema.Tool, args: list[str]) -> list[str]:
        """How a tool is run: its CLI's Typer app, by module, in this environment's Python."""
        return [sys.executable, "-X", "utf8", "-m", "docling_studio.runcli", cli_schema.module_for(tool), *args]

    def _managed_args(self, tool: cli_schema.Tool, values: dict, output: Path, positional: list[str]) -> list[str]:
        if tool.id in ("convert", "convert-remote"):
            return ["--output", str(output)]
        if tool.id == "serialize":
            stem = Path(positional[0]).stem if positional else "document"
            return ["--output", str(output / (stem + EXTENSIONS.get(str(values.get("to") or "html"), ".out")))]
        if tool.id == "doclang-pack":
            stem = Path(positional[0]).stem if positional else "document"
            return ["--output", str(output / (stem.removesuffix(".dclg") + ".dclx"))]
        return []

    @staticmethod
    def _title(tool: cli_schema.Tool, checked: dict) -> str:
        names = [i.get("name") or i.get("url") or i.get("path") for items in checked.values() for i in items]
        if not names:
            return tool.title
        return names[0] + (f" and {len(names) - 1} more" if len(names) > 1 else "")

    @staticmethod
    def _count(checked: dict) -> int | None:
        items = [i for items in checked.values() for i in items]
        return None if any(i.get("folder") for i in items) else len(items) or None

    def again(self, rid: str) -> dict:
        """The request that made a run, to fill the form again: its files come from the run's
        input/ folder, secrets have to be typed again."""
        run = self.get(rid)
        if not run:
            raise RunError("No such run.")
        again: dict[str, list] = {}
        input_dir = self.root / rid / "input"
        taken = sorted(p.name for p in input_dir.iterdir()) if input_dir.is_dir() else []
        for name, items in run["inputs"].items():
            again[name] = []
            for item in items:
                if item["kind"] in ("upload", "run"):
                    # the copy this run kept, under the name it was given there
                    match = item["name"] if item["name"] in taken else next((t for t in taken if Path(t).stem.startswith(Path(item["name"]).stem)), None)
                    if match:
                        again[name].append({"kind": "run", "run": rid, "file": f"input/{match}", "name": match})
                else:
                    again[name].append(item)
        return {"tool": run["tool"], "values": run["values"], "inputs": again, "service": run.get("service"),
                "had_secrets": run.get("had_secrets", [])}

    # Running ----------------------------------------------------------------------------------

    def _dispatch(self) -> None:
        while True:
            with self._lock:
                while True:
                    running = sum(1 for r in self._runs.values() if r["status"] == "running")
                    queued = sorted((r for r in self._runs.values() if r["status"] == "queued"), key=lambda r: r["created"])
                    if queued and running < settings.get()["max_parallel_runs"]:
                        run = queued[0]
                        break
                    self._wake.wait(timeout=2)
                self._update(run["id"], status="running", started=_now())
            threading.Thread(target=self._execute, args=(run["id"],), name=f"run-{run['id']}", daemon=True).start()

    def _execute(self, rid: str) -> None:
        run = self.get(rid)
        run_dir = self.root / rid
        env = {k: v for k, v in os.environ.items() if not k.startswith(ENV_DROP)}
        # plain lines: no colours, rich tables wide enough to read, Python output as it happens
        env.update(PYTHONUNBUFFERED="1", NO_COLOR="1", TERM="dumb", COLUMNS="160", PYTHONIOENCODING="utf-8",
                   **self._env.pop(rid, {}))
        secrets = self._secrets.get(rid, [])
        kwargs: dict = {"cwd": run_dir / "output", "env": env, "stdin": subprocess.DEVNULL,
                        "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        log = open(run_dir / "log.txt", "ab")
        try:
            log.write(f"$ {run['command']}\n\n".encode())
            log.flush()
            try:
                proc = subprocess.Popen(self._argv.pop(rid), **kwargs)
            except OSError as e:
                self._update(rid, status="failed", ended=_now(), error=f"Couldn't start: {e}")
                return
            with self._lock:
                self._procs[rid] = proc
                self._update(rid, pid=proc.pid)
                cancel_early = rid in self._cancelled
            if cancel_early:
                self._kill(proc)
            last_error = self._pump(rid, proc, log, secrets)
            code = proc.wait()
        finally:
            log.close()
        delivered, finish_error = self._finish(rid, run_dir, code, rid in self._cancelled)
        with self._lock:
            self._procs.pop(rid, None)
            self._secrets.pop(rid, None)
            cancelled = rid in self._cancelled
            self._cancelled.discard(rid)
            outputs = index_outputs(run_dir / "output")
            status = "cancelled" if cancelled else "succeeded" if code == 0 else "failed"
            progress = self._runs[rid]["progress"]
            if status == "succeeded" and progress.get("failed"):
                status = "partial"  # Docling carried on past documents it couldn't convert
            if finish_error and status in ("succeeded", "partial"):
                status, last_error = "failed", finish_error
            self._update(rid, status=status, exit_code=code, ended=_now(), pid=None,
                         error=None if status in ("succeeded", "cancelled") else (last_error or f"Stopped with exit code {code}."),
                         outputs={"count": len(outputs["files"]), "size": outputs["total_size"],
                                  "documents": len(outputs["documents"])},
                         delivered=delivered)
            self._wake.notify_all()

    def _finish(self, rid: str, run_dir: Path, code: int, cancelled: bool) -> tuple[list | None, str | None]:
        """A job's finish step, once Docling has succeeded: (files saved, or why that failed)."""
        finish = self._runs[rid].get("finish")
        if not finish or code != 0 or cancelled:
            return None, None
        from . import simple
        with open(run_dir / "log.txt", "ab") as log:
            def write(text: str) -> None:
                log.write((text + "\n").encode("utf-8"))
            with self._lock:
                self._update(rid, progress={**self._runs[rid]["progress"], "phase": "saving"})
            try:
                return simple.deliver(finish, run_dir / "output", write), None
            except simple.JobError as e:
                write(str(e))
                return None, str(e)

    def _pump(self, rid: str, proc: subprocess.Popen, log, secrets: list[str]) -> str | None:
        """Copy the command's output to the log, line by line (a progress bar's \\r updates are kept
        to their last state), and follow its progress. Returns the last error-looking line."""
        last_error = None
        buffer = b""
        assert proc.stdout is not None
        while chunk := proc.stdout.read1(65536):  # type: ignore[union-attr]
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for raw in lines:
                last_error = self._line(rid, raw, log, secrets) or last_error
            log.flush()
        if buffer:
            last_error = self._line(rid, buffer, log, secrets) or last_error
        return last_error

    def _line(self, rid: str, raw: bytes, log, secrets: list[str]) -> str | None:
        text = raw.decode("utf-8", errors="replace").split("\r")
        line = ANSI.sub("", next((t for t in reversed(text) if t.strip()), "")).rstrip()
        line = redact(line, secrets)
        log.write((line + "\n").encode("utf-8"))
        changes = {}
        progress = dict(self._runs[rid]["progress"])
        if m := FINISHED_DOC.search(line):
            progress["done"] += 1
            progress["finished"] = [*progress.get("finished", []), m.group(1)]
            progress["phase"] = "converting"
            changes["progress"] = progress
        elif MODELS.search(line) and progress.get("phase") != "converting":
            if progress.get("phase") != "models":
                progress["phase"] = "models"
                changes["progress"] = progress
        elif CONVERTING.search(line) and progress.get("phase") != "converting":
            progress["phase"] = "converting"
            changes["progress"] = progress
        elif m := PROCESSED.search(line):
            progress.update(processed=int(m.group(1)), failed=int(m.group(2)))
            changes["progress"] = progress
        if changes:
            with self._lock:
                self._update(rid, **changes)
        stripped = line.strip()
        if re.search(r"\b(ERROR|Error|Exception|failed|Traceback)\b", stripped) and "of which 0 failed" not in stripped:
            return stripped[:500]
        return None

    def cancel(self, rid: str) -> dict:
        with self._lock:
            run = self._runs.get(rid)
            if not run:
                raise RunError("No such run.")
            if run["status"] == "queued":
                self._argv.pop(rid, None)
                self._secrets.pop(rid, None)
                self._env.pop(rid, None)
                self._update(rid, status="cancelled", ended=_now())
            elif run["status"] == "running":
                self._cancelled.add(rid)
                proc = self._procs.get(rid)
                if proc:
                    threading.Thread(target=self._kill, args=(proc,), daemon=True).start()
            return self.get(rid)

    @staticmethod
    def _kill(proc: subprocess.Popen, grace: float = 5) -> None:
        """Stop a run and everything it started: politely, then for good."""
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def stop_all(self) -> None:
        for rid in [r["id"] for r in self.active()]:
            self.cancel(rid)

    def delete(self, rid: str) -> None:
        with self._lock:
            run = self._runs.get(rid)
            if not run:
                raise RunError("No such run.")
            if run["status"] in ("queued", "running"):
                raise RunError("Stop the run before deleting it.")
            self._runs.pop(rid)
        shutil.rmtree(self.root / rid, ignore_errors=True)

    def save_more(self, rid: str, formats: list[str]) -> dict:
        """A finished job's results saved as more formats (simple.save_more), added to its files."""
        from . import simple
        run = self.get(rid)
        if not run:
            raise RunError("No such run.")
        if not run.get("finish") or run["status"] not in ("succeeded", "partial"):
            raise RunError("Only a finished conversion can be saved as another format.")
        with open(self.root / rid / "log.txt", "ab") as log:
            def write(text: str) -> None:
                log.write((text + "\n").encode("utf-8"))
            try:
                added = simple.save_more(run, self.root / rid / "output", formats, write)
            except simple.JobError as e:
                raise RunError(str(e))
        with self._lock:
            current = self._runs[rid]
            finish = {**current["finish"], "formats": list(dict.fromkeys([*current["finish"]["formats"], *formats]))}
            self._update(rid, delivered=[*(current.get("delivered") or []), *added], finish=finish)
        return self.get(rid)

    def rename(self, rid: str, title: str) -> dict:
        title = (title or "").strip()[:120]
        if not title:
            raise RunError("Give the run a name.")
        with self._lock:
            if rid not in self._runs:
                raise RunError("No such run.")
            self._update(rid, title=title)
        return self.get(rid)

    # Keeping ----------------------------------------------------------------------------------

    def _update(self, rid: str, **changes) -> None:
        run = self._runs[rid]
        run.update(changes)
        self._save(run)

    def _save(self, run: dict) -> None:
        write_json(self.root / run["id"] / "run.json", run)

    def _sweep_old(self) -> None:
        days = settings.get()["keep_runs_days"]
        if not days:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        for run in list(self._runs.values()):
            if run["status"] not in ("queued", "running") and (run.get("ended") or run["created"]) < cutoff:
                self._runs.pop(run["id"])
                shutil.rmtree(self.root / run["id"], ignore_errors=True)


class _Empty:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def seek(self, n):
        pass

    def read(self, n):
        return b""


def wait(manager: RunManager, rid: str, timeout: float = 60) -> dict:
    """For tests and scripts: the run once it has finished."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.get(rid)
        if run and run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise TimeoutError(rid)
