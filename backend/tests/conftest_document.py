"""A small Docling document, shaped like Docling's JSON: a heading, a paragraph, a bullet and a
numbered list, a table with a merged header and numbers, a picture with a caption, and a page
footer (furniture, left out of Word). Used by the fake Docling and the exporter tests."""

import base64


def _png() -> str:
    """A small real PNG, base64."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 80, 200)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


PNG = _png()


def ref(path: str) -> dict:
    return {"$ref": path}


def cell(text, r, c, rows=1, cols=1, header=False):
    return {"text": text, "start_row_offset_idx": r, "end_row_offset_idx": r + rows, "start_col_offset_idx": c,
            "end_col_offset_idx": c + cols, "row_span": rows, "col_span": cols, "column_header": header, "row_header": False}


def sample_document(name: str = "report") -> dict:
    texts = [
        {"self_ref": "#/texts/0", "label": "section_header", "level": 1, "text": "Annual report", "content_layer": "body"},
        {"self_ref": "#/texts/1", "label": "text", "text": "Revenue grew in every region.", "content_layer": "body"},
        {"self_ref": "#/texts/2", "label": "list_item", "text": "North", "enumerated": False, "marker": "-", "content_layer": "body", "parent": ref("#/groups/0")},
        {"self_ref": "#/texts/3", "label": "list_item", "text": "South", "enumerated": True, "marker": "(2)", "content_layer": "body", "parent": ref("#/groups/0")},
        {"self_ref": "#/texts/4", "label": "caption", "text": "Figure 1: Growth", "content_layer": "body", "parent": ref("#/pictures/0")},
        {"self_ref": "#/texts/5", "label": "page_footer", "text": "Page 1 of 9", "content_layer": "furniture"},
        {"self_ref": "#/texts/6", "label": "text", "text": "words inside the chart", "content_layer": "body", "parent": ref("#/pictures/0")},
    ]
    table_cells = [cell("Region", 0, 0, header=True), cell("Revenue", 0, 1, cols=2, header=True),
                   cell("North", 1, 0), cell("1,234", 1, 1), cell("5.5", 1, 2)]
    return {
        "schema_name": "DoclingDocument", "version": "1.10.0", "name": name,
        "origin": {"mimetype": "application/pdf", "filename": f"{name}.pdf"},
        "body": {"self_ref": "#/body", "children": [ref("#/texts/0"), ref("#/texts/1"), ref("#/groups/0"), ref("#/tables/0"), ref("#/pictures/0")]},
        "furniture": {"self_ref": "#/furniture", "children": [ref("#/texts/5")]},
        "groups": [{"self_ref": "#/groups/0", "label": "list", "children": [ref("#/texts/2"), ref("#/texts/3")], "content_layer": "body"}],
        "texts": texts,
        "tables": [{"self_ref": "#/tables/0", "label": "table", "content_layer": "body", "prov": [{"page_no": 2}], "children": [], "captions": [],
                    "data": {"num_rows": 2, "num_cols": 3, "table_cells": table_cells, "grid": []}}],
        "pictures": [{"self_ref": "#/pictures/0", "label": "picture", "content_layer": "body", "prov": [{"page_no": 3}],
                      "children": [ref("#/texts/4"), ref("#/texts/6")], "captions": [ref("#/texts/4")],
                      "image": {"mimetype": "image/png", "dpi": 72, "size": {"width": 1, "height": 1}, "uri": f"data:image/png;base64,{PNG}"},
                      "annotations": [{"kind": "description", "text": "A bar chart of revenue."}]}],
        "key_value_items": [], "form_items": [], "pages": {"1": {"page_no": 1}},
    }
