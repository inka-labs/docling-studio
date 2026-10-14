# Paperlift (working name): the `consumer` branch

A private desktop document converter for everyday users, built on Docling Studio. You drop in PDFs,
scans or Office files, choose **Word, Excel, Markdown, plain text or a web page**, and press Convert.
The files land in `~/Documents/Paperlift`, and nothing leaves the computer.

`main` stays Docling Studio, the power tool. This branch adds the everyday app on top, and the whole
of Docling Studio is still available in it under **Settings → Advanced mode**.

## What's in it

| | |
|---|---|
| One-screen converter | `frontend/src/simple/Home.tsx`: drop or choose files (the computer's own Open dialog), a folder or a web address. Choose formats, with optional scanned-page, language, pages and pictures settings. Choices are remembered. |
| Word and Excel | `backend/docling_studio/exporters.py`: Docling has neither, so these are written from its JSON with python-docx and openpyxl (both MIT). Word gets headings, lists, merged-cell tables, pictures, captions and AI picture descriptions. Excel gets a sheet per table, with real numbers. |
| Jobs | `simple.py` maps the few choices to Docling options, then saves the finished files without overwriting anything. Progress is in plain words, including the first-run model download. |
| Results | Open in Word or Excel, Show in folder, an in-app preview, and friendly error messages with the log behind "Details". |
| Pricing hook | `entitlements.py`: one `plan()` and the features a free plan could leave out (batch, folders, Word, Excel, AI picture descriptions, Advanced mode). It's checked on the server and shown in the UI. Everything is on ("Preview") until pricing is decided. |
| Name in one place | `backend/docling_studio/brand.py` and `frontend/src/brand.ts`. The app has its own folder (`~/.paperlift`), keychain entry and port (8767), so it can sit next to Docling Studio. |
| Licences | `packaging/notices.py` writes `THIRD_PARTY_NOTICES.md` from the actual environment at each release, and the release zips include it. |

## Before charging money

1. **Name.** "Paperlift" is a placeholder. Check trademarks, the .com and app-store names, then change
   `brand.py`, `brand.ts` and the installers (`packaging/`). Don't put "Docling" in the product
   name: it's an LF AI & Data project, so say "powered by Docling" instead.
2. **Licences, the items `THIRD_PARTY_NOTICES.md` flags:**
   - **readline (GPL-3.0)** comes in through conda's Python on macOS and Linux. It is the one to fix. Either use a
     Python built against libedit, or get legal advice on shipping it as is.
   - **python-bidi and soxr (LGPL)** come with EasyOCR and audio. Using them as unmodified Python packages is
     normally fine, but the notices must say so. Dropping the audio and EasyOCR extras removes them.
   - **certifi and tqdm (MPL-2.0)** are fine unmodified.
   - **saxonche** is only used for DocLang validation in Advanced mode. Drop it from the paid build if in doubt.
   - **The models** used by default are Apache-2.0 or CDLA-Permissive-2.0, so commercial use is allowed. Some VLM presets in Advanced
     mode are under other licences, so keep Advanced mode's VLM presets out of what's marketed, or check each one.
3. **Signing.** Unsigned installers trigger macOS Gatekeeper and Windows SmartScreen warnings, and most paying
   customers stop there. You need an Apple Developer ID with notarisation ($99/yr) and a Windows code-signing
   certificate.
4. **Payments.** Decide the model (see `entitlements.py`). A merchant-of-record store such as Lemon Squeezy or
   Paddle handles tax and gives license keys; `plan()` would check the key and cache the result for offline use.
5. **A real app window.** It currently opens in the browser. For a product, wrap it in a native window
   (pywebview or Tauri) with a dock icon and a menu.
6. **Smaller download.** The full Docling stack is about 2 GB. A product build could drop the VLM, audio and
   video extras (keeping layout, tables and OCR), which would roughly halve it.
7. **Updates.** Port Ecoscope Studio's in-app *Update now* (`selfupdate.py`); the installers already accept the
   unattended flag.
8. **Support basics.** A website, a privacy statement ("your documents never leave your computer"), an
   end-user licence agreement, and an e-mail address for help.
