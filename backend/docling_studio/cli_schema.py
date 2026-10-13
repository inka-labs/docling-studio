"""What Studio can run: the Docling CLIs' commands, each a "tool" with a form, and how a form's
values become a command line.

The options come from Docling itself (introspect.py, run once per installed Docling version and
cached), so every option of the installed version is in the forms, including ones added after
Studio was written; they land in "Other options" until a rule below groups them. On top of that
this module adds what the CLI can't say about itself: which section an option belongs in, which
options Studio fills in (the sources, the output folder), which hold secrets, and when an option
matters (the VLM model only with --pipeline vlm).
"""

import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .core import settings
from .core.store import home, read_json, write_json


class SchemaError(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    id: str
    command: str  # as introspect.py keys it: "<program> <subcommand…>"
    title: str
    summary: str
    # how its positional arguments are filled: "sources" (many files, folders or URLs) or, per
    # argument name, "file" (one file: uploaded, on this computer, or from an earlier run)
    inputs: dict = field(default_factory=dict)
    # set by Studio, not shown in the form (the inputs are shown, in their own card)
    managed: frozenset = frozenset()
    # Studio's starting values where they differ from Docling's
    initial: dict = field(default_factory=dict)
    service: bool = False  # runs against a saved docling-serve service (services.py)


TOOLS = [
    Tool("convert", "docling convert", "Convert",
         "Convert documents on this computer: PDF, Word, PowerPoint, Excel, HTML, images, audio, video and more, "
         "to Markdown, HTML, JSON, chunks and other formats.",
         inputs={"source": "sources"},
         managed=frozenset({"output", "output_file", "version", "logo", "show_external_plugins", "quiet"}),
         initial={"to": ["md", "json"]}),
    Tool("convert-remote", "docling convert-remote", "Convert on a server",
         "Send documents to a docling-serve service and save what it returns here.",
         inputs={"source": "sources"},
         managed=frozenset({"output", "service_url", "api_key"}),
         initial={"to": ["md", "json"]}, service=True),
    Tool("models", "docling-tools models download", "Download models",
         "Fetch Docling's models ahead of time (layout, tables, OCR, VLMs…), e.g. for a computer that will run offline.",
         managed=frozenset({"quiet"})),
    Tool("hf-models", "docling-tools models download-hf-repo", "Download from Hugging Face",
         "Fetch any model from Hugging Face by its repository id into the models folder.",
         managed=frozenset({"quiet"})),
    Tool("serialize", "docling-serialize", "Export a Docling document",
         "Turn a Docling JSON or YAML document into HTML, Markdown, DocTags, DocLang, text or JSON, without converting again.",
         inputs={"source": "file"}, managed=frozenset({"output", "version"})),
    Tool("doclang-validate", "doclang validate", "Validate DocLang",
         "Check a DocLang XML document against the bundled XSD schema and Schematron rules.",
         inputs={"xml_file": "file"}, managed=frozenset({"quiet"})),
    Tool("doclang-pack", "doclang pack", "Pack DocLang",
         "Bundle a DocLang markup file with page images and assets into a .dclx archive.",
         inputs={"document": "file"}, managed=frozenset({"output", "quiet"})),
]
TOOLS_BY_ID = {t.id: t for t in TOOLS}
# docling-view isn't a tool: it opens a page in the browser, which Studio shows in the run instead.
SHOWN_IN_RUNS = {"docling-view": "Open any Docling JSON result and choose Document view."}

# Options whose value is a password, an API key or request headers (often an Authorization token):
# never saved with a run or in presets, and blanked out of the command shown and the log.
SECRETS = frozenset({"pdf_password", "api_key", "headers", "html_image_headers"})

# Sections, in order: the first rule matching an option's name places it.
SECTIONS = [
    ("output", "Output", r"^(to|image_export_mode|show_layout|split_page_view|embed_images|format|output_dir)$"),
    ("chunking", "Chunking", r"^chunks_"),
    ("input", "Input", r"^(from|page_range|pdf_backend|pdf_password|abort_on_error|document_timeout|timeout)$"),
    ("pipeline", "Pipeline & layout", r"^(pipeline|layout_engine|reading_order_separators)$"),
    ("ocr", "OCR", r"^(ocr|force_ocr|psm)$|^ocr_|^easyocr_|^rapidocr_"),
    ("tables", "Tables", r"^table"),
    ("enrichment", "Enrichment", r"^enrich_|^picture_|^chart_"),
    ("vlm", "VLM pipeline", r"^vlm_|_vlm_"),
    ("media", "Audio & video", r"^asr_|^video_"),
    ("web", "Web & HTML sources", r"^headers$|^html_image"),
    ("models", "Models & plugins", r"^(artifacts_path|enable_remote_services|allow_external_plugins|models|all|force)$"),
    ("service", "Service", r"^(max_concurrency|watcher)$"),
    ("contents", "Contents", r"^(pages|page|asset|assets)$"),
    ("checks", "Checks", r"^(validate|xsd_only|schematron_only|allow_empty_namespace)$"),
    ("performance", "Performance", r"^(device|num_threads|parser_threads|page_batch_size|release_native_memory)"),
    ("debug", "Debug & profiling", r"^debug_|profiling$|^verbose$"),
]
OTHER = ("other", "Other options")

# When an option matters: {option: {other option: values that make it matter}}. True = when that
# option is on. The form still shows the option, dimmed, with the condition.
WHEN = {
    "vlm_model": {"pipeline": ["vlm"]},
    "vlm_max_new_tokens": {"pipeline": ["vlm"]},
    "debug_vlm_native_output": {"pipeline": ["vlm"]},
    "parser_threads": {"pipeline": ["native"]},
    "chunks_type": {"to": ["chunks"]},
    "chunks_max_tokens": {"to": ["chunks"]},
    "chunks_tokenizer": {"to": ["chunks"], "chunks_type": ["hybrid"]},
    "ocr_mode": {"ocr": True},
    "ocr_engine": {"ocr": True},
    "ocr_lang": {"ocr": True},
    "psm": {"ocr": True, "ocr_engine": ["tesseract", "tesserocr"]},
    "table_mode": {"tables": True},
    "table_structure_engine": {"tables": True},
    "picture_description_max_new_tokens": {"enrich_picture_description": True},
    "chart_extraction_preset": {"enrich_chart_extraction": True},
    "html_image_headers_origin": {"html_image_headers": True},
    "video_frame_interval": {"video_sampling_mode": ["fixed"]},
    "video_cuts_per_minute": {"video_sampling_mode": ["scene"]},
    "video_prominence": {"video_sampling_mode": ["scene"]},
    "save_profiling": {"profiling": True},
}

LABELS = {
    "to": "Output formats", "from": "Input formats", "psm": "Tesseract page segmentation mode (PSM)",
    "ocr": "OCR", "force_ocr": "Force OCR", "page_range": "Pages", "show_layout": "Show layout boxes on page images",
    "models": "Models", "all": "All models", "page": "Page images", "pages": "Folder of page images",
    "asset": "Assets (ARCHIVE_PATH=SOURCE)", "assets": "Folder of assets", "validate": "Validate before packing", "num_threads": "Inference threads", "headers": "Request headers (JSON)",
    "html_image_headers": "Image request headers (JSON)", "verbose": "Log detail",
}
ACRONYMS = {"pdf": "PDF", "ocr": "OCR", "vlm": "VLM", "asr": "ASR", "html": "HTML", "url": "URL", "hf": "HF", "api": "API",
            "json": "JSON", "xsd": "XSD", "xml": "XML", "psm": "PSM", "easyocr": "EasyOCR", "rapidocr": "RapidOCR"}
# Values the help text lists for an option that takes any string ("Available presets: a, b").
LISTED = re.compile(r"(?:available values are|available presets)\s*:\s*([A-Za-z0-9_, .\-]+?)(?:\.\s|\.$|$)", re.I)

SCHEMA_VERSION = 2  # what introspect.py writes; a change reads the CLIs again
_cache_lock = threading.Lock()
_memory: dict | None = None


def _cache_path() -> Path:
    return home() / "cli-schema.json"


def _fingerprint() -> str:
    """Changes when the Docling packages in this environment do (an update reads the CLIs again)."""
    from importlib.metadata import PackageNotFoundError, version

    parts = [f"schema={SCHEMA_VERSION}"]
    for package in ("docling", "docling-slim", "docling-core", "doclang"):
        try:
            parts.append(f"{package}={version(package)}")
        except PackageNotFoundError:
            parts.append(f"{package}=-")
    return ";".join(parts)


def introspect() -> dict:
    proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "docling_studio.introspect"],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise SchemaError("Couldn't read Docling's options:\n" + (proc.stderr or proc.stdout)[-2000:])
    return json.loads(proc.stdout)


