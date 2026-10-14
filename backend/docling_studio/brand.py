"""The product's name and where it lives, in one place.

"DocuFlow" is a working name only. It's already the name of SayApps, Inc.'s product at docu-flow.ai,
so it must change before the app is sold or published. Change it here, in frontend/src/brand.ts and
in packaging/ (the installers).

Its own folder, keychain entry and port keep it apart from Docling Studio on the same computer.
"""

NAME = "DocuFlow"
SLUG = "docuflow"  # folders, keychain entries, service names
HOME_DIR = ".docuflow"  # in the user's home folder; DOCUFLOW_HOME overrides it
HOME_ENV = "DOCUFLOW_HOME"
PORT_ENV = "DOCUFLOW_PORT"
PORT = 8767
BUNDLE_ID = "app.docuflow.desktop"
TAGLINE = "Turn PDFs and scans into Word, Excel and text, privately on your computer."
