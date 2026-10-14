"""The product's name and where it lives, in one place. "Paperlift" is a working name: check it's
free to use (trademarks, domains, app stores) before selling under it, then change it here, in
frontend/src/brand.ts and in packaging/ (build_release.py fills it into the installers).

Its own folder, keychain entry and port keep it apart from Docling Studio on the same computer.
"""

NAME = "Paperlift"
SLUG = "paperlift"  # folders, keychain entries, service names
HOME_DIR = ".paperlift"  # in the user's home folder; PAPERLIFT_HOME overrides it
HOME_ENV = "PAPERLIFT_HOME"
PORT_ENV = "PAPERLIFT_PORT"
PORT = 8767
BUNDLE_ID = "app.paperlift.desktop"
TAGLINE = "Turn PDFs and scans into Word, Excel and text, privately on your computer."