def raw(refresh: bool = False) -> dict:
    """Docling's commands and options, read once per installed version."""
    global _memory
    with _cache_lock:
        fingerprint = _fingerprint()
        if not refresh and _memory and _memory.get("fingerprint") == fingerprint:
            return _memory
        cached = read_json(_cache_path(), {})
        if refresh or cached.get("fingerprint") != fingerprint:
            cached = {"fingerprint": fingerprint, **introspect()}
            write_json(_cache_path(), cached)
        _memory = cached
        return cached


def warm() -> None:
    """At start-up, in the background: the first form opens straight away."""
    try:
        raw()
    except Exception:  # noqa: BLE001 - shown when a form asks for it
        pass


def label(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    words = [ACRONYMS.get(w, w) for w in name.split("_")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def section(name: str) -> tuple[str, str]:
    for key, title, pattern in SECTIONS:
        if re.search(pattern, name):
            return key, title
    return OTHER


def _suggestions(param: dict, commands: dict) -> list[str]:
    match = LISTED.search(param.get("help", ""))
    if match:
        return [v.strip() for v in match.group(1).split(",") if v.strip()]
    for command in commands.values():  # the same option elsewhere with a fixed list (--from)
        for other in command["params"]:
            if other["name"] == param["name"] and other.get("choices"):
                return other["choices"]
    return []


def field_for(tool: Tool, param: dict, commands: dict) -> dict:
    name = param["name"]
    out = {k: param[k] for k in ("name", "kind", "opts", "secondary_opts", "type", "multiple", "required", "default", "help", "is_flag", "count")}
    out["choices"] = param.get("choices")
    out["label"] = label(name)
    out["section"], out["section_title"] = ("input", "Input") if name in tool.inputs else section(name)
    out["secret"] = name in SECRETS
    out["when"] = WHEN.get(name)
    out["input"] = tool.inputs.get(name) if param["kind"] == "argument" else None
    if out["type"] == "string" and not out["choices"]:
        out["suggestions"] = _suggestions(param, commands)
    initial = tool.initial.get(name, param["default"])
    if name == "verbose" and param.get("count"):
        initial = settings.get()["default_verbosity"]
        out["type"], out["choices"] = "choice", ["0", "1", "2"]
        out["choice_labels"] = {"0": "Quiet (warnings only)", "1": "Info (-v)", "2": "Debug (-vv)"}
    if out["multiple"] and initial is None:
        initial = []
    out["initial"] = initial
    return out


def tool_schema(tool: Tool, data: dict | None = None) -> dict:
    data = data or raw()
    command = data["commands"].get(tool.command)
    if not command:
        error = data.get("errors", {}).get(tool.command.split()[0])
        return {"id": tool.id, "title": tool.title, "summary": tool.summary, "command": tool.command,
                "available": False, "error": error or f"This Docling has no `{tool.command}` command."}
    fields = [field_for(tool, p, data["commands"]) for p in command["params"]
              if p["name"] not in tool.managed and not p["hidden"] and p["name"] != "help"]
    order = [key for key, _, _ in SECTIONS] + [OTHER[0]]
    fields.sort(key=lambda f: (f["kind"] != "argument", order.index(f["section"])))
    return {"id": tool.id, "title": tool.title, "summary": tool.summary, "command": tool.command,
            "help": command["help"], "available": True, "service": tool.service, "fields": fields}


def schema(refresh: bool = False) -> dict:
    data = raw(refresh)
    return {"tools": [tool_schema(t, data) for t in TOOLS], "versions": data.get("versions", {}),
            "devices": data.get("devices", []), "errors": data.get("errors", {}),
            "elsewhere": SHOWN_IN_RUNS}


def get_tool(tool_id: str) -> Tool:
    if tool_id not in TOOLS_BY_ID:
        raise SchemaError(f"No such tool: {tool_id}")
    return TOOLS_BY_ID[tool_id]


def command_params(tool: Tool) -> dict[str, dict]:
    command = raw()["commands"].get(tool.command)
    if not command:
        raise SchemaError(f"This Docling has no `{tool.command}` command.")
    return {p["name"]: p for p in command["params"]}


# Turning values into a command line -----------------------------------------------------------


def _coerce(param: dict, value):
    """One value, checked against its option's type. Raises SchemaError with the option's flag."""
    flag = param["opts"][0]
    kind = param["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise SchemaError(f"{flag} is on or off.")
        return value
    if kind == "int" or param.get("count"):
        try:
            number = int(str(value).strip())
        except ValueError:
            raise SchemaError(f"{flag} takes a whole number.")
        for bound, ok in (("min", lambda b: number >= b), ("max", lambda b: number <= b)):
            if param.get(bound) is not None and not ok(param[bound]):
                raise SchemaError(f"{flag} must be between {param.get('min', '…')} and {param.get('max', '…')}.")
        return number
    if kind == "float":
        try:
            return float(str(value).strip())
        except ValueError:
            raise SchemaError(f"{flag} takes a number.")
    text = str(value)
    if "\n" in text or "\x00" in text:
        raise SchemaError(f"{flag} can't contain line breaks.")
    if kind == "choice" and param.get("choices") and text not in param["choices"]:
        raise SchemaError(f"{flag} must be one of: {', '.join(param['choices'])}.")
    return text


def _empty(value) -> bool:
    return value is None or value == "" or value == []


def _same(param: dict, value) -> bool:
    default = param["default"]
    if param["multiple"]:
        return list(value) == list(default or [])
    if default is None:
        return False
    if param["type"] in ("int", "float") or param.get("count"):
        try:
            return float(value) == float(default)
        except (TypeError, ValueError):
            return False
    return str(value) == str(default) if not isinstance(value, bool) else value == default


def option_args(tool: Tool, values: dict) -> list[str]:
    """The option flags for the form's values: only those that differ from Docling's defaults (so the
    command shown is the one you'd type), in the order Docling lists them."""
    params = command_params(tool)
    unknown = [k for k in values if k not in params or k in tool.managed]
    if unknown:
        raise SchemaError(f"{tool.command} has no option {', '.join(sorted(unknown))}.")
    args: list[str] = []
    for name, param in params.items():
        if param["kind"] != "option" or name not in values:
            continue
        value = values[name]
        if _empty(value) and not (param["type"] == "bool"):
            continue
        if param["multiple"]:
            items = [_coerce(param, v) for v in (value if isinstance(value, list) else [value]) if not _empty(v)]
            if _same(param, items):
                continue
            for item in items:
                args += [param["opts"][0], str(item)]
            continue
        value = _coerce(param, value)
        if _same(param, value):
            continue
        if param.get("count"):
            args += ["-" + "v" * value] if value > 0 and param["opts"][-1] == "-v" else [param["opts"][0]] * value
        elif param["type"] == "bool":
            if value:
                args.append(param["opts"][0])
            elif param["secondary_opts"]:
                args.append(param["secondary_opts"][0])
        else:
            args += [param["opts"][0], str(value)]
    return args


def argument_names(tool: Tool) -> list[str]:
    return [n for n, p in command_params(tool).items() if p["kind"] == "argument"]


def module_for(tool: Tool) -> str:
    from .introspect import APPS
    return APPS[tool.command.split()[0]]


def subcommand(tool: Tool) -> list[str]:
    return tool.command.split()[1:]


def secret_values(values: dict) -> list[str]:
    """The secret values in a form's values (to blank them out of what's shown and logged)."""
    found = []
    for name in SECRETS:
        value = values.get(name)
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, str) and v.strip():
                found.append(v)
                if name.endswith("headers"):  # also each header value on its own, as a client may log them
                    try:
                        found += [str(x) for x in json.loads(v).values() if str(x).strip()]
                    except (ValueError, AttributeError):
                        pass
    return sorted(set(found), key=len, reverse=True)


def without_secrets(values: dict) -> dict:
    return {k: v for k, v in values.items() if k not in SECRETS}
