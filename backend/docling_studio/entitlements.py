"""What this copy of the app may do: the one place a paid plan plugs in.

Pricing isn't decided yet, so everything is on ("Preview"). When it is, plan() reads the license
(a key checked with the store, cached for offline use), and the features below decide what the
free plan leaves out. The UI asks /api/plan and shows locked features as such; simple.py calls
require() before starting a job, so the check isn't only in the browser.
"""

FEATURES = {
    "batch": "Convert more than one document at a time",
    "folders": "Convert every document in a folder",
    "word": "Save as Word",
    "excel": "Save tables as Excel",
    "csv": "Save tables as CSV",
    "describe_pictures": "Describe pictures with AI",
    "advanced": "Advanced mode: every Docling option",
}


class NotAllowed(Exception):
    def __init__(self, feature: str):
        super().__init__(f"{FEATURES.get(feature, feature)} isn't part of your plan.")
        self.feature = feature


def plan() -> dict:
    return {"name": "Preview", "paid": False, "features": {key: True for key in FEATURES},
            "message": "Everything is included while the app is in preview."}


def allowed(feature: str) -> bool:
    return plan()["features"].get(feature, False)


def require(feature: str) -> None:
    if not allowed(feature):
        raise NotAllowed(feature)
