# Docling Studio

A local, private UI for [Docling](https://docling.ai/)'s command-line tools: convert documents with every
option Docling has, then look through what it found. It's built the same way as Ecoscope Studio.

- **Every option, always current.** Studio reads Docling's CLIs when it starts (`introspect.py`), so each
  form has every option of the installed Docling, including ones added after Studio was written. Options
  are grouped into sections (Output, OCR, Tables, Enrichment, VLM pipeline, Audio & video…). An option
  that only matters with others set says so (*Used with --pipeline vlm*). Free-text options that list
  their values (OCR engine, VLM preset, layout engine…) offer them as suggestions.
- **All of Docling's tools:**

  | In Studio | Command |
  |---|---|
  | Convert | `docling convert`: PDF, Office, HTML, images, audio, video, e-mail, EPUB, LaTeX, XML… to Markdown, HTML, JSON, YAML, text, DocTags, DocLang, WebVTT, LaTeX, chunks |
  | Convert on a server | `docling convert-remote`, against a saved docling-serve service |
  | Download models / From Hugging Face | `docling-tools models download`, `download-hf-repo` |
  | Export a Docling document | `docling-serialize`: re-export a JSON result without converting again |
  | Validate / Pack DocLang | `doclang validate`, `doclang pack` |
  | A run's **Document** tab | what `docling-view` opens: each page beside its text |

- **Results you can read.** For each converted document, the run page has these tabs:
  - **Document**: the split page view.
  - **Markdown**: rendered, or as source.
  - **HTML**.
  - **Structure**: pages, and text by kind.
  - **Tables**: each extracted table, which you can copy or download as CSV.
  - **Pictures**: each picture with its caption, plus the picture classes and descriptions when enrichment is on.
  - **Chunks**: with token counts, headings and pages.
  - **Every other format as text**.
  - **Images**: page images, and the layout, OCR, cell and table debug images.
  - **Profiling**: time spent in each pipeline stage.
  - **Files**: every file, to download or show in the folder.
- **Inputs from anywhere:** drop files in, give a file or folder path on this computer (Docling reads it where it
  is), a web address, or a file an earlier run made.
- **Runs keep everything.** Each run keeps its command (copyable, exactly what you'd type), its live log,
  and its inputs and outputs. **Change and run again** reopens the form with the same settings and files.
  **Presets** save option sets by name. Runs queue (one at a time by default) and can be stopped.
- **Secrets stay secret.** PDF passwords and request headers are never saved with a run or a preset, and are
  blanked out of the command and the log. docling-serve API keys go into the system keychain and reach
  the CLI as environment variables, never on a command line.
- **Local only.** The server binds to 127.0.0.1 (port 8766, next to Ecoscope Studio's 8765). Every API call needs
  a session cookie set from a one-time link, and requests from other hosts or origins are refused.

## Install

**Easiest (Mac and Windows, no terminal):** download `Docling-Studio-<version>-mac.zip` or `-windows.zip`,
unzip it and double-click **Install Docling Studio**. See [packaging/](packaging/README.md) for building them.

**From the source:** you need [pixi](https://pixi.sh).

    cd docling-studio
    pixi run start

The first start installs Docling, PyTorch and the OCR/VLM/ASR extras (about 2 GB), then opens
<http://127.0.0.1:8766>. If it doesn't, use the sign-in link printed in the terminal. The first conversion
downloads Docling's models (**Models → Download models** does that ahead of time).

Supported: macOS 14+ on Apple silicon, Windows x64, Linux x64/arm64. Intel Macs aren't, because PyTorch
no longer ships for them. What's installed, and why, is in [pixi.toml](pixi.toml). Engines that need
something outside Python aren't bundled:
- **Tesseract** needs the `tesseract` program.
- **HTML rendering** needs Playwright's browser.
- **nemotron-ocr** is a separate install.

Install whichever you need into Studio's environment (`pixi add …`), and Settings lists Docling's plugins.

### Start at login, uninstall

    pixi run build-ui
    pixi run autostart install      # or: Settings → Start Docling Studio when I log in
    pixi run autostart uninstall

Studio keeps its runs, presets and settings in `~/.docling-studio` (delete it to start over). Service API keys are
keychain items under `docling-studio`. Docling's models are in `~/.cache/docling` and `~/.cache/huggingface`.

## Develop

    pixi run test          # backend tests (a stand-in for Docling, so they take seconds)
    pixi run serve         # the API on :8766
    pixi run dev-ui        # the UI with hot reload on :5174 (use the dev sign-in link `serve` prints)

| | |
|---|---|
| [introspect.py](backend/docling_studio/introspect.py) | reads the Docling CLIs' Typer apps into JSON (in a subprocess; the server never imports torch) |
| [cli_schema.py](backend/docling_studio/cli_schema.py) | the tools, sections, secrets and "used with" rules; form values → command line |
| [runs.py](backend/docling_studio/runs.py) | the queue, running a CLI (`runcli.py`), the log, redaction, outputs grouped per document |
| [docview.py](backend/docling_studio/docview.py) | reading a Docling JSON: summary, tables, pictures, the document view |
| [app.py](backend/docling_studio/app.py) | the HTTP API and its guard |
| [frontend/src/](frontend/src/) | React: `tools/ToolPage.tsx` (any tool's form), `form/FieldInput.tsx` (one option), `runs/Results.tsx` |

Docling quirks Studio works around:
- **Debug images:** Docling writes them to `./debug`, so a run works inside its own output folder.
- **Relative `--output`:** it nests referenced images one level too deep, so Studio always passes an absolute path.
- **`--to html` with `--to html_split_page`:** both write `<name>.html`, so the second overwrites the first.
- **`--show-external-plugins`:** this crashes in 2.138, so Settings lists the `docling` entry points itself.
