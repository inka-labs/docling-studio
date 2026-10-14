"""A small Docling document, made with docling-core itself so it's exactly what Docling writes: a
heading, a paragraph, a bullet and a numbered list, a table with a merged header and numbers, a
picture with a caption and a description, text Docling read inside the picture, and a page footer
(furniture, left out of Word). Used by the fake Docling and the exporter tests."""


def sample_document(name: str = "report") -> dict:
    from docling_core.types.doc import (
        ContentLayer, DocItemLabel, DoclingDocument, ImageRef, ProvenanceItem, TableCell, TableData,
    )
    from docling_core.types.doc.base import BoundingBox, Size
    from PIL import Image

    def prov(page: int) -> ProvenanceItem:
        return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=10, b=10), charspan=(0, 0))

    doc = DoclingDocument(name=name)
    for page in (1, 2, 3):
        doc.add_page(page_no=page, size=Size(width=600, height=800))
    doc.add_heading("Annual report", level=1)
    doc.add_text(label=DocItemLabel.TEXT, text="Revenue grew in every region.")
    group = doc.add_list_group()
    doc.add_list_item("North", parent=group, enumerated=False, marker="-")
    doc.add_list_item("South", parent=group, enumerated=True, marker="(2)")

    def cell(text, r, c, cols=1, header=False):
        return TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1, start_col_offset_idx=c,
                         end_col_offset_idx=c + cols, col_span=cols, column_header=header)

    cells = [cell("Region", 0, 0, header=True), cell("Revenue", 0, 1, cols=2, header=True),
             cell("North", 1, 0), cell("1,234", 1, 1), cell("5.5", 1, 2)]
    doc.add_table(data=TableData(num_rows=2, num_cols=3, table_cells=cells), prov=prov(2))

    caption = doc.add_text(label=DocItemLabel.CAPTION, text="Figure 1: Growth")
    picture = doc.add_picture(image=ImageRef.from_pil(Image.new("RGB", (4, 4), (40, 80, 200)), dpi=72),
                              caption=caption, prov=prov(3))
    doc.add_text(label=DocItemLabel.TEXT, text="words inside the chart", parent=picture)
    doc.add_text(label=DocItemLabel.PAGE_FOOTER, text="Page 1 of 9", content_layer=ContentLayer.FURNITURE)

    data = doc.export_to_dict()
    # what picture description (enrichment) adds
    data["pictures"][0]["annotations"] = [{"kind": "description", "text": "A bar chart of revenue.", "provenance": "test"}]
    return data
