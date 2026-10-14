import json
import sys
import textwrap
from pathlib import Path

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend

from docling_studio import brand, cli_schema

SCHEMA_CACHE = Path(__file__).parent / ".cli-schema-cache.json"
BASE = "http://127.0.0.1:8767"


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.items:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.items[(service, username)]


@pytest.fixture(scope="session")
def docling_schema():
    """Docling's real options, read once per test session (and kept between sessions for the same
    Docling): the tests check Studio against the CLI that's installed, not a copy of it."""
    fingerprint = cli_schema._fingerprint()
    try:
        cached = json.loads(SCHEMA_CACHE.read_text())
        if cached.get("fingerprint") == fingerprint:
            return cached
    except (OSError, ValueError):
        pass
    data = {"fingerprint": fingerprint, **cli_schema.introspect()}
    SCHEMA_CACHE.write_text(json.dumps(data))
    return data


@pytest.fixture(autouse=True)
def studio_home(tmp_path, monkeypatch, docling_schema):
    home = tmp_path / "studio"
    monkeypatch.setenv(brand.HOME_ENV, str(home))
    monkeypatch.setattr(cli_schema, "_memory", docling_schema)
    return home


@pytest.fixture(autouse=True)
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


# Stands in for a Docling CLI: prints its arguments and the service variables, writes what
# `docling convert` would for each source, and can fail or take its time.
FAKE_DOCLING = textwrap.dedent(
    """\
    import json, os, sys, time
    from conftest_document import sample_document
    from pathlib import Path
    args = sys.argv[1:]
    print("args:", " ".join(args), flush=True)
    print("service:", os.environ.get("DOCLING_SERVICE_URL"), os.environ.get("DOCLING_SERVICE_API_KEY"), flush=True)
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    out = Path(args[args.index("--output") + 1]) if "--output" in args else Path.cwd()
    sources = [a for a in args[1:] if Path(a).is_file()]
    for src in sources:
        stem = Path(src).stem
        (out / f"{stem}.json").write_text(json.dumps(sample_document(stem)))
        (out / f"{stem}.md").write_text("# " + stem)
        (out / f"{stem}.txt").write_text(stem)
        (out / "debug" / f"debug_{stem}").mkdir(parents=True, exist_ok=True)
        (out / "debug" / f"debug_{stem}" / "layout_page_1.png").write_bytes(b"png")
        print(f"INFO docling.document_converter: Finished converting document {Path(src).name} in 0.10 sec.", flush=True)
    if os.environ.get("FAKE_FAIL"):
        print("ERROR: could not convert", flush=True)
        sys.exit(2)
    print(f"Processed {len(sources)} docs, of which 0 failed", flush=True)
    """
)


@pytest.fixture
def fake_docling(tmp_path, monkeypatch):
    script = tmp_path / "fake_docling.py"
    script.write_text(FAKE_DOCLING)
    monkeypatch.setattr("docling_studio.runs.RunManager.command", staticmethod(lambda tool, args: [sys.executable, str(script), *args]))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))  # the fake's sample document
    return script


@pytest.fixture
def client():
    from docling_studio.app import COOKIE, create_app

    app = create_app()
    with TestClient(app, base_url=BASE) as c:
        c.cookies.set(COOKIE, app.state.token)
        c.app_token = app.state.token
        yield c


@pytest.fixture
def pdf(tmp_path) -> Path:
    path = tmp_path / "docs" / "report.pdf"
    path.parent.mkdir()
    path.write_bytes(b"%PDF-1.4 test")
    return path
