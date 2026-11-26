"""Page pictures for the review screen, made once and kept in pages/<doc>/."""

from pathlib import Path

from . import store

WIDTH = 1400  # pixels across: enough to read a dot-matrix scan, small enough to load quickly


def page_count(doc: dict) -> int:
    return int(doc.get("pages") or 1)


def picture(doc: dict, number: int, straight: bool) -> Path:
    """Page `number` (1-based) as a PNG; turned upright when the scan's orientation is known."""
    if not 1 <= number <= page_count(doc):
        raise ValueError("No such page.")
    angles = (store.read_json(store.path("orient", doc["id"] + ".json"), {}) or {}).get("angles") or []
    angle = angles[number - 1] if straight and number - 1 < len(angles) else 0
    target = store.path("pages", doc["id"], f"{number}-{angle}.png")
    if target.exists():
        return target
    from PIL import Image, ImageOps

    source = store.path("files", doc["file"])
    if source.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        with store.PDFIUM:
            pdf = pdfium.PdfDocument(source)
            try:
                page = pdf[number - 1]
                w, h = page.get_size()
                img = page.render(scale=WIDTH / max(min(w, h), 1)).to_pil().convert("RGB")
            finally:
                pdf.close()
    else:
        with Image.open(source) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
    if angle:
        img = img.rotate(angle, expand=True)
    img.thumbnail((WIDTH * 2, WIDTH * 2))
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    part = target.with_suffix(".part.png")
    img.save(part, optimize=True)
    part.replace(target)
    return target
