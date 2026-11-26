"""Running Docling on a test-set document, with an experiment's conversion settings, and keeping the result.

Conversion is the slow part (seconds a page); mapping fields is instant. So Docling's result is
cached per document and per conversion settings (cache/<conv>/<doc>.json): experiments that only
change the mapping, or re-run after a mapper change, reuse it.
"""

import hashlib
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

from . import store

OCR_ENGINES = {"auto": "Docling's choice", "rapidocr": "RapidOCR", "paddleocr": "PaddleOCR (PP-OCRv6 medium, English)",
               "easyocr": "EasyOCR", "ocrmac": "Apple Vision (Mac)", "tesseract": "Tesseract"}
DEFAULTS = {
    "extractor": "rules",       # rules: Docling + the mapper (extract.py) | vlm: DocumentExtractor
    "ocr": "auto",              # auto: OCR where there's no text layer | off | full: OCR every page
    "ocr_engine": "auto",
    "table_mode": "accurate",   # TableFormer: accurate | fast
    "straighten": True,         # turn sideways / upside-down scans upright first (orient.py)
    "vlm_model": "nuextract",   # vlm only: nuextract (NuExtract 2.0 2B) | granite_vision
}
CHOICES = {"extractor": ["rules", "vlm"], "ocr": ["auto", "off", "full"], "ocr_engine": list(OCR_ENGINES),
           "table_mode": ["accurate", "fast"], "straighten": [True, False], "vlm_model": ["nuextract", "granite_vision"]}
CONVERSION_KEYS = ("ocr", "ocr_engine", "table_mode", "straighten")


def check_config(config: dict) -> dict:
    out = dict(DEFAULTS)
    for key, value in (config or {}).items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key}")
        if value not in CHOICES[key]:
            raise ValueError(f"{key} can't be {value!r}.")
        out[key] = value
    return out


def conversion_key(config: dict) -> str:
    """Which cache a configuration's conversions go in: its conversion settings and Docling's version."""
    if config["extractor"] == "vlm":
        basis = {"vlm": config["vlm_model"], "straighten": config["straighten"], "docling": version("docling")}
    else:
        basis = {k: config[k] for k in CONVERSION_KEYS} | {"docling": version("docling"), "cells": 1}
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:10]


# Straightening --------------------------------------------------------------------------------


def page_images(path: Path, dpi: int = 200):
    """A document's pages as pictures."""
    from PIL import Image, ImageOps

    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        try:
            for page in pdf:
                yield page.render(scale=dpi / 72).to_pil().convert("RGB")
        finally:
            pdf.close()
    else:
        with Image.open(path) as img:
            yield ImageOps.exif_transpose(img).convert("RGB")


def orientation(doc: dict) -> list[int]:
    """How far each page of a scan has to turn (cached in orient/<doc>.json)."""
    cached = store.read_json(store.path("orient", doc["id"] + ".json"), None)
    if cached is not None:
        return cached["angles"]
    from . import orient

    angles = [orient.detect(img) for img in page_images(store.path("files", doc["file"]), dpi=150)]
    store.write_json(store.path("orient", doc["id"] + ".json"), {"angles": angles})
    return angles


def straightened(doc: dict, work: Path) -> Path:
    """The document to give Docling: the file itself, or for a turned scan an upright copy."""
    source = store.path("files", doc["file"])
    if doc.get("kind") == "digital":
        return source
    angles = orientation(doc)
    if not any(angles):
        return source
    pages = [img.rotate(angle, expand=True) if angle else img for img, angle in zip(page_images(source), angles)]
    target = work / (doc["id"] + ".pdf")
    pages[0].save(target, save_all=True, append_images=pages[1:], resolution=200)
    return target


# Docling ---------------------------------------------------------------------------------------


def _ocr_options(engine: str, full: bool):
    from docling.datamodel import pipeline_options as po

    if engine == "paddleocr":
        # RapidOCR already runs PaddleOCR's PP-OCR models (as ONNX), but by default the small Chinese
        # recogniser; this is PaddleOCR set up for these documents: English, the larger model.
        return po.RapidOcrOptions(force_full_page_ocr=full, lang=["en"], model_size="medium")
    cls = {"auto": po.OcrAutoOptions, "rapidocr": po.RapidOcrOptions, "easyocr": po.EasyOcrOptions,
           "ocrmac": po.OcrMacOptions, "tesseract": po.TesseractCliOcrOptions}[engine]
    return cls(force_full_page_ocr=full)


def converter(config: dict):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    # parsed pages: the text-line cells (PDF text or OCR), kept for the mapper (see run_docling)
    opts = PdfPipelineOptions(do_ocr=config["ocr"] != "off", do_table_structure=True, generate_parsed_pages=True)
    if config["ocr"] != "off":
        opts.ocr_options = _ocr_options(config["ocr_engine"], config["ocr"] == "full")
    opts.table_structure_options.mode = TableFormerMode.ACCURATE if config["table_mode"] == "accurate" else TableFormerMode.FAST
    opts.table_structure_options.do_cell_matching = True
    return DocumentConverter(allowed_formats=[InputFormat.PDF, InputFormat.IMAGE],
                             format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
                                             InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts)})


def cache_path(conv: str, doc_id: str, part: str = "") -> Path:
    return store.path("cache", conv, doc_id + (f".{part}" if part else "") + ".json")


