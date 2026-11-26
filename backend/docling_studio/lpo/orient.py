"""Standing a scanned page upright before Docling reads it.

Phone photos and scanner feeds of LPOs often come in sideways or upside down. Docling's layout and
table models expect upright pages, and only its Tesseract engine detects orientation (and then only
for the OCR, not the layout). So scans are turned here first:

1. RapidOCR's text detector finds the text boxes. Lines of text are long and thin: if most boxes
   are taller than they are wide, the page is on its side (90 or 270), otherwise it's 0 or 180.
2. RapidOCR's recogniser reads the longest boxes both ways round; the way it reads with more
   confidence is upright.

Pixel-profile methods were tried first and misread table-heavy pages; this costs a few seconds a
page, so it only runs on pages without a text layer.
"""

import numpy as np
from PIL import Image

_engine = None


def _ocr():
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR

        _engine = RapidOCR(params={"Global.log_level": "error"})
    return _engine


def _score(img: Image.Image) -> float:
    out = _ocr()(np.asarray(img.convert("RGB")), use_det=False, use_cls=False, use_rec=True)
    txts, scores = out.txts or (), out.scores or ()
    return float(sum(len(t.strip()) * s for t, s in zip(txts, scores)))


def detect(page: Image.Image, max_side: int = 1600, samples: int = 8) -> int:
    """How far to turn the page (PIL's Image.rotate, counter-clockwise) to stand it upright: 0, 90, 180 or 270."""
    img = page.convert("RGB")
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    det = _ocr()(np.asarray(img), use_det=True, use_cls=False, use_rec=False)
    boxes = [] if det.boxes is None else list(det.boxes)
    shapes = []
    for b in boxes:
        w = float(np.linalg.norm(b[1] - b[0]))
        h = float(np.linalg.norm(b[3] - b[0]))
        if max(w, h) > 2.5 * min(w, h):  # a line of text, not a stamp or a digit
            shapes.append((w, h, b))
    if not shapes:
        return 0
    tall = sum(h > w for w, h, _ in shapes)
    sideways = tall > len(shapes) - tall
    # the longest lines read most reliably
    shapes.sort(key=lambda s: max(s[0], s[1]), reverse=True)
    a = b = 0.0
    for w, h, quad in shapes[:samples]:
        xs, ys = quad[:, 0], quad[:, 1]
        crop = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
        if sideways:
            a += _score(crop.rotate(90, expand=True))
            b += _score(crop.rotate(270, expand=True))
        else:
            a += _score(crop)
            b += _score(crop.rotate(180, expand=True))
    if sideways:
        return 90 if a >= b else 270
    return 0 if a >= b else 180
