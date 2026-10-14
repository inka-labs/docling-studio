"""Word and Excel files from a Docling document (its JSON), for people who want a .docx or .xlsx
rather than Markdown. Docling has no writer for either, so these walk the document in reading
order themselves, with python-docx and openpyxl (both MIT, both already Docling dependencies).

Word gets the body only: headings at their level, paragraphs, lists (with the original's markers),
tables (merged cells kept, header rows bold), pictures with their captions, code and formulas.
Page headers, footers and page numbers (Docling's "furniture") are left out, as in its Markdown.
Excel gets one sheet per table.
"""

import base64
import io
import json
import re
from pathlib import Path

MAX_PICTURE_INCHES = 6.0


class ExportError(Exception):
    pass


def load(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ExportError(f"Couldn't read {Path(path).name}: {e}")
    if doc.get("schema_name") != "DoclingDocument":
        raise ExportError(f"{Path(path).name} isn't a Docling document.")
    return doc


def _resolve(doc: dict, ref: str):
    node = doc
    for part in ref.lstrip("#/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node.get(part)
        if node is None:
            return None
    return node


def _children(doc: dict, node: dict) -> list[dict]:
    out = []
    for child in node.get("children") or []:
        item = _resolve(doc, child.get("$ref", "")) if isinstance(child, dict) else None
        if item is not None:
            out.append(item)
    return out


def _refs(items) -> set[str]:
    return {i.get("$ref") for i in items or [] if isinstance(i, dict)}


def _image_bytes(image: dict | None, base: Path) -> bytes | None:
    uri = (image or {}).get("uri") or ""
    if uri.startswith("data:"):
        try:
            return base64.b64decode(uri.split(",", 1)[1])
        except (IndexError, ValueError):
            return None
    if uri:
        for candidate in (Path(uri), base / uri, base.parent / uri):
            if candidate.is_file():
                return candidate.read_bytes()
    return None


def _table_cells(table: dict) -> tuple[int, int, list[dict]]:
    data = table.get("data") or {}
    return int(data.get("num_rows") or 0), int(data.get("num_cols") or 0), data.get("table_cells") or []


# Word ---------------------------------------------------------------------------------------------


def to_word(json_path: Path, out: Path) -> dict:
    """Write out (.docx). Returns what went in: headings, paragraphs, tables, pictures."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt

    doc = load(json_path)
    word = Document()
    word.core_properties.title = doc.get("name") or ""
    word.core_properties.comments = "Converted with Docling"
    styles = {s.name for s in word.styles}
    counts = {"headings": 0, "paragraphs": 0, "tables": 0, "pictures": 0}
    base = Path(json_path).parent

    def para(text: str, style: str | None = None):
        p = word.add_paragraph(style=style if style in styles else None)
        p.add_run(text)
        return p

    def table(item: dict):
        rows, cols, cells = _table_cells(item)
        if not rows or not cols:
            return
        t = word.add_table(rows=rows, cols=cols)
        if "Table Grid" in styles:
            t.style = "Table Grid"
        done: set[tuple[int, int]] = set()
        for cell in cells:
            r0, r1 = cell.get("start_row_offset_idx", 0), cell.get("end_row_offset_idx", 1)
            c0, c1 = cell.get("start_col_offset_idx", 0), cell.get("end_col_offset_idx", 1)
            if (r0, c0) in done or r0 >= rows or c0 >= cols:
                continue
            target = t.cell(r0, c0)
            if r1 - 1 > r0 or c1 - 1 > c0:
                target = target.merge(t.cell(min(r1, rows) - 1, min(c1, cols) - 1))
            done.update((r, c) for r in range(r0, r1) for c in range(c0, c1))
            target.text = cell.get("text", "")
            if cell.get("column_header") or cell.get("row_header"):
                for run in target.paragraphs[0].runs:
                    run.bold = True
        counts["tables"] += 1

    def picture(item: dict):
        data = _image_bytes(item.get("image"), base)
        if not data:
            return
        size = (item.get("image") or {}).get("size") or {}
        dpi = (item.get("image") or {}).get("dpi") or 72
        width = min(MAX_PICTURE_INCHES, (size.get("width") or 400) / dpi) or MAX_PICTURE_INCHES
        try:
            word.add_picture(io.BytesIO(data), width=Inches(width))
            word.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:  # noqa: BLE001 - an image Word can't take is left out, not the document
            return
        counts["pictures"] += 1
        description = _description(item)
        if description:
            p = para(description, "Caption")
            for run in p.runs:
                run.italic = True

    def text_item(item: dict, list_depth: int):
        label, text = item.get("label"), (item.get("text") or "").strip()
        if not text:
            return
        if label == "title":
            para(text, "Title")
            counts["headings"] += 1
        elif label == "section_header":
            level = max(1, min(int(item.get("level") or 1), 9))
            word.add_heading(text, level=level)
            counts["headings"] += 1
        elif label == "list_item":
            marker = (item.get("marker") or "").strip()
            if item.get("enumerated") or (marker and marker not in ("-", "•", "*", "·")):
                p = para(f"{marker} {text}" if marker else text, "List Paragraph")
            else:
                p = para(text, "List Bullet" if list_depth <= 1 else "List Bullet 2")
            counts["paragraphs"] += 1
            return p
        elif label == "caption":
            para(text, "Caption")
        elif label == "footnote":
            p = para(text)
            for run in p.runs:
                run.font.size = Pt(8)
        elif label == "code":
            p = para(text, "No Spacing")
            for run in p.runs:
                run.font.name = "Courier New"
                run.font.size = Pt(9)
        elif label == "formula":
            p = para(text)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.italic = True
        elif label in ("checkbox_selected", "checkbox_unselected"):
            para(("☒ " if label == "checkbox_selected" else "☐ ") + text)
        else:
            para(text)
            counts["paragraphs"] += 1

    def walk(node: dict, list_depth: int = 0):
        for item in _children(doc, node):
            if item.get("content_layer", "body") != "body":
                continue
            ref = item.get("self_ref", "")
            if ref.startswith("#/groups/"):
                if item.get("label") == "inline":
                    joined = " ".join((c.get("text") or "").strip() for c in _children(doc, item) if c.get("text"))
                    if joined:
                        para(joined)
                        counts["paragraphs"] += 1
                    continue
                walk(item, list_depth + 1 if item.get("label") in ("list", "ordered_list") else list_depth)
            elif ref.startswith("#/tables/") or ref.startswith("#/pictures/"):
                (table if ref.startswith("#/tables/") else picture)(item)
                # their captions and footnotes, not the text Docling read inside a picture
                keep = _refs(item.get("captions")) | _refs(item.get("footnotes"))
                for child in _children(doc, item):
                    if child.get("self_ref") in keep:
                        text_item(child, list_depth)
            elif ref.startswith("#/texts/"):
                text_item(item, list_depth)
                walk(item, list_depth)  # a list item's nested list

    walk(doc.get("body") or {})
    out.parent.mkdir(parents=True, exist_ok=True)
    word.save(out)
    return counts


def _description(picture: dict) -> str | None:
    """What picture description (enrichment) said about a picture, if it ran."""
    for ann in picture.get("annotations") or []:
        if ann.get("kind") == "description" and ann.get("text"):
            return ann["text"]
    meta = picture.get("meta") or {}
    desc = meta.get("description") if isinstance(meta, dict) else None
    return desc.get("text") if isinstance(desc, dict) else None


# Excel --------------------------------------------------------------------------------------------


def _number(text: str):
    """'1,234.5' -> 1234.5, so Excel can sum the column; anything else stays text."""
    t = text.strip()
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?|-?\d+(\.\d+)?", t):
        try:
            value = float(t.replace(",", ""))
            return int(value) if value.is_integer() and "." not in t else value
        except ValueError:
            pass
    return text


def to_excel(json_path: Path, out: Path) -> dict:
    """Write out (.xlsx), one sheet per table. Raises ExportError when there are no tables."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    doc = load(json_path)
    tables = [t for t in doc.get("tables", []) if t.get("content_layer", "body") == "body"]
    if not tables:
        raise ExportError("Docling found no tables in this document.")
    book = Workbook()
    book.remove(book.active)
    for n, item in enumerate(tables, 1):
        pages = sorted({p.get("page_no") for p in item.get("prov") or [] if p.get("page_no")})
        sheet = book.create_sheet(f"Table {n}" + (f" (p{pages[0]})" if pages else ""))
        rows, cols, cells = _table_cells(item)
        widths = [8] * max(cols, 1)
        for cell in cells:
            r0, r1 = cell.get("start_row_offset_idx", 0), cell.get("end_row_offset_idx", 1)
            c0, c1 = cell.get("start_col_offset_idx", 0), cell.get("end_col_offset_idx", 1)
            target = sheet.cell(row=r0 + 1, column=c0 + 1)
            if target.coordinate in sheet.merged_cells:
                continue
            text = cell.get("text", "")
            header = cell.get("column_header") or cell.get("row_header")
            target.value = text if header else _number(text)
            if header:
                target.font = Font(bold=True)
            target.alignment = Alignment(wrap_text=True, vertical="top")
            if r1 - r0 > 1 or c1 - c0 > 1:
                sheet.merge_cells(start_row=r0 + 1, start_column=c0 + 1, end_row=r1, end_column=c1)
            if c1 - c0 == 1 and c0 < len(widths):
                widths[c0] = min(60, max(widths[c0], len(text) + 2))
        for c, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(c)].width = width
        if rows and any(c.get("column_header") for c in cells):
            header_rows = max(c.get("end_row_offset_idx", 1) for c in cells if c.get("column_header"))
            sheet.freeze_panes = sheet.cell(row=header_rows + 1, column=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)
    return {"tables": len(tables)}