def run_docling(source: Path, converter) -> tuple[object, list]:
    """Docling's document, and every page's text-line cells: [page, text, left, top, right, bottom]
    (top-left origin, the page's own units). The document merges lines into paragraphs, which on a
    scan can run a whole header block (labels and values) together; the cells keep each line where
    it is."""
    result = converter.convert(source, raises_on_error=True)
    cells = []
    # the document numbers pages from 1; Page.page_no has counted from 0 in some versions
    base = 1 if result.pages and min(p.page_no for p in result.pages) == 0 else 0
    for page in result.pages:
        if page.parsed_page is None or page.size is None:
            continue
        for cell in page.cells:
            text = (cell.text or "").strip()
            if not text:
                continue
            bb = cell.rect.to_bounding_box().to_top_left_origin(page_height=page.size.height)
            cells.append([page.page_no + base, text, round(bb.l, 2), round(bb.t, 2), round(bb.r, 2), round(bb.b, 2)])
    return result.document, cells


def load_cached(conv: str, doc_id: str):
    """(DoclingDocument, cells) from the cache, or None."""
    from docling_core.types.doc import DoclingDocument

    path = cache_path(conv, doc_id)
    if not path.exists():
        return None
    return DoclingDocument.load_from_json(path), store.read_json(cache_path(conv, doc_id, "cells"), [])


def convert(doc: dict, config: dict, conv: str, make_converter) -> tuple[object, list, bool]:
    """(DoclingDocument, text-line cells, whether it came from the cache)."""
    cached = load_cached(conv, doc["id"])
    if cached:
        return *cached, True
    with tempfile.TemporaryDirectory(dir=store.root()) as work:
        source = straightened(doc, Path(work)) if config["straighten"] else store.path("files", doc["file"])
        document, cells = run_docling(source, make_converter())
    path = cache_path(conv, doc["id"])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store.write_json(cache_path(conv, doc["id"], "cells"), cells)
    document.save_as_json(path)  # written last: its presence means the entry is complete
    return document, cells, False


# VLM extraction ---------------------------------------------------------------------------------


def vlm_template():
    """The template DocumentExtractor fills: our schema as a Pydantic model."""
    from typing import Optional

    from pydantic import BaseModel, Field

    class Line(BaseModel):
        item_code: Optional[str] = Field(None, description="Item or article code")
        barcode: Optional[str] = Field(None, description="Barcode (EAN), 8-14 digits")
        description: Optional[str] = Field(None, description="Item description")
        uom: Optional[str] = Field(None, description="Unit of measure, e.g. PCS, CTN")
        quantity: Optional[float] = Field(None, description="Quantity ordered or received")
        unit_price: Optional[float] = Field(None, description="Price of one unit")
        amount: Optional[float] = Field(None, description="Line total")

    class Lpo(BaseModel):
        document_type: Optional[str] = Field(None, description="purchase_order, goods_received_note, invoice, delivery_note, credit_note or other")
        lpo_number: Optional[str] = Field(None, description="LPO / purchase order number")
        order_date: Optional[str] = Field(None, description="Order date")
        delivery_date: Optional[str] = Field(None, description="Delivery date")
        buyer: Optional[str] = Field(None, description="The company placing the order (the retailer)")
        store: Optional[str] = Field(None, description="Store, branch or ship-to location")
        supplier: Optional[str] = Field(None, description="The supplier the order is placed with")
        currency: Optional[str] = Field(None, description="Currency code, e.g. KES")
        subtotal: Optional[float] = Field(None, description="Total before VAT")
        vat: Optional[float] = Field(None, description="VAT amount")
        total: Optional[float] = Field(None, description="Order total")
        lines: list[Line] = Field(default_factory=list, description="Line items")

    return Lpo


def extractor(config: dict):
    from docling.datamodel import vlm_model_specs
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import VlmExtractionPipelineOptions
    from docling.document_extractor import DocumentExtractor, ExtractionFormatOption

    opts = VlmExtractionPipelineOptions()
    if config["vlm_model"] == "granite_vision":
        from docling.datamodel.pipeline_options import ExtractionPromptStyle

        opts.vlm_options = vlm_model_specs.GRANITE_VISION_4_1_TRANSFORMERS
        opts.extraction_prompt_style = ExtractionPromptStyle.GRANITE_VISION
    from docling.pipeline.extraction_vlm_pipeline import ExtractionVlmPipeline

    option = ExtractionFormatOption(pipeline_cls=ExtractionVlmPipeline, pipeline_options=opts)
    return DocumentExtractor(allowed_formats=[InputFormat.PDF, InputFormat.IMAGE],
                             extraction_format_options={InputFormat.PDF: option, InputFormat.IMAGE: option})


def vlm_extract(doc: dict, config: dict, conv: str, make_extractor) -> tuple[dict, bool]:
    """(the extractor's answer merged across pages, whether it came from the cache)."""
    cached = cache_path(conv, doc["id"])
    if cached.exists():
        return store.read_json(cached, {}), True
    with tempfile.TemporaryDirectory(dir=store.root()) as work:
        source = straightened(doc, Path(work)) if config["straighten"] else store.path("files", doc["file"])
        result = make_extractor().extract(source=source, template=vlm_template())
    merged: dict = {"lines": []}
    for page in result.pages:
        data = page.extracted_data or {}
        for key, value in data.items():
            if key == "lines":
                merged["lines"] += [x for x in value or [] if isinstance(x, dict)]
            elif merged.get(key) in (None, "") and value not in (None, ""):
                merged[key] = value
    store.write_json(cached, merged)
    return merged, False
