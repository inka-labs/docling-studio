"""Write THIRD_PARTY_NOTICES.md: every package in the app's environment with its licence, and the
models Docling downloads. Run by build_release.py (so each release lists exactly what it ships), or:

    pixi run python packaging/notices.py

Licences that need a closer look before selling (copyleft, or none found) are listed first.
"""

import re
import sys
from importlib.metadata import distributions
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from docling_studio import brand  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "THIRD_PARTY_NOTICES.md"
# The models the everyday converter uses, and their licences (checked on Hugging Face, 2026-10).
MODELS = [
    ("docling-project/docling-layout-heron", "Layout analysis", "Apache-2.0"),
    ("docling-project/docling-models (TableFormer)", "Table structure", "CDLA-Permissive-2.0"),
    ("RapidOCR (PP-OCR models)", "Reading text in images", "Apache-2.0"),
    ("docling-project/DocumentFigureClassifier-v2.0", "Picture classes (when on)", "Apache-2.0"),
    ("docling-project/CodeFormulaV2", "Code and formulas (when on)", "CDLA-Permissive-2.0"),
    ("HuggingFaceTB/SmolVLM-256M-Instruct", "Picture descriptions (when on)", "Apache-2.0"),
    ("ibm-granite/granite-docling-258M", "VLM pipeline (Advanced mode)", "Apache-2.0"),
]
CHECK = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|CDDL|SSPL|CC-BY-NC|Commons Clause)", re.I)


def licence(dist) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c not in ("OSI Approved",)]
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0][:80] if text and text.upper() != "UNKNOWN" else "not stated"


def conda_packages() -> list[tuple[str, str, str]]:
    """The conda packages in the environment (Python itself, OpenSSL, libraries…), from conda-meta."""
    import json

    found = []
    for meta in (Path(sys.prefix) / "conda-meta").glob("*.json"):
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        if data.get("name") in ("pytest", "nodejs"):  # for building and testing, not shipped at run time
            continue
        found.append((data.get("name", meta.stem), data.get("version", ""), data.get("license") or "not stated"))
    return found


def main() -> None:
    rows = sorted({(d.metadata["Name"], d.version, licence(d)) for d in distributions()
                   if d.metadata["Name"] and d.metadata["Name"] != "docling-studio"}, key=lambda r: r[0].lower())
    conda = conda_packages()
    rows += [r for r in conda if r[0].lower() not in {n.lower() for n, _, _ in rows}]
    rows.sort(key=lambda r: r[0].lower())
    look = [r for r in rows if CHECK.search(r[2]) or r[2] == "not stated"]
    lines = [
        f"# Third-party notices for {brand.NAME}",
        "",
        f"{brand.NAME} converts documents with [Docling](https://github.com/docling-project/docling) (MIT licence),",
        "and includes the open-source software listed below, each under its own licence.",
        "",
        "## Models",
        "",
        "Docling downloads these the first time they are needed.",
        "",
        "| Model | Used for | Licence |",
        "|---|---|---|",
        *[f"| {m} | {u} | {lic} |" for m, u, lic in MODELS],
        "",
    ]
    if look:
        lines += ["## To check before selling", "",
                  "Copyleft licences, or packages whose licence wasn't stated in their metadata:", "",
                  "| Package | Version | Licence |", "|---|---|---|", *[f"| {n} | {v} | {lic} |" for n, v, lic in look], ""]
    lines += ["## Packages", "", "| Package | Version | Licence |", "|---|---|---|",
              *[f"| {n} | {v} | {lic} |" for n, v, lic in rows], ""]
    OUT.write_text("\n".join(lines))
    print(f"{OUT.name}: {len(rows)} packages, {len(look)} to check")


if __name__ == "__main__":
    main()
