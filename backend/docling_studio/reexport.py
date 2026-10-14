"""Docling's Markdown, text and HTML from a document it already converted (its JSON), written
the way `docling convert` writes them, so a saved conversion can be saved as another format without
reading the original again. Run in a subprocess (simple.py), as it imports docling-core:

    python -m docling_studio.reexport <document.json> <out dir> <embedded|placeholder> md text html
"""

import sys
from pathlib import Path

EXTENSIONS = {"md": ".md", "text": ".txt", "html": ".html"}


def main() -> None:
    from docling_core.types.doc import DoclingDocument, ImageRefMode

    source, out_dir, image_mode, *kinds = sys.argv[1:]
    doc = DoclingDocument.load_from_json(Path(source))
    mode = ImageRefMode.EMBEDDED if image_mode == "embedded" else ImageRefMode.PLACEHOLDER
    out = Path(out_dir)
    for kind in kinds:
        target = out / f"{Path(source).stem}{EXTENSIONS[kind]}"
        if kind == "md":
            doc.save_as_markdown(filename=target, image_mode=mode)
        elif kind == "html":
            doc.save_as_html(filename=target, image_mode=mode, split_page_view=False)
        elif kind == "text":
            target.write_text(doc.export_to_text(), encoding="utf-8")
        print(target)


if __name__ == "__main__":
    main()
