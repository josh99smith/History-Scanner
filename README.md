# 📜 History Scanner

A document-scanning web app for **historical and handwritten documents**, built on
[datalab-to/marker](https://github.com/datalab-to/marker). Upload a scan (image or
PDF), and marker performs layout analysis + OCR and returns clean Markdown — with
optional **Claude LLM enhancement** that dramatically improves transcription of messy
handwriting and faded historical text.

<p align="center"><em>Drag in a scan → get back searchable, structured text.</em></p>

## Two editions

This repo contains **two** ways to run History Scanner:

1. **Browser edition (`docs/`) — hostable entirely on GitHub Pages.** A static single-page
   app that calls **Claude's vision API directly from your browser** to transcribe documents.
   No server, no Python, no marker — just open the page, paste your own Anthropic API key
   (stored only in your browser), and scan. Best for "all on GitHub Pages." See
   [Browser edition on GitHub Pages](#browser-edition-on-github-pages).
2. **Server edition (`app/`) — the marker-powered app** described below. Runs the full
   [marker](https://github.com/datalab-to/marker) pipeline locally/Docker for the highest-fidelity
   structured output (tables, layout, JSON), with optional Claude LLM enhancement.

Both target historical and handwritten documents — pick based on whether you want a
zero-infrastructure hosted page (browser edition) or maximum-fidelity local processing
(server edition).

## Features

- **Drag-and-drop web UI** — works from a desktop or phone browser.
- **Handwriting & historical OCR** via marker's surya models, with **Force OCR** for scans.
- **LLM enhancement with Claude** (`marker --use_llm`) to correct and clean transcriptions.
- **Multiple inputs**: PDF, JPG/PNG/TIFF/BMP/WEBP images, plus DOCX, PPTX, XLSX, EPUB, HTML.
- **Markdown / HTML / JSON** output, with extracted images and one-click download.
- **Async job queue** so long conversions don't block the browser; live progress.
- **Docker-first**, with a CPU image out of the box and a GPU profile for speed.

## How it works

```
Browser ──upload──▶ FastAPI (/api/scan) ──▶ Job queue ──▶ marker (surya + optional Claude)
   ▲                                                              │
   └────────────── poll /api/jobs/{id} ◀── Markdown + images ◀────┘
```

marker loads several deep-learning models (a few GB, downloaded on first run) and is
GPU-accelerated when one is available. The app loads those models once and runs
conversions on a bounded worker pool (one at a time by default, since each marker
worker wants ~5 GB of VRAM).

## Quick start (Docker — recommended)

```bash
git clone https://github.com/josh99smith/history-scanner.git
cd history-scanner
cp .env.example .env          # then add your ANTHROPIC_API_KEY
docker compose up --build
```

Open <http://localhost:8000>.

> The **first** scan downloads marker's models (several GB) — this is slow once, then
> cached on the `marker-models` Docker volume.

### GPU acceleration

The default image is CPU-only (runs anywhere, but a multi-page scan can take a while).
For an NVIDIA GPU: install the [NVIDIA Container Toolkit], switch the Dockerfile to a
CUDA base image (see the note at the bottom of the `Dockerfile`), then:

```bash
docker compose --profile gpu up history-scanner-gpu
```

[NVIDIA Container Toolkit]: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

## Browser edition on GitHub Pages

The `docs/` folder is a **fully static app** — it runs the OCR by calling Claude's vision API
straight from the browser, so it can live 100% on GitHub Pages with no backend.

### Deploy it

1. Push this repo to GitHub.
2. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   The included workflow (`.github/workflows/pages.yml`) publishes `docs/` on every push to `main`.
   *(Alternative with no Actions: set Source to “Deploy from a branch”, branch `main`, folder `/docs`.)*
3. Open `https://<your-username>.github.io/<repo-name>/` — works great on mobile.

### Use it

1. Paste your **own** Anthropic API key (from [console.anthropic.com](https://console.anthropic.com/)).
   It is stored **only in your browser's `localStorage`** and sent **directly to Anthropic** — it
   never touches GitHub or any other server. Use "Forget" to clear it; avoid shared computers.
2. Drop in document images or a PDF (multiple pages welcome).
3. Pick a model — **Claude Opus 4.8** (best on hard handwriting) or **Sonnet 4.6** (cheaper/faster) —
   choose an **image size** (large images are downscaled in your browser before upload to cut token
   cost), set the **document language** and an optional **translation** target, toggle options
   (careful mode, preserve spelling), and **Transcribe**. The Markdown streams in live; copy or download it.

   - **Languages & translation:** set *Document language* to guide OCR on historical scripts —
     e.g. **German** triggers tailored handling of Kurrentschrift/Sütterlin handwriting, Fraktur
     print, long-s (ſ), ß, and umlauts. Set *Translate to* (currently **English**) to append a
     faithful modern translation after the transcription. The first supported pair is
     **German → English**; more languages are a one-line addition in `docs/index.html`
     (`LANGUAGES` / `TRANSLATE_TARGETS`).
4. A **live estimate** shows the approximate input cost before you scan, and the **actual cost**
   (from real token usage) is shown after each transcription.

### Trade-offs vs the server edition

- ✅ Zero infrastructure, free hosting, runs on any device, excellent on handwriting/historical script.
- ✅ Your key never leaves your browser (the page is static; there's no server to leak it).
- ⚠️ Not a full marker pipeline — no structured JSON/HTML, table-extraction, or page-stats objects;
  it produces clean Markdown text. For maximum-fidelity structured output, use the server edition.
- ⚠️ Each scan uses your Anthropic API credits.

## 📱 View it on your phone (public hosting)

The app binds to all interfaces and ships with a **password gate** and a
**Cloudflare tunnel**, so you can reach the full OCR app from your phone anywhere —
no port-forwarding, no static IP.

**1. Set a password** (so only you can use it — every scan spends your LLM budget):

```bash
# in .env
ACCESS_PASSWORD=choose-a-strong-password
ANTHROPIC_API_KEY=sk-ant-...
```

**2. Start the app + a public tunnel:**

```bash
docker compose --profile public up --build
```

**3. Grab the public URL** from the logs — look for a line like:

```
https://random-words-1234.trycloudflare.com
```

Open that on your phone, enter the password, and scan. The URL is HTTPS, so the
mobile UI and copy-to-clipboard work fully.

> **Stable URL?** A `trycloudflare.com` URL is random and changes each restart.
> For a permanent address on your own domain, create a *named* tunnel in the
> [Cloudflare dashboard], set its public hostname to point at
> `http://history-scanner:8000`, and put its token in `.env` as `TUNNEL_TOKEN`.

[Cloudflare dashboard]: https://one.dash.cloudflare.com/

### Where to run it

The tunnel just exposes whatever machine runs the container, so run it on:

- **Your own computer** (a desktop with a GPU is ideal — CPU works but is slow).
- **A cloud GPU host** (RunPod, Lambda, Vast.ai, a GPU VPS…). Install Docker,
  clone this repo, and run the same `docker compose --profile public up` command.

Either way the public URL is reachable from your phone. Keep the machine awake
and the container running for the link to stay live.

### Security notes for public deployments

- **Always set `ACCESS_PASSWORD`** before exposing the app — an open endpoint lets
  anyone burn your Claude API budget.
- The password gates the entire UI and API (`/api/health` stays open for uptime
  probes). Session is a signed, HTTP-only cookie; sign out from the header link.
- Consider lowering `MAX_UPLOAD_MB` and keeping `MAX_CONCURRENT_JOBS=1` to bound
  resource use.

## Quick start (local Python)

Requires **Python 3.10+** and [PyTorch](https://pytorch.org/get-started/locally/).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # installs marker-pdf[full] + the web app
cp .env.example .env                      # add your ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)       # load env vars (or use a tool like direnv)

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open <http://localhost:8000>.

## LLM enhancement (Claude)

For handwriting and historical documents, marker's `--use_llm` mode is the single
biggest quality lever. This app wires it to **Anthropic Claude** by default.

1. Get a key from <https://console.anthropic.com/>.
2. Put it in `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
3. Leave **LLM enhancement** ticked in the UI (it's on by default when a key is set).

Want a different provider? marker also supports Gemini, OpenAI, Ollama, Vertex and
Azure. Change `MARKER_LLM_SERVICE` in `.env` to the matching service class (e.g.
`marker.services.gemini.GoogleGeminiService`) and supply that provider's credentials.

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `ACCESS_PASSWORD` | — | If set, gates the whole app behind a login. **Set this before public hosting.** |
| `TUNNEL_TOKEN` | — | Cloudflare named-tunnel token for a stable public URL (optional). |
| `ANTHROPIC_API_KEY` | — | Claude key used for LLM enhancement. |
| `CLAUDE_MODEL_NAME` | `claude-sonnet-4-6` | Claude model marker calls. |
| `MARKER_LLM_SERVICE` | `marker.services.claude.ClaudeService` | marker LLM provider. |
| `DEFAULT_USE_LLM` | `true` | Default state of the LLM toggle. |
| `DEFAULT_FORCE_OCR` | `true` | Re-OCR every page (best for scans). |
| `MAX_UPLOAD_MB` | `50` | Upload size limit. |
| `MAX_CONCURRENT_JOBS` | `1` | Simultaneous conversions (raise only with lots of VRAM). |
| `TORCH_DEVICE` | auto | Force `cuda`, `mps`, or `cpu`. |
| `DATA_DIR` | `/tmp/history-scanner` | Where uploads + results are written. |

## API

The UI is a thin client over a small JSON API:

| Method & path | Description |
| --- | --- |
| `GET /api/health` | Engine status, LLM config, limits, whether auth is on. |
| `GET/POST /login`, `POST /logout` | Password gate (only when `ACCESS_PASSWORD` is set). |
| `POST /api/scan` | Multipart upload (`file`, `use_llm`, `force_ocr`, `output_format`, `languages`). Returns `202` + `job_id`. |
| `GET /api/jobs/{id}` | Job status; includes the transcribed `text` once `done`. |
| `GET /api/jobs/{id}/download` | Download the result file. |
| `GET /api/jobs/{id}/images/{name}` | An image extracted from the document. |

## Tips for historical & handwritten documents

- Keep **Force OCR** on for scanned images (don't trust any embedded text layer).
- Turn on **LLM enhancement** for handwriting — it corrects obvious OCR errors in context.
- Set **Languages** (e.g. `en,fr,la`) to steer the OCR model when you know the language(s).
- Scan at **300 DPI+** and de-skew for best results; marker handles rotation/layout but
  cleaner input always transcribes better.

## Development

```bash
pip install -r requirements-dev.txt
pytest          # web-layer tests; they mock marker so no models are downloaded
```

The marker imports are isolated inside functions in `app/marker_runner.py`, so the app
and test-suite import cleanly even when marker isn't installed.

## License & credits

Built on [marker](https://github.com/datalab-to/marker) by Datalab — see its repository
for its license and model terms. This project glues marker to a FastAPI web UI.
